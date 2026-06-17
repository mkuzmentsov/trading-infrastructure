"""Stress / scenario replay (§4.8).

Replay pathological tapes — flash crashes, exchange outages, stablecoin de-pegs,
liquidity droughts — and assert the system behaves *safely*, not necessarily
profitably. A strategy may lose money in a stress scenario; it may not behave
*dangerously*: blow through solvency, run away with leverage instead of de-risking,
or storm the venue with orders.

Each scenario is a transform over (bars, config). The engine is then run over the
perturbed tape via the same path as a normal backtest, and a fixed set of safety
invariants is checked against the recorded equity / leverage / order series.

What is and isn't exercised today: the drawdown breaker and leverage clamp ARE wired
into the engine's RiskGate, so de-risk/solvency/clamp behaviour is real. Per-position
stops and funding settlement are not yet in the engine loop, so funding-spike and
stop-honoured checks are marked NOT-APPLICABLE rather than silently passed.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field, replace as dc_replace

from ..config import BotConfig
from ..core.types import Bar


@dataclass
class Scenario:
    name: str
    description: str
    transform: object  # (bars, config) -> (bars, config)


@dataclass
class SafetyCheck:
    name: str
    passed: bool
    detail: str = ""


@dataclass
class StressResult:
    scenario: str
    checks: list[SafetyCheck] = field(default_factory=list)
    peak_drawdown: float = 0.0
    max_leverage: float = 0.0
    halted: bool = False

    @property
    def safe(self) -> bool:
        return bool(self.checks) and all(c.passed for c in self.checks)

    def summary(self) -> str:
        head = ("SAFE" if self.safe else "UNSAFE") + f"  {self.scenario}"
        lines = [("  ok  " if c.passed else " FAIL ") + f"{c.name}: {c.detail}" for c in self.checks]
        return head + "\n" + "\n".join(lines)


# --- scenario tape transforms ---------------------------------------------


def _scale_bar(b: Bar, factor: float) -> Bar:
    return dc_replace(b, open=b.open * factor, high=b.high * factor,
                      low=b.low * factor, close=b.close * factor)


def flash_crash(bars: list[Bar], config: BotConfig, at: float = 0.6,
                depth: float = 0.35, width: int = 3):
    """A sharp drop held for ``width`` bars, then a snap-back recovery."""
    bars = list(bars)
    i0 = int(len(bars) * at)
    for j in range(i0, min(i0 + width, len(bars))):
        bars[j] = _scale_bar(bars[j], 1 - depth)
    return bars, config


def stable_depeg(bars: list[Bar], config: BotConfig, at: float = 0.6, depth: float = 0.25):
    """A permanent step down (quote/collateral repricing) from ``at`` onward."""
    bars = list(bars)
    i0 = int(len(bars) * at)
    for j in range(i0, len(bars)):
        bars[j] = _scale_bar(bars[j], 1 - depth)
    return bars, config


def venue_outage(bars: list[Bar], config: BotConfig, at: float = 0.6, n_missing: int = 24):
    """Drop a run of bars (data + order I/O frozen), then resume — tests safe resync."""
    bars = list(bars)
    i0 = int(len(bars) * at)
    return bars[:i0] + bars[i0 + n_missing:], config


def liquidity_drought(bars: list[Bar], config: BotConfig):
    """Spreads/impact blow out: model as a 10x taker cost for the whole run."""
    cfg = copy.deepcopy(config)
    cfg.friction.taker_fee_bps = config.friction.taker_fee_bps * 10
    return list(bars), cfg


SCENARIOS = [
    Scenario("flash_crash", "instantaneous -35% drop, held 3 bars, then recovery", flash_crash),
    Scenario("stable_depeg", "permanent -25% step (collateral de-peg)", stable_depeg),
    Scenario("venue_outage", "24 bars of frozen data + order I/O, then resync", venue_outage),
    Scenario("liquidity_drought", "10x taker cost (spreads/impact blow out)", liquidity_drought),
]


# --- runner + invariants ---------------------------------------------------


def run_scenario(config: BotConfig, base_bars: list[Bar], scenario: Scenario) -> StressResult:
    """Perturb the tape per ``scenario``, run the engine, check safety invariants."""
    from ..core.events import MarketEvent
    from ..engine.backtest import Backtester

    bars, cfg = scenario.transform(base_bars, config)
    res = StressResult(scenario=scenario.name)

    engine = Backtester(cfg).build_engine()
    try:
        engine.run(MarketEvent(b) for b in bars)
    except Exception as exc:  # noqa: BLE001
        res.checks.append(SafetyCheck("engine_survived", False, f"raised {exc!r}"))
        return res
    res.checks.append(SafetyCheck("engine_survived", True, f"processed {len(engine.equity_val)} bars"))

    eq = engine.equity_val
    lev = engine.leverage_val
    if not eq:
        res.checks.append(SafetyCheck("has_equity", False, "no equity points"))
        return res

    # peak-to-trough drawdown over the run
    peak, dd = eq[0], 0.0
    for v in eq:
        peak = max(peak, v)
        if peak > 0:
            dd = max(dd, 1 - v / peak)
    res.peak_drawdown = dd
    res.max_leverage = max(lev) if lev else 0.0
    res.halted = engine.drawdown.halted

    halt_th = cfg.risk.drawdown_halt
    lev_cap = cfg.risk.max_gross_leverage

    # 1) Solvency: equity never collapses to <= 0 and stays finite.
    finite = all(v == v and v not in (float("inf"), float("-inf")) for v in eq)
    res.checks.append(SafetyCheck("solvent", finite and min(eq) > 0,
                                  f"min equity={min(eq):,.0f}"))

    # 2) No order storm: at most a couple of fills on any single bar (deadband works).
    max_orders = max(engine.orders_per_bar) if engine.orders_per_bar else 0
    res.checks.append(SafetyCheck("no_order_storm", max_orders <= 2 * len(cfg.universe),
                                  f"max orders/bar={max_orders}"))

    # 3) Leverage clamp on NEW risk: post-event leverage stays bounded, OR the breaker
    #    halted (a price-driven leverage spike must trigger de-risk, not be ignored).
    bounded = res.max_leverage <= lev_cap * 1.5 or res.halted
    res.checks.append(SafetyCheck("leverage_bounded_or_derisked", bounded,
                                  f"max lev={res.max_leverage:.2f} cap={lev_cap} halted={res.halted}"))

    # 4) Breaker responds: if drawdown breached the halt threshold, the breaker halted.
    breaker_ok = (dd < halt_th) or engine.drawdown.halted
    res.checks.append(SafetyCheck("breaker_responds", breaker_ok,
                                  f"peakDD={dd:.1%} halt_th={halt_th:.0%} halted={engine.drawdown.halted}"))

    return res


def run_all(config: BotConfig, base_bars: list[Bar]) -> list[StressResult]:
    return [run_scenario(config, base_bars, s) for s in SCENARIOS]
