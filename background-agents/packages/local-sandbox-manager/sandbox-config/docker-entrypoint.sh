#!/bin/bash
set -e
# Warn if cache directories aren't writable (stale root-owned volume)
for d in /cache/npm /cache/pnpm /cache/bun /cache/uv /cache/pip; do
    if [ -d "$d" ] && [ ! -w "$d" ]; then
        echo "[entrypoint] WARNING: $d not writable. Run: docker compose --profile reset-cache run --rm reset-cache"
    fi
done
exec "$@"
