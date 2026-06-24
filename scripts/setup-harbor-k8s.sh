#!/usr/bin/env bash
set -euo pipefail

# Druppie Platform - Harbor Registry Setup on local k3s (Helm)
#
# Installs Harbor into the local k3s cluster via the official Helm chart.
# HTTP-only (nodePort), no TLS, minimal add-ons — for local dev only.
#
# This is the k3s/Helm approach. It supersedes scripts/setup-harbor.sh, which
# installs Harbor as a sibling docker-compose project. Both work; pick one.
# The k3s install is preferred when k3s is already running because Harbor then
# lives with the rest of the deployment target (same cluster CI rolls out to).
#
# Usage:
#   sudo ./scripts/setup-harbor-k8s.sh             # Install (idempotent, safe to re-run)
#   sudo ./scripts/setup-harbor-k8s.sh status      # Show Harbor pods
#   sudo ./scripts/setup-harbor-k8s.sh logs        # Tail Harbor logs (last 50 lines)
#   sudo ./scripts/setup-harbor-k8s.sh uninstall   # Remove Harbor release + namespace (prompt)
#   sudo ./scripts/setup-harbor-k8s.sh help        # Show this help

# ---------------------------------------------------------------------------
# Config (overridable via environment)
# ---------------------------------------------------------------------------
HARBOR_NAMESPACE="${HARBOR_NAMESPACE:-harbor}"
HARBOR_PORT="${HARBOR_PORT:-30010}"
HARBOR_ADMIN_PASSWORD="${HARBOR_ADMIN_PASSWORD:-Harbor12345}"
HARBOR_PROJECT="${HARBOR_PROJECT:-ci}"
KUBECONFIG="${KUBECONFIG:-$HOME/.kube/config}"
export KUBECONFIG
HARBOR_RELEASE_NAME="${HARBOR_RELEASE_NAME:-harbor}"

# ---------------------------------------------------------------------------
# Logging (matches setup-kind.sh / setup-harbor.sh conventions)
# ---------------------------------------------------------------------------
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log()   { echo -e "${GREEN}[harbor-k8s]${NC} $*"; }
info()  { echo -e "${BLUE}[harbor-k8s]${NC} $*"; }
warn()  { echo -e "${YELLOW}[warn]${NC} $*"; }
error() { echo -e "${RED}[error]${NC} $*" >&2; exit 1; }

# ---------------------------------------------------------------------------
# Prerequisites
# ---------------------------------------------------------------------------
check_prerequisites() {
    log "Checking prerequisites..."

    command -v helm >/dev/null 2>&1 || error "helm not found. Install: https://helm.sh/docs/intro/install/"
    command -v kubectl >/dev/null 2>&1 || error "kubectl not found. Install: https://kubernetes.io/docs/tasks/tools/"
    command -v curl >/dev/null 2>&1 || error "curl not found."

    # k3s running? Prefer systemctl; fall back to a running k3s process.
    if command -v systemctl >/dev/null 2>&1 && systemctl list-unit-files 2>/dev/null | grep -q '^k3s\.service'; then
        if ! systemctl is-active --quiet k3s; then
            error "k3s is not running. Start it: sudo systemctl start k3s"
        fi
    elif ! pgrep -x k3s >/dev/null 2>&1; then
        warn "k3s service/process not detected via systemctl or pgrep. Continuing — will fail next if the API is unreachable."
    fi

    # kubectl actually works and reaches a cluster (also validates KUBECONFIG).
    if ! kubectl get nodes >/dev/null 2>&1; then
        error "kubectl cannot reach the cluster (kubectl get nodes failed). Check k3s is running and KUBECONFIG=$KUBECONFIG is valid."
    fi

    log "All prerequisites met."
}

# ---------------------------------------------------------------------------
# Install steps
# ---------------------------------------------------------------------------

# Idempotent: helm repo add is safe to repeat.
add_helm_repo() {
    log "Adding Harbor Helm repo..."
    helm repo add harbor https://helm.goharbor.io >/dev/null 2>&1 || true
    helm repo update >/dev/null 2>&1
    log "Helm repo ready."
}

