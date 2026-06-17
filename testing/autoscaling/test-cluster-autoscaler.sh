#!/usr/bin/env bash
# -----------------------------------------------------------------------------
# test-cluster-autoscaler.sh — Cluster Autoscaler node provisioning test
#
# Verifies that the Cluster Autoscaler provisions new nodes when pods become
# unschedulable due to resource pressure on the app pool.
#
# Context:
#   - Cluster runs on Hetzner with hetzner-k3s
#   - App pool: 1-10 nodes, CPX32 (4 vCPU, 8GB), labeled pool=app
#   - Cluster Autoscaler runs in kube-system namespace
#   - Node naming: druppie-app-1, druppie-app-2, etc.
#
# Usage:
#   ./test-cluster-autoscaler.sh [OPTIONS]
#
# Options:
#   --namespace NS          Kubernetes namespace          (default: druppie)
#   --target-nodes N        Target app-pool node count    (default: 2)
#   --timeout SECONDS       Max wait per phase            (default: 600)
#   --wait-scale-down       Wait for CA to scale back down after test
#   -h, --help              Show this help message
#
# Exit codes:
#   0  All checks passed
#   1  CA not running or pre-flight failed
#   2  Nodes didn't scale up within timeout
#   3  Pods didn't schedule after node appeared
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
TARGET_NODES=2
TIMEOUT=600
WAIT_SCALE_DOWN=false
STRESS_DEPLOYMENT="ca-stress-test"
STRESS_IMAGE="registry.k8s.io/pause:3.9"
CPU_PER_POD="800m"
MEMORY_PER_POD="1Gi"

# ---------------------------------------------------------------------------
# CLI argument parsing
# ---------------------------------------------------------------------------
usage() {
  cat <<EOF
Usage: $(basename "$0") [OPTIONS]

Test Cluster Autoscaler by deploying a stress workload that exceeds current
node capacity and verifying new nodes are provisioned.

Options:
  --namespace NS          Kubernetes namespace          (default: ${NAMESPACE})
  --target-nodes N        Target app-pool node count    (default: ${TARGET_NODES})
  --timeout SECONDS       Max wait per phase            (default: ${TIMEOUT})
  --wait-scale-down       Wait for CA to scale back down after cleanup
  -h, --help              Show this help message
EOF
  exit 0
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --namespace)
      NAMESPACE="$2"
      shift 2
      ;;
    --target-nodes)
      TARGET_NODES="$2"
      shift 2
      ;;
    --timeout)
      TIMEOUT="$2"
      shift 2
      ;;
    --wait-scale-down)
      WAIT_SCALE_DOWN=true
      shift
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

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Count nodes with label pool=app
get_app_pool_nodes() {
  kubectl get nodes -l pool=app --no-headers 2>/dev/null | wc -l | tr -d ' '
}

# Count pods in a specific phase for the stress deployment
get_stress_pod_count_by_phase() {
  local phase="$1"
  kubectl get pods -l "app=${STRESS_DEPLOYMENT}" -n "${NAMESPACE}" \
    --no-headers 2>/dev/null \
    | awk -v p="$phase" '$3==p {count++} END {print count+0}'
}

# Total stress pods (any phase)
get_stress_pod_total() {
  kubectl get pods -l "app=${STRESS_DEPLOYMENT}" -n "${NAMESPACE}" \
    --no-headers 2>/dev/null | wc -l | tr -d ' '
}

# ---------------------------------------------------------------------------
# Cleanup on exit
# ---------------------------------------------------------------------------
cleanup() {
  local exit_code=$?
  log_info "Cleaning up stress deployment..."
  kubectl delete deployment "${STRESS_DEPLOYMENT}" \
    --namespace "${NAMESPACE}" \
    --ignore-not-found=true >/dev/null 2>&1 || true
  exit "${exit_code}"
}
trap cleanup EXIT

# ---------------------------------------------------------------------------
# Test execution
# ---------------------------------------------------------------------------
REPLICAS=$(( TARGET_NODES * 4 ))

printf "\n=== Cluster Autoscaler Test ===\n"
printf "Namespace:    %s\n" "${NAMESPACE}"
printf "Target nodes: %s\n" "${TARGET_NODES}"
printf "Timeout:      %ds\n\n" "${TIMEOUT}"

# --- [1/4] Pre-flight checks ---
printf "[1/4] Pre-flight checks...\n"

