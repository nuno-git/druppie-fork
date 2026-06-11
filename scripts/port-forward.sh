#!/usr/bin/env bash
set -euo pipefail

# NOTE: This is for debugging only. The recommended way is via Ingress.
# Ensure ingress is enabled: global.ingress.enabled=true
# Then add to /etc/hosts: 127.0.0.1 druppie.localhost api.druppie.localhost auth.druppie.localhost git.druppie.localhost

NAMESPACE="druppie"

echo "=== Druppie Port-Forward (debug only — use Ingress for normal access) ==="
echo ""
echo "  Backend:    http://localhost:8000"
echo "  Frontend:   http://localhost:5173"
echo "  Keycloak:   http://localhost:8080"
echo "  Gitea:      http://localhost:3000"
echo ""
echo "Press Ctrl+C to stop."
echo ""

cleanup() { kill $(jobs -p) 2>/dev/null; }
trap cleanup EXIT

kubectl port-forward -n "$NAMESPACE" svc/druppie-backend 8000:8000 &
kubectl port-forward -n "$NAMESPACE" svc/druppie-frontend 5173:5173 &
kubectl port-forward -n "$NAMESPACE" svc/druppie-keycloak 8080:8080 &
kubectl port-forward -n "$NAMESPACE" svc/druppie-gitea 3000:3000 &

wait
