"""Triple-barrier labeling + sample weighting (§2.2).

Label each event by which barrier it touches first: take-profit (+1), stop-loss
(-1), or the vertical time limit (0). For meta-labeling (principle #3) we then map
this onto the *primary side*: the binary label is whether the side the primary model
took was right (profit barrier reached) — so the ML overlay learns "act / don't act
and how big", not direction.

Overlapping labels are down-weighted by concurrency (average uniqueness) so the
model isn't fooled by redundant, time-overlapping samples (López de Prado, AFML 3–4).
"""

from __future__ import annotations

from datetime import timedelta

import numpy as np
import pandas as pd

from ..core.types import Label, Symbol


def triple_barrier_labels(
    prices: pd.Series,
    events: pd.DatetimeIndex,
    pt_sl: tuple[float, float],
    vertical: timedelta,
    symbol: Symbol,
    target_vol: pd.Series | None = None,
    sides: pd.Series | None = None,
) -> list[Label]:
    """Compute triple-barrier outcomes for each event timestamp.

    ``pt_sl`` = (take-profit, stop-loss) widths as multiples of ``target_vol`` —
    dynamic barriers that scale with volatility. ``vertical`` is the max holding time.
    ``sides`` (optional, +1/-1 per event) makes barriers directional for meta-labeling:
    a long uses (+pt, -sl); a short mirrors them. Without sides, +pt/-sl are absolute.

    Each :class:`Label` carries ``outcome`` (+1 tp / -1 sl / 0 time), the realized
    return to the touch, and ``meta`` with the side and a ``correct`` flag (1 if the
    side's profit barrier was hit first) for meta-label training.
    """
    prices = prices.sort_index()
    pt, sl = pt_sl
    out: list[Label] = []

    for t0 in events:
        if t0 not in prices.index:
            continue
        p0 = float(prices.loc[t0])
        vol = float(target_vol.loc[t0]) if target_vol is not None and t0 in target_vol.index else 0.0
        if vol <= 0:
            continue
        side = float(sides.loc[t0]) if sides is not None and t0 in sides.index else 1.0
        if side == 0:
            continue

        up = p0 * (1 + pt * vol)
        dn = p0 * (1 - sl * vol)
        t1 = t0 + vertical
        path = prices.loc[(prices.index > t0) & (prices.index <= t1)]
        if path.empty:
            continue

        touch_ts = path.index[-1]
        outcome = 0
        for ts, px in path.items():
            if px >= up:
                outcome, touch_ts = 1, ts
                break
            if px <= dn:
                outcome, touch_ts = -1, ts
                break

        ret = float(prices.loc[touch_ts] / p0 - 1.0)
        # For meta-labeling: did the *side* make money before its stop?
        # long-correct == upper hit (outcome +1); short-correct == lower hit (outcome -1).
        correct = 1 if (side > 0 and outcome == 1) or (side < 0 and outcome == -1) else 0
        out.append(
            Label(
                symbol=symbol,
                event_ts=t0.to_pydatetime() if hasattr(t0, "to_pydatetime") else t0,
                outcome=outcome,
                ret=ret * side,  # return in the side's direction
                touch_ts=touch_ts.to_pydatetime() if hasattr(touch_ts, "to_pydatetime") else touch_ts,
                weight=1.0,
                meta={"side": side, "correct": correct},
            )
        )
    return out


def concurrency_weights(labels: list[Label], prices: pd.Series) -> list[float]:
    """Sample weights ∝ average uniqueness (inverse label overlap), §2.2.

    For each bar, count how many label spans [event, touch] cover it; a label's weight
    is the mean of 1/concurrency over its own span. Heavily overlapping labels get
    small weights so the effective sample size reflects independent information.
    """
    if not labels:
        return []
    index = prices.sort_index().index
    pos = {ts: i for i, ts in enumerate(index)}
    count = np.zeros(len(index))

    spans = []
    for lab in labels:
        e = pd.Timestamp(lab.event_ts)
        t = pd.Timestamp(lab.touch_ts)
        i0 = pos.get(e)
        i1 = pos.get(t)
        if i0 is None or i1 is None or i1 < i0:
            spans.append(None)
            continue
        count[i0 : i1 + 1] += 1
        spans.append((i0, i1))

    weights = []
    for span in spans:
        if span is None:
            weights.append(0.0)
            continue
        i0, i1 = span
        seg = count[i0 : i1 + 1]
        weights.append(float(np.mean(1.0 / seg)) if seg.size else 0.0)
    return weights
