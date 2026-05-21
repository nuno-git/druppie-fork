#!/usr/bin/env bash
# Install Sysbox CE on Ubuntu 22.04 / Debian and register it as a Docker
# runtime. Idempotent — safe to re-run.
#
# Usage:
#   sudo ./scripts/install-sysbox.sh
#
# After this succeeds, `docker info` will list "sysbox-runc" as an available
# runtime, and `ONESHOT_SANDBOX_RUNTIME=sysbox-runc oneshot ...` will use it.

set -euo pipefail

SYSBOX_VERSION="${SYSBOX_VERSION:-0.7.0}"
ARCH="$(dpkg --print-architecture)"
DEB_URL="https://downloads.nestybox.com/sysbox/releases/v${SYSBOX_VERSION}/sysbox-ce_${SYSBOX_VERSION}-0.linux_${ARCH}.deb"
DEB_TMP="/tmp/sysbox-ce_${SYSBOX_VERSION}-0.linux_${ARCH}.deb"

log() { printf '\n\033[1;34m==>\033[0m %s\n' "$*"; }
die() { printf '\n\033[1;31merror:\033[0m %s\n' "$*" >&2; exit 1; }

# ── Preflight ──────────────────────────────────────────────────────────────

[[ $EUID -eq 0 ]] || die "must be run as root (sudo $0)"

if ! command -v docker >/dev/null; then
  die "docker is not installed; install Docker Engine before Sysbox"
fi

# Already installed? Just report and exit.
if command -v sysbox-runc >/dev/null && docker info --format '{{json .Runtimes}}' | grep -q '"sysbox-runc"'; then
  log "sysbox-runc is already registered with Docker — nothing to do."
  docker info --format '{{json .Runtimes}}' | jq 'keys' || true
  exit 0
fi

# ── Prerequisites ──────────────────────────────────────────────────────────

log "installing prerequisites (jq, rsync, wget)"
apt-get update -qq
apt-get install -y -qq jq rsync wget

# ── Download package ───────────────────────────────────────────────────────

log "downloading sysbox-ce v${SYSBOX_VERSION} for ${ARCH}"
rm -f "$DEB_TMP"
wget --no-verbose -O "$DEB_TMP" "$DEB_URL"

# ── Install ────────────────────────────────────────────────────────────────

log "installing ${DEB_TMP}"
# `apt install ./file.deb` resolves deps cleanly; dpkg -i leaves half-states
# if dependencies are missing.
apt-get install -y "$DEB_TMP"

# ── Verify registration ────────────────────────────────────────────────────

log "verifying sysbox-runc is registered with Docker"
# The postinst script restarts dockerd. Give it a moment to come back.
for i in $(seq 1 20); do
  if docker info --format '{{json .Runtimes}}' 2>/dev/null | grep -q '"sysbox-runc"'; then
    break
  fi
  sleep 0.5
  if [[ $i -eq 20 ]]; then
    die "sysbox-runc did not appear in docker runtimes after restart. Check: systemctl status sysbox && journalctl -u sysbox"
  fi
done

docker info --format '{{json .Runtimes}}' | jq 'keys'

# ── Quick functional test ──────────────────────────────────────────────────

log "quick test: hello-world under sysbox-runc"
docker run --rm --runtime=sysbox-runc hello-world | head -5 || die "sysbox-runc smoke test failed"

log "sysbox installed and working."
printf '\nNext: run the oneshot smoke test with:\n  ONESHOT_SANDBOX_RUNTIME=sysbox-runc node scripts/smoketest.mjs\n\n'
