#!/bin/bash
set -e

# Druppie Core Installer
# Installs the main application logic (Druppie Core) via Helm

# Context Checks
if [ -z "$DRUPPIE_DOMAIN" ]; then
    echo "Error: DRUPPIE_DOMAIN is not set. Please source .secrets or run via druppie.sh"
    exit 1
fi

echo "Deploying Druppie Core to Kubernetes..."

# Path to the Helm chart and Core Source
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CHART_PATH="$SCRIPT_DIR/../core/deploy/helm"
CORE_DIR="$SCRIPT_DIR/../core"

# 1. Build Docker Image
echo "Building Druppie Core Docker Image..."
if ! command -v docker &> /dev/null; then
    echo "Error: Docker not found. Cannot build image."
    exit 1
fi
docker build -t druppie-core:latest "$CORE_DIR"

# 2. Import into k3d (if running locally on k3d)
# We use the cluster name from env or default
K3D_CLUSTER_NAME="${DRUPPIE_CLUSTER_NAME:-druppie-dev}"

if command -v k3d &> /dev/null; then
    if k3d cluster list | grep -q "$K3D_CLUSTER_NAME"; then
        echo "Importing image into k3d cluster '$K3D_CLUSTER_NAME'..."
        k3d image import druppie-core:latest -c "$K3D_CLUSTER_NAME"
    else
        echo "k3d installed but cluster '$K3D_CLUSTER_NAME' not found. Skipping import (assuming remote or other setup)."
    fi
else
    echo "k3d not found. Skipping image import."
fi

echo "Deploying Druppie Core to Kubernetes..."

# Install/Upgrade the Helm chart
# We use 'upgrade --install' to ensure idempotency
helm upgrade --install druppie-core "$CHART_PATH" \
  --namespace druppie \
  --create-namespace \
  --set ingress.host="$DRUPPIE_DOMAIN" \
  --wait
  # Note: values.yaml defaults to pullPolicy: IfNotPresent, which works with the pre-loaded image.

echo "✅ Druppie Core deployed successfully!"
