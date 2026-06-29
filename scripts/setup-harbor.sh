#!/usr/bin/env bash
set -euo pipefail

# Druppie Platform - Harbor Registry Setup (local dev)
#
# Installs Harbor v2.14.4 as a SIBLING docker-compose project in /opt/harbor
# (configurable via HARBOR_DIR). HTTP-only, no TLS — for local dev only.
#
# Harbor runs as its own compose project because it bundles nginx/redis/postgres
# with hardcoded container names that would collide with the druppie stack.
#
# Usage:
#   ./scripts/setup-harbor.sh            # Install (idempotent)
#   ./scripts/setup-harbor.sh start      # Start Harbor
#   ./scripts/setup-harbor.sh stop       # Stop Harbor
#   ./scripts/setup-harbor.sh restart    # Restart Harbor
#   ./scripts/setup-harbor.sh logs       # Tail Harbor logs
#   ./scripts/setup-harbor.sh down       # Remove Harbor containers + volumes (prompt)
#   ./scripts/setup-harbor.sh status     # Show Harbor container status

# ---------------------------------------------------------------------------
# Config (overridable via environment)
# ---------------------------------------------------------------------------
HARBOR_VERSION="${HARBOR_VERSION:-v2.14.4}"
HARBOR_DIR="${HARBOR_DIR:-/opt/harbor}"
HARBOR_HOST="${HARBOR_HOST:-harbor.local}"
HARBOR_PORT="${HARBOR_PORT:-8181}"
HARBOR_ADMIN_PASSWORD="${HARBOR_ADMIN_PASSWORD:-Harbor12345}"
HARBOR_DATA_DIR="${HARBOR_DATA_DIR:-${HARBOR_DIR}/data}"
HARBOR_DB_PASSWORD="${HARBOR_DB_PASSWORD:-root123}"
HARBOR_PROJECT="${HARBOR_PROJECT:-ci}"
INSTALLER_TGZ="/tmp/harbor-installer.tgz"

# ---------------------------------------------------------------------------
# Logging (matches setup-kind.sh conventions)
# ---------------------------------------------------------------------------
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log()   { echo -e "${GREEN}[harbor]${NC} $*"; }
info()  { echo -e "${BLUE}[harbor]${NC} $*"; }
warn()  { echo -e "${YELLOW}[warn]${NC} $*"; }
error() { echo -e "${RED}[error]${NC} $*" >&2; exit 1; }

# Run docker compose inside HARBOR_DIR with this project's name.
harbor_compose() {
    (cd "$HARBOR_DIR" && docker compose "$@")
}

# ---------------------------------------------------------------------------
# Prerequisites
# ---------------------------------------------------------------------------
check_prerequisites() {
    log "Checking prerequisites..."

    # Root or sudo — needed for /etc/hosts, /etc/docker/daemon.json, systemctl
    if [ "$(id -u)" -ne 0 ]; then
        error "Must run as root (or with sudo). This script edits /etc/hosts, /etc/docker/daemon.json, and restarts docker."
    fi

    # Docker daemon running
    if ! docker info >/dev/null 2>&1; then
        error "Docker daemon is not running. Start it first: sudo systemctl start docker"
    fi

    # docker compose (plugin)
    if ! docker compose version >/dev/null 2>&1; then
        error "docker compose plugin not found. Install the Docker Compose plugin."
    fi

    # curl
    command -v curl >/dev/null 2>&1 || error "curl not found."

    log "All prerequisites met."
}

# ---------------------------------------------------------------------------
# Install steps
# ---------------------------------------------------------------------------

# Download the online installer (~12KB; pulls images at install time).
download_installer() {
    local url="https://github.com/goharbor/harbor/releases/download/${HARBOR_VERSION}/harbor-online-installer-${HARBOR_VERSION}.tgz"

    if [ -f "$INSTALLER_TGZ" ]; then
        log "Installer archive already present at $INSTALLER_TGZ — reusing."
        return
    fi

    log "Downloading Harbor online installer ${HARBOR_VERSION}..."
    log "  $url"
    curl -fL --retry 3 -o "$INSTALLER_TGZ" "$url" || error "Failed to download Harbor installer."
    log "Download complete."
}

