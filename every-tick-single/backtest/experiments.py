#!/usr/bin/env python3
"""Research-program experiments (EXPERIMENTS.md) — richer loader than sim.py so
the frozen backtest baseline stays untouched.

Runs against tests/data/<date>/ dirs. Each experiment reports per-day (regime
variance is the whole story) and pooled, with the RUN RECORD fields.

Usage: python3 experiments.py <date> [<date> ...]
"""
from __future__ import annotations
import json, math, os, sys

COINS = ("btc", "eth", "sol", "xrp")


def _open(p):
    import gzip
    return gzip.open(p, "rt") if p.endswith(".gz") else open(p)


def load(date_dir):
    """→ {(coin, cid): bar} with snaps, prints(+side), positions, outcome, bar_ts."""
    bars = {}
    for c in COINS:
        for suf in ("_snap.jsonl", "_snap.jsonl.gz"):
            p = os.path.join(date_dir, c + suf)
            if os.path.exists(p):
                break
        else:
            continue
        for line in _open(p):
            try:
                e = json.loads(line)
            except Exception:
                continue
            if not isinstance(e, dict):
                continue
            ev = e.get("event")
            cid = e.get("condition_id")
            if ev in ("bar_snapshot", "trade_print") and cid:
                b = bars.setdefault((c, cid), {"coin": c, "snaps": [], "prints": [],
                                               "positions": [], "outcome": None,
                                               "bar_ts": e.get("market_start_ts")})
                if ev == "trade_print":
                    b["prints"].append((e.get("seconds_left", 0), e.get("direction"),
                                        e.get("price", 0), e.get("size", 0),
                                        (e.get("side") or "").upper()))
                else:
                    b["snaps"].append((e.get("seconds_left", 0), e.get("up_bid", 0),
                                       e.get("up_ask", 0), e.get("down_bid", 0),
                                       e.get("down_ask", 0)))
            elif ev == "paper_bar_settle":
                b = bars.get((c, e.get("paper_condition_id")))
                if b:
                    if e.get("outcome") in ("UP", "DOWN"):
                        b["outcome"] = e["outcome"]
                    for po in (e.get("positions") or []):
                        b["positions"].append({
                            "side": po["direction"], "entry": po["entry_price"],
                            "size": po["size"], "secs_left": po.get("entry_secs_left"),
                            "win": bool(po["win"] or po["exit_kind"] == "tp")})
    return bars


# ── BB-2: CLV (closing-line value) ────────────────────────────────────────────
def clv(bars):
    """CLV = (held-side final mark) − entry. Final mark = last snapshot mid of the
    held side (proxy for the closing line). Positive mean CLV = we buy below where
    the line closes = real edge, independent of the coin-flip outcome noise."""
    vals = []
    for b in bars.values():
        if not b["snaps"]:
            continue
        last = sorted(b["snaps"], key=lambda s: s[0])[0]  # smallest secs_left
        for p in b["positions"]:
            mid = ((last[1] + last[2]) / 2 if p["side"] == "UP"
                   else (last[3] + last[4]) / 2)
            if 0 < mid < 1:
                vals.append(mid - p["entry"])
    if not vals:
        return None
    m = sum(vals) / len(vals)
    sd = (sum((x - m) ** 2 for x in vals) / len(vals)) ** .5
    t = m / (sd / math.sqrt(len(vals))) if sd else 0
    return {"n": len(vals), "mean_clv": round(m, 4), "sd": round(sd, 3), "t": round(t, 1)}


# ── MS-1: early-bar order-flow imbalance gate ─────────────────────────────────
def flow_gate(bars, early_secs=60):
    """Cross-token directional order flow in the first `early_secs` (available at
    quote time): dir_imb = (UP-token volume − DOWN-token volume) / total. Positive
    = market accumulating UP → bullish. Bucket realized-fill win rate by whether
    the early flow AGREES with the side we hold. If 'with-flow' fills win more,
    flow is a usable same-bar gate/side-picker."""
    buckets = {"with_flow": [0, 0], "against_flow": [0, 0], "flat": [0, 0]}
    for b in bars.values():
        if not b["outcome"]:
            continue
        early = [pr for pr in b["prints"] if pr[0] >= 300 - early_secs]
        up_v = sum(pr[3] for pr in early if pr[1] == "UP")
        dn_v = sum(pr[3] for pr in early if pr[1] == "DOWN")
        tot = up_v + dn_v
        if not tot:
            continue
        imb = (up_v - dn_v) / tot           # >0 bullish (UP), <0 bearish (DOWN)
        flow_side = "UP" if imb > 0.1 else "DOWN" if imb < -0.1 else "flat"
        for p in b["positions"]:
            won = b["outcome"] == p["side"]
            key = ("flat" if flow_side == "flat"
                   else "with_flow" if flow_side == p["side"] else "against_flow")
            buckets[key][0] += won
            buckets[key][1] += 1
    return {k: {"n": v[1], "q": round(v[0] / v[1], 3) if v[1] else None}
            for k, v in buckets.items()}


