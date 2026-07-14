#!/usr/bin/env bash
#
# deploy-branch-env.sh — bring up a full, isolated Druppie instance for a git
# branch in its own namespace on the rijnland.dev RKE2 cluster.
#
# It layers branch-specific overrides on top of the base + rijnland Helm values:
#   namespace  druppie-<branch-slug>
#   host       druppie-<branch-slug>.rijnland.dev   (single label -> *.rijnland.dev cert)
#   node pin   a dedicated worker (RWO shared PVCs require co-location on one node)
#
# The wildcard *.rijnland.dev TLS secret is copied from the source namespace
# (default: druppie) into the new namespace, since TLS secrets are namespace-scoped.
#
# Usage:
#   ./scripts/deploy-branch-env.sh <branch> [-f extra-values.yaml] [--dry-run]
#
# Env overrides:
#   BRANCH_ENV_NODE        worker node to pin to   (default: ka-k8s-ai-workers-skbh7-d4qwl)
#   BRANCH_ENV_IMAGE_TAG   image tag for ALL components (default: chart default, i.e. latest)
#   BRANCH_ENV_REGISTRY    override global.imageRegistry (default: harbor.rijnland.dev/druppie)
#   BRANCH_ENV_TLS_SRC_NS  namespace to copy the TLS secret from (default: druppie)
#   BRANCH_ENV_TLS_SECRET  TLS secret name (default: druppie-tls)
#   BRANCH_ENV_PULL_SECRET        image pull secret name to copy in (default: harbor-regcred; empty to skip)
#   BRANCH_ENV_PULL_SECRET_SRC_NS namespace to copy the pull secret from (default: druppie)
#
# Requires: kubectl (pointed at the target cluster), helm, bash, base64.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CHART_DIR="${REPO_ROOT}/helm/druppie"

NODE="${BRANCH_ENV_NODE:-ka-k8s-ai-workers-skbh7-d4qwl}"
IMAGE_TAG="${BRANCH_ENV_IMAGE_TAG:-}"
REGISTRY="${BRANCH_ENV_REGISTRY:-harbor.rijnland.dev/druppie}"
TLS_SRC_NS="${BRANCH_ENV_TLS_SRC_NS:-druppie}"
TLS_SECRET="${BRANCH_ENV_TLS_SECRET:-druppie-tls}"
PULL_SECRET="${BRANCH_ENV_PULL_SECRET:-harbor-regcred}"
PULL_SECRET_SRC_NS="${BRANCH_ENV_PULL_SECRET_SRC_NS:-druppie}"

# Modules that mount a shared RWO PVC and must co-locate with the backend.
PINNED_MODULES=(coding docker archimate data_access filesearch web)
# All deployable components (used when overriding image tags for a branch build).
ALL_MODULES=(coding docker filesearch web archimate registry llm kubernetes vision data_access layout_service)

usage() {
  echo "usage: $0 <branch> [-f extra-values.yaml] [--dry-run]" >&2
  exit 2
}

BRANCH=""
DRY_RUN=()
EXTRA_VALUES=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run) DRY_RUN=(--dry-run); shift ;;
    -f|--values) EXTRA_VALUES+=(-f "$2"); shift 2 ;;
    -h|--help) usage ;;
    -*) echo "unknown flag: $1" >&2; usage ;;
    *) if [[ -z "$BRANCH" ]]; then BRANCH="$1"; shift; else echo "unexpected arg: $1" >&2; usage; fi ;;
  esac
done
[[ -n "$BRANCH" ]] || usage

# Sanitize branch -> DNS-1123 label (lowercase, [a-z0-9-], no leading/trailing dash).
SLUG="$(printf '%s' "$BRANCH" \
  | tr '[:upper:]' '[:lower:]' \
  | tr -c 'a-z0-9' '-' \
  | sed -e 's/-\{2,\}/-/g' -e 's/^-//' -e 's/-$//')"
[[ -n "$SLUG" ]] || { echo "branch '$BRANCH' produced an empty slug" >&2; exit 1; }

NS="druppie-${SLUG}"
HOST="druppie-${SLUG}.rijnland.dev"
# code-server IDE subdomain (behind oauth2-proxy). Single label under rijnland.dev.
DEV_HOST="druppie-${SLUG}-dev.rijnland.dev"

# Host must stay a single label under rijnland.dev to match the *.rijnland.dev cert.
if [[ "${HOST%.rijnland.dev}" == *.* ]]; then
  echo "refusing: host '$HOST' is not a single label under rijnland.dev" >&2
  exit 1
