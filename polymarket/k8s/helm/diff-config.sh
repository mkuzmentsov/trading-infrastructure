#!/usr/bin/env bash
# Compare a deployed bot's running env-var Secret to what the chart + overlay
# would render right now from disk. Useful to confirm "is the running config
# what I think it is?" before tuning, or after a reverted deploy.
#
# Usage:
#   ./diff-config.sh                          # default: pm-btc-1h-smart
#   ./diff-config.sh pm-btc-1h-smart
#   ./diff-config.sh pm-btc-15m-smart
#   ./diff-config.sh pm-eth-1h-smart
#
# Discovery: chart name comes from `helm get metadata`. The overlay file is
# expected at ../bots/<release_with_underscores>.yaml (matching deploy.sh).
#
# Sensitive fields (private keys, telegram, etc.) are filtered before diffing.
set -euo pipefail

RELEASE="${1:-pm-btc-1h-smart}"
NAMESPACE="${NAMESPACE:-polymarket}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

for cmd in kubectl helm jq python3; do
  command -v "$cmd" &>/dev/null || { echo "Error: '$cmd' not found"; exit 1; }
done

# --- Resolve chart dir + overlay file ---------------------------------------
META=$(helm get metadata "$RELEASE" -n "$NAMESPACE" 2>&1) || {
  echo "Error: release '$RELEASE' not found in namespace '$NAMESPACE'" >&2
  echo "Available releases:" >&2
  helm list -n "$NAMESPACE" -q >&2 || true
  exit 1
}
CHART_NAME=$(awk -F': ' '/^CHART:/ {print $2}' <<<"$META")
[[ -n "$CHART_NAME" ]] || { echo "Error: could not parse chart name from helm metadata" >&2; exit 1; }

CHART_DIR="$SCRIPT_DIR/$CHART_NAME"
[[ -d "$CHART_DIR" ]] || { echo "Error: chart dir not found: $CHART_DIR" >&2; exit 1; }

# Overlay file: pm-btc-1h-smart -> ../bots/pm_btc_1h_smart.yaml
OVERLAY_NAME="${RELEASE//-/_}"
OVERLAY_FILE="$SCRIPT_DIR/bots/${OVERLAY_NAME}.yaml"
[[ -f "$OVERLAY_FILE" ]] || { echo "Error: overlay file not found: $OVERLAY_FILE" >&2; exit 1; }

SECRET_NAME="${RELEASE}-secret"

echo "Release:    $RELEASE"
echo "Chart:      $CHART_DIR"
echo "Overlay:    $OVERLAY_FILE"
echo "Namespace:  $NAMESPACE"
echo "Secret:     $SECRET_NAME"
echo

# --- Filter pattern (env vars to exclude from diff) -------------------------
EXCLUDE='PRIVATE_KEY|PASSPHRASE|API_SECRET|API_KEY|TELEGRAM|FUNDER|ADDRESS|RPC_URL|TOKEN|CHAT_ID'

# --- Live secret env --------------------------------------------------------
LIVE=$(mktemp)
trap 'rm -f "$LIVE" "$LOCAL"' EXIT

kubectl get secret "$SECRET_NAME" -n "$NAMESPACE" -o json \
  | jq -r '.data | to_entries[] | "\(.key)=\(.value | @base64d)"' \
  | grep -vE "$EXCLUDE" | sort > "$LIVE"

# --- Locally-rendered overlay -----------------------------------------------
LOCAL=$(mktemp)
helm template "$RELEASE" "$CHART_DIR" -f "$OVERLAY_FILE" --namespace "$NAMESPACE" 2>/dev/null \
  | python3 -c "
import sys, yaml
for d in yaml.safe_load_all(sys.stdin):
    if d and d.get('kind') == 'Secret' and '$RELEASE' in d.get('metadata', {}).get('name', ''):
        for k, v in (d.get('stringData') or {}).items():
            print(f'{k}={v}')
" | grep -vE "$EXCLUDE" | sort > "$LOCAL"

LIVE_N=$(wc -l < "$LIVE")
LOCAL_N=$(wc -l < "$LOCAL")
echo "live: $LIVE_N keys   local: $LOCAL_N keys"
echo

if diff -q "$LIVE" "$LOCAL" >/dev/null; then
  echo "✓ in sync — running pod matches overlay byte-for-byte"
  exit 0
fi

echo "✗ DRIFT detected (< running pod / > local overlay rendered now)"
echo "================================================================"
diff "$LIVE" "$LOCAL"
exit 1
