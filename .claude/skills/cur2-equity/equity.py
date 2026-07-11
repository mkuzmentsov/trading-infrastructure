#!/usr/bin/env python3
"""Current total balance (mark-to-market equity) for the cur+2 bettor wallet.

    equity = free USDC (cash)  +  current value of OPEN (unresolved) positions

Free USDC is read live from a running cur2 pod (same shared Polymarket wallet as
the whole fleet). Open positions come from Polymarket's data-api; only
`redeemable=false` rows are open — resolved-and-lost tokens (redeemable, curPrice 0)
are worthless dust and won won positions are already redeemed into cash.

Kube context MUST already be Hetzner (`source .dev-env-source`); this only shells
out to `kubectl`, it does not switch context.

Usage:
  python3 equity.py [--pod-grep sol-cur2] [--ns every-tick-single] [--json]
"""
import argparse, json, subprocess, sys, urllib.request

WALLET = "0xD632C1e14323B75456eA0A58d90B05fB7B7a1b2F"   # shared funder/proxy (Safe)


def free_usdc(ns, grep):
    pods = subprocess.run(["kubectl", "get", "pods", "-n", ns, "--no-headers"],
                          capture_output=True, text=True).stdout
    pod = next((l.split()[0] for l in pods.splitlines() if grep in l and " Running" in l), None)
    if not pod:
        sys.exit(f"no Running pod matching '{grep}' in ns {ns} (is the fleet up? context Hetzner?)")
    out = subprocess.run(
        ["kubectl", "exec", "-n", ns, pod, "--", "sh", "-c",
         "cd /app/scripts && python3 -c "
         "'from engine.clob import fetch_usdc_balance; print(round(fetch_usdc_balance(),2))'"],
        capture_output=True, text=True).stdout
    for line in reversed(out.splitlines()):          # last line = the printed number
        line = line.strip()
        try:
            return float(line), pod
        except ValueError:
            continue
    sys.exit(f"could not read balance from pod {pod}:\n{out}")


def open_positions():
    url = (f"https://data-api.polymarket.com/positions?user={WALLET}"
           "&sizeThreshold=0.1&limit=500&sortBy=CURRENT&sortDirection=DESC")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    rows = json.loads(urllib.request.urlopen(req, timeout=15).read())
    open_ = [p for p in rows if not p.get("redeemable")]
    won_unredeemed = [p for p in rows if p.get("redeemable") and p.get("curPrice", 0) > 0.5]
    return open_, won_unredeemed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pod-grep", default="sol-cur2")
    ap.add_argument("--ns", default="every-tick-single")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    cash, pod = free_usdc(a.ns, a.pod_grep)
    open_, won = open_positions()
    open_val = sum(p.get("currentValue", 0) for p in open_)
    won_val = sum(p.get("currentValue", 0) for p in won)   # rare: un-redeemed wins → add to equity
    equity = cash + open_val + won_val

    if a.json:
        print(json.dumps({"free_usdc": round(cash, 2), "open_value": round(open_val, 2),
                          "won_unredeemed": round(won_val, 2), "equity": round(equity, 2),
                          "open_positions": [{"title": p["title"], "outcome": p["outcome"],
                                              "size": p["size"], "price": p["curPrice"],
                                              "value": round(p["currentValue"], 2)} for p in open_]}, indent=2))
        return

    print(f"free USDC (cash, via {pod}):   ${cash:>9.2f}")
    print(f"open positions ({len(open_)}) mark-to-mkt: ${open_val:>9.2f}")
    if won_val:
        print(f"un-redeemed WINS ({len(won)}):          ${won_val:>9.2f}  (add — claim these)")
    print(f"{'-'*40}")
    print(f"TOTAL EQUITY:                  ${equity:>9.2f}")
    if open_:
        print("\nopen (unresolved) positions:")
        for p in sorted(open_, key=lambda x: -x.get("currentValue", 0)):
            print(f"  {p['title'][:46]:46} {p['outcome']:4} "
                  f"sz={p['size']:>5.1f} cur={p['curPrice']:.3f} val=${p['currentValue']:.2f}")


if __name__ == "__main__":
    main()
