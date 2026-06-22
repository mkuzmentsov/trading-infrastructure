"""Walk-forward with periodic retraining (§4.5).

Mirrors the live model lifecycle: train on a rolling/expanding window, trade the
next out-of-sample block, retrain, repeat. This is the closest backtest analogue to
production and the one that exposes edge decay (principle #10).

For a *no-fit* strategy (fixed, pre-committed params) ``fit_fn`` is a no-op, so the run
becomes a pure period-robustness pass: the same strategy is scored on every sequential OOS
block, exposing whether the edge holds across regimes or lives in one favorable window.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

import pandas as pd


@dataclass
class WalkForwardConfig:
    train_window: timedelta
    test_window: timedelta
    retrain_every: timedelta
    expanding: bool = False  # True = anchored/expanding, False = rolling


@dataclass
class WalkForwardBlock:
    train_start: pd.Timestamp
    train_end: pd.Timestamp
    test_start: pd.Timestamp
    test_end: pd.Timestamp
    state: object          # whatever fit_fn returned (params / model / config)
    result: object         # whatever eval_fn returned (typically the OOS return series)


class WalkForward:
    def __init__(self, config: WalkForwardConfig) -> None:
        self.config = config

    def blocks(self, index: pd.DatetimeIndex) -> list[tuple]:
        """(train_start, train_end, test_start, test_end) tuples sliding across ``index``.
        Rolling by default; anchored/expanding when ``config.expanding``."""
        c = self.config
        index = pd.DatetimeIndex(index).sort_values()
        t0, tend = index[0], index[-1]
        out = []
        test_start = t0 + c.train_window
        while test_start < tend:
            train_start = t0 if c.expanding else max(t0, test_start - c.train_window)
            test_end = min(test_start + c.test_window, tend)
            out.append((train_start, test_start, test_start, test_end))
            test_start = test_start + c.retrain_every
        return out

    def run(self, dataset, fit_fn, eval_fn) -> list[WalkForwardBlock]:
        """Slide the window; at each step fit on train, evaluate OOS on the next block. ``dataset``
        must expose a DatetimeIndex via ``.index``. ``fit_fn(train_start, train_end)`` returns a
        state; ``eval_fn(state, test_start, test_end)`` returns the OOS result (e.g. a return
        Series). A fixed strategy makes fit_fn a no-op -> pure period-robustness pass. One block per step."""
        out = []
        for tr_s, tr_e, te_s, te_e in self.blocks(dataset.index):
            state = fit_fn(tr_s, tr_e)
            result = eval_fn(state, te_s, te_e)
            out.append(WalkForwardBlock(tr_s, tr_e, te_s, te_e, state, result))
        return out
