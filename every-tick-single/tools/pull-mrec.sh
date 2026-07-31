#!/bin/bash
# Pull one mrec coin's rolled .gz archives locally, verify (size + md5 + gzip -t),
# then delete ONLY the verified files on the pod. The live (uncompressed) current
# hour .jsonl is never touched.
set -uo pipefail
c="$1"; DEST="$2/$c"; NS=every-tick-single
# plain coin ("btc") -> the 5m recorder; names containing "mrec" ("btc-mrec1h",
# "btc-mrec1d") -> that recorder deployment directly
case "$c" in
  *mrec*) POD="deploy/${c}-every-tick-single" ;;
  *)      POD="deploy/${c}-mrec-every-tick-single" ;;
esac
mkdir -p "$DEST"

kubectl exec -n "$NS" "$POD" -- sh -c \
  'cd /app/logs/raw && for f in *.jsonl.gz; do [ -e "$f" ] || continue; printf "%s %s %s\n" "$f" "$(stat -c%s "$f")" "$(md5sum "$f" | cut -d" " -f1)"; done' \
  > "$DEST/.manifest" 2>/dev/null

n=$(grep -c . "$DEST/.manifest" 2>/dev/null || echo 0)
[ "$n" -eq 0 ] && { echo "$c: NO FILES (manifest empty) - nothing pulled, nothing deleted"; exit 1; }

ok=0; fail=0; : > "$DEST/.verified"
while read -r f size md5; do
  [ -z "${f:-}" ] && continue
  lf="$DEST/$f"
  for attempt in 1 2; do
    if [ -f "$lf" ] && [ "$(stat -f%z "$lf" 2>/dev/null)" = "$size" ] \
       && [ "$(md5 -q "$lf" 2>/dev/null)" = "$md5" ]; then break; fi
    kubectl exec -n "$NS" "$POD" -- cat "/app/logs/raw/$f" > "$lf" 2>/dev/null
  done
  lsize=$(stat -f%z "$lf" 2>/dev/null || echo 0)
  lmd5=$(md5 -q "$lf" 2>/dev/null || echo none)
  if [ "$lsize" = "$size" ] && [ "$lmd5" = "$md5" ] && gzip -t "$lf" 2>/dev/null; then
    echo "$f" >> "$DEST/.verified"; ok=$((ok+1))
  else
    fail=$((fail+1)); echo "$c FAIL $f local=$lsize/$size md5=$lmd5/$md5"
  fi
done < "$DEST/.manifest"

echo "$c: verified=$ok failed=$fail of $n"

# delete remotely ONLY what verified byte-for-byte and passed gzip -t
if [ "$ok" -gt 0 ]; then
  names=$(tr '\n' ' ' < "$DEST/.verified")
  kubectl exec -n "$NS" "$POD" -- sh -c "cd /app/logs/raw && rm -f $names" 2>/dev/null
  left=$(kubectl exec -n "$NS" "$POD" -- sh -c 'ls /app/logs/raw/*.jsonl.gz 2>/dev/null | wc -l' 2>/dev/null | tr -d ' ')
  echo "$c: deleted $ok remote gz, remaining gz on pod=$left"
fi
[ "$fail" -eq 0 ] || exit 2
exit 0
