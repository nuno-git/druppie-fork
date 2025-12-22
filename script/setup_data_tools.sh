#!/bin/bash

# Druppie Data & Versioning Setup
# Installs Gitea (Version Control) and MinIO (Data Lake)

set -e

COLOR_GREEN='\033[0;32m'
COLOR_BLUE='\033[0;34m'
COLOR_NC='\033[0m'

LOG_FILE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/../.druppie_history"

function log() {
    echo -e "${COLOR_BLUE}[SETUP]${COLOR_NC} $1"
}

function log_history() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') | SETUP     | DataTools  | $1" >> "$LOG_FILE"
}

# 1. Check Connectivity
log "Checking Kubernetes Connection..."
if ! kubectl cluster-info &> /dev/null; then
    echo "❌ Cannot connect to Kubernetes."
    exit 1
fi

# 2. Add Repos
log "Adding Helm Repositories..."
helm repo add gitea-charts https://dl.gitea.io/charts/
helm repo add minio https://charts.min.io/
helm repo add qdrant https://qdrant.github.io/qdrant-helm
helm repo up

# 3. Install Gitea (Lightweight Git Server)
log "Installing Gitea..."

# Clean up previous potentially stuck HA installation
if helm status gitea -n gitea &> /dev/null; then
    log "Removing previous Gitea installation to switch to lightweight mode..."
    helm uninstall gitea -n gitea --wait || true
    # Ensure PVCs for Postgres are not reused confusingly (optional, but cleaner)
    kubectl delete pvc -n gitea -l app.kubernetes.io/name=postgresql-ha || true
fi

helm upgrade --install gitea gitea-charts/gitea \
  --namespace gitea --create-namespace \
  --version 10.6.0 \
  --set gitea.admin.username=druppie_admin \
  --set gitea.admin.password=${DRUPPIE_GITEA_PASS} \
  --set persistence.size=1Gi \
  --set postgresql.enabled=false \
  --set postgresql-ha.enabled=false \
  --set redis.enabled=false \
  --set redis-cluster.enabled=false \
  --set gitea.config.database.DB_TYPE=postgres \
  --set gitea.config.database.HOST=postgres-postgresql.databases.svc.cluster.local:5432 \
  --set gitea.config.database.NAME=postgres \
  --set gitea.config.database.USER=postgres \
  --set gitea.config.database.PASSWD=${DRUPPIE_POSTGRES_PASS} \
  --wait
log_history "Gitea Installed"

# 4. Install MinIO (S3 Compatible Storage)
log "Installing MinIO..."
helm upgrade --install minio minio/minio \
  --namespace minio --create-namespace \
  --set rootUser=admin \
  --set rootPassword=${DRUPPIE_MINIO_PASS} \
  --set mode=standalone \
  --set replicas=1 \
  --set global.storageClass=local-path \
  --set volumePermissions.enabled=true \
  --set persistence.size=5Gi \
  --set resources.requests.memory=256Mi \
  --wait
log_history "MinIO Installed"

# 5. Install Qdrant (Vector DB for AI)
log "Installing Qdrant Vector DB..."
helm upgrade --install qdrant qdrant/qdrant \
  --namespace databases --create-namespace \
  --set replicaCount=1 \
  --set persistence.size=2Gi \
  --set apiKey=${DRUPPIE_QDRANT_KEY} \
  --wait
log_history "Qdrant Installed"

# 6. Success
echo -e "${COLOR_GREEN}"
echo "✅  Data Services Installed!"
echo "--------------------------"
echo " - Gitea:     http://gitea-http.gitea.svc.cluster.local:3000"
echo "   User:      druppie_admin"
echo "   Pass:      ${DRUPPIE_GITEA_PASS}"
echo ""
echo " - MinIO:     http://minio.minio.svc.cluster.local:9000"
echo "   User:      admin"
echo "   Pass:      ${DRUPPIE_MINIO_PASS}"
echo ""
echo " - Qdrant:    http://qdrant.databases.svc.cluster.local:6333"
echo "   API Key:   ${DRUPPIE_QDRANT_KEY}"
echo ""
echo "⚠️  Note: Port-forward to access locally:"
echo "   kubectl port-forward svc/gitea-http -n gitea 3000:3000"
echo "   kubectl port-forward svc/minio -n minio 9000:9000"
echo "   kubectl port-forward svc/qdrant -n databases 6333:6333"
echo -e "${COLOR_NC}"