# Extract installer to HARBOR_DIR (idempotent — skips if already extracted).
extract_installer() {
    # Already extracted if harbor.yml.tmpl (shipped in tarball) is present.
    if [ -f "${HARBOR_DIR}/harbor.yml.tmpl" ] && [ -f "${HARBOR_DIR}/install.sh" ]; then
        log "Harbor already extracted in $HARBOR_DIR — skipping extraction."
        return
    fi

    log "Extracting Harbor to $HARBOR_DIR..."
    mkdir -p "$HARBOR_DIR"
    # Extract to a temp dir first, then move contents so re-runs stay clean.
    local tmp_extract
    tmp_extract="$(mktemp -d)"
    tar -xzf "$INSTALLER_TGZ" -C "$tmp_extract"
    # Tarball contains a top-level "harbor/" directory.
    if [ -d "${tmp_extract}/harbor" ]; then
        cp -a "${tmp_extract}/harbor/." "$HARBOR_DIR/"
    else
        cp -a "${tmp_extract}/." "$HARBOR_DIR/"
    fi
    rm -rf "$tmp_extract"
    log "Extraction complete."
}

# Generate harbor.yml (HTTP-only, no TLS). Overwritten each run so config
# stays in sync with env vars.
generate_harbor_yml() {
    log "Generating harbor.yml (HTTP-only, no TLS)..."

    # hostname must NOT be localhost/127.0.0.1 — Harbor rejects it.
    case "$HARBOR_HOST" in
        localhost|127.0.0.1)
            error "HARBOR_HOST must not be 'localhost' or '127.0.0.1' (Harbor rejects it). Use a real hostname like harbor.local."
            ;;
    esac

    mkdir -p "$HARBOR_DATA_DIR"

    cat > "${HARBOR_DIR}/harbor.yml" <<EOF
# Generated by scripts/setup-harbor.sh — do not edit manually.
# HTTP-only local dev config (no TLS). Regenerated on each run.
hostname: ${HARBOR_HOST}

# HTTP only — https block intentionally omitted for local dev.
http:
  port: ${HARBOR_PORT}

harbor_admin_password: ${HARBOR_ADMIN_PASSWORD}

database:
  password: ${HARBOR_DB_PASSWORD}

# The default data volume (config/registry/etc. go under common/config).
data_volume: ${HARBOR_DATA_DIR}

# Minimal install: no Trivy, no Chartmuseum, no Notary.
trivy:
  ignore_unfixed: false
  skip_update: false
  offline_scan: false
  security_check: vuln

# Disable all optional add-ons to keep the install minimal.
notary:
  enabled: false
EOF

    log "harbor.yml written to ${HARBOR_DIR}/harbor.yml."
}

# Idempotently add harbor.local to /etc/hosts.
update_hosts() {
    if grep -q "[[:space:]]${HARBOR_HOST}\b" /etc/hosts; then
        log "/etc/hosts already has ${HARBOR_HOST} — skipping."
        return
    fi

    log "Adding ${HARBOR_HOST} to /etc/hosts..."
    echo "127.0.0.1 ${HARBOR_HOST}" >> /etc/hosts
    log "Added."
}

# Run Harbor's installer (calls prepare → generates docker-compose.yml + config).
run_installer() {
    log "Running Harbor install.sh..."
    log "  (This pulls all Harbor images and starts the stack — may take a few minutes.)"
    (cd "$HARBOR_DIR" && ./install.sh)
    log "Harbor installer finished."
}

