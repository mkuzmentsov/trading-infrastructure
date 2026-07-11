#!/usr/bin/env bash
# Build + push the generic-crypto-image (linux/amd64 for the Hetzner nodes).
# Usage: ./build.sh [tag]   (default 0.1)
set -euo pipefail
cd "$(dirname "$0")"
TAG="${1:-0.1}"
IMAGE="mkuzmentsov/generic-crypto-image:${TAG}"
echo "building + pushing ${IMAGE} (linux/amd64)"
docker buildx build --platform linux/amd64 -t "${IMAGE}" --push .
echo "done: ${IMAGE}"
