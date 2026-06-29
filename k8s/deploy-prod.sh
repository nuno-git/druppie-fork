#!/usr/bin/env bash
set -euo pipefail

export KUBECONFIG="${KUBECONFIG:-$HOME/.kube/config}"

echo "Creating namespaces..."
kubectl apply -f k8s/namespaces.yaml

echo "Applying namespace NetworkPolicy baseline..."
kubectl apply -f k8s/networkpolicies.yaml

echo "Deploying to druppie-prod..."
helm upgrade --install druppie-prod ./helm/druppie \
  -n druppie-prod \
  -f helm/druppie/values.yaml \
  -f helm/druppie/values-prod.yaml \
  --set backend.image.repository=localhost:30010/druppie/druppie-backend \
  --set backend.image.tag=latest \
  --set frontend.image.repository=localhost:30010/druppie/druppie-frontend \
  --set frontend.image.tag=latest

echo "Deploying to druppie-colab-dev..."
helm upgrade --install druppie-dev ./helm/druppie \
  -n druppie-colab-dev \
  -f helm/druppie/values.yaml \
  --set backend.image.repository=localhost:30010/druppie/druppie-backend \
  --set backend.image.tag=latest \
  --set frontend.image.repository=localhost:30010/druppie/druppie-frontend \
  --set frontend.image.tag=latest \
  --set backend.devMode=true

echo "Done. Check: kubectl get pods -n druppie-prod"
