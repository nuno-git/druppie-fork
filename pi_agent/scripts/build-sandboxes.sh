#!/usr/bin/env bash
# Build both sandbox images. Run from repo root.
set -euo pipefail

cd "$(dirname "$0")/.."

echo "→ building oneshot-sandbox:latest"
docker build -t oneshot-sandbox:latest sandbox/

echo "→ building oneshot-push-sandbox:latest"
docker build -t oneshot-push-sandbox:latest push-sandbox/

echo "✓ images ready:"
docker image ls | grep -E 'oneshot-(sandbox|push-sandbox)'
