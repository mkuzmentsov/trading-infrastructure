"""
Full-bar tail-buy backtest, per the user spec 2026-08-02:

  "buy losing side for <= 5c and hold till redemption (or sell at 50c)"

Differs from view.pkl/FINDINGS.md (last-180s only): entry is allowed at ANY
time during the live bar. One bet per (bar, side): at the FIRST instant that
side is trailing and its ask <= MAX_PX with size, we lift the ask (taker,
fee 0.07*p*(1-p) per crypto_fees_v2). Then:

  hold : redemption  -> won ? 1.0 : 0.0
  tp50 : first later in-bar bid >= 0.50 -> sell at that bid (taker fee),
         else redemption.

Causality: entry/exit use only the instant's book; the only future-looking
value is the resolution label. Streaming replay in file order (recorder
appends in time order), so no lookahead is possible by construction.

Usage: python3 fullbar_tail.py [mrec_root]
"""
from __future__ import annotations

import glob
import gzip
import json
import sys
from collections import defaultdict

COINS = ["btc", "eth", "sol", "xrp", "bnb", "doge"]
MAX_PX = 0.05
TP = 0.50


def fee(p: float) -> float:
    return 0.07 * p * (1.0 - p)


def run(root: str):
    bets = []          # dicts: coin ws side px tl asz exit_px exit_tl won
    open_pos = defaultdict(dict)   # ws -> side -> bet dict (entered, awaiting exit/RES)
    entered = defaultdict(set)     # ws -> sides already bet (one bet per bar-side)

    for coin in COINS:
        files = sorted(glob.glob(f"{root}/{coin}/{coin}-mrec-*.jsonl.gz"))
        open_pos.clear()
        entered.clear()
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
                        win = r.get("win")
                        for side, b in open_pos.pop(ws, {}).items():
                            if win in ("UP", "DOWN"):
                                b["won"] = (side == win)
                                bets.append(b)
                        continue
                    if ev != "SNAP" or r.get("role") != "cur":
                        continue
                    tl = r.get("tl")
                    if tl is None or tl <= 0:
                        continue
                    lead = r.get("lead_bps")
                    for side, a, asz, bd in (
                            ("UP", r.get("ua"), r.get("uas"), r.get("ub")),
                            ("DOWN", r.get("da"), r.get("das"), r.get("db"))):
                        b = open_pos[ws].get(side)
                        if b is not None:
                            # armed: check the 50c take-profit path
                            if b["exit_px"] is None and bd is not None and bd >= TP:
                                b["exit_px"], b["exit_tl"] = bd, tl
                            continue
                        if side in entered[ws]:
                            continue
                        if a is None or a > MAX_PX or not asz:
                            continue
                        if lead is None:
                            continue
                        trailing = (lead > 0) != (side == "UP")
                        if not trailing:
                            continue
                        entered[ws].add(side)
                        open_pos[ws][side] = {
                            "coin": coin, "ws": ws, "side": side,
                            "px": a, "tl": tl, "asz": asz,
                            "exit_px": None, "exit_tl": None, "won": None,
                        }
    return bets


def pnl_hold(b):
    return (1.0 if b["won"] else 0.0) - b["px"] - fee(b["px"])


def pnl_tp(b):
    if b["exit_px"] is not None:
        return b["exit_px"] - b["px"] - fee(b["px"]) - fee(b["exit_px"])
    return pnl_hold(b)


def table(bets, keyf, title, keyname):
    rows = defaultdict(list)
    for b in bets:
        rows[keyf(b)].append(b)
    print(f"\n## {title}")
    print(f"{keyname:>12} {'n':>6} {'win%':>7} {'tp-hit%':>8} "
          f"{'EV/sh hold':>11} {'EV/sh tp50':>11}")
    for k in sorted(rows):
        bs = rows[k]
        n = len(bs)
        w = sum(b["won"] for b in bs) / n * 100
        t = sum(b["exit_px"] is not None for b in bs) / n * 100
        eh = sum(pnl_hold(b) for b in bs) / n
        et = sum(pnl_tp(b) for b in bs) / n
        print(f"{str(k):>12} {n:>6} {w:>6.2f}% {t:>7.2f}% {eh:>+11.4f} {et:>+11.4f}")


def main():
    root = sys.argv[1] if len(sys.argv) > 1 else "../../data/mrec"
    bets = run(root)
    n = len(bets)
    if not n:
        print("no bets")
        return
    w = sum(b["won"] for b in bets) / n * 100
    eh = sum(pnl_hold(b) for b in bets) / n
    et = sum(pnl_tp(b) for b in bets) / n
    tp = sum(b["exit_px"] is not None for b in bets) / n * 100
    bars = len({(b["coin"], b["ws"]) for b in bets})
    print(f"POOLED: {n} bets over {bars} bars | win {w:.2f}% | tp-hit {tp:.2f}% | "
          f"EV/share hold {eh:+.4f} | EV/share tp50 {et:+.4f}")

    table(bets, lambda b: round(b["px"] * 100), "by entry ask (cents)", "ask_c")
    table(bets, lambda b: ("t>240" if b["tl"] > 240 else "t180-240" if b["tl"] > 180
                           else "t120-180" if b["tl"] > 120 else "t60-120" if b["tl"] > 60
                           else "t30-60" if b["tl"] > 30 else "t<=30"),
          "by entry time-left (s)", "tl bucket")
    table(bets, lambda b: b["coin"], "by coin", "coin")

    # the previously unmeasured zone: entries earlier than the 180s view
    early = [b for b in bets if b["tl"] > 180]
    if early:
        print(f"\n## EARLY-ONLY (tl>180s, outside the FINDINGS.md view): "
              f"n={len(early)}, win {sum(b['won'] for b in early)/len(early)*100:.2f}%, "
              f"EV/sh hold {sum(pnl_hold(b) for b in early)/len(early):+.4f}, "
              f"tp50 {sum(pnl_tp(b) for b in early)/len(early):+.4f}")

    # winners' path: does the 50c TP rescue or cap?
    winners = [b for b in bets if b["won"]]
    if winners:
        thr = sum(b["exit_px"] is not None for b in winners) / len(winners) * 100
        print(f"\nwinners passing through 50c before close: {thr:.1f}% of {len(winners)}")
    tp_losers = [b for b in bets if b["exit_px"] is not None and not b["won"]]
    print(f"spike-then-die (hit 50c, lost anyway): {len(tp_losers)}")


if __name__ == "__main__":
    main()
