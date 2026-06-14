"""Stream Binance USDⓈ-M futures aggTrades into compact HOURLY order-flow features.

aggTrades carry an `is_buyer_maker` flag → we recover signed taker volume (the
aggressor side), the core microstructure signal. Files are huge (GBs/month), so we
stream each month to a temp file, aggregate to hourly, then DELETE it — disk stays
bounded to one month at a time.

Output: data/<SYM>_ofi_1h.parquet  with columns:
  time, ofi (taker buy−sell)/(buy+sell), ntrades, vol_base, avg_size, max_size, buy_frac

Usage: python3 pattern-bot/fetch_binance_ofi.py --symbol BTCUSDT --start 2024-01 --end 2026-05
"""
from __future__ import annotations
import argparse, os, tempfile, time, zipfile
from pathlib import Path
import numpy as np, pandas as pd, requests

BASE = "https://data.binance.vision/data/futures/um/monthly/aggTrades"
DATA = Path(__file__).resolve().parent / "data"
HOUR = 3_600_000


def _months(start, end):
    sy, sm = map(int, start.split("-")); ey, em = map(int, end.split("-"))
    y, m = sy, sm
    while (y, m) <= (ey, em):
        yield y, m
        m += 1
        if m > 12:
            m, y = 1, y + 1


def month_ofi(sym, y, m):
    url = f"{BASE}/{sym}/{sym}-aggTrades-{y:04d}-{m:02d}.zip"
    tf = None
    try:
        with requests.get(url, stream=True, timeout=180) as r:
            if r.status_code == 404:
                return None
            r.raise_for_status()
            tf = tempfile.NamedTemporaryFile(delete=False, suffix=".zip")
            for chunk in r.iter_content(1 << 20):
                tf.write(chunk)
            tf.close()
        z = zipfile.ZipFile(tf.name)
        name = z.namelist()[0]
        # aggTrades cols: id,price,qty,first,last,transact_time,is_buyer_maker
        acc = {}   # hour -> [buy_qty, sell_qty, cnt, qsum, qmax]
        with z.open(name) as fh:
            for ch in pd.read_csv(fh, header=None, usecols=[2, 5, 6],
                                  names=["qty", "tt", "ibm"], dtype=str, chunksize=3_000_000):
                qty = pd.to_numeric(ch["qty"], errors="coerce")
                tt = pd.to_numeric(ch["tt"], errors="coerce")
                ok = qty.notna() & tt.notna()
                qty, tt, ibm = qty[ok].to_numpy(), tt[ok].to_numpy("int64"), ch["ibm"][ok]
                if len(tt) and tt[0] > 1e14:
                    tt = tt // 1000                      # microseconds → ms
                hour = (tt // HOUR) * HOUR
                sell = ibm.astype(str).str.lower().isin(["true", "1"]).to_numpy()  # buyer maker → taker sold
                buyq = np.where(~sell, qty, 0.0); sellq = np.where(sell, qty, 0.0)
                g = pd.DataFrame({"h": hour, "buy": buyq, "sell": sellq, "q": qty})
                agg = g.groupby("h").agg(buy=("buy", "sum"), sell=("sell", "sum"),
                                         cnt=("q", "size"), qsum=("q", "sum"), qmax=("q", "max"))
                for h, row in agg.iterrows():
                    a = acc.get(h)
                    if a is None:
                        acc[h] = [row.buy, row.sell, row.cnt, row.qsum, row.qmax]
                    else:
                        a[0] += row.buy; a[1] += row.sell; a[2] += row.cnt
                        a[3] += row.qsum; a[4] = max(a[4], row.qmax)
        rows = []
        for h, (b, s, cnt, qsum, qmax) in sorted(acc.items()):
            tot = b + s
            rows.append((int(h), (b - s) / tot if tot else 0.0, int(cnt), qsum,
                         qsum / cnt if cnt else 0.0, qmax, b / tot if tot else 0.5))
        return pd.DataFrame(rows, columns=["time", "ofi", "ntrades", "vol_base",
                                           "avg_size", "max_size", "buy_frac"])
    finally:
        if tf is not None and os.path.exists(tf.name):
            os.unlink(tf.name)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default="BTCUSDT")
    ap.add_argument("--start", default="2024-01")
    ap.add_argument("--end", default="2026-05")
    a = ap.parse_args()
    DATA.mkdir(parents=True, exist_ok=True)
    print(f"[ofi] {a.symbol} {a.start}→{a.end}  (streaming aggTrades → hourly)")
    frames = []
    for y, m in _months(a.start, a.end):
        t0 = time.time()
        try:
            d = month_ofi(a.symbol, y, m)
        except Exception as e:  # noqa: BLE001
            print(f"  {y}-{m:02d}: FAILED {e}"); continue
        if d is None or d.empty:
            print(f"  {y}-{m:02d}: missing"); continue
        frames.append(d)
        print(f"  {y}-{m:02d}: {len(d)} hrs  ({time.time()-t0:.0f}s)")
    out = pd.concat(frames, ignore_index=True).drop_duplicates("time").sort_values("time")
    p = DATA / f"{a.symbol}_ofi_1h.parquet"; out.to_parquet(p, index=False)
    print(f"[ofi] {len(out)} hourly rows "
          f"{pd.to_datetime(out['time'].iloc[0],unit='ms').date()}→"
          f"{pd.to_datetime(out['time'].iloc[-1],unit='ms').date()} -> {p.name}")


if __name__ == "__main__":
    main()
