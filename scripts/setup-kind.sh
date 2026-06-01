#!/usr/bin/env bash
set -euo pipefail

# Druppie Kubernetes - Kind Cluster Setup
# Usage: ./scripts/setup-kind.sh [create|delete|status]

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
CLUSTER_NAME="druppie"
NAMESPACE="druppie"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log() { echo -e "${GREEN}[druppie]${NC} $*"; }
warn() { echo -e "${YELLOW}[warn]${NC} $*"; }
error() { echo -e "${RED}[error]${NC} $*" >&2; exit 1; }

check_prerequisites() {
    log "Checking prerequisites..."
    command -v kind >/dev/null 2>&1 || error "kind not found. Install: https://kind.sigs.k8s.io/docs/user/quick-start/"
    command -v kubectl >/dev/null 2>&1 || error "kubectl not found. Install: https://kubernetes.io/docs/tasks/tools/"
    command -v helm >/dev/null 2>&1 || error "helm not found. Install: https://helm.sh/docs/intro/install/"
    log "All prerequisites met."
}

create_cluster() {
    if kind get clusters 2>/dev/null | grep -q "$CLUSTER_NAME"; then
        warn "Cluster '$CLUSTER_NAME' already exists. Use 'delete' first or 'status'."
        exit 0
    fi

    log "Creating kind cluster '$CLUSTER_NAME'..."
    kind create cluster \
        --config "$PROJECT_DIR/kind/cluster.yaml" \
        --image kindest/node:v1.29.2

    log "Waiting for nodes to be ready..."
    kubectl wait --for=condition=ready nodes --all --timeout=120s

    log "Cluster created successfully!"
    show_status
}

delete_cluster() {
    log "Deleting kind cluster '$CLUSTER_NAME'..."
    kind delete cluster --name "$CLUSTER_NAME"
    log "Cluster deleted."
}

deploy_chart() {
    log "Building Docker images and loading into kind..."
    # TODO: Add image build and load commands when Dockerfiles are ready

    log "Creating namespace..."
    kubectl create namespace "$NAMESPACE" --dry-run=client -o yaml | kubectl apply -f -

    log "Installing Helm chart..."
    helm upgrade --install druppie "$PROJECT_DIR/helm/druppie" \
        --namespace "$NAMESPACE" \
        --values "$PROJECT_DIR/helm/druppie/values.yaml" \
        --wait --timeout 10m

    log "Deploy complete!"
}

show_status() {
    log "Cluster status:"
    kubectl cluster-info --context "kind-$CLUSTER_NAME" 2>/dev/null || true
    echo ""
    kubectl get nodes
    echo ""
    log "Pods (namespace: $NAMESPACE):"
    kubectl get pods -n "$NAMESPACE" 2>/dev/null || warn "Namespace not yet created"
    echo ""
    log "Services (namespace: $NAMESPACE):"
    kubectl get svc -n "$NAMESPACE" 2>/dev/null || warn "Namespace not yet created"
    echo ""
    log "Port-forward commands for local access:"
    echo "  kubectl port-forward -n $NAMESPACE svc/backend 8000:8000"
    echo "  kubectl port-forward -n $NAMESPACE svc/frontend 5173:5173"
    echo "  kubectl port-forward -n $NAMESPACE svc/keycloak 8080:8080"
    echo "  kubectl port-forward -n $NAMESPACE svc/gitea 3000:3000"
}

case "${1:-create}" in
    create)
        check_prerequisites
        create_cluster
        ;;
    delete)
        delete_cluster
        ;;
    deploy)
        deploy_chart
        ;;
    status)
        show_status
        ;;
    all)
        check_prerequisites
        create_cluster
        deploy_chart
        ;;
    *)
        echo "Usage: $0 {create|delete|deploy|status|all}"
        exit 1
        ;;
esac
