#!/usr/bin/env bash
#
# vault-setup.sh — idempotent setup of HashiCorp Vault (dev mode) +
# External Secrets Operator (ESO) on the local k3s cluster.
#
# Automates steps 1-4 of the Vault/ESO install:
#   1. Install Vault (dev mode, in-memory) with a freshly generated root token
#   2. Configure KV v2 secrets engine + seed initial secrets + eso-read policy + k8s auth role
#   3. Install External Secrets Operator (with CRDs)
#   4. Apply the vault-backend ClusterSecretStore
#
# Safe to re-run: helm/kubectl steps are idempotent. Credentials are persisted
# to a gitignored file (see below) and reused on re-run, so password-backed
# stateful workloads (Postgres, Harbor) keep working across runs.
#
# Credentials are GENERATED at install time — none are committed to the repo.
# They are written to ${SECRETS_FILE} (default .vault-setup-secrets.env, mode
# 600, gitignored) and reused automatically next run. Override any value by
# exporting it first: VAULT_DEV_ROOT_TOKEN, HARBOR_ADMIN_PASSWORD.
#
# NOTE: Vault runs in DEV MODE — storage is in-memory. Restarting the vault-0
# pod (or the node) wipes all secrets. Re-run this script to re-seed.
#
# Usage:  ./k8s/vault-setup.sh

set -euo pipefail

# ---- Required env -----------------------------------------------------------
export KUBECONFIG="${KUBECONFIG:-$HOME/.kube/config}"

# Resolve repo root from script location (k8s/vault-setup.sh -> repo root).
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

VAULT_NS="vault"
ESO_NS="external-secrets"
VAULT_POD="vault-0"

log() { printf '\n\033[1m[%s]\033[0m %s\n' "$(date +%H:%M:%S)" "$*"; }

# ---- Pre-flight -------------------------------------------------------------
command -v kubectl >/dev/null || { echo "kubectl not found"; exit 1; }
command -v helm    >/dev/null || { echo "helm not found";    exit 1; }
command -v openssl >/dev/null || { echo "openssl not found"; exit 1; }
kubectl get nodes >/dev/null 2>&1 || { echo "cluster unreachable (KUBECONFIG=$KUBECONFIG)"; exit 1; }

# ---- Generate / load credentials (never committed) --------------------------
# Secrets persist to a gitignored, mode-600 file so re-runs reuse the SAME
# values. This matters: Postgres/Harbor set their password only on first init
# from a persistent volume — re-seeding a fresh password while the volume lives
# would lock the app out. Precedence: explicit env var > saved file > new random.
SECRETS_FILE="${SECRETS_FILE:-${REPO_ROOT}/.vault-setup-secrets.env}"
umask 077
# shellcheck disable=SC1090
[ -f "${SECRETS_FILE}" ] && . "${SECRETS_FILE}"

# Alnum-only passwords avoid '/ + =' breaking shell/env/URL/Postgres/Harbor use.
rand_pw() { openssl rand -base64 24 | tr -dc 'A-Za-z0-9'; }
VAULT_DEV_ROOT_TOKEN="${VAULT_DEV_ROOT_TOKEN:-$(openssl rand -hex 16)}"
HARBOR_ADMIN_PASSWORD="${HARBOR_ADMIN_PASSWORD:-$(rand_pw)}"

cat > "${SECRETS_FILE}" <<EOF
VAULT_DEV_ROOT_TOKEN=${VAULT_DEV_ROOT_TOKEN}
HARBOR_ADMIN_PASSWORD=${HARBOR_ADMIN_PASSWORD}
EOF

# ---- 1. Helm repos ----------------------------------------------------------
log "Adding Helm repos"
helm repo add hashicorp       https://helm.releases.hashicorp.com 2>/dev/null || true
helm repo add external-secrets https://charts.external-secrets.io 2>/dev/null || true
helm repo update >/dev/null

# ---- 2. Install Vault (dev mode) --------------------------------------------
log "Installing Vault (dev mode)"
kubectl create namespace "${VAULT_NS}" 2>/dev/null || true
helm upgrade --install vault hashicorp/vault -n "${VAULT_NS}" \
  -f "${REPO_ROOT}/helm/vault/values.yaml" \
  --set server.dev.enabled=true \
  --set server.dev.devRootToken="${VAULT_DEV_ROOT_TOKEN}" \
  --set injector.enabled=false \
  --set server.resources.requests.memory=256Mi \
  --set server.resources.requests.cpu=100m \
  --wait

