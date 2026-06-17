"""Meta-label model training under purged CV (§3, §4, principle #3, #11).

Fits a gradient-boosted tree (sklearn HistGradientBoostingClassifier — GBTs first,
DL deferred) to predict the binary meta-label (was the primary side correct?), and
evaluates it OUT-OF-SAMPLE inside purged & embargoed folds so the AUC is leakage-free.

The decisive question this answers cheaply (fail-fast): does the model have *any* OOS
predictive power over the triple-barrier outcome? If pooled OOS AUC ≈ 0.5, the meta
layer cannot help the baseline and must not be wired into the book (principle #4).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from ..validation.purged_cv import PurgedKFold


@dataclass
class MetaLabelResult:
    oos_auc: float                       # pooled out-of-sample ROC-AUC
    fold_aucs: list[float]
    base_rate: float                     # P(correct) — the no-skill baseline
    n_samples: int
    n_features: int
    importances: pd.Series = field(default_factory=lambda: pd.Series(dtype=float))  # MDA, OOS

    def summary(self) -> str:
        edge = self.oos_auc - 0.5
        verdict = "SIGNAL" if self.oos_auc >= 0.53 else "NO OOS EDGE"
        top = ", ".join(f"{k}={v:+.3f}" for k, v in self.importances.head(5).items())
        return (
            f"OOS AUC={self.oos_auc:.3f} (edge {edge:+.3f}) [{verdict}]  "
            f"base_rate={self.base_rate:.1%}  n={self.n_samples}\n"
            f"top MDA features: {top}"
        )


def _make_model(seed: int = 0):
    from sklearn.ensemble import HistGradientBoostingClassifier

    return HistGradientBoostingClassifier(
        max_depth=3, max_iter=200, learning_rate=0.05,
        l2_regularization=1.0, early_stopping=False, random_state=seed,
    )


def train_meta_label_cv(
    X: pd.DataFrame,
    y: pd.Series,
    weights: pd.Series | None,
    label_spans: pd.Series,
    *,
    n_splits: int = 6,
    embargo_pct: float = 0.01,
    seed: int = 0,
    mda_repeats: int = 3,
) -> MetaLabelResult:
    """Fit + evaluate the meta-label model under purged CV; return OOS AUC + MDA."""
    from sklearn.metrics import roc_auc_score

    X = X.sort_index()
    y = y.reindex(X.index)
    spans = label_spans.reindex(X.index)
    w = weights.reindex(X.index) if weights is not None else None

    cv = PurgedKFold(n_splits=n_splits, embargo_pct=embargo_pct)
    rng = np.random.default_rng(seed)
    oos_pred = pd.Series(np.nan, index=X.index)
    fold_aucs: list[float] = []
    imp_accum = pd.Series(0.0, index=X.columns)
    imp_folds = 0

    for tr, te in cv.split(X, spans):
        if len(tr) < 50 or len(te) < 20:
            continue
        ytr = y.iloc[tr]
        if ytr.nunique() < 2:
            continue
        model = _make_model(seed)
        fit_kw = {"sample_weight": w.iloc[tr].to_numpy()} if w is not None else {}
        model.fit(X.iloc[tr].to_numpy(), ytr.to_numpy(), **fit_kw)

        Xte = X.iloc[te].to_numpy()
        yte = y.iloc[te].to_numpy()
        p = model.predict_proba(Xte)[:, 1]
        oos_pred.iloc[te] = p
        if len(np.unique(yte)) == 2:
            base_auc = roc_auc_score(yte, p)
            fold_aucs.append(float(base_auc))
            # MDA: permute each feature on the test fold, measure AUC drop (OOS).
            for j, col in enumerate(X.columns):
                drops = []
                for _ in range(mda_repeats):
                    Xp = Xte.copy()
                    Xp[:, j] = rng.permutation(Xp[:, j])
                    drops.append(base_auc - roc_auc_score(yte, model.predict_proba(Xp)[:, 1]))
                imp_accum[col] += float(np.mean(drops))
            imp_folds += 1

    mask = oos_pred.notna() & y.notna()
    pooled = oos_pred[mask]
    ypool = y[mask]
    oos_auc = float(roc_auc_score(ypool, pooled)) if ypool.nunique() == 2 else 0.5
    importances = (imp_accum / imp_folds).sort_values(ascending=False) if imp_folds else imp_accum

    return MetaLabelResult(
        oos_auc=oos_auc,
        fold_aucs=fold_aucs,
        base_rate=float(y.mean()),
        n_samples=int(mask.sum()),
        n_features=X.shape[1],
        importances=importances,
    )
