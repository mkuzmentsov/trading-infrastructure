#!/usr/bin/env python3
"""Backtest library for every-tick-single — runs EXPERIMENTS.md sims against
event dumps from the running bots.

Data model (per coin events jsonl):
  bar_snapshot        — 15s book states; carries condition_id of ITS bar.
  paper_bar_settle    — fires at bar END; its market_start_ts belongs to the
                        NEXT bar (trap) — join on paper_condition_id.

Usage (CLI):
  python3 sim.py <events_dir> <klines_json>
where events_dir has {coin}_snap.jsonl and klines_json is
{coin: [[ts, open, close], ...]} of 5m candles covering the window.
"""
from __future__ import annotations

import gzip
import json
import os
import sys

COINS = ("btc", "eth", "sol", "xrp")


# ── loading ───────────────────────────────────────────────────────────────────

def _open(path):
    return gzip.open(path, "rt") if path.endswith(".gz") else open(path)


def load_events(events_dir: str, coins=COINS) -> dict:
    """→ {(coin, condition_id): {snaps:[(secs_left, up_bid, up_ask, down_bid,
    down_ask)], positions:[...], outcome, bar_ts}}"""
    bars: dict = {}
    for c in coins:
        for suffix in ("_snap.jsonl", "_snap.jsonl.gz"):
            path = os.path.join(events_dir, c + suffix)
            if os.path.exists(path):
                break
        else:
            continue
        for line in _open(path):
            try:
                e = json.loads(line)
            except Exception:
                continue
            ev = e.get("event")
            if ev in ("bar_snapshot", "trade_print") and e.get("condition_id"):
                k = (c, e["condition_id"])
                b = bars.setdefault(k, {"snaps": [], "prints": [], "positions": [],
                                        "outcome": None, "bar_ts": e.get("market_start_ts")})
                if ev == "trade_print":
                    b["prints"].append((e.get("seconds_left", 0), e.get("direction"),
                                        e.get("price", 0), e.get("size", 0)))
                    continue
                b["snaps"].append((e.get("seconds_left", 0),
                                   e.get("up_bid", 0), e.get("up_ask", 0),
                                   e.get("down_bid", 0), e.get("down_ask", 0)))
            elif ev == "paper_bar_settle":
                k = (c, e.get("paper_condition_id"))
                if k in bars:
                    if e.get("outcome") in ("UP", "DOWN"):
                        bars[k]["outcome"] = e["outcome"]
                    for po in (e.get("positions") or []):
                        bars[k]["positions"].append({
                            "side": po["direction"], "entry": po["entry_price"],
                            "size": po["size"],
                            "win": bool(po["win"] or po["exit_kind"] == "tp"),
                            "exit_kind": po["exit_kind"],
                        })
    return bars


# ── regime (no lookahead: bar t classified from bar t-1 vs trailing window) ───

def classify_regimes(klines: dict, trail: int = 36) -> dict:
    """→ {(coin, bar_ts): 'chop'|'mid'|'trend'} using |ret| of the PREVIOUS
    bar against the trailing p60/p85 of |ret| (per coin)."""
    out = {}
    for c, rows in klines.items():
        rets = [abs(cl / op - 1) * 1e4 for _, op, cl in rows]
        for i in range(1, len(rows)):
            lo = max(0, i - trail)
            window = sorted(rets[lo:i]) or [0]
            p60 = window[int(len(window) * .60)]
            p85 = window[min(int(len(window) * .85), len(window) - 1)]
            prev = rets[i - 1]
            out[(c, rows[i][0])] = ("trend" if prev >= p85
                                    else ("chop" if prev <= p60 else "mid"))
    return out


# ── E1: q(P | regime) grid ────────────────────────────────────────────────────

