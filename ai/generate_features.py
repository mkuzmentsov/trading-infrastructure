"""
Feature engineering script for 1-minute OHLCV+trades data.

Input CSV columns: timestamp (unix seconds), open, high, low, close, volume, trades

Dependencies:
    pip install pandas numpy pandas-ta scipy
"""

import warnings
import argparse
import numpy as np
import pandas as pd
import pandas_ta as ta

warnings.filterwarnings("ignore")

# ── Config ────────────────────────────────────────────────────────────────────

FORWARD_RETURNS = [5, 15, 60, 240]   # minutes ahead for target labels
MTF_PERIODS     = [5, 15, 60]        # minutes for multi-timeframe resample

# ── Helpers ───────────────────────────────────────────────────────────────────

EPS = 1e-9


def _safe_div(a: pd.Series, b: pd.Series) -> pd.Series:
    return a / b.replace(0, np.nan)


def _hl_range(df: pd.DataFrame) -> pd.Series:
    return df["high"] - df["low"]


# ── Feature groups ────────────────────────────────────────────────────────────

def add_price_features(df: pd.DataFrame) -> pd.DataFrame:
    """Returns, log-returns and candle structure."""
    c = df["close"]
    o, h, l = df["open"], df["high"], df["low"]

    # simple & log returns at multiple lookbacks
    for n in [1, 5, 15, 30, 60, 240]:
        df[f"ret_{n}m"]     = c.pct_change(n)
        df[f"log_ret_{n}m"] = np.log(c / c.shift(n))

    # candle body / wick decomposition
    body       = c - o
    hl         = _hl_range(df).replace(0, np.nan)
    df["body_ratio"]        = body / o                            # +/- sign preserved
    df["hl_range_ratio"]    = hl / c                              # normalized range
    df["upper_wick_ratio"]  = (h - np.maximum(o, c)) / hl
    df["lower_wick_ratio"]  = (np.minimum(o, c) - l) / hl
    df["open_gap"]          = (o - c.shift(1)) / c.shift(1)      # gap vs prev close

    return df


def add_moving_averages(df: pd.DataFrame) -> pd.DataFrame:
    """SMA, EMA ratios to close and crossover signals."""
    c = df["close"]

    sma_periods = [7, 14, 20, 50, 100, 200]
    ema_periods = [9, 21, 50, 200]

    sma = {}
    ema = {}

    for p in sma_periods:
        sma[p] = c.rolling(p).mean()
        df[f"sma{p}_ratio"] = _safe_div(c, sma[p]) - 1

    for p in ema_periods:
        ema[p] = c.ewm(span=p, adjust=False).mean()
        df[f"ema{p}_ratio"] = _safe_div(c, ema[p]) - 1

    # crossover signals (1 = fast above slow, 0 = below)
    df["ema9_x_ema21"]   = (ema[9]  > ema[21]).astype(int)
    df["ema21_x_ema50"]  = (ema[21] > ema[50]).astype(int)
    df["ema50_x_ema200"] = (ema[50] > ema[200]).astype(int)

    # distance between two key MAs (normalised)
    df["ema9_ema21_spread"]   = _safe_div(ema[9]  - ema[21],  c)
    df["ema21_ema50_spread"]  = _safe_div(ema[21] - ema[50],  c)
    df["ema50_ema200_spread"] = _safe_div(ema[50] - ema[200], c)

    return df


def add_momentum(df: pd.DataFrame) -> pd.DataFrame:
    """RSI, MACD, Stochastic, CCI, Williams %R, ROC."""
    c, h, l = df["close"], df["high"], df["low"]

    # RSI at three periods
    for p in [7, 14, 21]:
        rsi = ta.rsi(c, length=p)
        df[f"rsi{p}"] = rsi / 100.0   # normalise to [0,1]

    # MACD (12,26,9)
    macd_df = ta.macd(c, fast=12, slow=26, signal=9)
    if macd_df is not None:
        df["macd"]        = _safe_div(macd_df.iloc[:, 0], c)  # normalised to price
        df["macd_signal"] = _safe_div(macd_df.iloc[:, 2], c)
        df["macd_hist"]   = _safe_div(macd_df.iloc[:, 1], c)

    # Stochastic (14,3,3)
    stoch = ta.stoch(h, l, c, k=14, d=3, smooth_k=3)
    if stoch is not None:
        df["stoch_k"] = stoch.iloc[:, 0] / 100.0
        df["stoch_d"] = stoch.iloc[:, 1] / 100.0

    # CCI 20 (normalised to [-1,1] range typical ±100)
    cci = ta.cci(h, l, c, length=20)
    if cci is not None:
        df["cci20"] = cci / 200.0

    # Williams %R 14  (range -100..0, shift to 0..1)
    willr = ta.willr(h, l, c, length=14)
    if willr is not None:
        df["willr14"] = (willr + 100) / 100.0

    # Rate of Change
    for p in [10, 20]:
        df[f"roc{p}"] = ta.roc(c, length=p) / 100.0

    # Momentum
    for p in [10, 20]:
        df[f"mom{p}"] = _safe_div(c - c.shift(p), c.shift(p))

    return df


