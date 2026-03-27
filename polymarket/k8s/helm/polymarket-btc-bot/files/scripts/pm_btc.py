"""
Polymarket BTC direction bot.

Strategy:
  1. Fetch live BTC/USDT 1-min OHLCV from Binance (via ccxt).
  2. Compute the same 107 features as generate_features.py.
  3. Run a pre-trained LightGBM model → P(BTC UP in N minutes).
  4. Scan Polymarket for active BTC price-direction markets.
  5. Bet small amounts whenever model edge > MIN_EDGE.
  6. Size via quarter-Kelly, capped at BET_SIZE_MAX.

Environment variables (injected by K8s Secret):
  MODEL_PATH            path to LightGBM .txt model (default /app/data/model.txt)
  DRY_RUN               "true" / "false"
  MIN_EDGE              min edge to bet (default 0.05 = 5pp)
  BET_SIZE_MIN          min bet in USDC (default 0.50)
  BET_SIZE_MAX          max bet in USDC (default 5.00)
  LOOP_INTERVAL_SECS    seconds between cycles (default 300)
  POLYMARKET_PK         hex private key
  POLYMARKET_ADDRESS    wallet address
  POLYMARKET_API_KEY / _SECRET / _PASSPHRASE
  POLYMARKET_SIGNATURE_TYPE  0=EOA, 2=Gnosis Safe
  POLYMARKET_FUNDER     Safe address (if type=2)
  TELEGRAM_TOKEN / TELEGRAM_CHAT_ID
  DATA_DIR              persistent data directory (default /app/data)
"""

from __future__ import annotations

import json
import logging
import math
import os
import time
import warnings
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import ccxt
import eth_abi
import lightgbm as lgb
import numpy as np
import pandas as pd
import pandas_ta as ta
import requests

warnings.filterwarnings("ignore")

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("pm_btc")

# Silence noisy third-party loggers that flood DEBUG output
logging.getLogger("ccxt").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)

# ── Config from env ───────────────────────────────────────────────────────────
MODEL_PATH         = os.getenv("MODEL_PATH",         "/app/data/model.txt")
DATA_DIR           = Path(os.getenv("DATA_DIR",      "/app/data"))
DRY_RUN            = os.getenv("DRY_RUN",            "true").lower() == "true"
MIN_EDGE           = float(os.getenv("MIN_EDGE",     "0.05"))
BET_SIZE_MIN       = float(os.getenv("BET_SIZE_MIN", "0.50"))
BET_SIZE_MAX       = float(os.getenv("BET_SIZE_MAX", "5.00"))
LOOP_INTERVAL      = int(os.getenv("LOOP_INTERVAL_SECS", "300"))

POLYMARKET_PK       = os.getenv("POLYMARKET_PK",      "")
POLYMARKET_ADDRESS  = os.getenv("POLYMARKET_ADDRESS",  "")
POLYMARKET_API_KEY  = os.getenv("POLYMARKET_API_KEY",  "")
POLYMARKET_API_SECRET     = os.getenv("POLYMARKET_API_SECRET",     "")
POLYMARKET_API_PASSPHRASE = os.getenv("POLYMARKET_API_PASSPHRASE", "")
SIGNATURE_TYPE      = int(os.getenv("POLYMARKET_SIGNATURE_TYPE", "0"))
POLYMARKET_FUNDER   = os.getenv("POLYMARKET_FUNDER",   "")

TELEGRAM_TOKEN   = os.getenv("TELEGRAM_TOKEN",  "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID","")

GAMMA_API  = "https://gamma-api.polymarket.com"
CLOB_HOST  = "https://clob.polymarket.com"
DATA_API   = "https://data-api.polymarket.com"
CHAIN_ID   = 137   # Polygon

CTF_CONTRACT = "0x4D97DCd97eC945f40cF65F87097ACe5EA0476045"  # ConditionalTokens on Polygon
USDC_ADDRESS = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"  # USDC.e on Polygon
POLYGON_RPC  = os.getenv("POLYGON_RPC_URL", "https://rpc.ankr.com/polygon")

CANDLES_NEEDED = 350  # warm-up buffer for longest indicator lookbacks

# ── Feature engineering (mirrors generate_features.py exactly) ────────────────

EPS = 1e-9


def _safe_div(a: pd.Series, b: pd.Series) -> pd.Series:
    return a / b.replace(0, np.nan)


def _add_price(df: pd.DataFrame) -> pd.DataFrame:
    c, o, h, l = df["close"], df["open"], df["high"], df["low"]
    for n in [1, 5, 15, 30, 60, 240]:
        df[f"ret_{n}m"]     = c.pct_change(n)
        df[f"log_ret_{n}m"] = np.log(c / c.shift(n))
    body = c - o
    hl   = (h - l).replace(0, np.nan)
    df["body_ratio"]       = body / o
    df["hl_range_ratio"]   = hl / c
    df["upper_wick_ratio"] = (h - np.maximum(o, c)) / hl
    df["lower_wick_ratio"] = (np.minimum(o, c) - l) / hl
    df["open_gap"]         = (o - c.shift(1)) / c.shift(1)
    return df


def _add_ma(df: pd.DataFrame) -> pd.DataFrame:
    c = df["close"]
    sma, ema = {}, {}
    for p in [7, 14, 20, 50, 100, 200]:
        sma[p] = c.rolling(p).mean()
        df[f"sma{p}_ratio"] = _safe_div(c, sma[p]) - 1
    for p in [9, 21, 50, 200]:
        ema[p] = c.ewm(span=p, adjust=False).mean()
        df[f"ema{p}_ratio"] = _safe_div(c, ema[p]) - 1
    df["ema9_x_ema21"]       = (ema[9]  > ema[21]).astype(int)
    df["ema21_x_ema50"]      = (ema[21] > ema[50]).astype(int)
    df["ema50_x_ema200"]     = (ema[50] > ema[200]).astype(int)
    df["ema9_ema21_spread"]  = _safe_div(ema[9]  - ema[21],  c)
    df["ema21_ema50_spread"] = _safe_div(ema[21] - ema[50],  c)
    df["ema50_ema200_spread"]= _safe_div(ema[50] - ema[200], c)
    return df


