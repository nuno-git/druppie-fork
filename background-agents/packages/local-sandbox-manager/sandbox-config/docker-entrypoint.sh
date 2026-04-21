#!/bin/bash
set -e
# Warn if cache directories aren't writable (stale root-owned volume)
for d in /cache/npm /cache/pnpm /cache/bun /cache/uv /cache/pip; do
    if [ -d "$d" ] && [ ! -w "$d" ]; then
        echo "[entrypoint] WARNING: $d not writable. Run: docker compose --profile reset-cache run --rm reset-cache"
    fi
done
# Install Druppie SDK if mounted (volume from host)
if [ -d "/druppie-sdk" ] && [ -f "/druppie-sdk/pyproject.toml" ]; then
    pip install --no-cache-dir /druppie-sdk 2>/dev/null || echo "[entrypoint] WARNING: Failed to install druppie-sdk"
fi
exec "$@"