# Check Cluster Autoscaler deployment exists and is available
if ! kubectl get deployment cluster-autoscaler -n kube-system >/dev/null 2>&1; then
  log_fail "Cluster Autoscaler deployment not found in kube-system"
  printf "  Install or enable CA in iac/cluster.yaml:\n"
  printf "    addons.cluster_autoscaler.enabled: true\n"
  exit 1
fi

CA_REPLICAS=$(kubectl get deployment cluster-autoscaler -n kube-system \
  -o jsonpath='{.status.readyReplicas}' 2>/dev/null || echo "0")
if [[ "${CA_REPLICAS}" == "0" || -z "${CA_REPLICAS}" ]]; then
  log_fail "Cluster Autoscaler has no ready replicas"
  exit 1
fi
printf "  ✅ Cluster Autoscaler running\n"

# Record initial worker node count
INITIAL_WORKERS=$(get_worker_node_count)
INITIAL_APP_NODES=$(get_app_pool_nodes)
printf "  ✅ Initial worker nodes: %s\n" "${INITIAL_WORKERS}"
printf "  ✅ Initial app-pool nodes: %s\n" "${INITIAL_APP_NODES}"

# --- [2/4] Deploy stress workload ---
printf "\n[2/4] Deploying stress workload (%d pods, %s CPU each)...\n" \
  "${REPLICAS}" "${CPU_PER_POD}"

# Remove any leftover deployment from a previous run
kubectl delete deployment "${STRESS_DEPLOYMENT}" \
  --namespace "${NAMESPACE}" \
  --ignore-not-found=true >/dev/null 2>&1 || true

# Deploy the stress deployment via heredoc
kubectl apply -f - <<EOF >/dev/null
apiVersion: apps/v1
kind: Deployment
metadata:
  name: ${STRESS_DEPLOYMENT}
  namespace: ${NAMESPACE}
  labels:
    app: ${STRESS_DEPLOYMENT}
    test: cluster-autoscaler
spec:
  replicas: ${REPLICAS}
  selector:
    matchLabels:
      app: ${STRESS_DEPLOYMENT}
  template:
    metadata:
      labels:
        app: ${STRESS_DEPLOYMENT}
        test: cluster-autoscaler
    spec:
      nodeSelector:
        pool: app
      containers:
        - name: pause
          image: ${STRESS_IMAGE}
          resources:
            requests:
              cpu: "${CPU_PER_POD}"
              memory: "${MEMORY_PER_POD}"
EOF

printf "  ⏳ Waiting for pods to go Pending...\n"

# Wait briefly for pods to be created, then poll for pending pods and new nodes
sleep 5

SCALE_UP_START=$(date +%s)
SCALE_UP_OK=false
FIRST_NEW_NODE_TIME=""
PENDING_COUNT=0
APP_NODES_NOW="${INITIAL_APP_NODES}"

while (( $(date +%s) - SCALE_UP_START < TIMEOUT )); do
  PENDING_COUNT=$(get_stress_pod_count_by_phase "Pending")
  APP_NODES_NOW=$(get_app_pool_nodes)

  printf "  %s | Pending: %d | App nodes: %d" \
    "$(date +%H:%M:%S)" "${PENDING_COUNT}" "${APP_NODES_NOW}"

  if (( APP_NODES_NOW > INITIAL_APP_NODES )); then
    if [[ -z "${FIRST_NEW_NODE_TIME}" ]]; then
      FIRST_NEW_NODE_TIME=$(( $(date +%s) - SCALE_UP_START ))
      printf " ← new node provisioned!"
    fi
    SCALE_UP_OK=true
  fi
  printf "\n"

  # If we have new nodes and all pending pods are scheduling, move on
  if [[ "${SCALE_UP_OK}" == "true" ]]; then
    # Give CA a bit more time to finish provisioning
    sleep 15
    break
  fi

  sleep "${POLL_INTERVAL}"
done

SCALE_UP_ELAPSED=$(( $(date +%s) - SCALE_UP_START ))

if [[ "${SCALE_UP_OK}" != "true" ]]; then
  printf "\n=== Results ===\n"
  printf "  Nodes: %d → %d\n" "${INITIAL_APP_NODES}" "$(get_app_pool_nodes)"
  printf "  CA scale-up: ❌ FAIL (no new node within %ds)\n" "${TIMEOUT}"
  printf "  Hint: check CA logs: kubectl logs -f deployment/cluster-autoscaler -n kube-system\n"
  exit 2
fi

printf "  ✅ New node(s) provisioned in %ds\n" "${FIRST_NEW_NODE_TIME}"

