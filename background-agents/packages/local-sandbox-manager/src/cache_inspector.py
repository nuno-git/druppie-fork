"""Inspect cached packages in the shared dependency cache volume."""

import json
import logging
import re
import subprocess
import time
from datetime import datetime, timezone

from . import config

log = logging.getLogger("sandbox-api")

MAX_PACKAGES_PER_MANAGER = 500
CACHE_TTL_SECONDS = 60

_cached_result: dict | None = None
_cached_at: float = 0.0


def inspect_cached_packages() -> dict:
    """Run a Docker container to list packages from the shared dep cache volume.

    Results are cached in-memory for 60 seconds.
    """
    global _cached_result, _cached_at

    volume = config.SANDBOX_CACHE_VOLUME
    if not volume:
        return {"managers": {}, "total_count": 0, "scanned_at": None}

    now = time.monotonic()
    if _cached_result is not None and (now - _cached_at) < CACHE_TTL_SECONDS:
        return _cached_result

    result = _scan_volume(volume)
    _cached_result = result
    _cached_at = now
    return result


def _scan_volume(volume: str) -> dict:
    """Mount the cache volume read-only in an Alpine container and list packages."""

    # Shell script that prints JSON-ish output we can parse.
    # Each line is: MANAGER\tNAME\tVERSION
    # POSIX sh compatible — Alpine uses ash, not bash
    script = r"""
MAX=500

# --- npm: parse cacache index for package tgz URLs ---
if [ -d /cache/npm/_cacache/index-v5 ]; then
    grep -rh '"key"' /cache/npm/_cacache/index-v5/ 2>/dev/null \
        | sed -n 's|.*registry\.npmjs\.org/\([^"]*\)\.tgz.*|\1|p' \
        | sed 's|.*/-/||' \
        | sort -u \
        | head -$MAX \
        | while IFS= read -r entry; do
            ver=$(echo "$entry" | sed 's/.*-\([0-9][0-9.]*\)$/\1/')
            name=$(echo "$entry" | sed "s/-${ver}\$//")
            [ -n "$name" ] && [ -n "$ver" ] && printf 'npm\t%s\t%s\n' "$name" "$ver"
        done
fi

# --- bun: package.json in versioned dirs ---
if [ -d /cache/bun ]; then
    find /cache/bun -maxdepth 2 -name "package.json" -size +10c 2>/dev/null | head -$MAX | while read -r pj; do
        n=$(grep -o '"name" *: *"[^"]*"' "$pj" 2>/dev/null | head -1 | sed 's/.*: *"//;s/"//')
        v=$(grep -o '"version" *: *"[^"]*"' "$pj" 2>/dev/null | head -1 | sed 's/.*: *"//;s/"//')
        [ -n "$n" ] && [ -n "$v" ] && printf 'bun\t%s\t%s\n' "$n" "$v"
    done
fi

# --- pnpm: package.json in content store ---
if [ -d /cache/pnpm ]; then
    find /cache/pnpm -name "package.json" -size +10c 2>/dev/null | head -$MAX | while read -r pj; do
        n=$(grep -o '"name" *: *"[^"]*"' "$pj" 2>/dev/null | head -1 | sed 's/.*: *"//;s/"//')
        v=$(grep -o '"version" *: *"[^"]*"' "$pj" 2>/dev/null | head -1 | sed 's/.*: *"//;s/"//')
        [ -n "$n" ] && [ -n "$v" ] && printf 'pnpm\t%s\t%s\n' "$n" "$v"
    done
fi

# --- uv: METADATA files with Name/Version ---
if [ -d /cache/uv ]; then
    find /cache/uv -name "METADATA" 2>/dev/null | head -$MAX | while read -r meta; do
        n=$(grep -m1 '^Name:' "$meta" 2>/dev/null | sed 's/^Name: *//')
        v=$(grep -m1 '^Version:' "$meta" 2>/dev/null | sed 's/^Version: *//')
        [ -n "$n" ] && [ -n "$v" ] && printf 'uv\t%s\t%s\n' "$n" "$v"
    done
fi

# --- pip: extract project/version from msgpack HTTP cache via strings ---
if [ -d /cache/pip/http-v2 ]; then
    find /cache/pip/http-v2 -type f ! -name "*.body" 2>/dev/null | head -$MAX | while read -r f; do
        s=$(strings "$f" 2>/dev/null)
        p=$(echo "$s" | grep -A1 '^x-pypi-file-project$' | tail -1)
        v=$(echo "$s" | grep -A1 '^x-pypi-file-version$' | tail -1)
        [ -n "$p" ] && [ -n "$v" ] && [ "$p" != "x-pypi-file-project" ] && printf 'pip\t%s\t%s\n' "$p" "$v"
    done | sort -u
fi
"""

    try:
        proc = subprocess.run(
            [
                "docker", "run", "--rm",
                "-v", f"{volume}:/cache:ro",
                "alpine", "sh", "-c", script,
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
    except subprocess.TimeoutExpired:
        log.warning("Cache inspection timed out")
        return {"managers": {}, "total_count": 0, "scanned_at": None, "error": "timeout"}
    except FileNotFoundError:
        log.warning("docker command not found")
        return {"managers": {}, "total_count": 0, "scanned_at": None, "error": "docker not found"}

    if proc.returncode != 0:
        log.warning("Cache inspection failed (exit %d): %s", proc.returncode, proc.stderr[:500])
        return {"managers": {}, "total_count": 0, "scanned_at": None, "error": proc.stderr[:200]}

    # Parse TSV output
    managers: dict[str, list[dict[str, str]]] = {}
    for line in proc.stdout.strip().splitlines():
        parts = line.split("\t", 2)
        if len(parts) != 3:
            continue
        mgr, name, version = parts
        name = name.strip()
        version = version.strip()
        if not name or not version:
            continue
        if mgr not in managers:
            managers[mgr] = []
        if len(managers[mgr]) < MAX_PACKAGES_PER_MANAGER:
            managers[mgr].append({"name": name, "version": version})

    total = sum(len(pkgs) for pkgs in managers.values())
    scanned_at = datetime.now(timezone.utc).isoformat()

    return {
        "managers": managers,
        "total_count": total,
        "scanned_at": scanned_at,
    }
