"""Feature importance with substitution awareness — MDA (§4.6).

Mean Decrease Accuracy: shuffle one feature's values within the OOS folds and
measure the drop in performance. Unlike impurity-based importance, MDA is computed
out-of-sample and is robust to substitution effects when paired with feature
clustering (correlated features otherwise split credit and both look unimportant).
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def mda_importance(make_model, X: pd.DataFrame, y: pd.Series, splits, sample_weight=None,
                   repeats: int = 3, seed: int = 0) -> pd.DataFrame:
    """Per-feature MDA across CV folds. Returns mean + std importance per feature.

    ``make_model`` is a zero-arg factory returning a fresh estimator; ``splits`` is an
    iterable of (train_idx, test_idx) positional arrays (e.g. from PurgedKFold). For
    each fold: fit on train, score AUC on test, then permute each feature column and
    measure the AUC drop. Computed inside purged CV used for evaluation (§4.4, NFR3).
    """
    from sklearn.metrics import roc_auc_score

    rng = np.random.default_rng(seed)
    per_feature: dict[str, list[float]] = {c: [] for c in X.columns}
    for tr, te in splits:
        ytr, yte = y.iloc[tr].to_numpy(), y.iloc[te].to_numpy()
        if len(np.unique(ytr)) < 2 or len(np.unique(yte)) < 2:
            continue
        model = make_model()
        kw = {"sample_weight": sample_weight.iloc[tr].to_numpy()} if sample_weight is not None else {}
        model.fit(X.iloc[tr].to_numpy(), ytr, **kw)
        Xte = X.iloc[te].to_numpy()
        base = roc_auc_score(yte, model.predict_proba(Xte)[:, 1])
        for j, col in enumerate(X.columns):
            drops = []
            for _ in range(repeats):
                Xp = Xte.copy()
                Xp[:, j] = rng.permutation(Xp[:, j])
                drops.append(base - roc_auc_score(yte, model.predict_proba(Xp)[:, 1]))
            per_feature[col].append(float(np.mean(drops)))

    rows = {c: (float(np.mean(v)) if v else 0.0, float(np.std(v)) if v else 0.0)
            for c, v in per_feature.items()}
    return (
        pd.DataFrame(rows, index=["mean", "std"]).T.sort_values("mean", ascending=False)
    )
