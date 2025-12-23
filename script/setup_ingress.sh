#!/bin/bash

# Druppie Ingress Setup
# Configures Ingress rules to expose all installed services via Kong Gateway using Subdomains.

set -e

COLOR_GREEN='\033[0;32m'
COLOR_BLUE='\033[0;34m'
COLOR_NC='\033[0m'

LOG_FILE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/../.druppie_history"

function log() {
    echo -e "${COLOR_BLUE}[SETUP]${COLOR_NC} $1"
}

function log_history() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') | SETUP     | Ingress    | $1" >> "$LOG_FILE"
}

# 1. Check if Kong is installed
log "Checking for Kong Gateway..."
if ! kubectl get svc -n kong kong-kong-proxy &> /dev/null; then
    echo "⚠️  Kong Gateway not found. Please run 'Bootstrap Platform' first."
    exit 1
fi

log "Applying Subdomain Ingress Rules (Domain: ${DRUPPIE_DOMAIN})..."

# IAM Namespace (Keycloak)
log "Configuring IAM Ingress (keycloak.${DRUPPIE_DOMAIN})..."
cat <<EOF | kubectl apply -f -
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: iam-ingress
  namespace: iam
spec:
  ingressClassName: kong
  rules:
  - host: keycloak.${DRUPPIE_DOMAIN}
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: keycloak
            port:
              number: 80
EOF

# GIS Namespace
log "Configuring GIS Ingress (geoserver, nodeodm, geonode on .${DRUPPIE_DOMAIN})..."
cat <<EOF | kubectl apply -f -
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: gis-ingress
  namespace: gis
  annotations:
    konghq.com/strip-path: "false"
spec:
  ingressClassName: kong
  rules:
  - host: geoserver.${DRUPPIE_DOMAIN}
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: geoserver
            port:
              number: 8080
  - host: nodeodm.${DRUPPIE_DOMAIN}
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: nodeodm
            port:
              number: 3000
  - host: geonode.${DRUPPIE_DOMAIN}
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: geonode
            port:
              number: 80
EOF

# Data Namespace (Gitea)
log "Configuring Data Ingress (gitea.${DRUPPIE_DOMAIN})..."
cat <<EOF | kubectl apply -f -
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: gitea-ingress
  namespace: gitea
spec:
  ingressClassName: kong
  rules:
  - host: gitea.${DRUPPIE_DOMAIN}
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: gitea-http
            port:
              number: 3000
EOF

# MinIO Namespace
log "Configuring MinIO Ingress (minio.${DRUPPIE_DOMAIN})..."
cat <<EOF | kubectl apply -f -
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: minio-ingress
  namespace: minio
spec:
  ingressClassName: kong
  rules:
  - host: minio.${DRUPPIE_DOMAIN}
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: minio-console
            port:
              number: 9001
EOF

# Databases Namespace (pgAdmin)
log "Configuring Databases Ingress (pgadmin.${DRUPPIE_DOMAIN})..."
cat <<EOF | kubectl apply -f -
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: pgadmin-ingress
  namespace: databases
spec:
  ingressClassName: kong
  rules:
  - host: pgadmin.${DRUPPIE_DOMAIN}
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: pgadmin
            port:
              number: 80
EOF

# Observability Namespace (Grafana)
log "Configuring Observability Ingress (grafana.${DRUPPIE_DOMAIN})..."
cat <<EOF | kubectl apply -f -
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: observability-ingress
  namespace: observability
spec:
  ingressClassName: kong
  rules:
  - host: grafana.${DRUPPIE_DOMAIN}
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: grafana
            port:
              number: 80
EOF

# Kong Admin API
log "Configuring Kong Admin Ingress (kong.${DRUPPIE_DOMAIN}, api.${DRUPPIE_DOMAIN})..."
cat <<EOF | kubectl apply -f -
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: kong-admin-ingress
  namespace: kong
spec:
  ingressClassName: kong
  rules:
  - host: kong.${DRUPPIE_DOMAIN}
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: kong-kong-manager
            port:
              number: 8002
  - host: api.${DRUPPIE_DOMAIN}
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: kong-kong-admin
            port:
              number: 8001