fi
# Namespace must be a valid DNS-1123 label (<=63 chars).
if (( ${#NS} > 63 )); then
  echo "refusing: namespace '$NS' exceeds 63 chars" >&2
  exit 1
fi

echo "==> Branch:    $BRANCH"
echo "==> Namespace: $NS"
echo "==> Host:      https://$HOST"
echo "==> Dev IDE:   https://$DEV_HOST"
echo "==> Node pin:  $NODE"
echo "==> Context:   $(kubectl config current-context)"

is_dry_run() { [[ ${#DRY_RUN[@]} -gt 0 ]]; }

# 1. Namespace
if ! kubectl get namespace "$NS" >/dev/null 2>&1; then
  echo "==> Creating namespace $NS"
  is_dry_run || kubectl create namespace "$NS"
fi

# 2. Copy the wildcard TLS secret into the target namespace (idempotent).
# Use real temp files (not process substitution): Windows kubectl.exe cannot
# read the /proc/<pid>/fd paths that <(...) produces under Git Bash/MSYS.
if ! is_dry_run; then
  echo "==> Copying TLS secret $TLS_SECRET from $TLS_SRC_NS into $NS"
  tmpdir="$(mktemp -d)"
  trap 'rm -rf "$tmpdir"' EXIT
  kubectl -n "$TLS_SRC_NS" get secret "$TLS_SECRET" -o jsonpath='{.data.tls\.crt}' | base64 -d > "$tmpdir/tls.crt"
  kubectl -n "$TLS_SRC_NS" get secret "$TLS_SECRET" -o jsonpath='{.data.tls\.key}' | base64 -d > "$tmpdir/tls.key"
  [[ -s "$tmpdir/tls.crt" && -s "$tmpdir/tls.key" ]] || { echo "TLS secret $TLS_SECRET in $TLS_SRC_NS has no tls.crt/tls.key" >&2; exit 1; }
  kubectl create secret tls "$TLS_SECRET" -n "$NS" \
    --cert="$tmpdir/tls.crt" \
    --key="$tmpdir/tls.key" \
    --dry-run=client -o yaml | kubectl apply -f -
fi

# 2b. Copy the Harbor image pull secret into the target namespace (idempotent).
if [[ -n "$PULL_SECRET" ]] && ! is_dry_run; then
  echo "==> Copying image pull secret $PULL_SECRET from $PULL_SECRET_SRC_NS into $NS"
  dockercfg="$(kubectl -n "$PULL_SECRET_SRC_NS" get secret "$PULL_SECRET" -o jsonpath='{.data.\.dockerconfigjson}' | base64 -d)"
  [[ -n "$dockercfg" ]] || { echo "pull secret $PULL_SECRET in $PULL_SECRET_SRC_NS has no .dockerconfigjson" >&2; exit 1; }
  kubectl create secret generic "$PULL_SECRET" -n "$NS" \
    --type=kubernetes.io/dockerconfigjson \
    --from-literal=.dockerconfigjson="$dockercfg" \
    --dry-run=client -o yaml | kubectl apply -f -
fi

# 3. Helm install/upgrade
HELM_ARGS=(
  upgrade --install druppie "$CHART_DIR"
  --namespace "$NS" --create-namespace
  -f "${CHART_DIR}/values.yaml"
  -f "${CHART_DIR}/values-rijnland.yaml"
  --set "global.instance=${NS}"
  --set "global.domain=${HOST}"
  # Branch envs are reached via Traefik ingress, not NodePort. Request ClusterIP
  # so they don't grab cluster-global NodePorts already held by the live instance.
  --set "backend.service.type=ClusterIP"
  --set "frontend.service.type=ClusterIP"
  --set "keycloak.service.type=ClusterIP"
  --set "gitea.service.type=ClusterIP"
  --set "backend.nodeSelector.kubernetes\.io/hostname=${NODE}"
  # Dev workspace: the branch namespace IS the hot-reloading workspace. The
  # baked backend/frontend Deployments are skipped; <instance>-backend /
  # <instance>-frontend Services route to the workspace pod instead.
  --set "devWorkspace.enabled=true"
  --set "devWorkspace.stackMode=real"
  --set "devWorkspace.gitBranch=${BRANCH}"
  --set "devWorkspace.codeServer.devHost=${DEV_HOST}"
  --set "devWorkspace.oauth.issuerUrl=https://${HOST}/realms/druppie"
  --set "devWorkspace.nodeSelector.kubernetes\.io/hostname=${NODE}"
)
for m in "${PINNED_MODULES[@]}"; do
  HELM_ARGS+=(--set "modules.${m}.nodeSelector.kubernetes\.io/hostname=${NODE}")
done
[[ -n "$REGISTRY" ]] && HELM_ARGS+=(--set "global.imageRegistry=${REGISTRY}")
[[ -n "$PULL_SECRET" ]] && HELM_ARGS+=(--set "global.imagePullSecrets[0].name=${PULL_SECRET}")
if [[ -n "$IMAGE_TAG" ]]; then
  HELM_ARGS+=(--set "backend.image.tag=${IMAGE_TAG}" \
              --set "frontend.image.tag=${IMAGE_TAG}" \
              --set "init.image.tag=${IMAGE_TAG}")
  for m in "${ALL_MODULES[@]}"; do
    HELM_ARGS+=(--set "modules.${m}.image.tag=${IMAGE_TAG}")
  done
fi
HELM_ARGS+=("${EXTRA_VALUES[@]}")
HELM_ARGS+=("${DRY_RUN[@]}")
is_dry_run || HELM_ARGS+=(--wait --timeout 10m)

echo "==> helm ${HELM_ARGS[*]}"
helm "${HELM_ARGS[@]}"

if ! is_dry_run; then
  echo "==> Done. Environment for '$BRANCH' is at https://$HOST (namespace $NS)"
  echo "    kubectl -n $NS get pods"
fi