def _add_momentum(df: pd.DataFrame) -> pd.DataFrame:
    c, h, l = df["close"], df["high"], df["low"]
    for p in [7, 14, 21]:
        rsi = ta.rsi(c, length=p)
        df[f"rsi{p}"] = rsi / 100.0 if rsi is not None else np.nan
    macd_df = ta.macd(c, fast=12, slow=26, signal=9)
    if macd_df is not None:
        df["macd"]        = _safe_div(macd_df.iloc[:, 0], c)
        df["macd_signal"] = _safe_div(macd_df.iloc[:, 2], c)
        df["macd_hist"]   = _safe_div(macd_df.iloc[:, 1], c)
    stoch = ta.stoch(h, l, c, k=14, d=3, smooth_k=3)
    if stoch is not None:
        df["stoch_k"] = stoch.iloc[:, 0] / 100.0
        df["stoch_d"] = stoch.iloc[:, 1] / 100.0
    cci = ta.cci(h, l, c, length=20)
    if cci is not None:
        df["cci20"] = cci / 200.0
    willr = ta.willr(h, l, c, length=14)
    if willr is not None:
        df["willr14"] = (willr + 100) / 100.0
    for p in [10, 20]:
        roc = ta.roc(c, length=p)
        df[f"roc{p}"] = roc / 100.0 if roc is not None else np.nan
        df[f"mom{p}"] = _safe_div(c - c.shift(p), c.shift(p))
    return df


def _add_volatility(df: pd.DataFrame) -> pd.DataFrame:
    c, h, l, o = df["close"], df["high"], df["low"], df["open"]
    for p in [7, 14, 21]:
        atr = ta.atr(h, l, c, length=p)
        if atr is not None:
            df[f"atr{p}_ratio"] = _safe_div(atr, c)
    bb = ta.bbands(c, length=20, std=2)
    if bb is not None:
        df["bb_width"] = _safe_div(bb.iloc[:, 0] - bb.iloc[:, 2], c)
        df["bb_pct"]   = bb.iloc[:, 1]
        df["bb_pos"]   = _safe_div(c - bb.iloc[:, 2], bb.iloc[:, 0] - bb.iloc[:, 2])
    log_ret = np.log(c / c.shift(1))
    for p in [20, 60, 120]:
        df[f"hvol{p}"] = log_ret.rolling(p).std() * np.sqrt(1440)
    log_hl = np.log(h / l)
    log_co = np.log(c / o)
    gk = 0.5 * log_hl**2 - (2 * np.log(2) - 1) * log_co**2
    df["gk_vol20"] = gk.rolling(20).mean().apply(np.sqrt) * np.sqrt(1440)
    ema20  = c.ewm(span=20, adjust=False).mean()
    atr14  = ta.atr(h, l, c, length=14)
    if atr14 is not None:
        kc_u = ema20 + 2 * atr14
        kc_l = ema20 - 2 * atr14
        df["kc_pos"] = _safe_div(c - kc_l, kc_u - kc_l)
    return df


def _add_volume(df: pd.DataFrame) -> pd.DataFrame:
    c, h, l, v = df["close"], df["high"], df["low"], df["volume"]
    t = df["trades"]
    for p in [10, 20, 50]:
        df[f"vol_ratio{p}"] = _safe_div(v, v.rolling(p).mean())
    df["avg_trade_size"] = _safe_div(v, t)
    for p in [10, 20]:
        df[f"trades_ratio{p}"] = _safe_div(t, t.rolling(p).mean())
    avg_ts = df["avg_trade_size"].rolling(20).mean()
    std_ts = df["avg_trade_size"].rolling(20).std()
    df["avg_trade_size_z"] = _safe_div(df["avg_trade_size"] - avg_ts, std_ts)
    obv = ta.obv(c, v)
    if obv is not None:
        df["obv_ratio"] = _safe_div(obv, obv.rolling(50).mean()) - 1
    tp = (h + l + c) / 3
    vwap60 = (tp * v).rolling(60).sum() / v.rolling(60).sum()
    df["vwap60_dev"] = _safe_div(c - vwap60, c)
    mfi = ta.mfi(h, l, c, v, length=14)
    if mfi is not None:
        df["mfi14"] = mfi / 100.0
    cmf = ta.cmf(h, l, c, v, length=20)
    if cmf is not None:
        df["cmf20"] = cmf
    # Volume-weighted price trend slope
    x = np.arange(20)
    stacked20 = pd.concat([np.log(c), v], axis=1).values

    def _vwt_slope20(y_v):
        y, w = y_v[:20], y_v[20:]
        w = w / (w.sum() + EPS)
        xw = (x * w).sum(); yw = (y * w).sum()
        x2w = ((x**2) * w).sum()
        return (((x - xw) * w * (y - yw)).sum()) / (((x - xw)**2 * w).sum() + EPS)

    slopes20 = pd.Series(
        [_vwt_slope20(np.concatenate([stacked20[i:i+20, 0], stacked20[i:i+20, 1]]))
         for i in range(len(stacked20) - 19)],
        index=df.index[19:],
    )
    df["vwt_slope20"] = slopes20

    x60 = np.arange(60)
    stacked60 = stacked20

    def _vwt_slope60(y_v):
        y, w = y_v[:60], y_v[60:]
        w = w / (w.sum() + EPS)
        xw = (x60 * w).sum(); yw = (y * w).sum()
        return (((x60 - xw) * w * (y - yw)).sum()) / (((x60 - xw)**2 * w).sum() + EPS)

    slopes60 = pd.Series(
        [_vwt_slope60(np.concatenate([stacked60[i:i+60, 0], stacked60[i:i+60, 1]]))
         for i in range(len(stacked60) - 59)],
        index=df.index[59:],
    )
    df["vwt_slope60"] = slopes60
    return df


