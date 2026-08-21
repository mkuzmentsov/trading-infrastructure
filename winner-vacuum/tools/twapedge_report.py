#!/usr/bin/env python3
"""twapedge fleet status. Run after `source .dev-env-source`.

    python3 winner-vacuum/tools/twapedge_report.py [hours]

The bot is a falsification test of the 2026-08-07 TWAP settlement switch: the
same signal is -EV under point settlement and +EV under TWAP settlement, so
BEFORE the switch this fleet is expected to LOSE (~27% hit rate) and after it
to flip. The report therefore splits every number at the boundary and scores
the three candidate settlement rules against the real outcome.
"""
import collections
import json
import os
import subprocess
import sys
import time

NS = "every-tick-single"
COINS = ["btc", "eth", "sol", "xrp", "doge", "bnb"]
SWITCH = 1786060800          # 2026-08-07 00:00:00 UTC
HOURS = float(sys.argv[1]) if len(sys.argv) > 1 else 24.0


def pull(coin):
    cmd = ["kubectl", "exec", "-n", NS, f"deploy/{coin}-twapedge-{NS}", "--",
           "sh", "-c", "cd /app/logs && for f in logs-training-events.jsonl.*.gz; do [ -e \"$f\" ] && gunzip -c \"$f\"; done 2>/dev/null; cat logs-training-events.jsonl 2>/dev/null"]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    except Exception as e:
        return [], str(e)[:60]
    rows = []
    for line in out.stdout.splitlines():
        try:
            rows.append(json.loads(line))
        except Exception:
            continue
    return rows, None


def kyiv(ts=None):
    return time.strftime("%Y-%m-%d %H:%M", time.gmtime((ts or time.time()) + 3 * 3600))


def main():
    cutoff = time.time() - HOURS * 3600
    all_rows = {}
    errs = {}
    for c in COINS:
        r, e = pull(c)
        all_rows[c] = r
        if e:
            errs[c] = e

    print(f"twapedge PAPER fleet — {kyiv()} Kyiv   (last {HOURS:.0f}h)")
    sw = SWITCH - time.time()
    print(f"TWAP settlement switch: {kyiv(SWITCH)} Kyiv — "
          f"{'in %.1fh' % (sw/3600) if sw > 0 else 'ACTIVE %.1fh ago' % (-sw/3600)}")
    if errs:
        print(f"!! pull errors: {errs}")

    print(f"\n{'coin':>5} {'evals':>6} {'bets':>5} {'settled':>8} {'won':>4} "
          f"{'hit%':>6} {'paper PnL':>10} {'maxDD':>8} {'up':>6} {'lat':>5}")
    fleet = []
    tot_bets = tot_won = 0
    tot_pnl = 0.0
    rule = collections.Counter()
    for c in COINS:
        rows = [r for r in all_rows[c] if r.get("t", 0) >= cutoff]
        ev = [r for r in rows if r.get("ev") == "PF_TE_EVAL"]
        bets = [r for r in rows if r.get("ev") == "PF_TE_BET"]
        st = [r for r in rows if r.get("ev") == "PF_TE_SETTLE"]
        hb = [r for r in rows if r.get("ev") == "PF_TE_HB"]
        done = [r for r in st if r.get("bet_side")]
        won = sum(1 for r in done if r.get("bet_side") == r.get("won"))
        pnl = sum(float(r.get("pnl") or 0) for r in st)
        cum = 0.0
        peak = 0.0
        dd = 0.0
        for r in sorted(st, key=lambda x: x["t"]):
            cum += float(r.get("pnl") or 0)
            peak = max(peak, cum)
            dd = min(dd, cum - peak)
        for r in st:
            for k in ("point_ok", "h1_ok", "h2_ok"):
                if r.get(k) is not None:
                    rule[(k, bool(r[k]))] += 1
        starts = [r for r in all_rows[c] if r.get("ev") == "PF_TE_START"]
        up = (time.time() - starts[-1]["t"]) / 3600 if starts else 0
        lat = hb[-1].get("rtds_lat") if hb else None
        tot_bets += len(done)
        tot_won += won
        tot_pnl += pnl
        fleet += [(r["t"], float(r.get("pnl") or 0)) for r in st]
        print(f"{c:>5} {len(ev):>6} {len(bets):>5} {len(done):>8} {won:>4} "
              f"{(won/len(done)*100 if done else 0):>5.0f}% {pnl:>+10.2f} "
              f"{dd:>8.2f} {up:>5.1f}h {str(lat):>5}")

    cum = peak = dd = 0.0
    for _, p in sorted(fleet):
        cum += p
        peak = max(peak, cum)
        dd = min(dd, cum - peak)
    print(f"{'FLEET':>5} {'':>6} {'':>5} {tot_bets:>8} {tot_won:>4} "
          f"{(tot_won/tot_bets*100 if tot_bets else 0):>5.0f}% {tot_pnl:>+10.2f} "
          f"{dd:>8.2f}")

    print("\nwhich settlement rule matches the real outcome "
          "(all bars, not just bets):")
    for k, lab in (("point_ok", "point sample at T"),
                   ("h1_ok", "TWAP [T-32,T-3]"),
                   ("h2_ok", "TWAP [T-29,T]")):
        y, n = rule[(k, True)], rule[(k, False)]
        if y + n:
            print(f"   {lab:<20} {y:>5}/{y+n:<5} = {y/(y+n)*100:6.2f}%")

    print("\nexpectation split at the switch (the falsification test):")
    for lab, lo, hi in (("BEFORE switch", 0, SWITCH), ("AFTER switch", SWITCH, 9e9)):
        d = [r for c in COINS for r in all_rows[c]
             if r.get("ev") == "PF_TE_SETTLE" and r.get("bet_side")
             and lo <= r.get("t", 0) < hi]
        if not d:
            print(f"   {lab:<14} no settled bets yet")
            continue
        w = sum(1 for r in d if r.get("bet_side") == r.get("won"))
        p = sum(float(r.get("pnl") or 0) for r in d)
        exp = "should LOSE (~27% hit)" if lo == 0 else "should WIN (~100% hit)"
        print(f"   {lab:<14} {len(d):>4} bets  {w/len(d)*100:>5.1f}% hit  "
              f"{p:>+9.2f}   [{exp}]")


if __name__ == "__main__":
    main()