def add_volatility(df: pd.DataFrame) -> pd.DataFrame:
    """ATR, Bollinger Bands, historical vol, Garman-Klass."""
    c, h, l, o = df["close"], df["high"], df["low"], df["open"]

    # ATR normalised by close
    for p in [7, 14, 21]:
        atr = ta.atr(h, l, c, length=p)
        if atr is not None:
            df[f"atr{p}_ratio"] = _safe_div(atr, c)

    # Bollinger Bands (20, 2)
    bb = ta.bbands(c, length=20, std=2)
    if bb is not None:
        df["bb_width"]  = _safe_div(bb.iloc[:, 0] - bb.iloc[:, 2], c)   # (upper-lower)/close
        df["bb_pct"]    = bb.iloc[:, 1]                                   # %B already in [0,1]
        df["bb_pos"]    = _safe_div(c - bb.iloc[:, 2],
                                    bb.iloc[:, 0] - bb.iloc[:, 2])       # position within band

    # Historical volatility: rolling std of log returns, annualised proxy
    log_ret = np.log(c / c.shift(1))
    for p in [20, 60, 120]:
        df[f"hvol{p}"] = log_ret.rolling(p).std() * np.sqrt(1440)  # 1440 min/day

    # Garman-Klass volatility estimator (20-period)
    log_hl = np.log(h / l)
    log_co = np.log(c / o)
    gk_daily = 0.5 * log_hl**2 - (2 * np.log(2) - 1) * log_co**2
    df["gk_vol20"] = gk_daily.rolling(20).mean().apply(np.sqrt) * np.sqrt(1440)

    # Keltner channel position (using EMA20 ± 2*ATR14)
    ema20 = c.ewm(span=20, adjust=False).mean()
    atr14 = ta.atr(h, l, c, length=14)
    if atr14 is not None:
        kc_upper = ema20 + 2 * atr14
        kc_lower = ema20 - 2 * atr14
        df["kc_pos"] = _safe_div(c - kc_lower, kc_upper - kc_lower)

    return df


def add_volume_features(df: pd.DataFrame) -> pd.DataFrame:
    """Volume ratios, OBV, VWAP, MFI, CMF, trades-derived features."""
    c, h, l, v = df["close"], df["high"], df["low"], df["volume"]
    t = df["trades"]

    # Volume relative to rolling averages
    for p in [10, 20, 50]:
        avg_vol = v.rolling(p).mean()
        df[f"vol_ratio{p}"] = _safe_div(v, avg_vol)

    # Average trade size (BTC per trade)
    df["avg_trade_size"] = _safe_div(v, t)

    # Trades intensity relative to rolling average
    for p in [10, 20]:
        avg_t = t.rolling(p).mean()
        df[f"trades_ratio{p}"] = _safe_div(t, avg_t)

    # Trade size z-score (20-period)
    avg_ts = df["avg_trade_size"].rolling(20).mean()
    std_ts = df["avg_trade_size"].rolling(20).std()
    df["avg_trade_size_z"] = _safe_div(df["avg_trade_size"] - avg_ts, std_ts)

    # OBV (normalised by its own 50-period rolling mean for stationarity)
    obv = ta.obv(c, v)
    if obv is not None:
        df["obv_ratio"] = _safe_div(obv, obv.rolling(50).mean()) - 1

    # VWAP deviation (rolling 60-bar intraday proxy)
    tp = (h + l + c) / 3
    vwap60 = (tp * v).rolling(60).sum() / v.rolling(60).sum()
    df["vwap60_dev"] = _safe_div(c - vwap60, c)

    # Money Flow Index 14
    mfi = ta.mfi(h, l, c, v, length=14)
    if mfi is not None:
        df["mfi14"] = mfi / 100.0

    # Chaikin Money Flow 20
    cmf = ta.cmf(h, l, c, v, length=20)
    if cmf is not None:
        df["cmf20"] = cmf

    # Volume-price trend slope (linear regression of log-price over last N bars, weighted by vol)
    for p in [20, 60]:
        x = np.arange(p)
        def vwt_slope(y_v):
            # y_v is a flat array of [log_close * p, volume * p] stacked
            y = y_v[:p]
            w = y_v[p:]
            w = w / (w.sum() + EPS)
            xw = (x * w).sum()
            yw = (y * w).sum()
            x2w = ((x**2) * w).sum()
            b = (((x - xw) * w * (y - yw)).sum()) / (((x - xw)**2 * w).sum() + EPS)
            return b
        stacked = pd.concat([np.log(c), v], axis=1).values
        slopes = pd.Series(
            [vwt_slope(np.concatenate([stacked[i:i+p, 0], stacked[i:i+p, 1]]))
             for i in range(len(stacked) - p + 1)],
            index=df.index[p-1:]
        )
        df[f"vwt_slope{p}"] = slopes

    return df


