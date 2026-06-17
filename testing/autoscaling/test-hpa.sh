#!/usr/bin/env bash
# -----------------------------------------------------------------------------
# test-hpa.sh — HPA smoke test for druppie-kubernetes
#
# Quick test (under 5 minutes) that verifies HPA scale-up and scale-down
# for a given component (backend or frontend).
#
# Usage:
#   ./test-hpa.sh [--namespace NS] [--component backend|frontend] [--timeout SECONDS]
#
# Defaults:  namespace=druppie  component=backend  timeout=300
#
# Exit codes:
#   0  Both scale-up and scale-down passed
#   1  Scale-up failed
#   2  Scale-up passed but scale-down failed
# -----------------------------------------------------------------------------

set -euo pipefail

# ---------------------------------------------------------------------------
# Resolve paths & source common library
# ---------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
source "${SCRIPT_DIR}/lib/common.sh"

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
COMPONENT="backend"
TIMEOUT=300
RELEASE_NAME="${RELEASE_NAME:-druppie}"
LOAD_POD_NAME="hpa-test-load"
LOAD_REPLICAS=5

# ---------------------------------------------------------------------------
# CLI argument parsing
# ---------------------------------------------------------------------------
usage() {
  cat <<EOF
Usage: $(basename "$0") [OPTIONS]

Options:
  --namespace NS         Kubernetes namespace          (default: ${NAMESPACE})
  --component COMP       Component to test: backend|frontend  (default: ${COMPONENT})
  --timeout SECONDS      Scale-up timeout in seconds   (default: ${TIMEOUT})
  -h, --help             Show this help message
EOF
  exit 0
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --namespace)
      NAMESPACE="$2"
      shift 2
      ;;
    --component)
      COMPONENT="$2"
      shift 2
      ;;
    --timeout)
      TIMEOUT="$2"
      shift 2
      ;;
    -h|--help)
      usage
      ;;
    *)
      log_fail "Unknown argument: $1"
      usage
      ;;
  esac
done

# Derive HPA name, service port, and target endpoint
HPA_NAME="${RELEASE_NAME}-${COMPONENT}"
case "${COMPONENT}" in
  backend)  PORT=8000; ENDPOINT="/api/sessions" ;;
  frontend) PORT=5173; ENDPOINT="/" ;;
  *)
    log_fail "Unknown component '${COMPONENT}'. Must be 'backend' or 'frontend'."
    exit 1
    ;;
esac

SCALE_DOWN_TIMEOUT=$(( TIMEOUT * 2 ))

# ---------------------------------------------------------------------------
# Cleanup on exit
# ---------------------------------------------------------------------------
cleanup() {
  local exit_code=$?
  cleanup_load_generator "${NAMESPACE}" "${LOAD_POD_NAME}" 2>/dev/null || true
  exit "${exit_code}"
}
trap cleanup EXIT

# ---------------------------------------------------------------------------
# Helper: print a polling status line
# ---------------------------------------------------------------------------
poll_status_line() {
  local ns="$1"
  local hpa="$2"
  printf "  %s | Replicas: %s | CPU: %s%% | Nodes: %s\n" \
    "$(date +%H:%M:%S)" \
    "$(get_hpa_replicas "${ns}" "${hpa}")" \
    "$(get_hpa_cpu "${ns}" "${hpa}")" \
    "$(get_worker_node_count)"
}

# ---------------------------------------------------------------------------
# Helper: deploy N load generator pods as a deployment
# ---------------------------------------------------------------------------
deploy_load_generators() {
  local ns="$1"
  local name="$2"
  local replicas="$3"
  local target_url="$4"

  kubectl delete deployment "${name}" --namespace "${ns}" --ignore-not-found=true >/dev/null 2>&1 || true

  kubectl apply -f - <<MANIFEST >/dev/null
apiVersion: apps/v1
kind: Deployment
metadata:
  name: ${name}
  namespace: ${ns}
  labels:
    app: ${name}
    test: hpa-load-generator
spec:
  replicas: ${replicas}
  selector:
    matchLabels:
      app: ${name}
  template:
    metadata:
      labels:
        app: ${name}
        test: hpa-load-generator
    spec:
      containers:
        - name: loader
          image: ${LOAD_GENERATOR_IMAGE}
          command: ["/bin/sh", "-c"]
          args:
            - |
              while true; do
                wget -q -O /dev/null ${target_url} 2>/dev/null || true
              done
          resources:
            requests:
              cpu: "50m"
              memory: "32Mi"
MANIFEST
}

remove_load_generators() {
  local ns="$1"
  local name="$2"
  kubectl delete deployment "${name}" --namespace "${ns}" --ignore-not-found=true >/dev/null 2>&1 || true
}

# ---------------------------------------------------------------------------
# Test execution
# ---------------------------------------------------------------------------
START_TIME="$(date '+%Y-%m-%d %H:%M:%S')"

printf "\n=== HPA Smoke Test ===\n"
printf "Component: %s\n" "${COMPONENT}"
printf "Namespace: %s\n" "${NAMESPACE}"
printf "Start:     %s\n\n" "${START_TIME}"

