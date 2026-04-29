#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ $# -lt 2 ]]; then
  cat <<'EOF'
Usage:
  ./replay-vs-actual.sh <strategy-yaml> <bundle-dir>

Examples:
  ./replay-vs-actual.sh ../bots/pm_btc_3.yaml ./pm-btc-logs_pm-btc-3_20260419_101700
  ./replay-vs-actual.sh ../bots/pm_btc_2.yaml ./pm-btc-logs_pm-btc-2_20260418_174254
EOF
  exit 1
fi

YAML_PATH="$1"
BUNDLE_DIR="$2"

exec python3 "$SCRIPT_DIR/files/scripts/strategies/replay_vs_actual_report.py" "$YAML_PATH" "$BUNDLE_DIR"
