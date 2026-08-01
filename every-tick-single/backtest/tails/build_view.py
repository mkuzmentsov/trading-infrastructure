"""
Build a flat, causal analysis view of the tail zone from mrec.

Output: tails/view.pkl — one row per (coin, bar, side, second) for the last
LOOKBACK seconds of every bar, restricted to moments where that side is
quoted in the tail zone (ask <= MAX_PX). Every column is knowable AT THAT
INSTANT; the only future-looking column is `won`, the label.

Columns
  coin bar side tl                 identity / seconds to close
  ask ask_sz bid bid_sz spread     that side's book right then
  lead_bps                         spot vs bar open, signed (+ = UP ahead)
  trail                            True if this side is the TRAILING side
  gap_bps                          |lead|, how far this side is behind
  sigma_bps                        causal realised vol, bps per sqrt(second),
                                   from this bar's own spot path so far
  z                                gap_bps / (sigma_bps * sqrt(tl))
  p_model                          Phi(-z): model prob this side ends ahead
  edge                             p_model - ask
  vol volsh                        market volume so far in the bar
  won                              LABEL: did this side win

Sizing note: ask_sz is the size resting at that quote, i.e. an upper bound on
what a taker could lift at `ask` at that instant.

Usage: python3 build_view.py [mrec_root] [out.pkl]
"""
from __future__ import annotations

import glob
import gzip
import json
import math
import pickle
import sys
from collections import defaultdict

COINS = ["btc", "eth", "sol", "xrp", "bnb", "doge"]
LOOKBACK = 180.0      # seconds before close to keep
MAX_PX = 0.10         # tail zone
VOL_WIN = 60.0        # seconds of spot history for the causal vol estimate


def _phi(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def build(root: str):
    rows = []
    for coin in COINS:
        files = sorted(glob.glob(f"{root}/{coin}/{coin}-mrec-*.jsonl.gz"))
        if not files:
            continue
        bars = defaultdict(lambda: {"win": None, "snaps": []})
        for fn in files:
            with gzip.open(fn, "rt") as fh:
                for line in fh:
                    try:
                        r = json.loads(line)
                    except Exception:
                        continue
                    ws, ev = r.get("ws"), r.get("ev")
                    if ws is None:
                        continue
                    if ev == "RES":
                        bars[ws]["win"] = r.get("win")
                    elif ev == "SNAP" and r.get("role") == "cur":
                        tl = r.get("tl")
                        if tl is None or tl <= 0 or tl > LOOKBACK:
                            continue
                        bars[ws]["snaps"].append(r)

        for ws, b in bars.items():
            if not b["win"] or not b["snaps"]:
                continue
            snaps = sorted(b["snaps"], key=lambda r: -r["tl"])   # forward in time
            # causal spot path -> rolling realised vol in bps/sqrt(s)
            spots = []            # (elapsed_s, spot)
            last_sec = None
            for r in snaps:
                tl = r["tl"]
                spot = r.get("spot")
                if spot:
                    spots.append((300.0 - tl, spot))
                sec = int(tl)
                if sec == last_sec:          # one row per whole second
                    continue
                last_sec = sec

                lead = r.get("lead_bps")
                if lead is None:
                    continue

                # realised vol from this bar's own path, last VOL_WIN seconds
                sigma = None
                if len(spots) >= 8:
                    t_now = spots[-1][0]
                    win = [(t, s) for t, s in spots if t >= t_now - VOL_WIN]
                    if len(win) >= 8:
                        rets = []
                        for i in range(1, len(win)):
                            dt = win[i][0] - win[i - 1][0]
                            if dt <= 0 or win[i - 1][1] <= 0:
                                continue
                            lr = math.log(win[i][1] / win[i - 1][1]) * 1e4
                            rets.append(lr / math.sqrt(dt))
                        if len(rets) >= 8:
                            m = sum(rets) / len(rets)
                            var = sum((x - m) ** 2 for x in rets) / (len(rets) - 1)
                            sigma = math.sqrt(var)
                if not sigma or sigma <= 0:
                    continue

                for side, a, asz, bd, bsz in (
                        ("UP", r.get("ua"), r.get("uas"), r.get("ub"), r.get("ubs")),
                        ("DOWN", r.get("da"), r.get("das"), r.get("db"), r.get("dbs"))):
                    if a is None or a > MAX_PX or not asz:
                        continue
                    trail = (lead > 0) != (side == "UP")
                    gap = abs(lead)
                    z = gap / (sigma * math.sqrt(max(tl, 1e-6)))
                    p = _phi(-z) if trail else _phi(z)
                    rows.append(dict(
                        coin=coin, bar=ws, side=side, tl=round(tl, 1),
                        ask=a, ask_sz=asz, bid=bd, bid_sz=bsz,
                        spread=None if bd is None else round(a - bd, 4),
                        lead_bps=round(lead, 3), trail=trail, gap_bps=round(gap, 3),
                        sigma_bps=round(sigma, 4), z=round(z, 4),
                        p_model=round(p, 6), edge=round(p - a, 6),
                        vol=r.get("vol"), volsh=r.get("volsh"),
                        won=(side == b["win"]),
                    ))
        print(f"  {coin}: {len(rows)} rows so far", flush=True)
    return rows


def main():
    root = sys.argv[1] if len(sys.argv) > 1 else "every-tick-single/data/mrec"
    out = sys.argv[2] if len(sys.argv) > 2 else "every-tick-single/backtest/tails/view.pkl"
    rows = build(root)
    with open(out, "wb") as fh:
        pickle.dump(rows, fh)
    bars = len({(r["coin"], r["bar"]) for r in rows})
    print(f"\nwrote {out}: {len(rows)} rows over {bars} bars")


if __name__ == "__main__":
    main()