# ── MS-4: implied vs realized vol, traded as TAKER ────────────────────────────
def implied_vs_realized(bars, klines, theta=0.05):
    """Flagship. At bar open the market prices p_up (from up mid). A realized-vol
    fair p_up from the trailing move gives an independent estimate. When they
    diverge > theta, BUY the underpriced side as a TAKER at the ask (pay the
    fill), hold to expiry. This sidesteps maker adverse selection entirely.

    Fair p_up ≈ Phi(drift/sigma): with ~zero drift over 5m, fair ≈ 0.5 always,
    so this mainly tests whether the market's deviation from 0.5 is itself
    mispriced (fade extremes) — a cheap first cut; the real version conditions
    on realized sigma and momentum."""
    from statistics import NormalDist
    nd = NormalDist()
    # trailing realized sigma per coin (5m log-ret std over trailing 36)
    sig = {}
    for c, rows in klines.items():
        rets = [math.log(cl / op) for _, op, cl in rows if op > 0 and cl > 0]
        for i in range(len(rows)):
            w = rets[max(0, i - 36):i]
            sig[(c, rows[i][0])] = (sum(x * x for x in w) / len(w)) ** .5 if w else 0
    trades = []
    for b in bars.values():
        if not b["outcome"] or not b["snaps"]:
            continue
        first = sorted(b["snaps"], key=lambda s: -s[0])[0]  # largest secs_left
        up_mid = (first[1] + first[2]) / 2
        up_ask, dn_ask = first[2], first[4]
        if not (0 < up_mid < 1):
            continue
        # market-implied vs fair 0.5 (zero-drift): fade the deviation
        dev = up_mid - 0.5
        if abs(dev) < theta:
            continue
        # if UP is overpriced (up_mid>0.5+theta) buy DOWN at its ask, else buy UP
        if dev > 0:
            side, ask = "DOWN", dn_ask
        else:
            side, ask = "UP", up_ask
        if not (0 < ask < 1):
            continue
        won = b["outcome"] == side
        fee = 0.07 * ask * (1 - ask)  # taker fee schedule
        pnl = (1 - ask - fee) if won else (-ask - fee)
        trades.append((won, pnl))
    if not trades:
        return None
    n = len(trades)
    return {"n": n, "q": round(sum(w for w, _ in trades) / n, 3),
            "pnl_per_share": round(sum(p for _, p in trades) / n, 4),
            "total_pnl_10sh": round(10 * sum(p for _, p in trades), 2)}


def main():
    dates = sys.argv[1:]
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.join(here, "..", "tests", "data")
    pooled = {}
    print(f"{'date':11} {'CLV(mean,t,n)':>22} {'MS1 bal/with/against q':>26} {'MS4(q,pnl/sh,n)':>22}")
    for d in dates:
        dd = os.path.join(root, d)
        bars = load(dd)
        kl = json.load(_open(os.path.join(dd, "klines_5m.json.gz")))
        c = clv(bars)
        f = flow_gate(bars)
        m = implied_vs_realized(bars, kl)
        cstr = f"{c['mean_clv']:+.3f} t={c['t']} n={c['n']}" if c else "-"
        wf, af = f["with_flow"], f["against_flow"]
        fstr = f"with={wf['q']}(n{wf['n']}) vs={af['q']}(n{af['n']})"
        mstr = f"{m['q']},{m['pnl_per_share']:+.3f},n{m['n']}" if m else "-"
        print(f"{d:11} {cstr:>22} | MS1 {fstr:>30} | MS4 {mstr:>20}")
        pooled[d] = (c, f, m)


if __name__ == "__main__":
    main()


