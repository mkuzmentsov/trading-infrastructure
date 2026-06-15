"""Walk-forward with periodic retraining (§4.5).

Mirrors the live model lifecycle: train on a rolling/expanding window, trade the
next out-of-sample block, retrain, repeat. This is the closest backtest analogue to
production and the one that exposes edge decay (principle #10).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta


@dataclass
class WalkForwardConfig:
    train_window: timedelta
    test_window: timedelta
    retrain_every: timedelta
    expanding: bool = False  # True = anchored/expanding, False = rolling


class WalkForward:
    def __init__(self, config: WalkForwardConfig) -> None:
        self.config = config

    def run(self, dataset, fit_fn, eval_fn) -> list:
        """Slide the window; at each step fit on train, evaluate OOS on the next block.
        Returns the per-block OOS results (stitched into the walk-forward equity curve)."""
        raise NotImplementedError("generate train/test blocks; fit_fn then eval_fn per block")
