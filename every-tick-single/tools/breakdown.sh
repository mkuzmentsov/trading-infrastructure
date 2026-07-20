#!/usr/bin/env bash
# Tail-fleet breakdown — per-coin stats + real on-chain balance.
#
# USAGE (from repo root, after sourcing the k3s context):
#   cd <repo root> && source .dev-env-source        # hetzner-k3s-cluster-master1
#   every-tick-single/tools/breakdown.sh [VARIANT] [WINDOW]
#
#   VARIANT: tail-every (5m v1, default) | tailv3 (5m gated) | tail15 (15m) | all
#   WINDOW:  today (today-UTC, default) | life (since inception, uses rotated .gz)
#
# Columns: bets | win% | PnL | maxDD | fill% | avg_fill_px
# Then prints REAL BALANCE = on-chain pUSD (Polymarket USD wrapper) — the CLOB
# get_balance_allowance view LAGS by tens of $, so we read the token directly.
set -uo pipefail
NS=every-tick-single
VARIANT="${1:-tail-every}"
WINDOW="${2:-today}"

ctx=$(kubectl config current-context 2>/dev/null)
if [[ "$ctx" != "hetzner-k3s-cluster-master1" ]]; then
  echo "ERROR: kube context is '$ctx'. Run: cd <repo root> && source .dev-env-source" >&2
  exit 1
fi

# match set: 'all' -> every tail bot; else the specific variant suffix
case "$VARIANT" in
  all)        RE='-tail(-every|v3|15|1h)?-' ;;
  tail-every) RE='-tail-every' ;;
  *)          RE="-${VARIANT}-" ;;
esac

date '+%H:%M %Z'; echo "variant=$VARIANT window=$WINDOW"
printf '%-16s %5s %5s %9s %8s %5s %6s\n' bot bets win% PnL maxDD fill avg_px
for pod in $(kubectl get pods -n "$NS" --no-headers | awk -v re="$RE" '$1 ~ re && $3=="Running" {print $1}' | sort); do
  n=$(echo "$pod" | sed 's/-every-tick.*//')
  kubectl exec -n "$NS" "$pod" -- python3 -c "
import json, glob, gzip, time
WIN='$WINDOW'
cut = (time.time() - time.time()%86400) if WIN=='today' else 0
files = ['/app/logs/logs-training-events.jsonl'] if WIN=='today' else sorted(glob.glob('/app/logs/logs-training-events.jsonl*'))
n=w=0; p=0.0; eq=pk=dd=0.0; spent=[]; fpx=[]
for f in files:
    op = gzip.open if f.endswith('.gz') else open
    try:
        for line in op(f,'rt'):
            try: e=json.loads(line)
            except: continue
            if e.get('t',0) < cut: continue
            if e.get('ev')=='FAV_BET_SETTLE':
                n+=1; w+=bool(e.get('won')); x=e.get('pnl',0); p+=x
                eq+=x; pk=max(pk,eq); dd=max(dd,pk-eq)
            elif e.get('ev')=='FAV_BET_PLACED' and e.get('fill_qty'):
                spent.append(min(1.0, e['fill_qty']*e.get('fill_px',0.06)/4.96)); fpx.append(e.get('fill_px',0))
    except FileNotFoundError: pass
f = f'{100*sum(spent)/len(spent):.0f}%' if spent else '-'
ap = f'{sum(fpx)/len(fpx):.3f}' if fpx else '-'
print(f'{n}|{100*w/max(n,1):.0f}%|{p:+.2f}|{dd:.2f}|{f}|{ap}')" 2>/dev/null \
  | awk -F'|' -v b="$n" '{printf "%-16s %5s %5s %9s %8s %5s %6s\n", b, $1, $2, $3, $4, $5, $6}'
done
echo
every-tick-single/tools/balance.sh 2>/dev/null || "$(dirname "$0")/balance.sh"
