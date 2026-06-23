#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

log()  { echo -e "${GREEN}[druppie]${NC} $*"; }
warn() { echo -e "${YELLOW}[warn]${NC} $*"; }
err()  { echo -e "${RED}[error]${NC} $*" >&2; }

CLUSTER_NAME="druppie"
NAMESPACE="druppie"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

stop_docker_compose() {
    if docker compose ps --status running -q 2>/dev/null | grep -q .; then
        log "Stopping Docker Compose services..."
        docker compose --profile dev --profile init --profile infra --profile prod down 2>/dev/null || true
    fi
}

stop_kind() {
    if kind get clusters 2>/dev/null | grep -q "$CLUSTER_NAME"; then
        log "Deleting kind cluster '$CLUSTER_NAME'..."
        kind delete cluster --name "$CLUSTER_NAME"
    fi
}

stop_all() {
    stop_docker_compose
    stop_kind
}

check_kind_prerequisites() {
    local missing=()
    command -v kind    >/dev/null 2>&1 || missing+=("kind")
    command -v kubectl >/dev/null 2>&1 || missing+=("kubectl")
    command -v helm    >/dev/null 2>&1 || missing+=("helm")
    if [ ${#missing[@]} -gt 0 ]; then
        err "Missing tools: ${missing[*]}"
        err "Install them before using Kubernetes mode."
        exit 1
    fi
}

# ---------------------------------------------------------------------------
# Docker Compose mode
# ---------------------------------------------------------------------------

start_docker() {
    stop_all
    log "Starting Druppie with Docker Compose (dev profile)..."
    docker compose --profile dev --profile init up -d
    echo ""
    log "Druppie is starting up. Services:"
    echo ""
    echo -e "  ${CYAN}Frontend${NC}   http://localhost:${FRONTEND_PORT:-5273}"
    echo -e "  ${CYAN}Backend${NC}    http://localhost:${BACKEND_PORT:-8100}"
    echo -e "  ${CYAN}Keycloak${NC}   http://localhost:${KEYCLOAK_PORT:-8180}"
    echo -e "  ${CYAN}Gitea${NC}      http://localhost:${GITEA_PORT:-3100}"
    echo -e "  ${CYAN}Adminer${NC}    http://localhost:${ADMINER_PORT:-8081}"
    echo ""
    log "View logs: docker compose logs -f"
}

# ---------------------------------------------------------------------------
# Kubernetes (kind) mode
# ---------------------------------------------------------------------------

build_and_load_images() {
    log "Building Docker images and loading into kind..."

    build_one() {
        local name="$1" dockerfile="$2" context="$3"
        log "  Building $name..."
        docker build -q -t "$name:latest" -f "$dockerfile" "$context" >/dev/null
        kind load docker-image "$name:latest" --name "$CLUSTER_NAME" 2>/dev/null
    }

    build_one "druppie-backend"  "$SCRIPT_DIR/Dockerfile"      "$SCRIPT_DIR"
    build_one "druppie-frontend" "$SCRIPT_DIR/frontend/Dockerfile" "$SCRIPT_DIR/frontend"
    build_one "druppie-init"     "$SCRIPT_DIR/Dockerfile.init"  "$SCRIPT_DIR"

    local MCP_DIR="$SCRIPT_DIR/druppie/mcp-servers"
    for module in coding docker filesearch web archimate registry llm vision; do
        if [ -f "$MCP_DIR/module-$module/Dockerfile" ]; then
            build_one "druppie-module-$module" "$MCP_DIR/module-$module/Dockerfile" "$MCP_DIR"
        fi
    done

    log "All images built and loaded into kind."
}

install_nginx_ingress() {
    if ! kubectl get ns ingress-nginx >/dev/null 2>&1 || \
       ! kubectl get pods -n ingress-nginx -l app.kubernetes.io/component=controller --field-selector=status.phase=Running -o name 2>/dev/null | grep -q .; then
        log "Installing NGINX Ingress Controller..."
        kubectl apply -f https://raw.githubusercontent.com/kubernetes/ingress-nginx/main/deploy/static/provider/kind/deploy.yaml
        log "Waiting for ingress controller to be ready..."
        kubectl wait --namespace ingress-nginx \
            --for=condition=ready pod \
            --selector=app.kubernetes.io/component=controller \
            --timeout=120s
    else
        log "NGINX Ingress Controller already running."
    fi
}

deploy_helm_chart() {
    log "Creating namespace..."
    kubectl create namespace "$NAMESPACE" --dry-run=client -o yaml | kubectl apply -f -

    log "Installing Helm chart..."
    helm upgrade --install druppie "$SCRIPT_DIR/helm/druppie" \
        --namespace "$NAMESPACE" \
        --values "$SCRIPT_DIR/helm/druppie/values.yaml" \
        --wait --timeout 10m

    log "Helm deploy complete!"
}

wait_for_pods() {
    log "Waiting for pods to be ready (timeout 5m)..."
    local deadline=$((SECONDS + 300))
    while [ $SECONDS -lt $deadline ]; do
        local not_ready
        not_ready=$(kubectl get pods -n "$NAMESPACE" --no-headers 2>/dev/null \
            | grep -v Completed \
            | grep -v Running \
            | grep -cv "^$" || true)
        if [ "$not_ready" -eq 0 ] 2>/dev/null; then
            log "All pods running!"
            return 0
        fi
        sleep 5
    done
    warn "Some pods are not ready yet. Check: kubectl get pods -n $NAMESPACE"
}

start_kubernetes() {
    check_kind_prerequisites
    stop_all

    log "Starting Druppie with Kubernetes (kind)..."
    echo ""

    # 1. Create cluster if needed
    if kind get clusters 2>/dev/null | grep -q "$CLUSTER_NAME"; then
        log "Kind cluster '$CLUSTER_NAME' already exists, reusing."
    else
        log "Creating kind cluster '$CLUSTER_NAME'..."
        kind create cluster \
            --config "$SCRIPT_DIR/kind/cluster.yaml" \
            --image kindest/node:v1.29.2
        log "Waiting for nodes..."
        kubectl wait --for=condition=ready nodes --all --timeout=120s
    fi

    # 2. Build and load images
    build_and_load_images

    # 3. Install ingress controller
    install_nginx_ingress

    # 4. Deploy helm chart
    deploy_helm_chart

    # 5. Wait for pods
    wait_for_pods

    echo ""
    log "Druppie is running on Kubernetes!"
    echo ""
    echo -e "  ${CYAN}All services${NC}  http://localhost:9080"
    echo -e "    /          Frontend"
    echo -e "    /api       Backend API"
    echo -e "    /realms    Keycloak"
    echo -e "    /git       Gitea"
    echo ""
    echo -e "  ${CYAN}Status${NC}   kubectl get pods -n $NAMESPACE"
    echo -e "  ${CYAN}Logs${NC}     kubectl logs -n $NAMESPACE -f deploy/druppie-backend"
    echo ""
}

# ---------------------------------------------------------------------------
# Stop mode
# ---------------------------------------------------------------------------

do_stop() {
    log "Stopping all Druppie services..."
    stop_all
    log "Everything stopped."
}

# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------

do_status() {
    echo -e "${BOLD}=== Druppie Status ===${NC}"
    echo ""

    # Docker Compose
    local compose_running
    compose_running=$(docker compose ps --status running -q 2>/dev/null | wc -l || echo 0)
    if [ "$compose_running" -gt 0 ]; then
        echo -e "  ${GREEN}Docker Compose${NC}: $compose_running container(s) running"
        docker compose ps --format "table {{.Name}}\t{{.Status}}\t{{.Ports}}" 2>/dev/null | head -25
    else
        echo -e "  ${YELLOW}Docker Compose${NC}: not running"
    fi
    echo ""

    # Kind
    if kind get clusters 2>/dev/null | grep -q "$CLUSTER_NAME"; then
        echo -e "  ${GREEN}Kind cluster${NC}: running"
        kubectl get nodes 2>/dev/null | sed 's/^/    /'
        echo ""
        echo "  Pods:"
        kubectl get pods -n "$NAMESPACE" --no-headers 2>/dev/null | sed 's/^/    /' || echo "    (none)"
    else
        echo -e "  ${YELLOW}Kind cluster${NC}: not running"
    fi
    echo ""
}

# ---------------------------------------------------------------------------
# Interactive menu
# ---------------------------------------------------------------------------

show_menu() {
    echo ""
    echo -e "${BOLD}=== Druppie Startup ===${NC}"
    echo ""
    echo -e "  ${CYAN}1${NC}) Docker Compose  (dev mode, hot reload)"
    echo -e "  ${CYAN}2${NC}) Kubernetes      (kind cluster + Helm)"
    echo -e "  ${CYAN}3${NC}) Stop all"
    echo -e "  ${CYAN}4${NC}) Status"
    echo -e "  ${CYAN}q${NC}) Quit"
    echo ""
    read -rp "Choose [1-4/q]: " choice
    case "$choice" in
        1) start_docker ;;
        2) start_kubernetes ;;
        3) do_stop ;;
        4) do_status ;;
        q|Q) exit 0 ;;
        *) err "Invalid choice: $choice"; show_menu ;;
    esac
}

# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

# Source .env if it exists (for port vars)
if [ -f "$SCRIPT_DIR/.env" ]; then
    set -a
    # shellcheck disable=SC1091
    source "$SCRIPT_DIR/.env"
    set +a
fi

case "${1:-}" in
    docker)     start_docker ;;
    kubernetes|k8s) start_kubernetes ;;
    stop)       do_stop ;;
    status)     do_status ;;
    "")         show_menu ;;
    *)
        echo "Usage: $0 {docker|kubernetes|stop|status}"
        echo "  Or run without arguments for interactive menu."
        exit 1
        ;;
esac