# Merge "harbor.local:8181" into /etc/docker/daemon.json insecure-registries
# WITHOUT clobbering existing keys. Uses python3 (universally available).
configure_insecure_registry() {
    local registry="${HARBOR_HOST}:${HARBOR_PORT}"
    local daemon_json="/etc/docker/daemon.json"

    mkdir -p /etc/docker

    # Start from existing file or empty object.
    local base="{}"
    if [ -f "$daemon_json" ]; then
        base="$(cat "$daemon_json")"
    fi

    # Merge with python3 so we never lose existing config keys.
    local merged
    merged="$(python3 - "$daemon_json" "$registry" "$base" <<'PY'
import json, sys
path, registry, raw = sys.argv[1], sys.argv[2], sys.argv[3]
try:
    cfg = json.loads(raw) if raw.strip() else {}
except json.JSONDecodeError:
    print(f"ERROR: {path} contains invalid JSON. Aborting to avoid clobbering.", file=sys.stderr)
    sys.exit(1)
registries = cfg.setdefault("insecure-registries", [])
if not isinstance(registries, list):
    print("ERROR: existing insecure-registries is not a list. Refusing to overwrite.", file=sys.stderr)
    sys.exit(1)
if registry not in registries:
    registries.append(registry)
# stable key ordering for readability
cfg["insecure-registries"] = registries
print(json.dumps(cfg, indent=2))
PY
)" || error "Failed to merge insecure-registries into $daemon_json."

    if [ -f "$daemon_json" ]; then
        cp -a "$daemon_json" "${daemon_json}.bak.$(date +%s)"
        log "Backed up existing daemon.json."
    fi

    printf '%s\n' "$merged" > "$daemon_json"
    log "Configured insecure-registry '${registry}' in $daemon_json."

    # Restart Docker so the new insecure-registry takes effect.
    warn "Restarting the Docker daemon — this will restart ALL running containers."
    warn "Press Ctrl+C within 10s to abort."
    sleep 10

    if systemctl restart docker 2>/dev/null; then
        log "Docker daemon restarted."
    else
        warn "Could not restart docker via systemctl. Please restart docker manually:"
        warn "  sudo systemctl restart docker"
    fi
}

# Wait for Harbor health endpoint.
wait_for_health() {
    local url="http://${HARBOR_HOST}:${HARBOR_PORT}/api/v2.0/health"
    log "Waiting for Harbor to become healthy at ${url}..."
    for i in $(seq 1 30); do
        if curl -sf "$url" >/dev/null 2>&1; then
            log "Harbor is healthy (after ${i} attempt(s))."
            return 0
        fi
        printf '  .'
        sleep 5
    done
    echo
    error "Harbor did not become healthy within ~2.5 minutes. Check: cd ${HARBOR_DIR} && docker compose logs"
}

# Create the default CI project (idempotent — 409 if it exists).
create_default_project() {
    local name="${HARBOR_PROJECT}"
    log "Creating default project '${name}' (if it does not exist)..."

    local resp
    resp="$(curl -s -o /dev/null -w '%{http_code}' \
        -u "admin:${HARBOR_ADMIN_PASSWORD}" \
        -X GET \
        "http://${HARBOR_HOST}:${HARBOR_PORT}/api/v2.0/projects?project_name=${name}")" || true

    if [ "$resp" = "200" ]; then
        log "Project '${name}' already exists — skipping."
        return
    fi

    curl -sf -u "admin:${HARBOR_ADMIN_PASSWORD}" \
        -X POST \
        "http://${HARBOR_HOST}:${HARBOR_PORT}/api/v2.0/projects" \
        -H "Content-Type: application/json" \
        -d "{\"project_name\":\"${name}\",\"public\":false}" \
        && log "Project '${name}' created." \
        || warn "Could not create project '${name}' (it may already exist, or the API was not ready)."
}

# ---------------------------------------------------------------------------
# Full install
# ---------------------------------------------------------------------------
do_install() {
    check_prerequisites
    download_installer
    extract_installer
    generate_harbor_yml
    update_hosts
    run_installer
    configure_insecure_registry
    wait_for_health
    create_default_project
    print_summary
}

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
print_summary() {
    echo ""
    echo -e "${GREEN}==============================================${NC}"
    echo -e "${GREEN}  Harbor Registry is ready!${NC}"
    echo -e "${GREEN}==============================================${NC}"
    echo ""
    echo "  Harbor is running at http://${HARBOR_HOST}:${HARBOR_PORT}"
    echo "    Admin:     admin / ${HARBOR_ADMIN_PASSWORD}"
    echo "    Project:   ${HARBOR_PROJECT} $(curl -sf -u "admin:${HARBOR_ADMIN_PASSWORD}" "http://${HARBOR_HOST}:${HARBOR_PORT}/api/v2.0/projects?project_name=${HARBOR_PROJECT}" >/dev/null 2>&1 && echo "(created)" || echo "(see logs)")"
    echo "    Data dir:  ${HARBOR_DATA_DIR}"
    echo "    Install:   ${HARBOR_DIR}"
    echo ""
    echo -e "${BLUE}To push images:${NC}"
    echo "  docker login ${HARBOR_HOST}:${HARBOR_PORT}"
    echo "  docker tag myapp:latest ${HARBOR_HOST}:${HARBOR_PORT}/${HARBOR_PROJECT}/myapp:latest"
    echo "  docker push ${HARBOR_HOST}:${HARBOR_PORT}/${HARBOR_PROJECT}/myapp:latest"
    echo ""
    echo -e "${BLUE}To create a robot account for CI:${NC}"
    echo "  Visit http://${HARBOR_HOST}:${HARBOR_PORT} → project ${HARBOR_PROJECT} → Robot Accounts → New Robot Account"
    echo ""
    echo -e "${BLUE}Lifecycle (run this script with a subcommand):${NC}"
    echo "  ./scripts/setup-harbor.sh status   # show container status"
    echo "  ./scripts/setup-harbor.sh stop     # stop Harbor"
    echo "  ./scripts/setup-harbor.sh start    # start Harbor"
    echo "  ./scripts/setup-harbor.sh restart  # restart Harbor"
    echo "  ./scripts/setup-harbor.sh logs     # tail logs"
    echo "  ./scripts/setup-harbor.sh down     # remove containers + volumes"
    echo ""
}

