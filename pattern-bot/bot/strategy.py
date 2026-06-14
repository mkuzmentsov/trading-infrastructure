"""Trade logic (pure decisions; no I/O).

Mirrors funding-carry's `decide()` philosophy: given current state, return a list
of Action dicts. main.py executes them (or logs them in dry_run); backtest.py
simulates them. The trade *geometry* (entry / stop / target / size) lives in
`plan_trade()` and exit detection in `check_exit()`, both pure — the backtester
and the live bot call the SAME functions, so sim and live can't diverge.

Trade model (measured move + stop):
  double_top  → SHORT: stop just ABOVE the higher peak; target = neckline − height.
  double_bottom → LONG: stop just BELOW the lower trough; target = neckline + height.
  (or fixed R:R if risk.target_mode == 'fixed_rr')

Sizing is risk-based: we risk `risk_per_trade_pct` of equity to the stop, capped
by `max_leverage` notional.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Optional

from patterns import PatternSignal, PatternCfg


# Map a signal's kind back to its pattern family (for per-family config lookup).
_FAMILY = {
    "double_top": "double", "double_bottom": "double",
    "head_shoulders": "head_shoulders", "inv_head_shoulders": "head_shoulders",
    "triple_top": "triple", "triple_bottom": "triple",
    "triangle": "triangle", "wedge": "wedge", "rectangle": "rectangle", "flag": "flag",
}


def family_of(kind: str) -> str:
    return _FAMILY.get(kind, kind)


@dataclass(frozen=True)
class RiskCfg:
    sizing_mode: str = "risk"           # "risk": size so a stop-out loses risk_per_trade_pct of equity.
                                        # "fixed_fraction": notional = position_pct × max_leverage × equity
                                        #   (i.e. commit position_pct of equity as margin at max_leverage).
    position_pct: float = 0.25          # fixed_fraction: margin fraction of equity committed per trade
    risk_per_trade_pct: float = 0.005   # risk mode: fraction of equity risked to the stop
    max_leverage: float = 5.0           # leverage (also caps notional in risk mode)
    stop_buffer_pct: float = 0.002      # place stop this far beyond the peak/trough
    stop_height_frac: float = 0.0       # >0: place stop INSIDE the pattern, this fraction of the
                                        # height back from the neckline toward the peak/trough
                                        # (e.g. 0.5 → ~2:1 RR). 0 = stop beyond the extreme (wide).
    target_mode: str = "measured_move"  # "measured_move" | "fixed_rr" | "pct"
    fixed_rr: float = 2.0               # reward:risk when target_mode == "fixed_rr"
    stop_loss_pct: float = 0.20         # hard stop % from entry  (target_mode == "pct")
    take_profit_pct: float = 0.60       # hard take-profit % from entry (target_mode == "pct")
    max_hold_bars: int = 0              # 0 = no time stop; else close after N bars
    min_notional: float = 10.0          # don't open positions smaller than this $

    @classmethod
    def from_dict(cls, d: Mapping) -> "RiskCfg":
        d = d or {}
        return cls(
            sizing_mode=str(d.get("sizing_mode", "risk")).lower(),
            position_pct=float(d.get("position_pct", 0.25)),
            risk_per_trade_pct=float(d.get("risk_per_trade_pct", 0.005)),
            max_leverage=float(d.get("max_leverage", 5.0)),
            stop_buffer_pct=float(d.get("stop_buffer_pct", 0.002)),
            stop_height_frac=float(d.get("stop_height_frac", 0.0)),
            target_mode=str(d.get("target_mode", "measured_move")).lower(),
            fixed_rr=float(d.get("fixed_rr", 2.0)),
            stop_loss_pct=float(d.get("stop_loss_pct", 0.20)),
            take_profit_pct=float(d.get("take_profit_pct", 0.60)),
            max_hold_bars=int(d.get("max_hold_bars", 0)),
            min_notional=float(d.get("min_notional", 10.0)),
        )


@dataclass
class Position:
    coin: str
    side: str            # "long" | "short"
    size: float          # coin units, always positive
    entry_px: float
    stop_px: float
    target_px: float
    confirm_time: int    # the signal that opened this (dedup key)
    opened_time: int = 0  # ms timestamp of the entry bar
    bars_held: int = 0    # incremented by the caller each bar
    # pattern info (for charting / inspection; defaults when not supplied)
    p1_time: int = 0     # ms timestamp of the 1st key pivot
    p2_time: int = 0     # ms timestamp of the last key pivot
    neckline: float = 0.0
    kind: str = ""       # pattern kind, e.g. "double_top", "head_shoulders"
    anchors: tuple = ()  # ms timestamps of all the pattern's pivots

    @property
    def notional(self) -> float:
        return self.size * self.entry_px


def plan_trade(signal: PatternSignal, mark_px: float, equity: float,
               cfg: RiskCfg) -> Optional[dict]:
    """Compute entry/stop/target/size for a fresh signal. Returns an `open_trade`
    action dict, or None if the geometry is invalid (e.g. we'd be entering on the
    wrong side of the stop because price already ran too far past the neckline)."""
    if mark_px <= 0 or equity <= 0:
        return None
    long = signal.direction == "long"

    if cfg.target_mode == "pct":
        # Hard percentage stop/target from entry — ignores pattern geometry.
        if long:
            stop = mark_px * (1.0 - cfg.stop_loss_pct)
            target = mark_px * (1.0 + cfg.take_profit_pct)
        else:
            stop = mark_px * (1.0 + cfg.stop_loss_pct)
            target = mark_px * (1.0 - cfg.take_profit_pct)
    else:
        # Stop: either beyond the further-out extreme (wide, ≈1× height of risk),
        # or — if stop_height_frac>0 — INSIDE the pattern, a fraction of the height
        # back from the neckline toward the extreme (tighter → higher RR).
        beyond = (signal.extreme_level * (1.0 - cfg.stop_buffer_pct) if long
                  else signal.extreme_level * (1.0 + cfg.stop_buffer_pct))
        if cfg.stop_height_frac > 0:
            stop = signal.neckline - cfg.stop_height_frac * signal.height if long \
                else signal.neckline + cfg.stop_height_frac * signal.height
            # An in-pattern stop assumes entry is at the neckline. If entry is
            # already beyond it (e.g. a second_peak entry near the extreme), the
            # stop would be on the wrong side of entry → fall back to beyond-extreme.
            if (long and stop >= mark_px) or (not long and stop <= mark_px):
                stop = beyond
        else:
            stop = beyond
        # Target is the measured move from the neckline, or a fixed R:R off the stop.
        risk_per_unit_geom = abs(mark_px - stop)
        if cfg.target_mode == "fixed_rr":
            target = (mark_px + cfg.fixed_rr * risk_per_unit_geom) if long \
                else (mark_px - cfg.fixed_rr * risk_per_unit_geom)
        else:  # measured_move
            target = signal.neckline + signal.height if long else signal.neckline - signal.height

    risk_per_unit = abs(mark_px - stop)
    if risk_per_unit <= 0:
        return None
    # Reject if price already blew past the stop (entry on the wrong side).
    if long and mark_px <= stop:
        return None
    if not long and mark_px >= stop:
        return None
    # A target behind the entry (can happen with a late measured-move confirm); skip.
    if long and target <= mark_px:
        return None
    if not long and target >= mark_px:
        return None

    # Position size.
    if cfg.sizing_mode == "fixed_fraction":
        # Commit position_pct of equity as margin, at max_leverage → notional exposure.
        notional = cfg.position_pct * cfg.max_leverage * equity
        size = notional / mark_px
    else:
        # Risk-based: size so a stop-out loses risk_per_trade_pct of equity; cap by leverage.
        size = (cfg.risk_per_trade_pct * equity) / risk_per_unit
        notional = size * mark_px
        max_notional = equity * cfg.max_leverage
        if notional > max_notional:
            size = max_notional / mark_px
            notional = size * mark_px
    if notional < cfg.min_notional or size <= 0:
        return None

    rr = abs(target - mark_px) / risk_per_unit
    return {
        "kind": "open_trade", "coin": signal.coin, "side": signal.direction,
        "pattern": signal.kind, "size": size, "entry": mark_px,
        "stop": stop, "target": target, "rr": rr,
        "confirm_time": signal.confirm_time,
        "why": (f"{signal.kind} neckline={signal.neckline:.4g} "
                f"height={signal.height:.4g} stop={stop:.4g} target={target:.4g} "
                f"RR={rr:.2f}"),
    }


def check_exit(pos: Position, high: float, low: float, cfg: RiskCfg
               ) -> Optional[tuple[str, float]]:
    """Has the position hit its stop, target, or time limit this bar?

    Returns (reason, exit_px) or None. For live use, pass the current mark as both
    `high` and `low`. Stop is checked before target so a bar that straddles both
    is scored as a loss (conservative). exit_px is the stop/target level (assume
    it filled there); timeout has no level so the caller uses the current price.
    """
    if pos.side == "long":
        if low <= pos.stop_px:
            return "stop_hit", pos.stop_px
        if high >= pos.target_px:
            return "target_hit", pos.target_px
    else:  # short
        if high >= pos.stop_px:
            return "stop_hit", pos.stop_px
        if low <= pos.target_px:
            return "target_hit", pos.target_px
    if cfg.max_hold_bars > 0 and pos.bars_held >= cfg.max_hold_bars:
        return "timeout", 0.0  # caller substitutes current price
    return None


def decide(signal: Optional[PatternSignal], pos: Optional[Position],
           equity: float, mark_px: float, last_confirm_time: Optional[int],
           cfg: RiskCfg) -> list[dict]:
    """Live decision step for one coin.

    - If a position is open, only manage it (close on stop/target/timeout).
    - Else, if a fresh, not-yet-acted signal exists, open a trade.
    A signal fires once per pattern, but the same closed break bar stays "current"
    for the rest of its candle, so we dedup on confirm_time to avoid re-entering.
    """
    acts: list[dict] = []

    if pos is not None:
        ex = check_exit(pos, mark_px, mark_px, cfg)
        if ex is not None:
            reason, _ = ex
            acts.append({"kind": "close_trade", "coin": pos.coin, "reason": reason,
                         "why": f"{reason} @ mark={mark_px:.4g} "
                                f"(stop={pos.stop_px:.4g} target={pos.target_px:.4g})"})
        return acts

    if signal is not None and signal.confirm_time != last_confirm_time:
        act = plan_trade(signal, mark_px, equity, cfg)
        if act is not None:
            acts.append(act)
        else:
            acts.append({"kind": "alert", "coin": signal.coin,
                         "why": f"{signal.kind} confirmed but trade geometry invalid "
                                f"(entered too late / size too small) — skipping"})
    return acts


def resolve_detectors(cfg: dict) -> list[tuple[str, PatternCfg, RiskCfg]]:
    """Build a (family, PatternCfg, RiskCfg) bundle for each active pattern family,
    merging global `pattern`/`risk` config with per-family `pattern_overrides`.

    Each family's override dict may carry BOTH pattern fields (e.g. tri_window) and
    risk fields (e.g. stop_height_frac); PatternCfg/RiskCfg.from_dict each pick out
    their own keys, so a single merged dict feeds both. Returned in config order —
    the caller checks them in that order and the first fresh confirmation wins.
    """
    pat = dict(cfg.get("pattern", {}) or {})
    risk = dict(cfg.get("risk", {}) or {})
    overrides = cfg.get("pattern_overrides", {}) or {}
    out: list[tuple[str, PatternCfg, RiskCfg]] = []
    for fam in list(pat.get("pattern_types", ["double"])):
        ov = overrides.get(fam, {}) or {}
        pcfg = PatternCfg.from_dict({**pat, **ov, "pattern_types": [fam]})
        rcfg = RiskCfg.from_dict({**risk, **ov})
        out.append((fam, pcfg, rcfg))
    return out
