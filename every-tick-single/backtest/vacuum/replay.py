"""
Vacuum replay over mrec data.

Reproduces winner-vacuum/src/vacuum.py's decision path bar-by-bar from the
100ms mrec snapshots and checks it against what the live bot actually did.

Logic mirrored (defaults = btc_vacuum.yaml):
  EARLY  place: tl <= 45s and |lead| >= 8bps  -> rest BUY @0.99 on the leader
  PRE    place: tl <= 2.0s and |lead| >= 3bps -> rest BUY @0.995 (fine px)
  watchdog    : abort if |lead| < 2bps or the lead flips before close
  fill window : first 45s after close
  settle      : +0.01/share if the locked side won, -0.99/share if it lost

Fill model: a taker SELL print on the locked token at a price <= our bid could
have hit us. That is an UPPER BOUND on our fill (it ignores queue position -
other bids sit at the same price), so FILLED SHARES ARE OPTIMISTIC. The
lock/outcome verdict, which is what decides win vs loss, is exact.

Usage: python3 replay.py [data_dir] [--coin btc]
"""
from __future__ import annotations

import glob
import gzip
import json
import os
import sys
import time
from collections import defaultdict

EARLY_LEAD_BPS = 8.0
EARLY_PLACE_SECS = 45.0
PRE_LEAD_BPS = 3.0
PRE_PLACE_SECS = 2.0
PRE_CANCEL_BPS = 2.0
MIN_LEAD_BPS = 3.0     # vacuum.py:481 post-close lock gate
CAP = 0.99
FINE_PX = 0.995
FIRE_MAX = 45.0


def load(data_dir: str, coin: str):
    """bar -> {'cur': [(tl, lead)], 'post': [(t, prints)], 'win': str, 'end': int}"""
    bars: dict[int, dict] = defaultdict(
        lambda: {"cur": [], "post": [], "win": None, "end": 0, "q": ""})
    files = sorted(glob.glob(f"{data_dir}/{coin}-mrec-*.jsonl.gz"))
    for fn in files:
        with gzip.open(fn, "rt") as fh:
            for line in fh:
                try:
                    r = json.loads(line)
                except Exception:
                    continue
                ev = r.get("ev")
                ws = r.get("ws")
                if ws is None:
                    continue
                if ev == "BAR":
                    bars[ws]["end"] = r.get("end") or 0
                    bars[ws]["q"] = r.get("q") or ""
                elif ev == "RES":
                    bars[ws]["win"] = r.get("win")
                elif ev == "SNAP":
                    role = r.get("role")
                    lead = r.get("lead_bps")
                    tl = r.get("tl")
                    if role == "cur":
                        if lead is not None:
                            bars[ws]["cur"].append((tl, lead))
                    elif role == "post":
                        trd = r.get("trd")
                        if trd:
                            bars[ws]["post"].append((r["t"], trd))
                        # the live bot's authoritative lock is taken AT/just
                        # after close (vacuum.py:481, MIN_LEAD_BPS) - not from
                        # the pre-close lead that decided the resting order
                        if lead is not None and tl is not None and -3.0 <= tl <= 0.0:
                            prev = bars[ws].get("close_lead")
                            if prev is None or tl > prev[0]:
                                bars[ws]["close_lead"] = (tl, lead)
    return bars, files