def add_trend_features(df: pd.DataFrame) -> pd.DataFrame:
    """ADX/DI, Ichimoku components."""
    c, h, l = df["close"], df["high"], df["low"]

    # ADX 14
    adx_df = ta.adx(h, l, c, length=14)
    if adx_df is not None:
        df["adx14"]     = adx_df.iloc[:, 0] / 100.0
        df["dmp14"]     = adx_df.iloc[:, 1] / 100.0   # +DI
        df["dmn14"]     = adx_df.iloc[:, 2] / 100.0   # -DI
        df["di_diff14"] = df["dmp14"] - df["dmn14"]   # directional bias

    # Ichimoku (9,26,52 — standard)
    ichi = ta.ichimoku(h, l, c, tenkan=9, kijun=26, senkou=52)
    if ichi is not None and len(ichi) == 2:
        ichi_df = ichi[0]
        for col in ichi_df.columns:
            label = col.split("_")[0].lower()
            df[f"ichi_{label}"] = _safe_div(ichi_df[col] - c, c)

    return df


def add_statistical_features(df: pd.DataFrame) -> pd.DataFrame:
    """Rolling skewness, kurtosis, z-scores, autocorrelation."""
    c = df["close"]
    log_ret = np.log(c / c.shift(1))

    for p in [20, 60]:
        df[f"ret_skew{p}"]  = log_ret.rolling(p).skew()
        df[f"ret_kurt{p}"]  = log_ret.rolling(p).kurt()
        df[f"close_z{p}"]   = (c - c.rolling(p).mean()) / (c.rolling(p).std() + EPS)

    # 1-lag autocorrelation of returns (mean-reversion vs momentum signal)
    for p in [20, 60]:
        df[f"ret_ac1_{p}"] = log_ret.rolling(p).apply(
            lambda x: pd.Series(x).autocorr(lag=1), raw=False
        )

    # price entropy proxy: normalised range of returns distribution
    for p in [30, 60]:
        df[f"ret_range{p}"] = (
            log_ret.rolling(p).max() - log_ret.rolling(p).min()
        )

    return df


def add_time_features(df: pd.DataFrame) -> pd.DataFrame:
    """Hour, day-of-week, session, cyclical encodings."""
    ts = df["timestamp_dt"]

    df["hour"]       = ts.dt.hour
    df["dow"]        = ts.dt.dayofweek        # 0=Mon … 6=Sun
    df["is_weekend"] = (df["dow"] >= 5).astype(int)

    # Cyclical encoding (sin/cos) so hour 23 and 0 are adjacent
    df["hour_sin"] = np.sin(2 * np.pi * df["hour"] / 24)
    df["hour_cos"] = np.cos(2 * np.pi * df["hour"] / 24)
    df["dow_sin"]  = np.sin(2 * np.pi * df["dow"]  / 7)
    df["dow_cos"]  = np.cos(2 * np.pi * df["dow"]  / 7)

    # Market session (UTC hours)
    def session(h):
        if 0 <= h < 8:   return 0   # Asia
        if 8 <= h < 15:  return 1   # Europe / London open
        return 2                     # US / overlap

    df["session"] = df["hour"].map(session)

    # Drop helper column
    df.drop(columns=["timestamp_dt"], inplace=True)

    return df


