---
name: cur2-equity
description: Get the cur+2 bettor wallet's current TOTAL balance = free USDC + current value of open positions (mark-to-market equity). Use when the user asks for total balance, equity, net worth, or "balance including / adjusted for open positions".
---

# cur2-equity

One-shot mark-to-market equity for the shared cur+2 bettor wallet
(`0xD632…`, used by sol-cur2 / eth-cur2 / any cur2 bot):

```
equity = free USDC (cash)  +  current value of OPEN (unresolved) positions
```

Kube context MUST be Hetzner first (silently hits AWS EKS otherwise):
`cd <repo root> && source .dev-env-source && kubectl config current-context`
→ `hetzner-k3s-cluster-master1`. Run from the repo root.

```
python3 .claude/skills/cur2-equity/equity.py            # human-readable breakdown
python3 .claude/skills/cur2-equity/equity.py --json     # machine-readable
```
Prints free USDC, open-position mark-to-market, and TOTAL EQUITY, plus a line per
open position. Flags: `--pod-grep sol-cur2` (which pod to read cash from — any
running cur2 pod works), `--ns every-tick-single`.

## How it works / gotchas

- **Free USDC** is read live via `engine.clob.fetch_usdc_balance` exec'd inside a
  running cur2 pod (no local py_clob_client needed).
- **Open positions** from `data-api.polymarket.com/positions?user=<wallet>`. Only
  `redeemable=false` rows are OPEN and counted. `redeemable=true` + `curPrice≈0` are
  resolved-and-LOST dust (hundreds of them) → worth $0, ignored. Won positions are
  auto-redeemed into cash, so **cash already includes wins — don't double-count**.
  The rare `redeemable=true` + `curPrice≈1` is an un-redeemed win; the script adds it
  and flags "claim these".
- These 5m markets resolve in minutes, so a position sitting near 0.50 will snap to
  $0 or ~$10 shortly — equity jitters as bars settle. It's a snapshot.
- For the realized-PnL time series (not the point-in-time equity), use `/cur2-pnl-chart`.