def simulate(bars: dict):
    out = []
    for ws in sorted(bars):
        b = bars[ws]
        if not b["cur"] or not b["win"]:
            continue
        cur = sorted(b["cur"], key=lambda x: -x[0])       # tl descending
        end_ts = b["end"] or (ws + 300)

        # ── placement: walk the tape forward exactly like on_tick ────────────
        placed = None          # (side, px, source)
        for tl, lead in cur:
            if tl < 0:
                break
            if placed is None:
                if tl <= EARLY_PLACE_SECS and abs(lead) >= EARLY_LEAD_BPS:
                    placed = ("UP" if lead > 0 else "DOWN", CAP, "early")
                elif tl <= PRE_PLACE_SECS and abs(lead) >= PRE_LEAD_BPS:
                    placed = ("UP" if lead > 0 else "DOWN", FINE_PX, "pre")
            else:
                side, px, src = placed
                flipped = (lead > 0) != (side == "UP")
                if abs(lead) < PRE_CANCEL_BPS or flipped:
                    out.append(dict(ws=ws, side=side, src=src, px=px, win=b["win"],
                                    aborted=True, supply=0.0, lock_ok=None,
                                    lead_close=lead, q=b["q"]))
                    placed = "ABORTED"
                    break
                if src == "early" and tl <= PRE_PLACE_SECS:
                    placed = (side, FINE_PX, "early+fine")
        if placed is None or placed == "ABORTED":
            if placed is None:
                out.append(dict(ws=ws, side=None, src=None, px=None, win=b["win"],
                                aborted=False, supply=0.0, lock_ok=None,
                                lead_close=cur[-1][1] if cur else None, q=b["q"]))
            continue

        side, px, src = placed

        # ── lock at close (vacuum.py:481): |lead| >= MIN_LEAD_BPS or SKIP ────
        cl = b.get("close_lead")
        close_lead = cl[1] if cl else None
        if close_lead is None or abs(close_lead) < MIN_LEAD_BPS:
            out.append(dict(ws=ws, side=None, src=src, px=px, win=b["win"],
                            aborted=False, supply=0.0, lock_ok=None,
                            skip="tie_print_lock_off", lead_close=close_lead,
                            rested=side, q=b["q"]))
            continue
        side = "UP" if close_lead > 0 else "DOWN"
        tok = "U" if side == "UP" else "D"
        # ── fill: taker SELL prints on our token at/below our bid, in +0..45s ─
        supply = 0.0
        first_fill_dt = None
        for _t, prints in b["post"]:
            for p in prints:
                pt, ptok, price, size, pside = p[0], p[1], p[2], p[3], p[4]
                dt = pt - end_ts
                if dt < 0 or dt > FIRE_MAX:
                    continue
                if ptok != tok or pside != "SELL":
                    continue
                if price <= px + 1e-9:
                    supply += size
                    if first_fill_dt is None:
                        first_fill_dt = dt
        lock_ok = (side == b["win"])
        out.append(dict(ws=ws, side=side, src=src, px=px, win=b["win"],
                        aborted=False, supply=round(supply, 2), lock_ok=lock_ok,
                        lead_close=close_lead,
                        first_fill_dt=first_fill_dt, q=b["q"]))
    return out


def main():
    data_dir = sys.argv[1] if len(sys.argv) > 1 else "every-tick-single/data/mrec/btc"
    coin = "btc"
    bars, files = load(data_dir, coin)
    res = simulate(bars)
    with open(os.path.join(os.path.dirname(__file__), "replay_out.json"), "w") as fh:
        json.dump(res, fh)

    placed = [r for r in res if r["side"] and not r["aborted"]]
    filled = [r for r in placed if r["supply"] > 0]
    wins = [r for r in filled if r["lock_ok"]]
    loss = [r for r in filled if not r["lock_ok"]]
    print(f"files={len(files)} bars_with_res={len(res)}")
    print(f"no-lock (gate not met): {len([r for r in res if r['side'] is None])}")
    print(f"aborted by watchdog   : {len([r for r in res if r['aborted']])}")
    print(f"locked+rested         : {len(placed)}")
    print(f"  of those, supply>0  : {len(filled)}")
    print(f"  lock correct        : {len([r for r in placed if r['lock_ok']])}/{len(placed)}")
    print(f"  filled & correct    : {len(wins)}")
    print(f"  filled & WRONG (loss): {len(loss)}")
    for r in loss:
        print("   LOSS bar=%d %s locked=%s won=%s lead_close=%.2fbps supply=%.0fsh %s"
              % (r["ws"], time.strftime("%d %b %H:%M", time.gmtime(r["ws"])),
                 r["side"], r["win"], r["lead_close"] or 0, r["supply"], r["q"][-24:]))


if __name__ == "__main__":
    main()
