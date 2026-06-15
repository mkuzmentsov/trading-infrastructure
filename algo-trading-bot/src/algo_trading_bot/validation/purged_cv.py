"""Purged & embargoed K-fold CV — mandatory (§4.1).

Financial labels overlap in time (a triple-barrier label spans [event, touch]). If
a train sample's label window overlaps the test window, information leaks and every
metric is inflated. So: PURGE train samples whose label spans intersect the test
fold, and EMBARGO a small gap after the test fold to kill serial-correlation leakage
(López de Prado, AFML ch. 7).

All tuning — feature selection, hyperparameters — happens INSIDE these folds, never
on the full set (§4.4, NFR3).
"""

from __future__ import annotations

from typing import Iterator

import numpy as np
import pandas as pd


class PurgedKFold:
    def __init__(self, n_splits: int = 6, embargo_pct: float = 0.01) -> None:
        self.n_splits = n_splits
        self.embargo_pct = embargo_pct

    def split(
        self, X: pd.DataFrame, label_spans: pd.Series
    ) -> Iterator[tuple[np.ndarray, np.ndarray]]:
        """Yield (train_idx, test_idx) with overlapping train labels purged and an
        embargo applied after each test fold.

        ``label_spans`` maps each sample's index -> the end time of its label window,
        so overlap can be detected.
        """
        raise NotImplementedError(
            "partition into n_splits contiguous test folds; for each, drop train samples "
            "whose [t, label_span[t]] intersects the test window; embargo embargo_pct after."
        )
