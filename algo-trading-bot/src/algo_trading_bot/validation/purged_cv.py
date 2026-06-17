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
        """Yield (train_idx, test_idx) positional arrays with overlapping train labels
        purged and an embargo applied after each test fold.

        ``X`` is indexed by event time (sorted). ``label_spans`` maps each event's
        index -> the end time of its label window, so overlap can be detected.
        """
        n = len(X)
        if n == 0:
            return
        idx = X.index
        spans = label_spans.reindex(idx)
        embargo = int(n * self.embargo_pct)
        bounds = np.linspace(0, n, self.n_splits + 1).astype(int)

        for k in range(self.n_splits):
            lo, hi = bounds[k], bounds[k + 1]
            if hi <= lo:
                continue
            test_pos = np.arange(lo, hi)
            test_start = idx[lo]
            test_end = idx[hi - 1]

            # Purge: drop train samples whose label span [t, span[t]] overlaps the test
            # window [test_start, test_end]. Embargo: also drop the `embargo` samples
            # immediately after the test block (serial-correlation leakage).
            embargo_end = idx[min(hi - 1 + embargo, n - 1)]
            keep = []
            for i in range(n):
                if lo <= i < hi:
                    continue
                t = idx[i]
                span_end = spans.iloc[i]
                if pd.isna(span_end):
                    continue
                overlaps = (t <= test_end) and (span_end >= test_start)
                in_embargo = test_end < t <= embargo_end
                if overlaps or in_embargo:
                    continue
                keep.append(i)
            yield np.array(keep, dtype=int), test_pos
