"""Combinatorial Purged Cross-Validation + Probability of Backtest Overfitting (§4.2).

Instead of one train/test split, CPCV forms many by choosing k of N purged groups
as the test set in all combinations. This yields a *distribution* of OOS backtest
paths rather than a single number, and lets us estimate PBO — the probability that
the strategy that looked best in-sample is below median out-of-sample. High PBO =
the "edge" is an overfit artifact (López de Prado, AFML ch. 11–12).
"""

from __future__ import annotations

from typing import Iterator

import numpy as np
import pandas as pd


class CombinatorialPurgedCV:
    def __init__(self, n_groups: int = 6, n_test_groups: int = 2, embargo_pct: float = 0.01) -> None:
        self.n_groups = n_groups
        self.n_test_groups = n_test_groups
        self.embargo_pct = embargo_pct

    def split(
        self, X: pd.DataFrame, label_spans: pd.Series
    ) -> Iterator[tuple[np.ndarray, np.ndarray]]:
        """Yield (train_idx, test_idx) for every C(n_groups, n_test_groups) combination,
        purged + embargoed as in PurgedKFold."""
        raise NotImplementedError("enumerate group combinations; purge+embargo each split")

    def n_paths(self) -> int:
        """Number of distinct OOS backtest paths this configuration produces."""
        raise NotImplementedError("comb(n_groups, n_test_groups) -> recombined into paths")


def probability_of_backtest_overfitting(
    in_sample_perf: np.ndarray, out_sample_perf: np.ndarray
) -> float:
    """PBO via the rank-logit method over CPCV splits (AFML ch. 11).

    For each split, take the config that ranked best in-sample; record whether it
    fell below the OOS median. PBO = fraction of splits where it did.
    """
    raise NotImplementedError("rank IS winners; measure OOS rank; logit-aggregate -> PBO in [0,1]")
