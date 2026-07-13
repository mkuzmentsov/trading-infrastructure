"""cur+2 direction predictor for the live 50c experiment. Loads the frozen sklearn
models (embedded in cur2_models.py) and computes p_up from recent Binance 5m klines.
Feature spec MUST match backtest/fiftycent/train_export.features() exactly.
Requires numpy + pandas + scikit-learn (present in generic-crypto-image)."""
from __future__ import annotations

import base64
import json
import pickle
import urllib.request

import numpy as np
import pandas as pd

from strategy.cur2_models import MODELS_B64

LAGS = [1, 2, 3, 6, 12, 24]
_BINANCE = ["https://api.binance.com", "https://data-api.binance.vision"]
_models: dict = {}


def _load():
    if not _models:
        for coin, b64 in MODELS_B64.items():
            _models[coin] = pickle.loads(base64.b64decode(b64))
    return _models


def compute_features(d: pd.DataFrame) -> pd.DataFrame:
    d = d.copy()
    d["y"] = (d["close"] >= d["open"]).astype(int)
    d["clc"] = d["close"].pct_change()
    d["range"] = (d["high"] - d["low"]) / d["open"]
    d["tbr"] = (d["takerBuyBase"] / d["volume"].replace(0, np.nan)) - 0.5
    dt = pd.to_datetime(d["openTime"], unit="ms"); d["hour"] = dt.dt.hour
    F = {}
    for k in LAGS:
        F[f"clc{k}"] = d["clc"].shift(k); F[f"y{k}"] = d["y"].shift(k) - 0.5
    F["mom3"] = d["clc"].rolling(3).sum().shift(1); F["mom6"] = d["clc"].rolling(6).sum().shift(1)
    F["mom12"] = d["clc"].rolling(12).sum().shift(1)
    v = d["clc"].rolling(12).std().shift(1); F["vol12"] = v
    F["zmom6"] = d["clc"].rolling(6).sum().shift(1) / (v * np.sqrt(6)); F["revert"] = -d["clc"].shift(1) / v
    F["rng6"] = d["range"].rolling(6).mean().shift(1)
    F["tbr1"] = d["tbr"].shift(1); F["tbr3"] = d["tbr"].rolling(3).mean().shift(1)
    F["volz"] = ((d["volume"] - d["volume"].rolling(48).mean()) / d["volume"].rolling(48).std()).shift(1)
    F["hsin"] = np.sin(2 * np.pi * d["hour"] / 24); F["hcos"] = np.cos(2 * np.pi * d["hour"] / 24)
    return pd.DataFrame(F, index=d.index)


def fetch_klines(coin: str, limit: int = 200) -> pd.DataFrame | None:
    sym = f"{coin.upper()}USDT"
    import time
    for base in _BINANCE:
        try:
            url = f"{base}/api/v3/klines?symbol={sym}&interval=5m&limit={limit}"
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            raw = json.loads(urllib.request.urlopen(req, timeout=10).read())
            now = time.time() * 1000
            rows = [k for k in raw if k[6] < now]           # closed bars only
            return pd.DataFrame({
                "openTime": [int(k[0]) for k in rows],
                "open": [float(k[1]) for k in rows], "high": [float(k[2]) for k in rows],
                "low": [float(k[3]) for k in rows], "close": [float(k[4]) for k in rows],
                "volume": [float(k[5]) for k in rows], "closeTime": [int(k[6]) for k in rows],
                "takerBuyBase": [float(k[9]) for k in rows],
            })
        except Exception:
            continue
    return None


def predict(coin: str, klines: pd.DataFrame | None = None) -> float | None:
    """p_up for the cur+2 bar. Returns None if model/coin unavailable or data short."""
    m = _load().get(coin)
    if m is None:
        return None
    if klines is None:
        klines = fetch_klines(coin)
    if klines is None or len(klines) < 60:
        return None
    feats = compute_features(klines)[m["features"]].iloc[[-1]]
    if feats.isnull().any(axis=1).iloc[0]:
        return None
    return float(m["model"].predict_proba(feats.values)[0, 1])


def predict_recent(coin: str, n: int = 288) -> list[float]:
    """p_up over the last ~n closed bars — used to seed the bettor's rolling debias
    center so it's calibrated from the first live bar. Returns [] if unavailable."""
    m = _load().get(coin)
    if m is None:
        return []
    klines = fetch_klines(coin, limit=min(1000, n + 80))
    if klines is None or len(klines) < 60:
        return []
    feats = compute_features(klines)[m["features"]].dropna()
    if feats.empty:
        return []
    p = m["model"].predict_proba(feats.values)[:, 1]
    return [float(x) for x in p[-n:]]
