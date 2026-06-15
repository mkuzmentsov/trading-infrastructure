"""Feature importance with substitution awareness — MDA (§4.6).

Mean Decrease Accuracy: shuffle one feature's values within the OOS folds and
measure the drop in performance. Unlike impurity-based importance, MDA is computed
out-of-sample and is robust to substitution effects when paired with feature
clustering (correlated features otherwise split credit and both look unimportant).
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def mda_importance(model, X: pd.DataFrame, y: pd.Series, cv, sample_weight=None) -> pd.DataFrame:
    """Per-feature MDA across CV folds. Returns mean + std importance per feature.

    Computed inside the same purged CV used for evaluation (§4.4, NFR3).
    """
    raise NotImplementedError(
        "for each purged fold: score baseline; for each feature: permute column, rescore; "
        "importance = baseline - permuted; aggregate mean/std across folds."
    )