# --- [1/5] Pre-flight checks ---
printf "[1/5] Pre-flight checks...\n"
assert_hpa_exists "${NAMESPACE}" "${HPA_NAME}"
printf "  ✅ HPA found: %s\n" "${HPA_NAME}"

assert_metrics_server
printf "  ✅ Metrics server running\n"

# --- [2/5] Record baseline ---
BASELINE_REPLICAS="$(get_hpa_replicas "${NAMESPACE}" "${HPA_NAME}")"
BASELINE_NODES="$(get_worker_node_count)"

printf "\n[2/5] Baseline: %s replicas, %s worker nodes\n" \
  "${BASELINE_REPLICAS}" "${BASELINE_NODES}"

# --- [3/5] Start load generator & wait for scale-up ---
TARGET_URL="http://${HPA_NAME}.${NAMESPACE}.svc.cluster.local:${PORT}${ENDPOINT}"

printf "\n[3/5] Starting %d load generators → %s\n" "${LOAD_REPLICAS}" "${TARGET_URL}"

deploy_load_generators "${NAMESPACE}" "${LOAD_POD_NAME}" "${LOAD_REPLICAS}" "${TARGET_URL}"

sleep 10

printf "  ⏳ Waiting for scale-up (%ds timeout)...\n" "${TIMEOUT}"

SCALE_UP_OK=false
SCALE_UP_ELAPSED=0
PEAK_REPLICAS="${BASELINE_REPLICAS}"
SCALE_UP_START="$(date +%s)"

while (( SCALE_UP_ELAPSED < TIMEOUT )); do
  CURRENT_REPLICAS="$(get_hpa_replicas "${NAMESPACE}" "${HPA_NAME}")" || CURRENT_REPLICAS="${BASELINE_REPLICAS}"
  if (( CURRENT_REPLICAS > PEAK_REPLICAS )); then
    PEAK_REPLICAS="${CURRENT_REPLICAS}"
  fi
  poll_status_line "${NAMESPACE}" "${HPA_NAME}"

  if (( CURRENT_REPLICAS > BASELINE_REPLICAS )); then
    SCALE_UP_OK=true
    break
  fi

  sleep "${POLL_INTERVAL}"
  SCALE_UP_ELAPSED=$(( $(date +%s) - SCALE_UP_START ))
done

SCALE_UP_SECONDS=$(( $(date +%s) - SCALE_UP_START ))

if [[ "${SCALE_UP_OK}" != "true" ]]; then
  printf "\n=== Results ===\n"
  printf "  Replicas: %s → %s (peak) → %s (final)\n" \
    "${BASELINE_REPLICAS}" "${PEAK_REPLICAS}" "$(get_hpa_replicas "${NAMESPACE}" "${HPA_NAME}")"
  printf "  Scale-up:   ❌ FAIL (did not scale within %ds)\n" "${TIMEOUT}"
  exit 1
fi

printf "  ✅ Scaled to %s replicas in %ds\n" "${PEAK_REPLICAS}" "${SCALE_UP_SECONDS}"

# --- [4/5] Stop load generator & wait for scale-down ---
remove_load_generators "${NAMESPACE}" "${LOAD_POD_NAME}"

printf "\n[4/5] Load generator stopped. Waiting for scale-down (%ds timeout)...\n" "${SCALE_DOWN_TIMEOUT}"

SCALE_DOWN_OK=false
SCALE_DOWN_START="$(date +%s)"

while (( $(date +%s) - SCALE_DOWN_START < SCALE_DOWN_TIMEOUT )); do
  CURRENT_REPLICAS="$(get_hpa_replicas "${NAMESPACE}" "${HPA_NAME}")" || CURRENT_REPLICAS="${PEAK_REPLICAS}"
  poll_status_line "${NAMESPACE}" "${HPA_NAME}"

  if (( CURRENT_REPLICAS <= BASELINE_REPLICAS )); then
    SCALE_DOWN_OK=true
    break
  fi

  sleep "${POLL_INTERVAL}"
done

SCALE_DOWN_SECONDS=$(( $(date +%s) - SCALE_DOWN_START ))

# --- [5/5] Results ---
FINAL_REPLICAS="$(get_hpa_replicas "${NAMESPACE}" "${HPA_NAME}")"

printf "\n=== Results ===\n"
printf "  Replicas: %s → %s (peak) → %s (final)\n" \
  "${BASELINE_REPLICAS}" "${PEAK_REPLICAS}" "${FINAL_REPLICAS}"

printf "  Scale-up:   ✅ PASS (scaled to %s in %ds)\n" \
  "${PEAK_REPLICAS}" "${SCALE_UP_SECONDS}"

if [[ "${SCALE_DOWN_OK}" == "true" ]]; then
  printf "  Scale-down: ✅ PASS (returned to %s in %ds)\n" \
    "${FINAL_REPLICAS}" "${SCALE_DOWN_SECONDS}"
  exit 0
else
  printf "  Scale-down: ❌ FAIL (did not return to %s within %ds, currently at %s)\n" \
    "${BASELINE_REPLICAS}" "${SCALE_DOWN_TIMEOUT}" "${FINAL_REPLICAS}"
  exit 2
fi
