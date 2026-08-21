#!/usr/bin/env python3
"""makersim.py — can a MAKER bid on 5m updown markets be profitable?

Every previous maker attempt died on one of two things: adverse selection
(informed takers lift the winner, so whoever rests buys the loser) or the queue
(the 0.99 wall is thousands of shares deep, we never reach the front). Our own
v2 fleet (08-16/17) resting 0.99/0.991 got only **17 true maker fills in 14h**
(17/17 correct, +0.95%/$) — the leg was never really tested, supply was.

So this sim asks the supply question honestly, with a queue model (bug ledger
#11: a maker backtest without a queue is fiction).

FILL MODEL (side-agnostic, so it does not depend on the print `side` field,
which is only ~60% consistent with the BBO):
  * we rest a BUY at price P, size SH, placed at tl=START on one token
  * P is either the best bid ("join": queue_ahead = the recorded size at that
    level) or one tick above it ("improve": we are alone at a new level,
    queue_ahead = 0, only legal when it stays below the best ask)
  * a print at price <= P AND <= the prevailing best bid can only be a seller
    hitting bids (no ask can exist at or below the best bid), so its size is
    genuine fill flow for us; we fill once cumulative flow > queue_ahead
  * we only count flow while P >= the prevailing best bid — once the bid moves
    above us we are buried and must not claim fills
  * order is cancelled at tl=CANCEL (default 3s); no post-close resting (the
    0.99-wall lesson from btc-vacuum)
  * maker fills pay NO fee (`feeSchedule.takerOnly: true`); the 0.2 rebate is
    NOT credited here, so results are conservative

SIDE SELECTION, three variants, always reported together:
  oracle  — the eventual winner (upper bound: if this is not profitable, stop)
  bookfav — the side with the higher bid at placement (no signal needed)
  proxy   — Binance-spot recon (mrec `lead_bps` mean over the TWAP window so
            far) with the §28 time-scaled gate; ⚠️ 2-3x pessimistic vs the
            bot's Chainlink recon (bug ledger #19)

Usage: python3 tools/makersim.py [coin ...]
"""
import collections, glob, gzip, json, os, statistics, sys
from multiprocessing import Pool

ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "every-tick-single/data/mrec")
COINS = ["btc", "eth", "sol", "xrp", "doge", "bnb"]
SH = 5.0                     # venue minimum order size
CANCEL_TL = 3.0
TICK = 0.01
STARTS = [45, 30, 20, 15, 10]
RULES = ["improve", "join"]
BANDS = [(0.80, 0.98), (0.90, 0.98), (0.55, 0.98),
         (0.985, 0.999), (0.96, 0.999)]   # the v2 level (0.99/0.991)
# §28 time-scaled gate: |est| bps required at a given tl
GATE = [(25, 2.0), (18, 1.3), (12, 0.8), (0, 0.5)]


def gate_for(tl):
    for lo, g in GATE:
        if tl >= lo:
            return g
    return 0.5


def sim_bar(snaps, win):
    """snaps: list of (tl, ub,ubs,ua, db,dbs,da, lead_bps, trd). -> results."""
    out = {}
    # --- the proxy recon: running mean of lead_bps over [T-62, T-3] ---
    lead_sum = lead_n = 0.0
    est_at = {}
    for tl, *_rest in snaps:
        pass
    acc_s, acc_n = 0.0, 0
    for s in snaps:
        tl = s[0]
        lb = s[7]
        if lb is not None and 3 <= tl <= 62:
            acc_s += lb
            acc_n += 1
        est_at[round(tl, 1)] = (acc_s / acc_n) if acc_n else None

    for start in STARTS:
        # placement snapshot = first snap at tl <= start
        idx = next((i for i, s in enumerate(snaps) if s[0] <= start), None)
        if idx is None:
            continue
        p = snaps[idx]
        tl0, ub, ubs, ua, db, dbs, da, lb, _ = p
        est = est_at.get(round(tl0, 1))
        for side_rule in ("oracle", "bookfav", "proxy", "proxycx"):
            if side_rule == "oracle":
                up = (win == "UP")
            elif side_rule == "bookfav":
                if ub is None or db is None or ub == db:
                    continue
                up = ub > db
            else:
                if est is None or abs(est) < gate_for(tl0):
                    continue
                up = est > 0
            bid = ub if up else db
            ask = ua if up else da
            if bid is None:
                continue
            for rule in RULES:
                if rule == "improve":
                    tick = 0.001 if bid >= 0.99 - 1e-9 else TICK
                    px = round(bid + tick, 3)
                    if ask is not None and px >= ask:      # would cross
                        continue
                    queue = 0.0
                else:
                    px = round(bid, 3)
                    queue = (ubs if up else dbs) or 0.0
                for band in BANDS:
                    if not (band[0] <= px <= band[1]):
                        continue
                    key = (side_rule, start, rule, band)
                    # ---- walk forward and fill ----
                    flow, filled = 0.0, 0.0
                    for s in snaps[idx:]:
                        tl = s[0]
                        if tl < CANCEL_TL:
                            break
                        if side_rule == "proxycx":
                            e = est_at.get(round(tl, 1))
                            if e is not None and ((e > 0) != up or abs(e) < 0.3):
                                break            # cancel on flip / decay
                        bb = s[1] if up else s[4]
                        if bb is not None and bb > px + 1e-9:
                            continue          # buried: our level is behind
                        for t in (s[8] or []):
                            if (t[1] == "U") != up:
                                continue
                            tp, tsz = float(t[2]), float(t[3])
                            if tp <= px + 1e-9 and (bb is None or tp <= bb + 1e-9):
                                flow += tsz
                        if flow > queue:
                            filled = min(SH, flow - queue)
                            break
                    if filled > 0:
                        wonside = (win == "UP") == up
                        out[key] = (filled, px, wonside, tl0, est)
                    else:
                        out.setdefault(key, None)
    return out


