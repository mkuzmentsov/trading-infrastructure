"""
LightGBM model loading and inference.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import lightgbm as lgb
import numpy as np
import pandas as pd

from config import MODEL_PATH, log

_booster: Optional[lgb.Booster] = None
_model_mtime: float = 0.0


def load_model() -> Optional[lgb.Booster]:
    global _booster, _model_mtime
    path = Path(MODEL_PATH)
    if not path.exists():
        log.warning("Model file not found at %s — running without predictions", MODEL_PATH)
        return None
    mtime = path.stat().st_mtime
    if _booster is None or mtime != _model_mtime:
        log.info("Loading model from %s …", MODEL_PATH)
        _booster = lgb.Booster(model_file=str(path))
        _model_mtime = mtime
        log.info("Model loaded (%d trees)", _booster.num_trees())
    return _booster


def predict_up_probability(features: pd.Series) -> float:
    """Returns P(BTC UP) in [0, 1], or 0.5 if model unavailable."""
    booster = load_model()
    if booster is None:
        return 0.5
    x = features.values.reshape(1, -1)
    prob = booster.predict(x)[0]
    return float(prob)
