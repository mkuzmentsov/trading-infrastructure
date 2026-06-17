"""Build a point-in-time labeled dataset for the meta-label model (§2.2, principle #3).

Turns a bar series into (X, y, weights, label_spans):

* **X** — a causal feature matrix (each row uses only data knowable at that bar's
  close). Feature families: trend spread, momentum, volatility regime, range
  position, primary-signal conviction, calendar.
* **y** — the binary meta-label: was the *primary side* (sign of the trend spread)
  correct, i.e. did its profit barrier hit before its stop (triple-barrier).
* **weights** — average-uniqueness sample weights for overlapping labels.
* **label_spans** — event ts -> label-touch ts, consumed by PurgedKFold to purge
  overlapping train samples.

All features are shifted/rolling so there is no lookahead; the label alone looks
forward, which is correct — that is the thing being predicted.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..core.types import Symbol
from .labeling import concurrency_weights, triple_barrier_labels

FEATURE_COLUMNS = [
    "ema_spread", "conviction", "ret_vol", "vol_ratio",
    "mom_fast", "mom_slow", "dist_high", "dist_low", "hour", "dow",
]


def _bars_to_frame(bars: list) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "close": [b.close for b in bars],
            "high": [b.high for b in bars],
            "low": [b.low for b in bars],
        },
        index=pd.DatetimeIndex([b.ts for b in bars], name="ts"),
    ).sort_index()


def build_labeled_dataset(
    bars: list,
    *,
    fast: int = 20,
    slow: int = 100,
    vol_window: int = 48,
    vertical_bars: int = 24,
    pt_sl: tuple[float, float] = (1.0, 1.0),
    symbol: str = "BTC",
):
    """Return (X: DataFrame, y: Series, w: Series, spans: Series).

    ``pt_sl`` is in units of horizon volatility (per-bar vol scaled by sqrt(vertical)),
    so a 1.0 take-profit means "one typical move over the holding window".
    """
    df = _bars_to_frame(bars)
    close = df["close"]

    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    ret = np.log(close).diff()
    ret_vol = ret.rolling(vol_window).std()

    feats = pd.DataFrame(index=df.index)
    feats["ema_spread"] = (ema_fast - ema_slow) / close
    feats["conviction"] = (feats["ema_spread"].abs() / ret_vol).replace([np.inf, -np.inf], np.nan)
    feats["ret_vol"] = ret_vol
    feats["vol_ratio"] = ret_vol / ret_vol.rolling(7 * 24).mean()
    feats["mom_fast"] = close.pct_change(fast)
    feats["mom_slow"] = close.pct_change(slow)
    feats["dist_high"] = (close - df["high"].rolling(vol_window).max()) / close
    feats["dist_low"] = (close - df["low"].rolling(vol_window).min()) / close
    feats["hour"] = df.index.hour
    feats["dow"] = df.index.dayofweek

    side = np.sign(feats["ema_spread"]).rename("side")

    # Valid events: features fully warm and a non-flat primary side.
    valid = feats[FEATURE_COLUMNS].notna().all(axis=1) & (side != 0)
    events = df.index[valid]

    horizon_vol = (ret_vol * np.sqrt(vertical_bars)).rename("hv")
    vertical = pd.Timedelta(df.index[1] - df.index[0]) * vertical_bars
    labels = triple_barrier_labels(
        prices=close, events=events, pt_sl=pt_sl, vertical=vertical,
        symbol=Symbol(symbol), target_vol=horizon_vol, sides=side,
    )
    if not labels:
        empty = pd.DataFrame(columns=FEATURE_COLUMNS)
        return empty, pd.Series(dtype=float), pd.Series(dtype=float), pd.Series(dtype="datetime64[ns, UTC]")

    w = concurrency_weights(labels, close)
    ev_idx = pd.DatetimeIndex([pd.Timestamp(lab.event_ts) for lab in labels])
    X = feats.loc[ev_idx, FEATURE_COLUMNS]
    y = pd.Series([lab.meta["correct"] for lab in labels], index=ev_idx, name="correct")
    weights = pd.Series(w, index=ev_idx, name="w")
    spans = pd.Series([pd.Timestamp(lab.touch_ts) for lab in labels], index=ev_idx, name="span_end")
    return X, y, weights, spans