EOF

# ---------------------------------------------------------
# Landing Page (Portal) Setup
# ---------------------------------------------------------
log "Deploying Dashboard Portal..."

# 1. Prepare Content for Portal (HTML + Favicon)
TMP_DIR=$(mktemp -d)
# Resolve Project Root (assuming script is in script/ folder)
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOGO_FILE="$PROJECT_ROOT/druppie_logo.svg"
HTML_FILE="$TMP_DIR/index.html"
ICON_FILENAME="favicon.svg"

# If logo exists, use it
if [ -f "$LOGO_FILE" ]; then
    cp "$LOGO_FILE" "$TMP_DIR/$ICON_FILENAME"
    ICON_HREF="$ICON_FILENAME"
    log "Using local logo: $LOGO_FILE"
else
    # Fallback to emoji data uri
    ICON_HREF="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>💧</text></svg>"
    log "Using fallback emoji logo."
fi

# Generate HTML
cat <<EOF > "$HTML_FILE"
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Druppie DEV Platform</title>
    <link rel="icon" href="${ICON_HREF}">
    <style>
        :root {
            --primary: #2563eb;
            --bg: #f8fafc;
            --card-bg: #ffffff;
            --text: #1e293b;
        }
        body { 
            font-family: -apple-system, system-ui, sans-serif;
            background: var(--bg);
            color: var(--text);
            margin: 0;
            padding: 40px;
            line-height: 1.5;
        }
        .container {
            max-width: 1200px;
            margin: 0 auto;
        }
        h1 { font-size: 2.5rem; margin-bottom: 0.5rem; color: #0f172a; }
        p.subtitle { color: #64748b; font-size: 1.1rem; margin-bottom: 3rem; }
        
        .grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
            gap: 24px;
        }
        
        .card {
            background: var(--card-bg);
            border-radius: 12px;
            padding: 24px;
            box-shadow: 0 4px 6px -1px rgb(0 0 0 / 0.1);
            transition: transform 0.2s, box-shadow 0.2s;
            text-decoration: none;
            color: inherit;
            border: 1px solid #e2e8f0;
            display: flex;
            flex-direction: column;
        }
        .card:hover {
            transform: translateY(-4px);
            box-shadow: 0 10px 15px -3px rgb(0 0 0 / 0.1);
            border-color: var(--primary);
        }
        
        .category {
            text-transform: uppercase;
            letter-spacing: 0.05em;
            font-size: 0.75rem;
            font-weight: 700;
            color: var(--primary);
            margin-bottom: 12px;
        }
        .title {
            font-size: 1.25rem;
            font-weight: 600;
            margin-bottom: 8px;
        }
        .desc {
            color: #64748b;
            font-size: 0.9rem;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1><img src="favicon.svg" alt="Logo" style="height: 1em; vertical-align: -0.15em; margin-right: 12px;"> Druppie Platform</h1>
        <p class="subtitle">Central Access Portal</p>
        
        <div class="grid">
            <!-- IAM -->
            <a href="http://keycloak.${DRUPPIE_DOMAIN}/" class="card" target="_blank">
                <div class="category">Identity & Access</div>
                <div class="title">Keycloak</div>
                <div class="desc">User management and authentication services.</div>
            </a>

            <!-- Observability -->
            <a href="http://grafana.${DRUPPIE_DOMAIN}/" class="card" target="_blank">
                <div class="category">Observability</div>
                <div class="title">Grafana</div>
                <div class="desc">Metrics dashboards, logs (Loki) and traces.</div>
            </a>

            <!-- Data Services -->
            <a href="http://gitea.${DRUPPIE_DOMAIN}/" class="card" target="_blank">
                <div class="category">Data Services</div>
                <div class="title">Gitea</div>
                <div class="desc">Git repositories and version control.</div>
            </a>

            <a href="http://minio.${DRUPPIE_DOMAIN}/" class="card" target="_blank">
                <div class="category">Data Services</div>
                <div class="title">MinIO</div>
                <div class="desc">Object storage (S3) console.</div>
            </a>

            <a href="http://pgadmin.${DRUPPIE_DOMAIN}/" class="card" target="_blank">
                <div class="category">Data Services</div>
                <div class="title">pgAdmin</div>
                <div class="desc">PostgreSQL database management UI.</div>
            </a>

            <!-- GIS -->
            <a href="http://geoserver.${DRUPPIE_DOMAIN}/geoserver/web/" class="card" target="_blank">
                <div class="category">GIS Services</div>
                <div class="title">GeoServer</div>
                <div class="desc">Geospatial data server and maps.</div>
            </a>

            <a href="http://geonode.${DRUPPIE_DOMAIN}/" class="card" target="_blank">
                <div class="category">GIS Services</div>
                <div class="title">GeoNode</div>
                <div class="desc">Geospatial content management system.</div>
            </a>
            
            <a href="http://nodeodm.${DRUPPIE_DOMAIN}/" class="card" target="_blank">
                <div class="category">GIS Services</div>
                <div class="title">NodeODM</div>
                <div class="desc">Drone imagery processing engine.</div>
            </a>

            <!-- Admin -->
            <a href="http://rancher.${DRUPPIE_DOMAIN}/" class="card" target="_blank">
                <div class="category">System Administration</div>
                <div class="title">Rancher</div>
                <div class="desc">Kubernetes cluster management UI.</div>
            </a>

            <a href="http://kong.${DRUPPIE_DOMAIN}/" class="card" target="_blank">
                <div class="category">System Administration</div>
                <div class="title">Kong Manager</div>
                <div class="desc">API Gateway Manager GUI.</div>
            </a>
        </div>
    </div>
</body>
</html>
EOF

# Create ConfigMap from generated files
# We use --dry-run=client to generate YAML, which we then apply. This handles updates/creation idempotentlyish.
# However, kubectl create configmap from file adds binary data if needed.
kubectl create configmap portal-html -n kong --from-file="$TMP_DIR" --dry-run=client -o yaml | kubectl apply -f -

# Clean up
rm -rf "$TMP_DIR"

# 2. Deploy Nginx serving the ConfigMap
cat <<EOF | kubectl apply -f -
apiVersion: apps/v1
kind: Deployment
metadata:
  name: portal
  namespace: kong
spec:
  replicas: 1
  selector:
    matchLabels:
      app: portal
  template:
    metadata:
      labels:
        app: portal
    spec:
      containers:
      - name: nginx
        image: nginx:alpine
        ports:
        - containerPort: 80
        volumeMounts:
        - name: html
          mountPath: /usr/share/nginx/html
      volumes:
      - name: html
        configMap:
          name: portal-html
---
apiVersion: v1
kind: Service
metadata:
  name: portal
  namespace: kong
spec:
  selector:
    app: portal
  ports:
  - port: 80
    targetPort: 80
---
# ---------------------------------------------------------
# Error Page (Service Unavailable)
# ---------------------------------------------------------
# ConfigMap for Error HTML
apiVersion: v1
kind: ConfigMap
metadata:
  name: error-html
  namespace: kong
data:
  index.html: |
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Service Unavailable</title>
        <style>
            body { font-family: -apple-system, sans-serif; background: #f8fafc; color: #334155; display: flex; align-items: center; justify-content: center; height: 100vh; margin: 0; text-align: center; }
            .container { background: white; padding: 40px; border-radius: 12px; box-shadow: 0 4px 6px -1px rgb(0 0 0 / 0.1); max-width: 400px; }
            h1 { color: #ef4444; margin-bottom: 10px; }
            p { margin-bottom: 20px; line-height: 1.5; }
            a { color: #2563eb; text-decoration: none; font-weight: 500; }
            a:hover { text-decoration: underline; }
            .icon { font-size: 3rem; margin-bottom: 20px; }
        </style>
    </head>
    <body>
        <div class="container">
            <div class="icon">🚧</div>
            <h1>Service Unavailable</h1>
            <p>This service is currently not installed or is unavailable on your system.</p>
            <a href="/">Return to Portal</a>
        </div>
    </body>
    </html>
---
# Deployment for Error Page
apiVersion: apps/v1
kind: Deployment
metadata:
  name: error-page
  namespace: kong
spec:
  replicas: 1
  selector:
    matchLabels:
      app: error-page
  template:
    metadata:
      labels:
        app: error-page
    spec:
      containers:
      - name: nginx
        image: nginx:alpine
        ports:
        - containerPort: 80
        volumeMounts:
        - name: html
          mountPath: /usr/share/nginx/html
      volumes:
      - name: html
        configMap:
          name: error-html
---
# Service for Error Page
apiVersion: v1
kind: Service
metadata:
  name: error-page
  namespace: kong
spec:
  selector:
    app: error-page
  ports:
  - port: 80
    targetPort: 80
EOF

# ---------------------------------------------------------
# Validating Upstreams (Fallback for Missing Services)
# ---------------------------------------------------------
# This ensures that if a service (e.g. GeoNode on macOS) wasn't installed, 
# we create a placeholder Service pointing to the Error Page so Ingress doesn't break/404.

function ensure_fallback_service() {
    local ns=$1
    local svc=$2
    
    # Check if svc exists
    if ! kubectl get svc "$svc" -n "$ns" &> /dev/null; then
        log "Service '$svc' in '$ns' not found. Creating Fallback to Error Page..."
        
        # Create ExternalName service pointing to error-page.kong.svc.cluster.local
        # Note: ExternalName works at DNS level. Kong resolves it.
        kubectl create service externalname "$svc" --external-name error-page.kong.svc.cluster.local -n "$ns" --dry-run=client -o yaml | kubectl apply -f -
    fi
}

# Check known optional services
ensure_fallback_service "gis" "geonode"
ensure_fallback_service "gis" "nodeodm"
ensure_fallback_service "databases" "pgadmin"
# ensure_fallback_service "gitea" "gitea-http" # Usually installed


# 3. Ingress for Root Path (Portal)
# The Portal stays on the root domain (e.g. localhost) for easy access, 
# or could be portal.${DRUPPIE_DOMAIN}. For now, let's keep it root or ${DRUPPIE_DOMAIN} if not localhost.
# The logic below allows http://<DRUPPIE_DOMAIN>/ to hit the portal.

log "Configuring Portal Ingress (Root)..."
cat <<EOF | kubectl apply -f -
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: portal-ingress
  namespace: kong
spec:
  ingressClassName: kong
  rules:
  # Primary Domain (e.g. localhost or example.com)
  - host: ${DRUPPIE_DOMAIN}
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: portal
            port:
              number: 80
  # Fallback for explicit localhost if domain is something else but user is local
  - host: localhost
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: portal
            port:
              number: 80
EOF

log_history "Ingress Rules & Portal Applied"

# Force portal reload to pick up HTML changes
log "Reloader Portal Deployment..."
kubectl rollout restart deployment/portal -n kong

# Success Message
echo -e "${COLOR_GREEN}"
echo "✅  Subdomain Ingress Configured!"
echo "---------------------------------"
echo "Domain: ${DRUPPIE_DOMAIN}"
echo "Service URLs:"
echo " - Portal:        http://${DRUPPIE_DOMAIN}/"
echo " - Keycloak:      http://keycloak.${DRUPPIE_DOMAIN}/"
echo " - Gitea:         http://gitea.${DRUPPIE_DOMAIN}/"
echo " - MinIO:         http://minio.${DRUPPIE_DOMAIN}/"
echo " - pgAdmin:       http://pgadmin.${DRUPPIE_DOMAIN}/"
echo " - GeoServer:     http://geoserver.${DRUPPIE_DOMAIN}/geoserver/"
echo " - NodeODM:       http://nodeodm.${DRUPPIE_DOMAIN}/"
echo " - GeoNode:       http://geonode.${DRUPPIE_DOMAIN}/"
echo " - Grafana:       http://grafana.${DRUPPIE_DOMAIN}/"
echo " - Rancher:       http://rancher.${DRUPPIE_DOMAIN}/"
echo " - Kong Mgr:      http://kong.${DRUPPIE_DOMAIN}/"
echo " - Kong Admin:    http://api.${DRUPPIE_DOMAIN}/"
echo ""
echo -e "${COLOR_NC}"
