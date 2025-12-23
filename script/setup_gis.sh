#!/bin/bash

# Druppie GIS Services Setup
# Installs GeoServer (Map Server) and WebODM (Drone Mapping)

set -e

COLOR_GREEN='\033[0;32m'
COLOR_BLUE='\033[0;34m'
COLOR_NC='\033[0m'

LOG_FILE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/../.druppie_history"

function log() {
    echo -e "${COLOR_BLUE}[SETUP]${COLOR_NC} $1"
}

function log_history() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') | SETUP     | GIS        | $1" >> "$LOG_FILE"
}

# 1. Check Connectivity
log "Checking Kubernetes Connection..."
if ! kubectl cluster-info &> /dev/null; then
    echo "❌ Cannot connect to Kubernetes."
    exit 1
fi

# 2. Add Repos
# 2. Add Repos
log "Adding Helm Repositories..."
# Or use Kartoza which is popular for GIS:
helm repo add kartoza https://kartoza.github.io/charts
helm repo up

# 3. Create Namespace
kubectl create namespace gis --dry-run=client -o yaml | kubectl apply -f -

# 4. Install GeoServer (Manual Manifest)
log "Installing GeoServer (via Manifest)..."
# Cleanup Helm
helm uninstall geoserver -n gis &> /dev/null || true
kubectl delete deploy geoserver -n gis &> /dev/null || true
kubectl delete svc geoserver -n gis &> /dev/null || true

cat <<EOF | kubectl apply -f -
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: geoserver-data
  namespace: gis
spec:
  accessModes:
    - ReadWriteOnce
  resources:
    requests:
      storage: 5Gi
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: geoserver
  namespace: gis
spec:
  replicas: 1
  selector:
    matchLabels:
      app: geoserver
  template:
    metadata:
      labels:
        app: geoserver
    spec:
      initContainers:
      - name: fix-perms
        image: busybox
        command: ["sh", "-c", "chown -R 1000:1000 /opt/geoserver/data_dir"]
        volumeMounts:
        - name: geoserver-data
          mountPath: /opt/geoserver/data_dir
      containers:
      - name: geoserver
        image: kartoza/geoserver:2.26.1
        ports:
        - containerPort: 8080
        env:
        - name: GEOSERVER_ADMIN_USER
          value: "admin"
        - name: GEOSERVER_ADMIN_PASSWORD
          value: "${DRUPPIE_GEOSERVER_PASS}"
        - name: GEOSERVER_DATA_DIR
          value: "/opt/geoserver/data_dir"
        - name: GEOSERVER_CSRF_WHITELIST
          value: "geoserver.${DRUPPIE_DOMAIN}"
        volumeMounts:
        - name: geoserver-data
          mountPath: /opt/geoserver/data_dir
        resources:
          requests:
            memory: "1Gi"
            cpu: "500m"
          limits:
            memory: "2Gi"
      volumes:
      - name: geoserver-data
        persistentVolumeClaim:
          claimName: geoserver-data
---
apiVersion: v1
kind: Service
metadata:
  name: geoserver
  namespace: gis
spec:
  selector:
    app: geoserver
  ports:
  - port: 8080
    targetPort: 8080
  type: ClusterIP
EOF

log "Waiting for GeoServer..."
kubectl rollout status deployment/geoserver -n gis --timeout=300s
log_history "GeoServer Installed (Manual Manifest)"


# Create GEO DBs
log "Ensuring GeoNode Databases exist..."
kubectl exec -n databases svc/postgres-postgresql -- env PGPASSWORD=${DRUPPIE_POSTGRES_PASS} psql -U postgres -c "CREATE DATABASE geonode;" || true
kubectl exec -n databases svc/postgres-postgresql -- env PGPASSWORD=${DRUPPIE_POSTGRES_PASS} psql -U postgres -c "CREATE DATABASE geonode_data;" || true

# FOR NOW DISABLED NEEDS MORE TESTING

# OS="$(uname)"
# if [[ "$OS" == "Darwin" ]]; then
#  log "GeoNode Not available on macOS..."   
# else
# # 5. Install GeoNode (GIS Portal)
# log "Installing GeoNode..."

# # Add Official Repo (Community Maintained)
# helm repo add geonode https://GeoNodeUserGroup-DE.github.io/geonode-k8s/
# helm repo up

# # Install via Helm (Robust community chart)
# helm upgrade --install geonode charts/geonode \
#   --namespace gis \
#   --set global.postgresql.host=postgres-postgresql.databases.svc.cluster.local \
#   --set global.postgresql.port=5432 \
#   --set global.postgresql.user=postgres \
#   --set global.postgresql.password=${DRUPPIE_POSTGRES_PASS} \
#   --set postgresql.enabled=false \
#   --set geonode.database.name=geonode \
#   --set geonode.geodatabase.name=geonode_data \
#   --set geoserver.url="http://geoserver.gis.svc.cluster.local:8080/geoserver/" \
#   --set geonode.siteUrl="http://geonode.${DRUPPIE_DOMAIN}/" \
#   --set geonode.adminUser=admin \
#   --set geonode.adminPassword=${DRUPPIE_POSTGRES_PASS} \
#   --set service.type=ClusterIP \
#   --wait
# log_history "GeoNode Installed (Helm)"
# fi

# 5. Install WebODM (Lightning/NodeODM)
# WebODM is complex on K8s (Storage/Postgres/Redis). 
# For this 'Light' script, we deploy a simplified NodeODM (processing node) and references.
# In a real PROD setup this would be full WebODM stack.
log "Installing NodeODM (Drone Processing Engine)..."
# Using raw manifest for simplicity as no official stable Helm chart exists for simple setups
cat <<EOF | kubectl apply -f -
apiVersion: apps/v1
kind: Deployment
metadata:
  name: nodeodm
  namespace: gis
spec:
  replicas: 1
  selector:
    matchLabels:
      app: nodeodm
  template:
    metadata:
      labels:
        app: nodeodm
    spec:
      containers:
      - name: nodeodm
        image: opendronemap/nodeodm:latest
        ports:
        - containerPort: 3000
---
apiVersion: v1
kind: Service
metadata:
  name: nodeodm
  namespace: gis
spec:
  selector:
    app: nodeodm
  ports:
  - port: 3000
    targetPort: 3000
  type: ClusterIP
EOF
log_history "NodeODM Installed"

# 6. Success
echo -e "${COLOR_GREEN}"
echo "✅  GIS Services Installed!"
echo "-------------------------"
echo " - GeoServer: http://geoserver.gis.svc.cluster.local:8080/geoserver"
echo "   User:      admin"
echo "   Pass:      geoserver"
echo ""
echo " - GeoNode:   http://geonode.gis.svc.cluster.local:80"
echo "   (Map Portal - Requires DB)"
echo ""
echo " - NodeODM:   http://nodeodm.gis.svc.cluster.local:3000"
echo "   (Drone Processing API)"
echo ""
echo "⚠️  Note: Port-forward to access locally:"
echo "   kubectl port-forward svc/geoserver -n gis 8080:8080"
echo "   kubectl port-forward svc/geonode -n gis 8000:80"
echo "   kubectl port-forward svc/nodeodm -n gis 3000:3000"
echo -e "${COLOR_NC}"
