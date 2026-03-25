#!/usr/bin/env bash
set -euo pipefail

echo "Uninstalling LiveKit from namespace element..."
helm uninstall livekit --namespace element

echo "Done."