def grid_q(bars: dict, regimes: dict, prices=(0.49, 0.48, 0.46, 0.44, 0.42, 0.40)) -> list:
    """Hypothetical single-side fill at P (either side whose min ask crossed P;
    both cross → both count as fills for q purposes). Returns rows of
    (P, regime, fills, wins, q, ev_per_fill)."""
    rows = []
    for P in prices:
        stats: dict = {}
        for (c, cid), b in bars.items():
            if not b["outcome"] or len(b["snaps"]) < 6:
                continue
            reg = regimes.get((c, b["bar_ts"]), "mid")
            prints = b.get("prints") or []
            if prints:
                # exact: a resting bid at P fills iff a print occurs at <= P
                up_fill = any(d == "UP" and 0 < px <= P for _, d, px, _ in prints)
                dn_fill = any(d == "DOWN" and 0 < px <= P for _, d, px, _ in prints)
            else:
                up_fill = min((s[2] for s in b["snaps"] if 0 < s[2] < 1), default=1) <= P
                dn_fill = min((s[4] for s in b["snaps"] if 0 < s[4] < 1), default=1) <= P
            for side, crossed in (("UP", up_fill), ("DOWN", dn_fill)):
                if not crossed:
                    continue
                st = stats.setdefault(reg, [0, 0])
                st[0] += 1
                st[1] += (b["outcome"] == side)
        for reg, (n, w) in sorted(stats.items()):
            q = w / n if n else 0
            rows.append({"P": P, "regime": reg, "fills": n, "wins": w,
                         "q": round(q, 4), "ev_per_fill": round(q * (1 - P) - (1 - q) * P, 4)})
    return rows


# ── E2: late-bar salvage sell ─────────────────────────────────────────────────

def sim_salvage(bars: dict, arm_secs=90, arm_below=0.20, salvage=0.20) -> dict:
    """Rule: at <=arm_secs left, if held side's bid <= arm_below → rest maker
    sell at `salvage`; fills if any later snapshot bid >= salvage."""
    base = rule = 0.0
    armed = saved = capped = n = 0
    for (c, cid), b in bars.items():
        for p in b["positions"]:
            n += 1
            e, sz = p["entry"], p["size"]
            bpnl = sz * ((1 - e) if p["win"] else -e)
            base += bpnl
            if p["exit_kind"] == "tp":
                rule += bpnl
                continue
            series = sorted(((s[0], s[1] if p["side"] == "UP" else s[3])
                             for s in b["snaps"]), key=lambda x: -x[0])
            late = [(sl, bid) for sl, bid in series if sl <= arm_secs]
            is_armed = bool(late) and 0 < late[0][1] <= arm_below
            if not is_armed:
                rule += bpnl
                continue
            armed += 1
            arm_sl = late[0][0]
            filled = any(bid >= salvage for sl, bid in series if sl <= arm_sl)
            if filled:
                rule += sz * (salvage - e)
                if p["win"]:
                    capped += 1
                else:
                    saved += 1
            else:
                rule += bpnl
    return {"positions": n, "baseline": round(base, 2), "with_rule": round(rule, 2),
            "delta": round(rule - base, 2), "armed": armed, "saved": saved,
            "capped_wins": capped}


# ── headline metrics (regression baseline) ────────────────────────────────────

def metrics(bars: dict) -> dict:
    fills = wins = settled = 0
    pnl = 0.0
    for b in bars.values():
        if b["outcome"]:
            settled += 1
        for p in b["positions"]:
            fills += 1
            wins += p["win"]
            pnl += p["size"] * ((1 - p["entry"]) if p["win"] else -p["entry"])
    return {"bars": settled, "fills": fills, "wins": wins,
            "q": round(wins / fills, 4) if fills else 0.0,
            "pnl_hold_to_expiry": round(pnl, 2)}


def main():
    events_dir, klines_path = sys.argv[1], sys.argv[2]
    bars = load_events(events_dir)
    klines = json.load(_open(klines_path))
    regimes = classify_regimes(klines)
    print("METRICS:", json.dumps(metrics(bars)))
    print("\nE1 grid q(P|regime)  [no-lookahead prev-bar regime]:")
    for r in grid_q(bars, regimes):
        print(f"  P={r['P']:.2f} {r['regime']:5} fills={r['fills']:3} q={r['q']*100:5.1f}%  EV/fill={r['ev_per_fill']:+.3f}")
    print("\nE2 salvage (90s / bid<=0.20 / sell@0.20):")
    print(" ", json.dumps(sim_salvage(bars)))


if __name__ == "__main__":
    main()
