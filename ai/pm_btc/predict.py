"""Inference helper for the live bot.

Import and call:
    from pm_btc.predict import MLSignal
    signal = MLSignal(model_path="/app/data/pm_btc_model.txt")
    p_up = signal.predict_p_up(snapshot_dict)

The snapshot dict must have the same shape the bot already writes to
logs-training.jsonl — btc.bar_open, btc.current_price, btc.ret_30s, pm.up_ask,
etc. This keeps training data and inference inputs identical.
"""
from __future__ import annotations

import os
import sys
from typing import Any, Optional

sys.path.insert(0, os.path.dirname(__file__))
from features import FEATURE_COLUMNS, extract_features  # noqa: E402


class MLSignal:
    """Loads a LightGBM booster and exposes a predict_p_up(snapshot) helper.

    Import is deferred so the bot's hot path isn't blocked by lightgbm loading
    if the env flag isn't set.
    """

    def __init__(self, model_path: str):
        try:
            import lightgbm as lgb
        except ImportError as e:
            raise RuntimeError("lightgbm is required for ML inference") from e
        self._booster = lgb.Booster(model_file=model_path)
        self._model_path = model_path

    def predict_p_up(self, snapshot: dict[str, Any]) -> Optional[float]:
        feats = extract_features(snapshot)
        if feats is None:
            return None
        row = [[feats[col] for col in FEATURE_COLUMNS]]
        pred = self._booster.predict(row)
        return float(pred[0])
