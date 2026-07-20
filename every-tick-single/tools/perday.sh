#!/usr/bin/env bash
# Per-coin, per-UTC-day PnL breakdown for a tail variant (uses rotated .gz).
# USAGE: cd <repo root> && source .dev-env-source
#        every-tick-single/tools/perday.sh [VARIANT]
#   VARIANT: tail-every (default) | tailv3 | tail15
set -uo pipefail
NS=every-tick-single
VARIANT="${1:-tail-every}"
case "$VARIANT" in tail-every) RE='-tail-every' ;; *) RE="-${VARIANT}-" ;; esac
for pod in $(kubectl get pods -n "$NS" --no-headers | awk -v re="$RE" '$1 ~ re && $3=="Running" {print $1}' | sort); do
  n=$(echo "$pod" | sed 's/-tail.*//')
  kubectl exec -n "$NS" "$pod" -- python3 -c "
import json, glob, gzip, time
from collections import defaultdict
days=defaultdict(lambda:[0,0,0.0])
for f in sorted(glob.glob('/app/logs/logs-training-events.jsonl*')):
    op=gzip.open if f.endswith('.gz') else open
    try:
        for line in op(f,'rt'):
            if 'FAV_BET_SETTLE' not in line: continue
            try: e=json.loads(line)
            except: continue
            if e.get('ev')!='FAV_BET_SETTLE': continue
            d=time.strftime('%m-%d', time.gmtime(e.get('t',0)))
            days[d][0]+=1; days[d][1]+=bool(e.get('won')); days[d][2]+=e.get('pnl',0)
    except Exception: pass
print(' | '.join(f'{d}:{v[0]}/{100*v[1]/max(v[0],1):.0f}%/{v[2]:+.0f}' for d,v in sorted(days.items())))" 2>/dev/null \
  | sed "s/^/$n: /"
done