def scan(path):
    """-> (res, per-bar sim results)"""
    bars = collections.defaultdict(list)
    res = {}
    for line in gzip.open(path, "rt"):
        if '"ev":"RES"' in line:
            r = json.loads(line)
            res[r["slug"]] = r["win"]
            continue
        if '"role":"cur"' not in line:
            continue
        r = json.loads(line)
        tl = r.get("tl")
        if tl is None or not (0 <= tl <= 95):
            continue
        bars[r["slug"]].append((tl, r.get("ub"), r.get("ubs"), r.get("ua"),
                                r.get("db"), r.get("dbs"), r.get("da"),
                                r.get("lead_bps"), r.get("trd")))
    return res, {k: sorted(v, key=lambda x: -x[0]) for k, v in bars.items()}


FILLS = []


def run(coin, procs=8):
    files = sorted(glob.glob(f"{ROOT}/{coin}/*.gz"))
    with Pool(procs) as p:
        parts = p.map(scan, files)
    res = {}
    for r, _ in parts:
        res.update(r)
    agg = collections.defaultdict(lambda: dict(bars=0, fills=0, wins=0,
                                               cost=0.0, payout=0.0, pxs=[]))
    nbars = 0
    coin_name = coin
    for _, bars in parts:
        for slug, snaps in bars.items():
            win = res.get(slug)
            if win not in ("UP", "DOWN") or len(snaps) < 200:
                continue
            nbars += 1
            for key, r in sim_bar(snaps, win).items():
                a = agg[key]
                a["bars"] += 1
                if r:
                    filled, px, wonside = r[0], r[1], r[2]
                    FILLS.append(dict(coin=coin_name, slug=slug, side=key[0],
                                      start=key[1], rule=key[2], band=key[3][0],
                                      px=px, sh=filled, won=wonside,
                                      tl=r[3], est=r[4]))
                    a["fills"] += 1
                    a["wins"] += 1 if wonside else 0
                    a["cost"] += filled * px
                    a["payout"] += filled if wonside else 0.0
                    a["pxs"].append(px)
    return coin, nbars, agg


def report(all_agg, nbars, days, label):
    print(f"\n=== {label} — {nbars} bars, ~{days:.1f} days ===")
    print(f"{'side':>8} {'place':>6} {'rule':>8} {'band':>12} {'quoted':>7} "
          f"{'fills':>6} {'fill%':>6} {'medpx':>6} {'win%':>7} {'PnL$':>9} "
          f"{'%/$':>7} {'$/day':>8}")
    rows = []
    for key, a in all_agg.items():
        if a["fills"] < 5:
            continue
        side, start, rule, band = key
        pnl = a["payout"] - a["cost"]
        rows.append((pnl / max(days, 1e-9), key, a, pnl))
    for perday, key, a, pnl in sorted(rows, reverse=True):
        side, start, rule, band = key
        print(f"{side:>8} T-{start:<4} {rule:>8} {band[0]:.2f}-{band[1]:.2f}  "
              f"{a['bars']:>7} {a['fills']:>6} {100*a['fills']/a['bars']:>5.1f}% "
              f"{statistics.median(a['pxs']):>6.3f} "
              f"{100*a['wins']/a['fills']:>6.1f}% {pnl:>+9.2f} "
              f"{100*pnl/max(a['cost'],1e-9):>+6.2f}% {perday:>+8.2f}")


if __name__ == "__main__":
    coins = sys.argv[1:] or COINS
    total = collections.defaultdict(lambda: dict(bars=0, fills=0, wins=0,
                                                 cost=0.0, payout=0.0, pxs=[]))
    tb = 0
    for c in coins:
        coin, nbars, agg = run(c)
        tb += nbars
        for k, a in agg.items():
            t = total[k]
            for f in ("bars", "fills", "wins"):
                t[f] += a[f]
            for f in ("cost", "payout"):
                t[f] += a[f]
            t["pxs"] += a["pxs"]
        print(f"{coin}: {nbars} bars simulated", flush=True)
        report(agg, nbars, nbars / 288.0, f"{coin} maker sim")
    report(total, tb, tb / (288.0 * len(coins)), f"POOLED {len(coins)} coins")
    with open("makerfills.jsonl", "w") as fh:
        for f in FILLS:
            fh.write(json.dumps(f) + "\n")
    print(f"\nwrote makerfills.jsonl ({len(FILLS)} fills)")
