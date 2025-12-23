#!/bin/bash

# Druppie Observability Setup
# Installs the LGTM Stack (Loki, Grafana, Tempo, Mimir/Prometheus)

set -e

COLOR_GREEN='\033[0;32m'
COLOR_BLUE='\033[0;34m'
COLOR_NC='\033[0m'

LOG_FILE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/../.druppie_history"

function log() {
    echo -e "${COLOR_BLUE}[SETUP]${COLOR_NC} $1"
}

function log_history() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') | SETUP     | Observability | $1" >> "$LOG_FILE"
}

# 1. Check Connectivity
log "Checking Kubernetes Connection..."
if ! kubectl cluster-info &> /dev/null; then
    echo "❌ Cannot connect to Kubernetes."
    exit 1
fi

# 2. Add Repos
log "Adding Helm Repositories..."
helm repo add grafana https://grafana.github.io/helm-charts
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo up

# 3. Install Prometheus (Metrics)
log "Installing Prometheus..."
helm upgrade --install prometheus prometheus-community/prometheus \
  --namespace observability --create-namespace \
  --set alertmanager.enabled=false \
  --set server.persistentVolume.size=5Gi \
  --wait
log_history "Prometheus Installed"

# 4. Install Loki (Logs) - Single Binary
log "Installing Loki (Single Binary)..."
helm upgrade --install loki grafana/loki \
  --namespace observability --create-namespace \
  --set deploymentMode=SingleBinary \
  --set loki.auth_enabled=false \
  --set loki.commonConfig.replication_factor=1 \
  --set loki.storage.type=filesystem \
  --set singleBinary.replicas=1 \
  --set read.replicas=0 \
  --set backend.replicas=0 \
  --set write.replicas=0 \
  --set loki.useTestSchema=true \
  --wait
log_history "Loki Installed"

# 4b. Install Alloy (Log Collector - Replaces Promtail)
log "Installing Alloy (Log Collector)..."
helm upgrade --install alloy grafana/alloy \
  --namespace observability --create-namespace \
  --set alloy.configMap.content="
    logging {
      level = \"info\"
      format = \"logfmt\"
    }

    loki.write \"default\" {
      endpoint {
        url = \"http://loki-gateway.observability.svc.cluster.local/loki/api/v1/push\"
      }
    }

    loki.source.kubernetes \"pods\" {
      targets = discovery.kubernetes.pods.targets
      forward_to = [loki.write.default.receiver]
    }

    discovery.kubernetes \"pods\" {
      role = \"pod\"
    }
    
    loki.source.kubernetes_events \"cluster_events\" {
      job_name   = \"integrations/kubernetes/eventhandler\"
      log_format = \"logfmt\"
      forward_to = [loki.write.default.receiver]
    }
  " \
  --wait
log_history "Alloy Installed"

# 5. Install Tempo (Tracing - optional/lightweight)
log "Installing Tempo..."
helm upgrade --install tempo grafana/tempo \
  --namespace observability --create-namespace \
  --set persistence.enabled=false \
  --wait
log_history "Tempo Installed"

# 6. Install Grafana (Dashboarding)
log "Installing Grafana..."

# Create values file for datasources
cat <<EOF > /tmp/grafana-values.yaml
datasources:
  datasources.yaml:
    apiVersion: 1
    datasources:
    - name: Prometheus
      type: prometheus
      url: http://prometheus-server.observability.svc.cluster.local
      access: proxy
      isDefault: true
    - name: Loki
      type: loki
      url: http://loki-gateway.observability.svc.cluster.local
      access: proxy
      jsonData:
        derivedFields:
          - datasourceUid: Tempo
            matcherRegex: "traceID=(\\w+)"
            name: TraceID
            url: "\$${__value.raw}"
    - name: Tempo
      type: tempo
      url: http://tempo.observability.svc.cluster.local:3100
      access: proxy
EOF

helm upgrade --install grafana grafana/grafana \
  --namespace observability --create-namespace \
  --set adminPassword=${DRUPPIE_GRAFANA_PASS} \
  --set service.type=ClusterIP \
  --set "grafana\.ini.server.root_url=http://grafana.${DRUPPIE_DOMAIN}/" \
  --set "grafana\.ini.server.serve_from_sub_path=false" \
  --set persistence.enabled=true \
  --set persistence.size=2Gi \
  -f /tmp/grafana-values.yaml

rm /tmp/grafana-values.yaml

log "Waiting for Grafana to be ready..."
kubectl rollout status deployment/grafana -n observability --timeout=300s
log "Waiting for Grafana Health Check (internal port 3000)..."
for i in {1..30}; do
  if kubectl exec -n observability deploy/grafana -- curl -s -f http://localhost:3000/api/health >/dev/null 2>&1; then
    echo "Grafana is Healthy!"
    break
  fi
  echo "Waiting for Grafana API..."
  sleep 5
done
log_history "Grafana Installed"

# 7. Success
echo -e "${COLOR_GREEN}"
echo "✅  Observability Stack (LGTM) Installed!"
echo "---------------------------------------"
echo " - Grafana:   http://grafana.observability.svc.cluster.local:80"
echo "   User:      admin"
echo "   Pass:      ${DRUPPIE_GRAFANA_PASS}"
echo "   Data:      Prometheus (Metrics), Loki (Logs), Tempo (Traces)"
echo ""
echo "⚠️  Note: Port-forward to access locally:"
echo "   kubectl port-forward svc/grafana -n observability 3000:80"
echo -e "${COLOR_NC}"