# helm upgrade --install makes this idempotent — safe to re-run with new values.
#
# All configuration is defined declaratively in helm/harbor/values.yaml.
# The CLI --set flags have been removed in favour of the values file (IaC rule).
install_harbor() {
    local values_file
    values_file="$(cd "$(dirname "$0")/.." && pwd)/helm/harbor/values.yaml"

    if [ ! -f "$values_file" ]; then
        error "Harbor values file not found: ${values_file}"
    fi

    log "Installing/upgrading Harbor (release: ${HARBOR_RELEASE_NAME}, namespace: ${HARBOR_NAMESPACE})..."
    log "  Values file: ${values_file}"
    log "  This pulls the Harbor images and starts ~8 pods — may take a few minutes."

    helm upgrade --install "$HARBOR_RELEASE_NAME" harbor/harbor \
        -n "$HARBOR_NAMESPACE" --create-namespace \
        -f "$values_file" \
        --wait --timeout 8m

    log "Helm release deployed."
}

# Poll the health endpoint through the nodePort until Harbor responds.
wait_for_health() {
    local url="http://localhost:${HARBOR_PORT}/api/v2.0/health"
    log "Waiting for Harbor to become healthy at ${url}..."
    for i in $(seq 1 36); do
        if curl -sf "$url" >/dev/null 2>&1; then
            log "Harbor is healthy (after ${i} attempt(s))."
            return 0
        fi
        printf '  .'
        sleep 5
    done
    echo
    error "Harbor did not become healthy within ~3 minutes. Check: kubectl get pods -n ${HARBOR_NAMESPACE}"
}

# Create the default CI project (idempotent — 409/conflict if it already exists).
create_default_project() {
    local name="${HARBOR_PROJECT}"
    log "Creating default project '${name}' (if it does not exist)..."

    # 200 means it exists already; anything else we try to create it.
    local resp
    resp="$(curl -s -o /dev/null -w '%{http_code}' \
        -u "admin:${HARBOR_ADMIN_PASSWORD}" \
        -X GET \
        "http://localhost:${HARBOR_PORT}/api/v2.0/projects?project_name=${name}")" || true

    if [ "$resp" = "200" ]; then
        log "Project '${name}' already exists — skipping."
        return
    fi

    curl -sf -u "admin:${HARBOR_ADMIN_PASSWORD}" \
        -X POST \
        "http://localhost:${HARBOR_PORT}/api/v2.0/projects" \
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
    add_helm_repo
    install_harbor
    wait_for_health
    create_default_project
    print_summary
}

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
print_summary() {
    local proj_state
    if curl -sf -u "admin:${HARBOR_ADMIN_PASSWORD}" \
        "http://localhost:${HARBOR_PORT}/api/v2.0/projects?project_name=${HARBOR_PROJECT}" >/dev/null 2>&1; then
        proj_state="(created)"
    else
        proj_state="(see logs)"
    fi

    echo ""
    echo -e "${GREEN}==============================================${NC}"
    echo -e "${GREEN}  Harbor Registry is ready! (k3s)${NC}"
    echo -e "${GREEN}==============================================${NC}"
    echo ""
    echo "  URL:       http://localhost:${HARBOR_PORT}"
    echo "  Namespace: ${HARBOR_NAMESPACE}  (release: ${HARBOR_RELEASE_NAME})"
    echo "  Admin:     admin / ${HARBOR_ADMIN_PASSWORD}"
    echo "  Project:   ${HARBOR_PROJECT} ${proj_state}"
    echo ""
    echo -e "${BLUE}To push images:${NC}"
    echo "  docker login localhost:${HARBOR_PORT}   # user: admin"
    echo "  docker tag myapp:latest localhost:${HARBOR_PORT}/${HARBOR_PROJECT}/myapp:latest"
    echo "  docker push localhost:${HARBOR_PORT}/${HARBOR_PROJECT}/myapp:latest"
    echo ""
    echo -e "${BLUE}To create a robot account for CI:${NC}"
    echo "  Visit http://localhost:${HARBOR_PORT} → ${HARBOR_PROJECT} → Robot Accounts → New Robot Account"
    echo ""
    echo -e "${BLUE}To configure the auto-deploy webhook:${NC}"
    echo "  Target:   http://localhost:${BACKEND_PORT:-8100}/api/registry/webhook"
    echo "  Event:    POST image push (Harbor → Backend → kubectl rollout restart)"
    echo "  Or via UI: ${HARBOR_PROJECT} → Webhooks → add the URL above"
    echo ""
    echo -e "${BLUE}Lifecycle (run this script with a subcommand):${NC}"
    echo "  $0 status     # show Harbor pods"
    echo "  $0 logs       # tail Harbor logs (last 50 lines)"
    echo "  $0 uninstall  # remove Harbor release + namespace (prompt)"
    echo ""
}