# ---------------------------------------------------------------------------
# Lifecycle subcommands
# ---------------------------------------------------------------------------
do_status() {
    check_docker_running
    log "Harbor container status:"
    harbor_compose ps || warn "Could not get status (Harbor may not be installed)."
}

do_stop() {
    check_docker_running
    log "Stopping Harbor..."
    harbor_compose stop
    log "Harbor stopped."
}

do_start() {
    check_docker_running
    log "Starting Harbor..."
    harbor_compose start
    log "Harbor started."
    wait_for_health
}

do_restart() {
    check_docker_running
    log "Restarting Harbor..."
    harbor_compose restart
    log "Harbor restarted."
    wait_for_health
}

do_logs() {
    check_docker_running
    log "Tailing Harbor logs (Ctrl+C to exit)..."
    harbor_compose logs -f
}

do_down() {
    check_docker_running
    warn "This will remove ALL Harbor containers and volumes."
    warn "All images in the registry will be LOST."
    echo ""
    read -r -p "Type 'yes' to permanently destroy Harbor data: " confirm
    if [ "$confirm" != "yes" ]; then
        log "Aborted — nothing was changed."
        exit 0
    fi
    log "Removing Harbor containers and volumes..."
    harbor_compose down -v
    log "Harbor removed. (Config and data dirs in ${HARBOR_DIR} are preserved.)"
    info "To fully reinstall: sudo ./scripts/setup-harbor.sh"
}

check_docker_running() {
    if ! docker info >/dev/null 2>&1; then
        error "Docker daemon is not running."
    fi
    if [ ! -f "${HARBOR_DIR}/docker-compose.yml" ]; then
        error "Harbor is not installed in ${HARBOR_DIR}. Run: sudo ./scripts/setup-harbor.sh"
    fi
}

# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------
usage() {
    echo "Usage: sudo $0 {install|start|stop|restart|logs|status|down}"
    echo ""
    echo "Commands:"
    echo "  install   Install/configure Harbor (default — idempotent, safe to re-run)"
    echo "  start     Start Harbor containers"
    echo "  stop      Stop Harbor containers"
    echo "  restart   Restart Harbor containers"
    echo "  logs      Tail Harbor logs"
    echo "  status    Show Harbor container status"
    echo "  down      Remove Harbor containers + volumes (with confirmation)"
    echo ""
    echo "Environment overrides:"
    echo "  HARBOR_VERSION=${HARBOR_VERSION}"
    echo "  HARBOR_DIR=${HARBOR_DIR}"
    echo "  HARBOR_HOST=${HARBOR_HOST}"
    echo "  HARBOR_PORT=${HARBOR_PORT}"
    echo "  HARBOR_ADMIN_PASSWORD=${HARBOR_ADMIN_PASSWORD}"
    echo "  HARBOR_DATA_DIR=${HARBOR_DATA_DIR}"
    exit 1
}

case "${1:-install}" in
    install|"")
        do_install
        ;;
    start)
        do_start
        ;;
    stop)
        do_stop
        ;;
    restart)
        do_restart
        ;;
    logs)
        do_logs
        ;;
    status)
        do_status
        ;;
    down)
        do_down
        ;;
    -h|--help|help)
        usage
        ;;
    *)
        error "Unknown command: '${1}'. Run: $0 --help"
        ;;
esac
