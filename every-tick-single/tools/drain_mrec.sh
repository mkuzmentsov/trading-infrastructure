#!/bin/zsh
# One drain cycle: pull completed (.gz) recorder files from all mrec pods,
# verify (size + gzip -t), then remove ONLY verified files from the pod.
set -u
cd /Users/maxkuzmentsov/development/projects/my/hummingbot/hummingbot-infra || exit 1
source .dev-env-source 2>/dev/null
NS=every-tick-single
DEST=/Users/maxkuzmentsov/development/projects/my/hummingbot/hummingbot-infra/every-tick-single/data/mrec
ok=0; fail=0; bytes=0
drain_pod() {
  local pod=$1
  local short=${pod%%-every-tick-single*}         # e.g. btc-mrec, eth-mrec15m
  local coin=${short%%-*}
  local sub=$short
  [ "$short" = "${coin}-mrec" ] && sub=$coin      # 5m keeps plain coin dir
  mkdir -p "$DEST/$sub"
  # only files SETTLED for >=90s: at the hour rollover all 17 pods gzip at
  # once and a file still being written changes size mid-transfer, which
  # fails verification (2026-09-07: 7 such failures in one cycle)
  local listing=$(kubectl exec -n $NS $pod -- sh -c 'now=$(date +%s); for f in /app/logs/raw/*.jsonl.gz; do [ -f "$f" ] || continue; m=$(stat -c %Y "$f" 2>/dev/null || echo 0); [ $((now - m)) -ge 90 ] && echo "$f $(wc -c < $f)"; done' 2>/dev/null)
  echo "$listing" | while read rf rsize; do
    [ -z "$rf" ] && continue
    local bn=$(basename $rf) lf="$DEST/$sub/$(basename $rf)" got=0
    for try in 1 2 3 4 5 6; do
      kubectl exec -n $NS $pod -- cat $rf > "$lf.part" 2>/dev/null
      # large event files (btc ~18MB) occasionally truncate on the exec
      # channel; back off a little between attempts
      [ $try -ge 2 ] && sleep $((try * 3))
      if [ "$(stat -f %z "$lf.part" 2>/dev/null || echo 0)" = "$rsize" ] && gzip -t "$lf.part" 2>/dev/null; then
        mv "$lf.part" "$lf"; got=1; break
      fi
    done
    if [ $got = 1 ]; then
      kubectl exec -n $NS $pod -- rm -f $rf 2>/dev/null && echo "DRAINED $sub/$bn $rsize"
    else
      rm -f "$lf.part"; echo "FAIL $sub/$bn"
    fi
  done
}
for pod in $(kubectl get pods -n $NS --no-headers | awk '/mrec/ && $3=="Running" {print $1}'); do
  drain_pod $pod &
  while [ $(jobs | wc -l) -ge 3 ]; do wait ${${(v)jobstates}[1]%%:*} 2>/dev/null || sleep 1; done
done
wait
echo CYCLE-DONE
