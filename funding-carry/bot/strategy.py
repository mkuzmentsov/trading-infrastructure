"""Funding-carry strategy logic (pure decisions; no I/O).

Given current state per coin, return a list of Action dicts. main.py executes
them (or logs them in dry_run). 'Hold, don't time': we open the basket and hold;
the only active logic is (a) regime-flip protection, (b) deleverage-on-stress,
(c) delta-drift rebalance.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

HRS_YR = 24 * 365


@dataclass
class CoinState:
    coin: str
    target_notional: float                 # fixed-sizing target (unused when sizing_mode='auto')
    mark_px: float
    funding_hourly: float                 # current hourly funding rate (signed)
    smoothed_funding_apr: float            # trailing-mean annualized funding
    funding_below_exit_hours: int          # consecutive hours smoothed <= exit_apr
    regime_exited: bool                    # we've closed this leg due to a funding-regime flip
    perp_size: float                       # signed; negative = short; 0 = no position
    perp_notional: float
    perp_liq_px: float                     # 0 if no position
    spot_coins: float                      # Kraken spot holding in coin units
    # Auto-sizing slices: this coin's share of usable Kraken USD + HL margin
    # (computed in main.py from weights). Zero in fixed-mode (unused).
    kr_usd_slice: float = 0.0
    hl_margin_slice: float = 0.0
    # Per-coin leverage cap override; 0 = fall back to cfg.max_leverage.
    # Useful for high-vol alts where you want a tighter cap than majors.
    max_leverage_override: float = 0.0
    @property
    def spot_notional(self) -> float:
        return self.spot_coins * self.mark_px
    @property
    def has_perp(self) -> bool:
        return self.perp_size != 0.0
    @property
    def liq_room_frac(self) -> float:
        """For a short: (liq_px - mark_px)/mark_px. Larger = safer. 0 if no position."""
        if not self.has_perp or self.perp_liq_px <= 0 or self.mark_px <= 0:
            return 1.0
        return max(0.0, (self.perp_liq_px - self.mark_px) / self.mark_px)


@dataclass
class Cfg:
    leverage: float                        # used in sizing_mode='fixed'; ignored in 'auto'
    sizing_mode: str = "fixed"             # 'fixed' (use target_notional + leverage)
                                           # or 'auto'  (derive from kr_usd_slice + hl_margin_slice)
    max_leverage: float = 3.0              # cap for auto mode (integer-rounded for HL set_leverage)
    min_open_notional: float = 25.0        # don't open pairs smaller than this $ amount (auto mode)
    deleverage_liq_room: float = 0.15      # reduce position if liq-room drops below this
    emergency_liq_room: float = 0.05       # close leg entirely below this
    deleverage_reduce_frac: float = 0.5    # how much of the position to cut when deleveraging
    delta_rebalance_pct: float = 0.08
    funding_exit_apr: float = 0.0
    funding_exit_persist_hours: int = 48
    funding_reentry_apr: float = 0.03
    min_notional_to_act: float = 25.0      # ignore drift/actions below this $ amount


def _auto_size(st: "CoinState", cfg: Cfg) -> tuple[float, int]:
    """Derive (notional_usd, leverage_int) from this coin's balance slices.

    Algorithm: notional is the smaller of the two leg constraints —
      - spot leg ≤ kr_usd_slice (can't buy more than we have on Kraken)
      - perp leg ≤ hl_margin_slice × max_leverage (margin × L)
    Leverage is the smallest integer L (capped at max_leverage) that lets
    the perp side cover the chosen notional. HL only accepts integer L,
    so we round UP — that allocates slightly less margin (safer / more
    headroom) than the float L would. Returns (0, 0) if either slice is
    too thin to open a meaningful position.
    """
    S = max(0.0, st.kr_usd_slice)
    H = max(0.0, st.hl_margin_slice)
    if S < cfg.min_open_notional or H <= 0:
        return 0.0, 0
    L_cap = st.max_leverage_override if st.max_leverage_override > 0 else cfg.max_leverage
    max_L = max(1, int(L_cap))
    # smallest L s.t. H*L >= S, capped at max_L
    import math
    L_needed = math.ceil(S / H) if H > 0 else max_L
    L = max(1, min(max_L, L_needed))
    notional = min(S, H * L)
    if notional < cfg.min_open_notional:
        return 0.0, 0
    return notional, L


# Action kinds: open_pair, close_pair, deleverage, rebalance_spot, mark_regime_exit, mark_regime_reentry, alert
def decide(st: CoinState, cfg: Cfg) -> list[dict]:
    acts: list[dict] = []

    # 1. regime re-entry: if we'd exited and funding recovered, clear the flag (re-open handled below)
    if st.regime_exited and st.smoothed_funding_apr >= cfg.funding_reentry_apr:
        acts.append({"kind": "mark_regime_reentry", "coin": st.coin,
                     "why": f"smoothed funding {st.smoothed_funding_apr:.1%} >= reentry {cfg.funding_reentry_apr:.1%}"})
        st.regime_exited = False  # so the open logic below can fire this cycle

    # 2. regime exit: funding has been at/below the exit threshold persistently -> close
    if (not st.regime_exited
            and st.funding_below_exit_hours >= cfg.funding_exit_persist_hours):
        if st.has_perp or st.spot_notional > cfg.min_notional_to_act:
            acts.append({"kind": "close_pair", "coin": st.coin,
                         "why": f"funding <= {cfg.funding_exit_apr:.1%} for {st.funding_below_exit_hours}h"})
        acts.append({"kind": "mark_regime_exit", "coin": st.coin})
        return acts  # nothing else this cycle

    if st.regime_exited:
        return acts  # stay flat until re-entry

    # 3. deleverage / emergency on margin stress
    if st.has_perp:
        if st.liq_room_frac <= cfg.emergency_liq_room:
            acts.append({"kind": "close_pair", "coin": st.coin, "emergency": True,
                         "why": f"liq-room {st.liq_room_frac:.1%} <= emergency {cfg.emergency_liq_room:.1%}"})
            return acts
        if st.liq_room_frac <= cfg.deleverage_liq_room:
            reduce_notional = st.perp_notional * cfg.deleverage_reduce_frac
            acts.append({"kind": "deleverage", "coin": st.coin,
                         "reduce_notional": reduce_notional,
                         "why": f"liq-room {st.liq_room_frac:.1%} <= deleverage {cfg.deleverage_liq_room:.1%}"})
            # after deleverage we expect the spot rebalance below to follow next cycle

    # 4. open the pair if we don't have it and funding is currently positive
    if not st.has_perp and st.spot_notional < cfg.min_notional_to_act:
        if st.funding_hourly > 0 and st.smoothed_funding_apr >= cfg.funding_reentry_apr * 0.0:  # i.e. >0
            if cfg.sizing_mode == "auto":
                notional, lev = _auto_size(st, cfg)
                if notional <= 0:
                    acts.append({"kind": "alert", "coin": st.coin,
                                 "why": f"want to open ({st.smoothed_funding_apr:+.1%} apr) but balances thin: "
                                        f"kr_slice=${st.kr_usd_slice:.2f}, hl_slice=${st.hl_margin_slice:.2f}"})
                    return acts
                acts.append({"kind": "open_pair", "coin": st.coin,
                             "notional": notional, "leverage": lev,
                             "why": f"open auto L={lev}x ${notional:.0f}: funding {st.smoothed_funding_apr:+.1%} apr"})
            else:
                acts.append({"kind": "open_pair", "coin": st.coin, "notional": st.target_notional,
                             "leverage": int(cfg.leverage),
                             "why": f"open: funding {st.smoothed_funding_apr:+.1%} apr"})
            return acts

    # 5. delta-drift rebalance: keep spot notional ≈ perp notional
    if st.has_perp:
        target = st.perp_notional
        drift = (st.spot_notional - target)
        if target > 0 and abs(drift) / target > cfg.delta_rebalance_pct and abs(drift) > cfg.min_notional_to_act:
            acts.append({"kind": "rebalance_spot", "coin": st.coin, "delta_notional": -drift,
                         "why": f"spot {st.spot_notional:.0f} vs perp {target:.0f} (drift {drift/target:+.1%})"})

    return acts
