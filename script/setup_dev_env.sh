#!/bin/bash

# Druppie Dev Environment Bootstrap
# Installs the Platform Base Layer (Flux, Kyverno, Tekton, Kong) into the current cluster.

set -e

COLOR_GREEN='\033[0;32m'
COLOR_BLUE='\033[0;34m'
COLOR_NC='\033[0m'

LOG_FILE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/../.druppie_history"

function log() {
    echo -e "${COLOR_BLUE}[SETUP]${COLOR_NC} $1"
}

function log_history() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') | SETUP     | Platform   | $1" >> "$LOG_FILE"
}

# 1. Check Connectivity
log "Checking Kubernetes Connection..."
if ! kubectl cluster-info &> /dev/null; then
    echo "❌ Cannot connect to Kubernetes."
    echo "💡 Run 'Install Kubernetes' first or check your KUBECONFIG."
    exit 1
fi
log "Connected to $(kubectl config current-context)."

# 1.5. Wait for Nodes to be Ready (Crucial for fresh local clusters)
function wait_for_nodes() {
    log "Waiting for all cluster nodes to be Ready..."
    if ! kubectl wait --for=condition=Ready nodes --all --timeout=120s; then
        echo "⚠️ Nodes are not ready yet. This might be fine if they are starting up, but could cause issues."
    else
        log "All nodes are Ready."
    fi
}
wait_for_nodes

# 2. Install Helm (if missing)
if ! command -v helm &> /dev/null; then
    log "Installing Helm..."
    curl https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash
fi

# Check for Secrets (Crucial for DB in Boot Layer)
if [ -z "$DRUPPIE_POSTGRES_PASS" ]; then
    echo "⚠️  DRUPPIE_POSTGRES_PASS is not set. Defaulting to 'postgres_p@ssw0rd' for Dev."
    DRUPPIE_POSTGRES_PASS="postgres_p@ssw0rd"
fi

# 3. Add Repos
log "Adding Helm Repositories..."
helm repo add fluxcd-community https://fluxcd-community.github.io/helm-charts
helm repo add kyverno https://kyverno.github.io/kyverno
helm repo add tekton-cd https://cdfoundation.github.io/tekton-helm-chart
helm repo add kong https://charts.konghq.com
helm repo add bitnami https://charts.bitnami.com/bitnami
helm repo up

# 4. Install Flux CD (GitOps Engine)
log "Installing Flux CD..."
kubectl apply -f https://github.com/fluxcd/flux2/releases/latest/download/install.yaml

log "Waiting for Flux Controllers..."
kubectl wait --for=condition=available deployment/source-controller -n flux-system --timeout=300s
kubectl wait --for=condition=available deployment/kustomize-controller -n flux-system --timeout=300s
kubectl wait --for=condition=available deployment/helm-controller -n flux-system --timeout=300s
kubectl wait --for=condition=available deployment/notification-controller -n flux-system --timeout=300s
log_history "Flux CD Installed"

# 5. Install Kyverno (Policy Engine)
log "Installing Kyverno..."
helm upgrade --install kyverno kyverno/kyverno \
  --namespace kyverno --create-namespace \
  --set admissionController.replicas=1 \
  --wait
log_history "Kyverno Installed"

# 6. Install Tekton (Build Engine)
# Tekton is complex via Helm, often easier via kubectl apply for base
log "Installing Tekton Pipelines..."
kubectl apply -f https://storage.googleapis.com/tekton-releases/pipeline/latest/release.yaml
log_history "Tekton Pipelines Installed"

# 7. Install Kong (API Gateway)
log "Installing Kong Gateway (Ingress)..."
helm upgrade --install kong kong/kong \
  --namespace kong --create-namespace \
  --set ingressController.installCRDs=false \
  --set proxy.type=LoadBalancer \
  --set controller.ingressClass.name=kong \
  --set controller.ingressClass.resource.enabled=true \
  --set controller.ingressClass.resource.default=true \
  --set admin.enabled=true \
  --set admin.http.enabled=true \
  --set manager.enabled=true \
  --wait
log_history "Kong Gateway Installed"

 # 8. Install Cert-Manager (Required for Rancher)
 log "Installing Cert-Manager (Required for Rancher)..."
 helm repo add jetstack https://charts.jetstack.io
 helm repo update
 helm upgrade --install cert-manager jetstack/cert-manager \
    --namespace cert-manager --create-namespace \
    --set crds.enabled=true \
    --wait

 log "Installing Rancher UI..."
 helm repo add rancher-stable https://releases.rancher.com/server-charts/stable
 helm repo update

 # 9. Install Rancher
 log "Deploying Rancher..."
 helm upgrade --install rancher rancher-stable/rancher \
      --namespace cattle-system --create-namespace \
      --set hostname=localhost \
      --set bootstrapPassword=${DRUPPIE_RANCHER_TOKEN} \
      --set ingress.tls.source=rancher \
      --set replicas=1 \
      --set ingress.ingressClassName=kong \
      --wait

    log "Waiting for Rancher to be ready..."
    kubectl -n cattle-system rollout status deploy/rancher

    log "Rancher UI Installed! 🤠"
    log "Access URL: https://localhost"
    log "Login: ${DRUPPIE_RANCHER_TOKEN}"
    log "(Note: Accept the self-signed certificate warning)"
    
    log_history "Rancher UI Installed"

# 10. Install Shared PostgreSQL (Boot Layer DB)
log "Installing Shared PostgreSQL (Boot Layer)..."

helm upgrade --install postgres bitnami/postgresql \
  --namespace databases --create-namespace \
  --set global.postgresql.auth.postgresPassword=${DRUPPIE_POSTGRES_PASS} \
  --set primary.persistence.size=5Gi \
  --set global.storageClass=local-path \
  --wait
log_history "PostgreSQL (Shared) Installed"

# echo "Enable PostGIS manually if needed:"
# kubectl exec -it -n databases svc/postgres-postgresql -env="PGPASSWORD=${DRUPPIE_POSTGRES_PASS}" -- psql -U postgres -c 'CREATE EXTENSION IF NOT EXISTS postgis;'
# log_history "PostGIS Enabled"

# 11. Install Redis (Cache Layer)
# log "Installing Redis (Cache Layer)..."
# helm upgrade --install redis bitnami/redis \
#   --namespace databases --create-namespace \
#   --set auth.password=${DRUPPIE_REDIS_PASS} \
#   --set architecture=standalone \
#   --set master.persistence.size=2Gi \
#   --set master.persistence.storageClass=local-path \
#   --wait
# log_history "Redis (Cache Layer) Installed"


# 12. Success
echo -e "${COLOR_GREEN}"
echo "✅  Platform Base Layer Installed Successfully!"
echo "-----------------------------------------------"
echo " - Flux CD (GitOps)"
echo " - Kyverno (Policies)"
echo " - Tekton (CI)"
echo " - Kong (Ingress)"
echo " - Cert-Manager (Required for Rancher)"
echo " - Rancher UI"
echo " - Postgres (Shared)"
# echo " - Redis (Cache Layer)"

echo ""
echo "You are ready to deploy applications."
echo -e "${COLOR_NC}"