log "Waiting for ${VAULT_POD} to be Ready"
kubectl wait --for=condition=ready pod -l app.kubernetes.io/name=vault \
  -n "${VAULT_NS}" --timeout=120s

log "Vault status"
kubectl exec -n "${VAULT_NS}" "${VAULT_POD}" -- vault status || true

# ---- 3. Configure KV v2 + seed secrets --------------------------------------
log "Enabling KV v2 at secret/ (ignored if already enabled)"
kubectl exec -n "${VAULT_NS}" "${VAULT_POD}" -- vault secrets enable -path=secret kv-v2 2>/dev/null || true

log "Seeding initial secrets (3-layer model)"
# Layer 1 — CI/CD Harbor credentials (password generated, never committed)
kubectl exec -n "${VAULT_NS}" "${VAULT_POD}" -- vault kv put secret/ci/harbor \
  username=admin password="${HARBOR_ADMIN_PASSWORD}" >/dev/null
# Layer 3 — Cluster static config
kubectl exec -n "${VAULT_NS}" "${VAULT_POD}" -- vault kv put secret/cluster/config \
  registry_url=localhost:30010 llm_base_url="" vault_addr=http://vault.vault.svc.cluster.local:8200 >/dev/null
# Backend LLM keys
kubectl exec -n "${VAULT_NS}" "${VAULT_POD}" -- vault kv put secret/backend/llm \
  zai_api_key="" deepinfra_api_key="" llm_provider="zai" >/dev/null
# Layer 2 — per-developer secrets (example for 'admin')
kubectl exec -n "${VAULT_NS}" "${VAULT_POD}" -- vault kv put secret/developers/admin \
  ssh_private_key="" zai_api_key="" git_remote_url="" >/dev/null

# ---- 4. Vault policy + Kubernetes auth --------------------------------------
log "Writing eso-read policy"
kubectl exec -i -n "${VAULT_NS}" "${VAULT_POD}" -- vault policy write eso-read - <<'EOF'
path "secret/data/*" {
  capabilities = ["read"]
}
path "secret/metadata/*" {
  capabilities = ["list", "read"]
}
EOF

log "Enabling + configuring Kubernetes auth"
kubectl exec -n "${VAULT_NS}" "${VAULT_POD}" -- vault auth enable kubernetes 2>/dev/null || true
kubectl exec -n "${VAULT_NS}" "${VAULT_POD}" -- sh -c \
  'vault write auth/kubernetes/config kubernetes_host="https://$KUBERNETES_PORT_443_TCP_ADDR:443"'
kubectl exec -n "${VAULT_NS}" "${VAULT_POD}" -- vault write auth/kubernetes/role/external-secrets \
  bound_service_account_names=external-secrets \
  bound_service_account_namespaces=external-secrets \
  policies=eso-read ttl=1h

# ---- 5. Install External Secrets Operator -----------------------------------
log "Installing External Secrets Operator"
helm upgrade --install external-secrets external-secrets/external-secrets \
  -n "${ESO_NS}" --create-namespace --set installCRDs=true --wait

log "Waiting for ESO pods to be Ready"
kubectl wait --for=condition=ready pod -l app.kubernetes.io/name=external-secrets \
  -n "${ESO_NS}" --timeout=120s

# ---- 6. ClusterSecretStore --------------------------------------------------
log "Applying vault-backend ClusterSecretStore"
kubectl apply -f "${REPO_ROOT}/k8s/vault-secret-store.yaml"

log "Validating ClusterSecretStore"
kubectl get clustersecretstore vault-backend

# ---- Summary ----------------------------------------------------------------
log "Done. Generated credentials saved (mode 600, gitignored — Vault dev mode is in-memory):"
echo "  ${SECRETS_FILE}"
echo "  Re-runs reuse these values automatically. Keep this file safe."

log "Verify with:"
echo "  kubectl get clustersecretstore vault-backend                    # STATUS=Valid"
echo "  kubectl get externalsecret -n druppie                          # STATUS=SecretSynced"
echo "  kubectl get externalsecret -n harbor harbor-admin              # STATUS=SecretSynced"
echo "  kubectl get secret harbor-creds -n druppie -o jsonpath='{.data}'"
