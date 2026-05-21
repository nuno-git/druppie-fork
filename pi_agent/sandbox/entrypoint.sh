#!/bin/bash
# Start dockerd inside the Kata microVM, then hand off to the exec daemon.
#
# Under Kata the VM has its own kernel, so starting a full dockerd here is just
# "Docker in a VM" — no host-kernel interaction. Agents can `docker compose up`
# as normal once the daemon is ready.
set -euo pipefail

# ── Start dockerd in the background ────────────────────────────────────────
# Use vfs storage-driver when overlay2 isn't usable (e.g. missing kernel mod in
# the Kata guest); overlay2 is preferred and works on stock Kata kernels.
DOCKERD_LOG=/var/log/dockerd.log
mkdir -p /var/lib/docker /var/run
dockerd \
    --host=unix:///var/run/docker.sock \
    --storage-driver=overlay2 \
    --iptables=true \
    >> "$DOCKERD_LOG" 2>&1 &
DOCKERD_PID=$!

# Wait (up to 30s) for the socket to become usable
for i in $(seq 1 60); do
    if docker info >/dev/null 2>&1; then
        echo "[entrypoint] dockerd ready (pid=$DOCKERD_PID)"
        break
    fi
    sleep 0.5
    if [ "$i" -eq 60 ]; then
        echo "[entrypoint] dockerd failed to start; tail of log:" >&2
        tail -n 100 "$DOCKERD_LOG" >&2 || true
        exit 1
    fi
done

# ── Hand off to the exec daemon ────────────────────────────────────────────
# Run as PID 1-equivalent: exec so signals (SIGTERM from docker stop) reach it.
exec python3 /app/daemon.py