def add_multitimeframe(df: pd.DataFrame) -> pd.DataFrame:
    """Resample 1m to 5m, 15m, 1h; compute RSI+EMA+ATR then merge back."""
    df = df.set_index("timestamp_dt_mtf")   # set datetime index temporarily

    for minutes in MTF_PERIODS:
        rule = f"{minutes}min"
        ohlcv = df[["open", "high", "low", "close", "volume"]].resample(rule, label="right", closed="right").agg(
            {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
        ).dropna()

        c_tf = ohlcv["close"]
        h_tf, l_tf = ohlcv["high"], ohlcv["low"]

        rsi_tf  = ta.rsi(c_tf, length=14)
        ema_tf  = c_tf.ewm(span=21, adjust=False).mean()
        atr_tf  = ta.atr(h_tf, l_tf, c_tf, length=14)

        mtf = pd.DataFrame({
            f"mtf_{minutes}m_rsi14":    rsi_tf / 100.0 if rsi_tf is not None else np.nan,
            f"mtf_{minutes}m_ema21_r":  _safe_div(c_tf, ema_tf) - 1,
            f"mtf_{minutes}m_atr14_r":  _safe_div(atr_tf, c_tf) if atr_tf is not None else np.nan,
        })

        # Forward-fill to 1m, then merge
        mtf = mtf.reindex(df.index, method="ffill")
        df = df.join(mtf)

    df = df.reset_index(drop=True)
    return df


def add_target(df: pd.DataFrame) -> pd.DataFrame:
    """Forward returns and binary direction labels."""
    c = df["close"]
    for n in FORWARD_RETURNS:
        fwd_ret = c.shift(-n) / c - 1
        df[f"target_ret_{n}m"]  = fwd_ret
        df[f"target_dir_{n}m"]  = (fwd_ret > 0).astype(float)
        # Last n rows have no valid target
        df.loc[df.index[-n:], [f"target_ret_{n}m", f"target_dir_{n}m"]] = np.nan
    return df


# ── Main ──────────────────────────────────────────────────────────────────────

def build_features(input_path: str, output_path: str) -> pd.DataFrame:
    print(f"Loading {input_path} …")
    df = pd.read_csv(input_path)

    # Parse timestamp
    df["timestamp_dt"]     = pd.to_datetime(df["timestamp"], unit="s", utc=True)
    df["timestamp_dt_mtf"] = df["timestamp_dt"]   # keep copy before MTF sets index

    print(f"  Rows: {len(df):,}  |  Date range: {df['timestamp_dt'].iloc[0]}  →  {df['timestamp_dt'].iloc[-1]}")

    steps = [
        ("Price / candle structure",  add_price_features),
        ("Moving averages",           add_moving_averages),
        ("Momentum",                  add_momentum),
        ("Volatility",                add_volatility),
        ("Volume",                    add_volume_features),
        ("Trend (ADX / Ichimoku)",    add_trend_features),
        ("Statistical",               add_statistical_features),
        ("Time",                      add_time_features),
        ("Multi-timeframe",           add_multitimeframe),
        ("Target labels",             add_target),
    ]

    for label, fn in steps:
        print(f"  → {label} …")
        df = fn(df)

    # Drop rows that are all-NaN due to warm-up period
    min_valid_idx = 200   # longest lookback
    df = df.iloc[min_valid_idx:].reset_index(drop=True)

    # Report
    n_features = len([c for c in df.columns if c not in
                       ("timestamp", "open", "high", "low", "close", "volume", "trades")
                       and not c.startswith("target_")])
    n_targets  = len([c for c in df.columns if c.startswith("target_")])
    print(f"\nFeature matrix: {len(df):,} rows × {n_features} features + {n_targets} target columns")
    print(f"Saving to {output_path} …")
    df.to_csv(output_path, index=False)
    print("Done.")

    return df


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate ML features from 1-minute OHLCV+trades CSV")
    parser.add_argument("--input",  default="BTCUSD_1.csv",      help="Input CSV path")
    parser.add_argument("--output", default="BTCUSD_features.csv", help="Output CSV path")
    args = parser.parse_args()

    build_features(args.input, args.output)