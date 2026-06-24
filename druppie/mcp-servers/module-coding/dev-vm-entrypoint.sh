#!/usr/bin/env bash
#
# dev-vm-entrypoint.sh — boot a Druppie developer workspace VM.
#
# Brings up all services a single dev-VM needs, WITHOUT systemd and WITHOUT
# --privileged. Designed to run as PID 1 inside a sysbox-runc container.
#
# Critical services (xrdp, sshd) start FIRST so the VM is reachable within
# seconds. Non-critical services (local Gitea) start in the background.
#
set -Eeuo pipefail

log() { printf '[dev-vm-entrypoint] %s\n' "$*"; }

# ---------------------------------------------------------------------------
# 0. Prepare filesystem
# ---------------------------------------------------------------------------
mkdir -p \
    /workspace /cache /run/sshd /run/xrdp /run/user/1000 /var/log /etc/docker
mkdir -p \
    /cache/tmp /cache/pip /cache/npm /cache/uv /cache/pnpm /cache/yarn /cache/bun
chmod 1777 /cache/tmp
chown developer:developer /workspace /cache /run/user/1000 2>/dev/null || true

# Apply per-VM password if provided
if [ -n "${DEV_VM_RDP_USERNAME:-}" ] && [ -n "${DEV_VM_RDP_PASSWORD:-}" ]; then
    echo "${DEV_VM_RDP_USERNAME}:${DEV_VM_RDP_PASSWORD}" | chpasswd
fi

# ---------------------------------------------------------------------------
# 1. Start dbus + SSH + xrdp (CRITICAL — must be fast)
# ---------------------------------------------------------------------------
log "Starting dbus..."
dbus-daemon --system --fork 2>/dev/null || log "WARNING: dbus failed to start."

log "Starting sshd..."
/usr/sbin/sshd 2>/dev/null || log "WARNING: sshd failed to start."

log "Starting xrdp..."
xrdp-sesman 2>/dev/null || log "WARNING: xrdp-sesman failed to start."
xrdp 2>/dev/null || log "WARNING: xrdp failed to start."

# ---------------------------------------------------------------------------
# 2. Start code-server (non-blocking)
# ---------------------------------------------------------------------------
log "Starting code-server..."
sudo -u developer -H code-server \
    --bind-addr 0.0.0.0:8080 --auth none /workspace \
    > /var/log/code-server.log 2>&1 &

log "Dev VM ready (critical services up)."
log "  sshd(:22)  xrdp(:3389)  code-server(:8080)"
if [ -n "${DEV_VM_RDP_PASSWORD:-}" ]; then
    log "  Developer login: developer / (per-VM password)"
else
    log "  Developer login: developer / developer"
fi

# ---------------------------------------------------------------------------
# 3. Start Docker daemon + local Gitea (BACKGROUND — non-critical)
# ---------------------------------------------------------------------------
(
    log "Starting dockerd (background)..."
    if [ ! -s /etc/docker/daemon.json ]; then
        printf '{\n  "insecure-registries": ["harbor.local:8181", "localhost:8181", "harbor.local:5000", "localhost:5000"]\n}\n' \
            > /etc/docker/daemon.json
    fi

    dockerd > /var/log/dockerd.log 2>&1 &
    for i in $(seq 1 30); do
        if docker info >/dev/null 2>&1; then
            log "dockerd ready."
            break
        fi
        [ "$i" -eq 30 ] && log "WARNING: dockerd not ready in 30s."
        sleep 1
    done

    log "Starting local Gitea (background)..."
    docker rm -f local-gitea >/dev/null 2>&1 || true
    GITEA_PASS="$(openssl rand -hex 10)"

    docker run -d --name local-gitea \
        --restart unless-stopped \
        -p 3000:3000 -p 2222:22 \
        -e GITEA__security__INSTALL_LOCK=true \
        -e GITEA__server__START_SSH_SERVER=true \
        -e GITEA__server__SSH_PORT=2222 \
        -e GITEA__server__SSH_LISTEN_PORT=22 \
        -v local-gitea-data:/data \
        gitea/gitea:1.21 2>/dev/null || {
        log "WARNING: local Gitea failed to start (nested Docker unavailable)."
        exit 0
    }

    printf 'Local Gitea\n  URL:      http://localhost:3000\n  SSH:      ssh://git@localhost:2222\n  Admin:    gitea_admin\n  Password: %s\n' \
        "$GITEA_PASS" > /workspace/.gitea-credentials
    chmod 600 /workspace/.gitea-credentials
    chown developer:developer /workspace/.gitea-credentials 2>/dev/null || true

    for i in $(seq 1 30); do
        if curl -sf http://localhost:3000/api/v1/version >/dev/null 2>&1; then
            log "Gitea healthy."
            docker exec local-gitea gitea admin user create \
                --admin --username gitea_admin --password "$GITEA_PASS" \
                --email admin@local.gitea --must-change-password=false \
                >/dev/null 2>&1 \
                || log "NOTE: gitea admin bootstrap skipped."
            log "Local Gitea ready (:3000, :2222)."
            exit 0
        fi
        sleep 2
    done
    log "WARNING: Gitea did not become healthy in 60s."
) || log "WARNING: local Gitea bootstrap failed; continuing without it."

# ---------------------------------------------------------------------------
# 4. Reap zombie children (PID 1 responsibility) and keep container alive
# ---------------------------------------------------------------------------
while true; do
    wait -n 2>/dev/null || sleep 300 &
    wait $! 2>/dev/null
done
