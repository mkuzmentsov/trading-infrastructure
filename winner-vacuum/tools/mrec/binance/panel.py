"""One row per (coin, bar, tl). The live estimator, the tail it is guessing, and Binance."""
import numpy as np, pandas as pd

cl  = pd.read_parquet("pq/cl.parquet")
res = pd.read_parquet("pq/res.parquet")
cur = pd.read_parquet("pq/snapcur.parquet")
bn  = pd.read_parquet("pq/bin.parquet")
TLS = list(range(3, 31))
out = []

for coin, g in cur.groupby("coin"):
    q = cl[cl.coin == coin]
    lo_ts = int(q.cl_ts.min()); hi_ts = int(q.cl_ts.max())
    grid = np.full(hi_ts - lo_ts + 1, np.nan)
    grid[q.cl_ts.values.astype(np.int64) - lo_ts] = q.cl.values
    have = ~np.isnan(grid)
    csum = np.nancumsum(np.nan_to_num(grid)); ccnt = np.cumsum(have)
    def wsum(a, b):                       # sum + count of REAL ticks over [a,b)
        a = max(a - lo_ts, 0); b = min(b - lo_ts, len(grid))
        if b <= a: return 0.0, 0
        return (csum[b-1] - (csum[a-1] if a else 0.0), int(ccnt[b-1] - (ccnt[a-1] if a else 0)))
    def last_at(T):                       # last real tick at or before T
        i = min(T, hi_ts) - lo_ts
        if i < 0: return np.nan
        j = np.where(have[:i+1])[0]
        return grid[j[-1]] if len(j) else np.nan

    bq = bn[bn.coin == coin]
    bt = bq.t.values.astype(np.float64); bm = bq.mid.values.astype(np.float64)
    rr = res[res.coin == coin].set_index("ws").win.to_dict()

    for ws, gb in g.groupby("ws"):
        ws = int(ws); end = ws + 300
        win = rr.get(ws)
        if win is None: continue
        s_sum, s_n = wsum(ws - 62, ws - 3)              # strike window
        if s_n < 40: continue
        strike = s_sum / s_n
        f_sum, f_n = wsum(end - 62, end - 3)            # final window
        if f_n < 40: continue
        final_bps = (f_sum / f_n - strike) / strike * 1e4
        gb = gb.sort_values("tl")
        tlv = gb.tl.values
        for tl in TLS:
            i = np.searchsorted(tlv, tl, side="right") - 1   # the row at or just past tl
            if i < 0: continue
            r = gb.iloc[i]
            if not np.isfinite(r.cl_ts): continue
            T = int(r.cl_ts)                                  # the relay frontier (bug #25)
            o_sum, k = wsum(end - 62, min(end - 3, T + 1))    # ticks actually in hand
            if k < 5: continue
            lastv = last_at(T)
            if not np.isfinite(lastv): continue
            ntail = 60 - k
            if ntail <= 0: continue
            t_sum, t_n = wsum(T + 1, end - 3)                 # the UNOBSERVED tail
            if t_n < max(1, ntail // 2): continue             # need the tail to be measurable
            bps = lambda v: (v - strike) / strike * 1e4
            h1 = bps((o_sum + lastv * ntail) / 60)            # THE LIVE ESTIMATOR
            j = np.searchsorted(bt, end - tl, side="right") - 1
            # Binance sits at a systematic LEVEL offset from the Chainlink aggregate
            # (+4.7 bps on average here), so only its CHANGE since the last chainlink
            # tick is comparable. jT = Binance at the relay frontier.
            jT = np.searchsorted(bt, T + 1.0, side="right") - 1
            if j < 0 or jT < 0: continue
            out.append((coin, ws, tl, k, ntail,
                        h1, bps(lastv), bps(o_sum / k), bps(t_sum / t_n), bps(bm[j]),
                        bps(bm[jT]), final_bps, win,
                        r.ua, r.ub, r.da, r.db, r.uas, r.das))

p = pd.DataFrame(out, columns=["coin","ws","tl","k","ntail","h1","last_bps","obs_bps",
                               "tail_bps","bin_bps","binT_bps","final_bps","win",
                               "ua","ub","da","db","uas","das"])
# THE feature: what Binance has done since Chainlink last printed (offset cancels)
p["bin_move"] = p.bin_bps - p.binT_bps
# THE target: how far the unobserved tail lands from the last tick (H1 assumes 0)
p["tail_err"] = p.tail_bps - p.last_bps
p["side_h1"]  = np.where(p.h1 > 0, "UP", "DOWN")
p["right_h1"] = p.side_h1 == p.win
p["fav_ask"]  = np.where(p.side_h1 == "UP", p.ua, p.da)
p["fav_bid"]  = np.where(p.side_h1 == "UP", p.ub, p.db)
p["day"]      = pd.to_datetime(p.ws, unit="s", utc=True).dt.strftime("%m-%d")
p.to_parquet("pq/panel.parquet", index=False)
print("panel", p.shape, "| bars", p.groupby(['coin','ws']).ngroups, "| coins", p.coin.nunique())
print(p[["bin_move","tail_err"]].describe().round(3))