# --- [3/4] Wait for all pods to schedule ---
printf "\n[3/4] Waiting for pods to schedule (%ds timeout)...\n" "${TIMEOUT}"

SCHEDULE_START=$(date +%s)
SCHEDULE_OK=false
RUNNING_COUNT=0

while (( $(date +%s) - SCHEDULE_START < TIMEOUT )); do
  RUNNING_COUNT=$(get_stress_pod_count_by_phase "Running")
  APP_NODES_NOW=$(get_app_pool_nodes)
  TOTAL_PODS=$(get_stress_pod_total)

  printf "  %s | Running: %d/%d | App nodes: %d\n" \
    "$(date +%H:%M:%S)" "${RUNNING_COUNT}" "${REPLICAS}" "${APP_NODES_NOW}"

  if (( TOTAL_PODS >= REPLICAS && RUNNING_COUNT >= REPLICAS )); then
    SCHEDULE_OK=true
    break
  fi

  sleep "${POLL_INTERVAL}"
done

SCHEDULE_ELAPSED=$(( $(date +%s) - SCHEDULE_START ))

if [[ "${SCHEDULE_OK}" != "true" ]]; then
  FINAL_RUNNING=$(get_stress_pod_count_by_phase "Running")
  FINAL_PENDING=$(get_stress_pod_count_by_phase "Pending")
  printf "\n=== Results ===\n"
  printf "  Nodes: %d → %d\n" "${INITIAL_APP_NODES}" "$(get_app_pool_nodes)"
  printf "  CA scale-up:   ✅ PASS (new node in %ds)\n" "${FIRST_NEW_NODE_TIME}"
  printf "  Pod scheduling: ❌ FAIL (%d/%d running, %d pending after %ds)\n" \
    "${FINAL_RUNNING}" "${REPLICAS}" "${FINAL_PENDING}" "${SCHEDULE_ELAPSED}"
  exit 3
fi

printf "  ✅ All %d pods running\n" "${REPLICAS}"

# --- [4/4] Cleanup ---
printf "\n[4/4] Cleanup...\n"

kubectl delete deployment "${STRESS_DEPLOYMENT}" \
  --namespace "${NAMESPACE}" \
  --ignore-not-found=true >/dev/null 2>&1

printf "  ✅ Stress deployment deleted\n"

# Optional: wait for scale-down
SCALE_DOWN_RESULT=""
if [[ "${WAIT_SCALE_DOWN}" == "true" ]]; then
  SCALE_DOWN_TIMEOUT=$(( TIMEOUT * 2 ))
  printf "\n  Waiting for scale-down (%ds timeout)...\n" "${SCALE_DOWN_TIMEOUT}"

  SCALE_DOWN_START=$(date +%s)
  SCALE_DOWN_OK=false

  while (( $(date +%s) - SCALE_DOWN_START < SCALE_DOWN_TIMEOUT )); do
    CURRENT_APP=$(get_app_pool_nodes)
    printf "  %s | App nodes: %d\n" "$(date +%H:%M:%S)" "${CURRENT_APP}"

    if (( CURRENT_APP <= INITIAL_APP_NODES )); then
      SCALE_DOWN_OK=true
      break
    fi

    sleep "${POLL_INTERVAL}"
  done

  SCALE_DOWN_ELAPSED=$(( $(date +%s) - SCALE_DOWN_START ))
  if [[ "${SCALE_DOWN_OK}" == "true" ]]; then
    SCALE_DOWN_RESULT="✅ PASS (returned to $(get_app_pool_nodes) in ${SCALE_DOWN_ELAPSED}s)"
  else
    SCALE_DOWN_RESULT="⚠️  did not scale down within ${SCALE_DOWN_TIMEOUT}s (current: $(get_app_pool_nodes))"
  fi
fi

# --- Final results ---
FINAL_APP_NODES=$(get_app_pool_nodes)

printf "\n=== Results ===\n"
printf "  Nodes: %d → %d\n" "${INITIAL_APP_NODES}" "${FINAL_APP_NODES}"
printf "  CA scale-up:   ✅ PASS (new node in %ds)\n" "${FIRST_NEW_NODE_TIME}"
printf "  Pod scheduling: ✅ PASS (all %d pods running)\n" "${REPLICAS}"

if [[ -n "${SCALE_DOWN_RESULT}" ]]; then
  printf "  Scale-down:    %s\n" "${SCALE_DOWN_RESULT}"
fi