def _add_trend(df: pd.DataFrame) -> pd.DataFrame:
    c, h, l = df["close"], df["high"], df["low"]
    adx_df = ta.adx(h, l, c, length=14)
    if adx_df is not None:
        df["adx14"]    = adx_df.iloc[:, 0] / 100.0
        df["dmp14"]    = adx_df.iloc[:, 1] / 100.0
        df["dmn14"]    = adx_df.iloc[:, 2] / 100.0
        df["di_diff14"]= df["dmp14"] - df["dmn14"]
    ichi = ta.ichimoku(h, l, c, tenkan=9, kijun=26, senkou=52)
    if ichi is not None and len(ichi) == 2:
        ichi_df = ichi[0]
        for col in ichi_df.columns:
            label = col.split("_")[0].lower()
            df[f"ichi_{label}"] = _safe_div(ichi_df[col] - c, c)
    return df


def _add_statistical(df: pd.DataFrame) -> pd.DataFrame:
    c = df["close"]
    log_ret = np.log(c / c.shift(1))
    for p in [20, 60]:
        df[f"ret_skew{p}"] = log_ret.rolling(p).skew()
        df[f"ret_kurt{p}"] = log_ret.rolling(p).kurt()
        df[f"close_z{p}"]  = (c - c.rolling(p).mean()) / (c.rolling(p).std() + EPS)
    for p in [20, 60]:
        df[f"ret_ac1_{p}"] = log_ret.rolling(p).apply(
            lambda x: pd.Series(x).autocorr(lag=1), raw=False
        )
    for p in [30, 60]:
        df[f"ret_range{p}"] = (
            log_ret.rolling(p).max() - log_ret.rolling(p).min()
        )
    return df


def _add_time(df: pd.DataFrame, dt_col: pd.Series) -> pd.DataFrame:
    df["hour"]       = dt_col.dt.hour
    df["dow"]        = dt_col.dt.dayofweek
    df["is_weekend"] = (df["dow"] >= 5).astype(int)
    df["hour_sin"]   = np.sin(2 * np.pi * df["hour"] / 24)
    df["hour_cos"]   = np.cos(2 * np.pi * df["hour"] / 24)
    df["dow_sin"]    = np.sin(2 * np.pi * df["dow"]  / 7)
    df["dow_cos"]    = np.cos(2 * np.pi * df["dow"]  / 7)

    def _session(h):
        if 0 <= h < 8:  return 0
        if 8 <= h < 15: return 1
        return 2

    df["session"] = df["hour"].map(_session)
    return df


def _add_mtf(df: pd.DataFrame, dt_series: pd.Series) -> pd.DataFrame:
    tmp = df.copy()
    tmp.index = dt_series
    for minutes in [5, 15, 60]:
        rule = f"{minutes}min"
        ohlcv = tmp[["open", "high", "low", "close", "volume"]].resample(
            rule, label="right", closed="right"
        ).agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}).dropna()
        c_tf, h_tf, l_tf = ohlcv["close"], ohlcv["high"], ohlcv["low"]
        rsi_tf = ta.rsi(c_tf, length=14)
        ema_tf = c_tf.ewm(span=21, adjust=False).mean()
        atr_tf = ta.atr(h_tf, l_tf, c_tf, length=14)
        mtf = pd.DataFrame({
            f"mtf_{minutes}m_rsi14":  rsi_tf / 100.0 if rsi_tf is not None else np.nan,
            f"mtf_{minutes}m_ema21_r": _safe_div(c_tf, ema_tf) - 1,
            f"mtf_{minutes}m_atr14_r": _safe_div(atr_tf, c_tf) if atr_tf is not None else np.nan,
        })
        mtf = mtf.reindex(tmp.index, method="ffill")
        for col in mtf.columns:
            df[col] = mtf[col].values
    return df


# Ordered feature list matching the trained model (107 features)
FEATURE_COLS = [
    # price
    "ret_1m","log_ret_1m","ret_5m","log_ret_5m","ret_15m","log_ret_15m",
    "ret_30m","log_ret_30m","ret_60m","log_ret_60m","ret_240m","log_ret_240m",
    "body_ratio","hl_range_ratio","upper_wick_ratio","lower_wick_ratio","open_gap",
    # MA
    "sma7_ratio","sma14_ratio","sma20_ratio","sma50_ratio","sma100_ratio","sma200_ratio",
    "ema9_ratio","ema21_ratio","ema50_ratio","ema200_ratio",
    "ema9_x_ema21","ema21_x_ema50","ema50_x_ema200",
    "ema9_ema21_spread","ema21_ema50_spread","ema50_ema200_spread",
    # momentum
    "rsi7","rsi14","rsi21","macd","macd_signal","macd_hist",
    "stoch_k","stoch_d","cci20","willr14","roc10","roc20","mom10","mom20",
    # volatility
    "atr7_ratio","atr14_ratio","atr21_ratio",
    "bb_width","bb_pct","bb_pos","hvol20","hvol60","hvol120","gk_vol20","kc_pos",
    # volume
    "vol_ratio10","vol_ratio20","vol_ratio50","avg_trade_size",
    "trades_ratio10","trades_ratio20","avg_trade_size_z",
    "obv_ratio","vwap60_dev","mfi14","cmf20","vwt_slope20","vwt_slope60",
    # trend
    "adx14","dmp14","dmn14","di_diff14",
    "ichi_isa","ichi_isb","ichi_its","ichi_iks","ichi_ics",
    # statistical
    "ret_skew20","ret_skew60","ret_kurt20","ret_kurt60",
    "close_z20","close_z60","ret_ac1_20","ret_ac1_60",
    "ret_range30","ret_range60",
    # time
    "hour","dow","is_weekend","hour_sin","hour_cos","dow_sin","dow_cos","session",
    # multi-timeframe
    "mtf_5m_rsi14","mtf_5m_ema21_r","mtf_5m_atr14_r",
    "mtf_15m_rsi14","mtf_15m_ema21_r","mtf_15m_atr14_r",
    "mtf_60m_rsi14","mtf_60m_ema21_r","mtf_60m_atr14_r",
]


