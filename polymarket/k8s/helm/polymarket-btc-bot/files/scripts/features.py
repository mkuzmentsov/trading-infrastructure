"""
Feature engineering — mirrors generate_features.py exactly.
compute_features() is the public entry point.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pandas_ta as ta

from config import log

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
    df["ema9_x_ema21"]        = (ema[9]  > ema[21]).astype(int)
    df["ema21_x_ema50"]       = (ema[21] > ema[50]).astype(int)
    df["ema50_x_ema200"]      = (ema[50] > ema[200]).astype(int)
    df["ema9_ema21_spread"]   = _safe_div(ema[9]  - ema[21],  c)
    df["ema21_ema50_spread"]  = _safe_div(ema[21] - ema[50],  c)
    df["ema50_ema200_spread"] = _safe_div(ema[50] - ema[200], c)
    return df


def _add_momentum(df: pd.DataFrame) -> pd.DataFrame:
    c, h, l = df["close"], df["high"], df["low"]
    for p in [3, 5]:
        rsi = ta.rsi(c, length=p)
        df[f"rsi{p}"] = rsi / 100.0 if rsi is not None else np.nan
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
        df[f"hvol{p}"] = log_ret.rolling(p).std() * np.sqrt(288)
    log_hl = np.log(h / l)
    log_co = np.log(c / o)
    gk = 0.5 * log_hl**2 - (2 * np.log(2) - 1) * log_co**2
    df["gk_vol20"] = gk.rolling(20).mean().apply(np.sqrt) * np.sqrt(288)
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
        df["adx14"]     = adx_df.iloc[:, 0] / 100.0
        df["dmp14"]     = adx_df.iloc[:, 1] / 100.0
        df["dmn14"]     = adx_df.iloc[:, 2] / 100.0
        df["di_diff14"] = df["dmp14"] - df["dmn14"]
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
    for minutes in [15, 60, 240]:
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


def _add_microstructure(df: pd.DataFrame) -> pd.DataFrame:
    c, v = df["close"], df["volume"]
    for p in [5, 10, 20]:
        df[f"dist_high{p}"] = (c.rolling(p).max() - c) / c
        df[f"dist_low{p}"]  = (c - c.rolling(p).min()) / c
    for p in [3, 5, 8]:
        ema = c.ewm(span=p, adjust=False).mean()
        df[f"ema{p}_dev"] = _safe_div(c - ema, c)
    df["vol_vs_prev"] = _safe_div(v, v.shift(1))
    direction = np.sign(c.diff())
    changes = (direction != direction.shift(1)).cumsum()
    df["bar_streak"] = direction * (changes.groupby(changes).cumcount() + 1)
    return df


# Ordered feature list matching the trained model
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
    "rsi3","rsi5","rsi7","rsi14","rsi21","macd","macd_signal","macd_hist",
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
    "mtf_15m_rsi14","mtf_15m_ema21_r","mtf_15m_atr14_r",
    "mtf_60m_rsi14","mtf_60m_ema21_r","mtf_60m_atr14_r",
    "mtf_240m_rsi14","mtf_240m_ema21_r","mtf_240m_atr14_r",
    # microstructure
    "dist_high5","dist_high10","dist_high20",
    "dist_low5","dist_low10","dist_low20",
    "ema3_dev","ema5_dev","ema8_dev",
    "vol_vs_prev","bar_streak",
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
    df = _add_microstructure(df)

    last = df.iloc[-1]
    result = pd.Series({col: last.get(col, np.nan) for col in FEATURE_COLS})
    return result