# ── follow-ups (2026-07-05): chase the MS-1 lead + new angles ──────────────────
def flow_side_picker(bars, early_secs=60):
    """Does bidding the FLOW side beat alternate (coin-flip)? For each bar compute
    early cross-token flow direction; 'flow-pick' q = outcome matches flow side.
    Compare to base outcome rate (best a blind picker gets)."""
    fp = [0, 0]; base_up = [0, 0]
    for b in bars.values():
        if not b["outcome"]:
            continue
        early = [pr for pr in b["prints"] if pr[0] >= 300 - early_secs]
        up_v = sum(pr[3] for pr in early if pr[1] == "UP")
        dn_v = sum(pr[3] for pr in early if pr[1] == "DOWN")
        if up_v + dn_v == 0:
            continue
        flow = "UP" if up_v > dn_v else "DOWN"
        fp[0] += (b["outcome"] == flow); fp[1] += 1
        base_up[0] += (b["outcome"] == "UP"); base_up[1] += 1
    return {"flow_pick_q": round(fp[0]/fp[1], 3) if fp[1] else None, "n": fp[1],
            "base_up_rate": round(base_up[0]/base_up[1], 3) if base_up[1] else None}


def momentum(bars):
    """Does the price MOVE in the first ~60s predict the outcome? Sign of
    (up_mid at ~240s left) − (up_mid at open). Continuation vs reversion at 5m."""
    cont = [0, 0]
    for b in bars.values():
        if not b["outcome"] or len(b["snaps"]) < 3:
            continue
        ss = sorted(b["snaps"], key=lambda s: -s[0])
        open_mid = (ss[0][1] + ss[0][2]) / 2
        early = [s for s in ss if s[0] <= 240]
        if not early:
            continue
        e_mid = (early[0][1] + early[0][2]) / 2
        if abs(e_mid - open_mid) < 0.02:
            continue
        pred = "UP" if e_mid > open_mid else "DOWN"   # continuation bet
        cont[0] += (b["outcome"] == pred); cont[1] += 1
    return {"continuation_q": round(cont[0]/cont[1], 3) if cont[1] else None, "n": cont[1]}


def loss_streaks(bars):
    """Do our fills clump into losing streaks (regime persistence)? P(next fill
    loses | this fill lost) vs base loss rate — tests a 'stop after N losses' gate."""
    seq = []
    for b in sorted(bars.values(), key=lambda x: x["bar_ts"] or 0):
        for p in b["positions"]:
            seq.append(0 if (b["outcome"] == p["side"]) else 1)
    if len(seq) < 20:
        return None
    base = sum(seq)/len(seq)
    after_loss = [seq[i+1] for i in range(len(seq)-1) if seq[i] == 1]
    return {"base_loss_rate": round(base, 3),
            "loss_after_loss": round(sum(after_loss)/len(after_loss), 3) if after_loss else None,
            "n": len(seq)}


def momentum_taker(bars, move_secs=240, min_move=0.02, fee_rate=0.07):
    """Momentum as a TAKER: if by `move_secs`-left the up_mid has moved > min_move
    from open, BUY the moved side AT ITS ASK (pay the adjusted price), hold to
    expiry. The 60s continuation win rate only matters net of the price already
    paid + taker fee. This is the real MS-4 (trend, not fade)."""
    trades = []
    for b in bars.values():
        if not b["outcome"] or len(b["snaps"]) < 3:
            continue
        ss = sorted(b["snaps"], key=lambda s: -s[0])
        open_mid = (ss[0][1] + ss[0][2]) / 2
        sig = [s for s in ss if s[0] <= move_secs]
        if not sig:
            continue
        s = sig[0]
        e_mid = (s[1] + s[2]) / 2
        move = e_mid - open_mid
        if abs(move) < min_move:
            continue
        if move > 0:
            side, ask = "UP", s[2]      # buy UP at up_ask
        else:
            side, ask = "DOWN", s[4]    # buy DOWN at down_ask
        if not (0 < ask < 1):
            continue
        won = b["outcome"] == side
        fee = fee_rate * ask * (1 - ask)
        trades.append(((1 - ask - fee) if won else (-ask - fee), won, ask))
    if not trades:
        return None
    n = len(trades)
    return {"n": n, "q": round(sum(w for _, w, _ in trades)/n, 3),
            "avg_ask_paid": round(sum(a for _, _, a in trades)/n, 3),
            "pnl_per_share": round(sum(p for p, _, _ in trades)/n, 4),
            "total_10sh": round(10*sum(p for p, _, _ in trades), 1)}
