#!/usr/bin/env bash
#
# dev-vm-entrypoint.sh — boot a Druppie developer workspace VM.
#
# Brings up all services a single dev-VM needs, WITHOUT systemd and WITHOUT
# --privileged. Designed to run as PID 1 inside a sysbox-runc container:
#
#     docker run -d --runtime sysbox-runc --network <sandbox-net> \
#         --memory 12g --cpus 4 --shm-size 2g --tmpfs /tmp:size=4g \
#         --storage-opt size=20G dev-vm-base:latest
#
# Services started (all bound to 0.0.0.0 so Guacamole/docker-network can reach them):
#   * dockerd         nested Docker (sysbox virtualizes the capabilities)
#   * local Gitea     gitea/gitea:1.21, DinD on :3000 (web) + :2222 (git SSH)
#   * sshd            :22  (password: developer/developer, keyless dev box)
#   * xrdp            :3389 (Guacamole RDP -> xfce4 session)
#   * code-server     :8080 (browser-based VS Code, no auth — behind Guacamole)
#
set -Eeuo pipefail

log() { printf '[dev-vm-entrypoint] %s\n' "$*"; }

# ---------------------------------------------------------------------------
# 0. Prepare filesystem + Docker daemon config
# ---------------------------------------------------------------------------
mkdir -p \
    /workspace /cache /run/sshd /run/xrdp /var/log /etc/docker
mkdir -p \
    /cache/tmp /cache/pip /cache/npm /cache/uv /cache/pnpm /cache/yarn /cache/bun
chmod 1777 /cache/tmp

# Ensure the developer user owns the shared roots (non-recursive; fresh VM).
chown developer:developer /workspace /cache 2>/dev/null || true

# Default dockerd config: Harbor insecure registry. Idempotent — recreated only
# if missing/empty so a runtime-mounted config is respected.
if [ ! -s /etc/docker/daemon.json ]; then
    cat > /etc/docker/daemon.json <<'JSON'
{
  "insecure-registries": ["harbor.local:8181", "localhost:8181", "harbor.local:5000", "localhost:5000"]
}
JSON
fi

# ---------------------------------------------------------------------------
# 1. Start Docker daemon (sysbox provides nested Docker; no --privileged)
# ---------------------------------------------------------------------------
log "Starting dockerd..."
dockerd > /var/log/dockerd.log 2>&1 &
DOCKERD_PID=$!
for i in $(seq 1 60); do
    if docker info >/dev/null 2>&1; then
        log "dockerd ready (pid ${DOCKERD_PID})."
        break
    fi
    if [ "$i" -eq 60 ]; then
        log "WARNING: dockerd did not become ready in 60s. Nested Docker unavailable. See /var/log/dockerd.log"
    fi
    sleep 1
done

# ---------------------------------------------------------------------------
# 2. Start local Gitea (non-fatal — a missing Gitea must NOT take down RDP/SSH)
# ---------------------------------------------------------------------------
(
    set -e
    if docker ps --format '{{.Names}}' | grep -q '^local-gitea$'; then
        log "Local Gitea already running."
        exit 0
    fi

    log "Starting local Gitea (gitea/gitea:1.21)..."
    # Clear any half-stopped container from a previous boot.
    docker rm -f local-gitea >/dev/null 2>&1 || true

    # Hex avoids the pipefail/SIGPIPE footgun of "openssl rand | tr | head".
    GITEA_PASS="$(openssl rand -hex 10)"

    docker run -d --name local-gitea \
        --restart unless-stopped \
        -p 3000:3000 -p 2222:22 \
        -e GITEA__security__INSTALL_LOCK=true \
        -e GITEA__server__START_SSH_SERVER=true \
        -e GITEA__server__SSH_PORT=2222 \
        -e GITEA__server__SSH_LISTEN_PORT=22 \
        -v local-gitea-data:/data \
        gitea/gitea:1.21

    printf 'Local Gitea\n  URL:      http://localhost:3000\n  SSH:      ssh://git@localhost:2222\n  Admin:    gitea_admin\n  Password: %s\n' \
        "$GITEA_PASS" > /workspace/.gitea-credentials
    chmod 600 /workspace/.gitea-credentials
    chown developer:developer /workspace/.gitea-credentials 2>/dev/null || true

    log "Waiting for Gitea to become healthy..."
    for i in $(seq 1 60); do
        if curl -sf http://localhost:3000/api/v1/version >/dev/null 2>&1; then
            log "Gitea healthy."
            break
        fi
        if [ "$i" -eq 60 ]; then
            log "WARNING: Gitea did not become healthy in 120s. See: docker logs local-gitea"
        fi
        sleep 2
    done

    # Bootstrap the admin account via the in-container CLI (best-effort).
    docker exec local-gitea gitea admin user create \
        --admin --username gitea_admin --password "$GITEA_PASS" \
        --email admin@local.gitea --must-change-password=false \
        >/dev/null 2>&1 \
        || log "NOTE: gitea admin bootstrap skipped (already exists or DB still migrating)."

    log "Local Gitea ready. Credentials in /workspace/.gitea-credentials."
) || log "WARNING: local Gitea bootstrap failed; continuing without it."

# ---------------------------------------------------------------------------
# 3. Start SSH daemon
# ---------------------------------------------------------------------------
log "Starting sshd..."
mkdir -p /run/sshd
/usr/sbin/sshd || log "WARNING: sshd failed to start."

# ---------------------------------------------------------------------------
# 4. Start xrdp (Guacamole connects here on :3389 -> xfce4)
# ---------------------------------------------------------------------------
log "Starting xrdp..."
xrdp-sesman || log "WARNING: xrdp-sesman failed to start."
xrdp || log "WARNING: xrdp failed to start."

# ---------------------------------------------------------------------------
# 5. Start code-server as the non-root developer user
# ---------------------------------------------------------------------------
log "Starting code-server..."
sudo -u developer -H code-server \
    --bind-addr 0.0.0.0:8080 --auth none /workspace \
    > /var/log/code-server.log 2>&1 &

# ---------------------------------------------------------------------------
# 6. Keep the container alive
# ---------------------------------------------------------------------------
log "Dev VM ready."
log "  sshd(:22)  gitea(:3000)  xrdp(:3389)  code-server(:8080)  gitea-ssh(:2222)"
log "  Developer login: developer / developer (sudo NOPASSWD)"

exec sleep infinity