def compute_features(ohlcv_df: pd.DataFrame) -> pd.Series:
    """
    Takes a DataFrame with columns [timestamp(unix s), open, high, low, close, volume, trades].
    Returns a Series with the feature vector for the LAST row.
    """
    df = ohlcv_df.copy().reset_index(drop=True)
    dt = pd.to_datetime(df["timestamp"], unit="s", utc=True)

    df = _add_price(df)
    df = _add_ma(df)
    df = _add_momentum(df)
    df = _add_volatility(df)
    df = _add_volume(df)
    df = _add_trend(df)
    df = _add_statistical(df)
    df = _add_time(df, dt)
    df = _add_mtf(df, dt)

    last = df.iloc[-1]
    # Ensure all feature cols exist (fill missing with NaN — LightGBM handles it)
    result = pd.Series({col: last.get(col, np.nan) for col in FEATURE_COLS})
    return result


# ── Live data ─────────────────────────────────────────────────────────────────

_exchange = ccxt.binance({"enableRateLimit": True})


def fetch_btc_ohlcv(n: int = CANDLES_NEEDED) -> pd.DataFrame:
    """Fetch last n 1-minute BTC/USDT candles from Binance."""
    raw = _exchange.fetch_ohlcv("BTC/USDT", timeframe="1m", limit=n)
    df = pd.DataFrame(raw, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df["timestamp"] = df["timestamp"] // 1000  # ms → seconds
    # Binance doesn't provide trade count; approximate from volume/close
    df["trades"] = (df["volume"] / df["close"] * 1000).round().astype(int).clip(lower=1)
    return df


# ── Model ─────────────────────────────────────────────────────────────────────

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


# ── Polymarket ─────────────────────────────────────────────────────────────────

def current_5m_slug() -> str:
    """Return the Gamma API slug for the current 5-minute BTC Up/Down market."""
    ts = (int(time.time()) // 300) * 300
    return f"btc-updown-5m-{ts}"


def _gamma_get(params: dict):
    """GET /markets from Gamma API with full request/response logging."""
    url = f"{GAMMA_API}/markets"
    log.info("Gamma API REQUEST  url=%s  params=%s", url, params)
    try:
        r = requests.get(url, params=params, timeout=15)
        log.info("Gamma API RESPONSE status=%d  url=%s  body=%s", r.status_code, r.url, r.text)
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        log.warning("Gamma API ERROR (params=%s): %s", params, exc)
        return None


def fetch_btc_5m_market() -> Optional[dict]:
    """
    Fetch the current BTC Up/Down 5-minute market by slug.
    Tries the current 5m boundary; if not found or already closed, tries the next one.
    Slug format: btc-updown-5m-{unix_timestamp_of_window_start}
    """
    for offset_secs in [0, 300]:
        ts   = (int(time.time()) // 300) * 300 + offset_secs
        slug = f"btc-updown-5m-{ts}"
        try:
            data = _gamma_get({"slug": slug})
            market = (data[0] if isinstance(data, list) else data) if data else None
            if market and market.get("active") and not market.get("closed"):
                log.info("Found market: %s  (slug=%s)", market.get("question", ""), slug)
                return market
        except Exception as exc:
            log.debug("Slug %s not found: %s", slug, exc)
    return None


def get_up_down_tokens(market: dict) -> tuple[Optional[dict], Optional[dict]]:
    """
    Parse the market's outcomes/outcomePrices/clobTokenIds fields (all JSON strings)
    and return (up_token, down_token) as dicts with keys: outcome, price, token_id.
    """
    try:
        outcomes  = json.loads(market.get("outcomes",     "[]"))
        prices    = json.loads(market.get("outcomePrices","[]"))
        token_ids = json.loads(market.get("clobTokenIds", "[]"))
    except (json.JSONDecodeError, TypeError):
        return None, None

    tokens = [
        {"outcome": outcomes[i], "price": float(prices[i]), "token_id": token_ids[i]}
        for i in range(len(outcomes))
        if i < len(prices) and i < len(token_ids)
    ]

    up, down = None, None
    for tok in tokens:
        label = tok["outcome"].lower()
        if "up" in label:
            up = tok
        elif "down" in label:
            down = tok
    # Fallback: index order (Up=0, Down=1 per Polymarket convention)
    if up is None and len(tokens) >= 2:
        up, down = tokens[0], tokens[1]
    return up, down


def compute_edge(p_model: float, p_market: float, direction: str) -> float:
    """
    Edge for betting on `direction` outcome.
    direction='up'   → p_model is P(UP)
    direction='down' → p_model is 1 - P(UP)
    """
    p_our = p_model if direction == "up" else 1.0 - p_model
    return p_our - p_market


def fetch_usdc_balance() -> float:
    """Fetch available USDC balance from Polymarket (6-decimal ERC-20)."""
    if DRY_RUN:
        return float(os.getenv("DRY_RUN_BALANCE", "100.0"))
    try:
        from py_clob_client.clob_types import AssetType, BalanceAllowanceParams
        clob = build_clob_client()
        data = clob.get_balance_allowance(params=BalanceAllowanceParams(asset_type=AssetType.COLLATERAL))
        bal  = float(data.get("balance", 0)) / 1_000_000   # USDC has 6 decimals
        log.info("Balance: $%.2f USDC", bal)
        return bal
    except Exception as exc:
        log.warning("Balance fetch failed: %s — using BET_SIZE_MIN", exc)
        return 0.0


def kelly_size(edge: float, market_price: float, balance: float) -> float:
    """
    True quarter-Kelly: bet = balance × 0.25 × f*
    Clamped to [BET_SIZE_MIN, BET_SIZE_MAX].
    """
    if market_price <= 0 or market_price >= 1 or balance <= 0:
        return BET_SIZE_MIN
    b = (1.0 / market_price) - 1.0   # net odds
    p = market_price + edge           # our estimated probability
    q = 1.0 - p
    f_kelly = max(0.0, (p * b - q) / b)
    size = balance * 0.25 * f_kelly
    return round(max(BET_SIZE_MIN, min(BET_SIZE_MAX, size)), 2)


# ── Telegram ──────────────────────────────────────────────────────────────────

def tg(text: str) -> None:
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML"},
            timeout=5,
        )
    except Exception:
        pass


# ── Order placement ───────────────────────────────────────────────────────────

def build_clob_client():
    from py_clob_client.client import ClobClient
    from py_clob_client.clob_types import ApiCreds
    creds = None
    if POLYMARKET_API_KEY:
        creds = ApiCreds(
            api_key=POLYMARKET_API_KEY,
            api_secret=POLYMARKET_API_SECRET,
            api_passphrase=POLYMARKET_API_PASSPHRASE,
        )
    client = ClobClient(
        host=CLOB_HOST,
        key=POLYMARKET_PK,
        chain_id=CHAIN_ID,
        creds=creds,
        signature_type=SIGNATURE_TYPE,
        funder=POLYMARKET_FUNDER or None,
    )
    if not POLYMARKET_API_KEY:
        client.set_api_creds(client.create_or_derive_api_creds())
    return client


def place_bet(clob, token: dict, size_usdc: float, condition_id: str = "", fee_rate_bps: int = 0) -> Optional[str]:
    """
    Buy the given token for `size_usdc` USDC.
    token dict must have keys: token_id, price.
    Returns order_id or None on failure.
    """
    from py_clob_client.clob_types import MarketOrderArgs, OrderType
    token_id = token.get("token_id")
    if not token_id:
        log.warning("No token_id in token dict: %s", token)
        return None
    try:
        order_args = MarketOrderArgs(token_id=token_id, amount=size_usdc, fee_rate_bps=fee_rate_bps)
        log.debug(
            "CLOB create_market_order REQUEST  token_id=%s  amount=%s  fee_rate_bps=%s",
            token_id, size_usdc, fee_rate_bps,
        )
        signed = clob.create_market_order(order_args)
        log.info("CLOB create_market_order RESPONSE  signed=%s", signed)
        log.info("CLOB post_order REQUEST  order_type=FOK  signed=%s", signed)
        resp   = clob.post_order(signed, OrderType.FOK)
        log.info("CLOB post_order RESPONSE  %s", resp)
        order_id = resp.get("orderID") or resp.get("order_id", "")
        return order_id
    except Exception as exc:
        log.error("Order failed: %s", exc)
        return None


# ── On-chain redemption ────────────────────────────────────────────────────────


def _rpc(method: str, params: list):
    payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    log.info("Polygon RPC REQUEST  method=%s  params=%s", method, params)
    resp = requests.post(POLYGON_RPC, json=payload, timeout=15)
    log.info("Polygon RPC RESPONSE  status=%d  body=%s", resp.status_code, resp.text)
    resp.raise_for_status()
    data = resp.json()
    if "error" in data:
        raise RuntimeError(f"RPC error: {data['error']}")
    return data["result"]


def _erc1155_balance(token_id_str: str, address: str) -> int:
    from eth_utils import keccak, to_checksum_address
    selector = keccak(b"balanceOf(address,uint256)")[:4]
    calldata = "0x" + (selector + eth_abi.encode(["address", "uint256"], [to_checksum_address(address), int(token_id_str)])).hex()
    log.info("ERC-1155 balanceOf REQUEST  contract=%s  token_id=%s  address=%s", CTF_CONTRACT, token_id_str, address)
    result = _rpc("eth_call", [{"to": CTF_CONTRACT, "data": calldata}, "latest"])
    balance = int(result, 16)
    log.info("ERC-1155 balanceOf RESPONSE  token_id=%s  balance=%d", token_id_str, balance)
    return balance


def _fetch_redeemable_positions() -> list:
    """Fetch positions with redeemable=true from the Data API."""
    url = f"{DATA_API}/positions"
    user = POLYMARKET_FUNDER if POLYMARKET_FUNDER else POLYMARKET_ADDRESS
    params = {"user": user, "redeemable": "true", "sizeThreshold": "0.01"}
    log.info("Data API positions REQUEST  url=%s  params=%s", url, params)
    try:
        r = requests.get(url, params=params, timeout=15)
        log.info("Data API positions RESPONSE  status=%d  body=%s", r.status_code, r.text[:1000])
        r.raise_for_status()
        result = r.json()
        if not isinstance(result, list):
            result = []
        return result
    except Exception as exc:
        log.warning("Data API positions ERROR: %s", exc)
        return []


def _fetch_recent_trades(clob) -> list:
    from py_clob_client.clob_types import TradeParams
    after_ts = int(time.time()) - 86400
    log.info("CLOB get_trades REQUEST  after=%d (last 24h)", after_ts)
    result = clob.get_trades(TradeParams(after=after_ts))
    if result is None:
        result = []
    log.info("CLOB get_trades RESPONSE  count=%d  data=%s", len(result), result)
    return result


def _has_trade_on_market(clob, condition_id: str) -> bool:
    from py_clob_client.clob_types import TradeParams
    log.info("CLOB get_trades REQUEST  market=%s", condition_id)
    result = clob.get_trades(TradeParams(market=condition_id))
    if result is None:
        result = []
    log.info("CLOB get_trades RESPONSE  market=%s  count=%d  data=%s", condition_id, len(result), result)
    return len(result) > 0


def _build_redeem_calldata(condition_id_hex: str) -> str:
    from eth_abi import encode
    from eth_utils import keccak, to_checksum_address

    selector = keccak(b"redeemPositions(address,bytes32,bytes32,uint256[])")[:4]
    cid_bytes = bytes.fromhex(condition_id_hex.removeprefix("0x")).rjust(32, b"\x00")
    encoded_args = encode(
        ["address", "bytes32", "bytes32", "uint256[]"],
        [to_checksum_address(USDC_ADDRESS), b"\x00" * 32, cid_bytes, [1, 2]],
    )
    return "0x" + (selector + encoded_args).hex()


def _send_tx(calldata: str, nonce: int, gas_price: int) -> str:
    from eth_utils import to_checksum_address
    from eth_account import Account

    account = Account.from_key(POLYMARKET_PK)
    tx = {
        "to": to_checksum_address(CTF_CONTRACT),
        "data": calldata,
        "nonce": nonce,
        "gasPrice": gas_price,
        "gas": 250_000,
        "chainId": CHAIN_ID,
        "value": 0,
    }
    signed = account.sign_transaction(tx)
    raw = getattr(signed, "raw_transaction", None) or getattr(signed, "rawTransaction", None)
    return _rpc("eth_sendRawTransaction", ["0x" + raw.hex()])


def _send_tx_via_safe(calldata: str, to: str, nonce: int, gas_price: int) -> str:
    """Submit a call through the Gnosis Safe (SIGNATURE_TYPE=2).

    The proxy wallet (POLYMARKET_ADDRESS) is the sole Safe owner and signs the
    EIP-712 SafeTx hash, then sends execTransaction to the Safe contract.
    """
    from eth_abi import encode
    from eth_utils import keccak, to_checksum_address
    from eth_account import Account
    from eth_keys import keys as eth_keys_lib

    account  = Account.from_key(POLYMARKET_PK)
    safe     = to_checksum_address(POLYMARKET_FUNDER)
    to_addr  = to_checksum_address(to)
    data_bytes = bytes.fromhex(calldata.removeprefix("0x"))

    # Get Safe's current nonce
    nonce_sel  = keccak(b"nonce()")[:4]
    raw_nonce  = _rpc("eth_call", [{"to": safe, "data": "0x" + nonce_sel.hex()}, "latest"])
    safe_nonce = int(raw_nonce, 16)

    # EIP-712 domain + SafeTx hash
    DOMAIN_SEP_TYPEHASH = keccak(b"EIP712Domain(uint256 chainId,address verifyingContract)")
    SAFE_TX_TYPEHASH    = keccak(
        b"SafeTx(address to,uint256 value,bytes data,uint8 operation,"
        b"uint256 safeTxGas,uint256 baseGas,uint256 gasPrice,address gasToken,"
        b"address refundReceiver,uint256 nonce)"
    )
    ZERO_ADDR = "0x0000000000000000000000000000000000000000"

    domain_sep = keccak(encode(
        ["bytes32", "uint256", "address"],
        [DOMAIN_SEP_TYPEHASH, CHAIN_ID, safe],
    ))
    safe_tx_hash = keccak(encode(
        ["bytes32", "address", "uint256", "bytes32", "uint8",
         "uint256", "uint256", "uint256", "address", "address", "uint256"],
        [SAFE_TX_TYPEHASH, to_addr, 0, keccak(data_bytes), 0,
         0, 0, 0, ZERO_ADDR, ZERO_ADDR, safe_nonce],
    ))
    msg_hash = keccak(b"\x19\x01" + domain_sep + safe_tx_hash)

    # Sign raw hash with proxy wallet private key
    pk = eth_keys_lib.PrivateKey(bytes.fromhex(POLYMARKET_PK.removeprefix("0x")))
    sig = pk.sign_msg_hash(msg_hash)
    signature = sig.r.to_bytes(32, "big") + sig.s.to_bytes(32, "big") + bytes([sig.v + 27])

    # Build execTransaction calldata
    exec_sel  = keccak(b"execTransaction(address,uint256,bytes,uint8,uint256,uint256,uint256,address,address,bytes)")[:4]
    exec_data = "0x" + (exec_sel + encode(
        ["address", "uint256", "bytes", "uint8", "uint256", "uint256", "uint256", "address", "address", "bytes"],
        [to_addr, 0, data_bytes, 0, 0, 0, 0, ZERO_ADDR, ZERO_ADDR, signature],
    )).hex()

    tx = {
        "to": safe,
        "data": exec_data,
        "nonce": nonce,
        "gasPrice": gas_price,
        "gas": 300_000,
        "chainId": CHAIN_ID,
        "value": 0,
    }
    signed = account.sign_transaction(tx)
    raw = getattr(signed, "raw_transaction", None) or getattr(signed, "rawTransaction", None)
    return _rpc("eth_sendRawTransaction", ["0x" + raw.hex()])


def redeem_resolved_positions() -> None:
    """
    Check recent trades against the Gamma API.
    If the market is closed/resolved and we hold tokens, call redeemPositions on-chain.
    Fetches nonce once and increments per tx to avoid collisions.
    """
    from eth_account import Account

    positions = _fetch_redeemable_positions()
    if not positions:
        log.info("No redeemable positions found")
        return

    # Check on-chain balance for each redeemable position
    to_redeem = []
    for pos in positions:
        condition_id = pos.get("conditionId", "")
        token_id     = pos.get("asset", "")
        question     = pos.get("title", condition_id[:16])

        if not condition_id or not token_id:
            log.warning("Position missing conditionId or asset: %s", pos)
            continue

        try:
            holder = POLYMARKET_FUNDER if POLYMARKET_FUNDER else POLYMARKET_ADDRESS
            balance = _erc1155_balance(token_id, holder)
        except Exception as exc:
            log.warning("Could not check ERC-1155 balance for %s: %s", condition_id[:16], exc)
            continue

        if balance <= 0:
            log.info("No on-chain token balance for %s — skipping", condition_id[:16])
            continue

        to_redeem.append((condition_id, question))

    if not to_redeem:
        return

    # Fetch nonce once with "pending" tag, increment per tx
    account = Account.from_key(POLYMARKET_PK)
    nonce = int(_rpc("eth_getTransactionCount", [account.address, "pending"]), 16)
    gas_price = int(int(_rpc("eth_gasPrice", []), 16) * 1.5)

    for condition_id, question in to_redeem:
        log.info("Market resolved, redeeming: %s", question[:60])
        try:
            calldata = _build_redeem_calldata(condition_id)
            if SIGNATURE_TYPE == 2 and POLYMARKET_FUNDER:
                tx_hash = _send_tx_via_safe(calldata, CTF_CONTRACT, nonce, gas_price)
            else:
                tx_hash = _send_tx(calldata, nonce, gas_price)
            log.info("Redeemed %s  tx=%s", question[:40], tx_hash)
            tg(f"💰 <b>Redeemed</b>\n{question[:80]}\ntx: {tx_hash}")
            nonce += 1
        except Exception as exc:
            err = str(exc)
            # Already redeemed externally (nonce consumed or tokens gone) — mark done
            if "nonce too low" in err or "already known" in err:
                log.info("Position already redeemed externally: %s", question[:40])
                nonce += 1
            else:
                log.error("Redeem failed for %s: %s", question[:40], exc)

    # Always attempt to claim any USDC.e sitting in the proxy wallet
    if POLYMARKET_FUNDER:
        try:
            _claim_to_funder()
        except Exception as exc:
            log.error("Claim failed: %s", exc)


def _claim_to_funder() -> None:
    """
    Transfer all USDC.e from the proxy wallet (POLYMARKET_ADDRESS) to the funder (POLYMARKET_FUNDER).
    Only relevant for Gnosis Safe setup (signature type 2) where they are different addresses.
    """
    from eth_abi import encode
    from eth_utils import keccak, to_checksum_address
    from eth_account import Account

    account = Account.from_key(POLYMARKET_PK)
    usdc    = to_checksum_address(USDC_ADDRESS)
    funder  = to_checksum_address(POLYMARKET_FUNDER)

    # Check proxy wallet USDC.e balance
    bal_selector = keccak(b"balanceOf(address)")[:4]
    bal_data     = "0x" + (bal_selector + encode(["address"], [account.address])).hex()
    raw_bal      = _rpc("eth_call", [{"to": usdc, "data": bal_data}, "latest"])
    balance      = int(raw_bal, 16)

    if balance == 0:
        log.info("Claim: proxy wallet USDC.e balance is 0 — nothing to claim")
        return

    usdc_amount = balance / 1_000_000
    log.info("Claiming %.2f USDC.e from proxy %s → funder %s", usdc_amount, account.address, funder)

    transfer_selector = keccak(b"transfer(address,uint256)")[:4]
    transfer_data     = "0x" + (transfer_selector + encode(["address", "uint256"], [funder, balance])).hex()

    nonce     = int(_rpc("eth_getTransactionCount", [account.address, "pending"]), 16)
    gas_price = int(int(_rpc("eth_gasPrice", []), 16) * 1.5)

    tx = {
        "to": usdc,
        "data": transfer_data,
        "nonce": nonce,
        "gasPrice": gas_price,
        "gas": 100_000,
        "chainId": CHAIN_ID,
        "value": 0,
    }
    signed   = account.sign_transaction(tx)
    raw      = getattr(signed, "raw_transaction", None) or getattr(signed, "rawTransaction", None)
    tx_hash  = _rpc("eth_sendRawTransaction", ["0x" + raw.hex()])
    log.info("Claim tx sent: %s  (%.2f USDC.e)", tx_hash, usdc_amount)
    tg(f"🏦 <b>Claimed</b>\n{usdc_amount:.2f} USDC.e → funder\ntx: {tx_hash}")


# ── Main loop ─────────────────────────────────────────────────────────────────

def _run_redemption(clob) -> None:  # noqa: ARG001
    if DRY_RUN:
        return
    try:
        redeem_resolved_positions()
    except Exception as exc:
        log.error("Redemption sweep failed: %s", exc)


def run_cycle(clob) -> None:
    cycle_start = time.time()
    log.info("── Cycle start ─────────────────────────────")

    # 1. Fetch live BTC data and compute features
    try:
        ohlcv = fetch_btc_ohlcv()
    except Exception as exc:
        log.error("Failed to fetch OHLCV: %s", exc)
        return

    btc_price = float(ohlcv["close"].iloc[-1])
    log.info("BTC price: $%.2f", btc_price)

    try:
        features = compute_features(ohlcv)
    except Exception as exc:
        log.error("Feature computation failed: %s", exc)
        return

    # 2. Model prediction
    p_up = predict_up_probability(features)
    log.info("P(UP 5m) = %.3f  P(DOWN) = %.3f", p_up, 1 - p_up)

    # No strong signal → skip
    confidence = abs(p_up - 0.5) * 2   # 0 = no signal, 1 = max confidence
    if confidence < 0.10:
        log.info("Low confidence (%.2f) — skipping cycle", confidence)
        _run_redemption(clob)
        return

    # 3. Fetch balance (drives true Kelly sizing)
    balance = fetch_usdc_balance()
    if balance < BET_SIZE_MIN and not DRY_RUN:
        log.warning("Balance $%.2f below minimum bet — skipping cycle", balance)
        _run_redemption(clob)
        return

    # 4. Fetch the current BTC Up/Down 5-min market by slug
    try:
        market = fetch_btc_5m_market()
    except Exception as exc:
        log.error("Failed to fetch market: %s", exc)
        _run_redemption(clob)
        return

    if market is None:
        log.info("No active btc-updown-5m market found — skipping cycle")
        _run_redemption(clob)
        return

    condition_id = market.get("conditionId") or market.get("condition_id", "")
    question     = market.get("question", "")

    if not DRY_RUN and _has_trade_on_market(clob, condition_id):
        log.info("Already bet on this market (%s) — skipping", question[:60])
        elapsed = time.time() - cycle_start
        log.info("── Cycle done in %.1fs ─────────────────────", elapsed)
        _run_redemption(clob)
        return

    up_token, down_token = get_up_down_tokens(market)
    if up_token is None or down_token is None:
        log.warning("Could not identify Up/Down tokens in market: %s", market)
        _run_redemption(clob)
        return

    up_price   = float(up_token.get("price",   0.5))
    down_price = float(down_token.get("price", 0.5))

    edge_up   = compute_edge(p_up, up_price,   "up")
    edge_down = compute_edge(p_up, down_price, "down")
    log.info(
        "Market: %s | up_p=%.3f down_p=%.3f | edge_up=%.3f edge_down=%.3f",
        question[:70], up_price, down_price, edge_up, edge_down,
    )

    # Pick the side with the best edge (if any clears MIN_EDGE)
    if edge_up >= edge_down and edge_up >= MIN_EDGE:
        direction, token, price, edge = "up",   up_token,   up_price,   edge_up
    elif edge_down > edge_up and edge_down >= MIN_EDGE:
        direction, token, price, edge = "down", down_token, down_price, edge_down
    else:
        log.info("No edge above %.2f on either side — skipping", MIN_EDGE)
        elapsed = time.time() - cycle_start
        log.info("── Cycle done in %.1fs ─────────────────────", elapsed)
        _run_redemption(clob)
        return

    size = kelly_size(edge, price, balance)
    p_model = p_up if direction == "up" else 1.0 - p_up
    log.info(
        "BET | %s | p_model=%.3f p_mkt=%.3f edge=%.3f size=$%.2f",
        direction.upper(), p_model, price, edge, size,
    )

    bets_placed = 0
    if DRY_RUN:
        log.info("  DRY_RUN — would bet %s $%.2f on %s", direction.upper(), size, question[:60])
    else:
        order_id = place_bet(clob, token, size, condition_id, int(market.get("takerBaseFee", 0)))
        if order_id:
            log.info("  Placed order %s", order_id)
            tg(
                f"🎯 <b>BTC 5m Bet</b>\n"
                f"Market: {question[:80]}\n"
                f"Direction: {direction.upper()}\n"
                f"P(model)={p_model:.2%}  P(market)={price:.2%}  edge={edge:.2%}\n"
                f"Size: ${size:.2f}  |  Order: {order_id}"
            )
            bets_placed += 1

    elapsed = time.time() - cycle_start
    log.info("── Cycle done in %.1fs | bets=%d ─────────────", elapsed, bets_placed)
    _run_redemption(clob)


def main() -> None:
    log.info("=" * 60)
    log.info("Polymarket BTC Bot starting")
    log.info("  DRY_RUN=%s  MIN_EDGE=%.2f  BET=[%.2f, %.2f]  LOOP=%ds",
             DRY_RUN, MIN_EDGE, BET_SIZE_MIN, BET_SIZE_MAX, LOOP_INTERVAL)
    log.info("  MODEL_PATH=%s", MODEL_PATH)
    log.info("=" * 60)

    if not POLYMARKET_PK and not DRY_RUN:
        raise RuntimeError("POLYMARKET_PK not set and DRY_RUN=false — refusing to start")

    # Pre-load model
    load_model()

    clob = None
    if not DRY_RUN:
        try:
            clob = build_clob_client()
            from py_clob_client.clob_types import AssetType, BalanceAllowanceParams
            bal_data = clob.get_balance_allowance(params=BalanceAllowanceParams(asset_type=AssetType.COLLATERAL))
            bal = float(bal_data.get("balance", 0)) / 1_000_000
            log.info("Wallet %s  balance: %.2f USDC", POLYMARKET_ADDRESS, bal)
        except Exception as exc:
            log.error("CLOB client init failed: %s", exc)
            if not DRY_RUN:
                raise

    def sleep_until_next_boundary() -> None:
        now = time.time()
        next_boundary = math.ceil(now / LOOP_INTERVAL) * LOOP_INTERVAL
        wait = next_boundary - now
        next_dt = datetime.fromtimestamp(next_boundary, tz=timezone.utc)
        log.info("Sleeping %.1fs until next boundary %s …", wait, next_dt.strftime("%H:%M:%S UTC"))
        time.sleep(wait)

    sleep_until_next_boundary()

    while True:
        try:
            run_cycle(clob)
        except KeyboardInterrupt:
            log.info("Interrupted — shutting down")
            break
        except Exception as exc:
            log.exception("Unhandled error in cycle: %s", exc)

        sleep_until_next_boundary()


if __name__ == "__main__":
    main()