# ---------------------------------------------------------------------------
# Lifecycle subcommands
# ---------------------------------------------------------------------------
do_status() {
    log "Harbor pods (namespace: ${HARBOR_NAMESPACE}):"
    kubectl get pods -n "$HARBOR_NAMESPACE" 2>/dev/null \
        || warn "No pods found in ${HARBOR_NAMESPACE}. Run: sudo $0"
}

do_logs() {
    log "Harbor logs (last 50 lines):"
    kubectl logs -n "$HARBOR_NAMESPACE" -l app.kubernetes.io/instance="${HARBOR_RELEASE_NAME}" --tail=50 2>/dev/null \
        || warn "No pods found for release '${HARBOR_RELEASE_NAME}' in ${HARBOR_NAMESPACE}."
}

do_uninstall() {
    warn "This will uninstall the Harbor Helm release and DELETE the '${HARBOR_NAMESPACE}' namespace."
    warn "All images stored in the registry will be LOST."
    echo ""
    read -r -p "Type 'yes' to permanently destroy Harbor on k3s: " confirm
    if [ "$confirm" != "yes" ]; then
        log "Aborted — nothing was changed."
        exit 0
    fi

    log "Uninstalling Harbor release '${HARBOR_RELEASE_NAME}'..."
    helm uninstall "$HARBOR_RELEASE_NAME" -n "$HARBOR_NAMESPACE" 2>/dev/null || warn "Release not found (already removed?)."
    log "Deleting namespace '${HARBOR_NAMESPACE}'..."
    kubectl delete namespace "$HARBOR_NAMESPACE" 2>/dev/null || warn "Namespace not found (already removed?)."
    log "Harbor removed from k3s."
    info "To reinstall: sudo $0"
}

# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------
usage() {
    echo "Usage: sudo $0 {install|status|logs|uninstall|help}"
    echo ""
    echo "Commands:"
    echo "  install    Install/upgrade Harbor on k3s (default — idempotent, safe to re-run)"
    echo "  status     Show Harbor pods"
    echo "  logs       Tail Harbor logs (last 50 lines)"
    echo "  uninstall  Remove Harbor release + namespace (with confirmation)"
    echo "  help       Show this help"
    echo ""
    echo "Environment overrides:"
    echo "  HARBOR_NAMESPACE=${HARBOR_NAMESPACE}"
    echo "  HARBOR_PORT=${HARBOR_PORT}"
    echo "  HARBOR_ADMIN_PASSWORD=${HARBOR_ADMIN_PASSWORD}"
    echo "  HARBOR_PROJECT=${HARBOR_PROJECT}"
    echo "  HARBOR_RELEASE_NAME=${HARBOR_RELEASE_NAME}"
    echo "  KUBECONFIG=${KUBECONFIG}"
    exit 1
}

case "${1:-install}" in
    install|"")
        do_install
        ;;
    status)
        do_status
        ;;
    logs)
        do_logs
        ;;
    uninstall)
        do_uninstall
        ;;
    -h|--help|help)
        usage
        ;;
    *)
        error "Unknown command: '${1}'. Run: $0 help"
        ;;
esac
