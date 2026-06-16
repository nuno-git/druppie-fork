#!/usr/bin/env bash
# -----------------------------------------------------------------------------
# test-hpa-load.sh — Full HPA load test with gradual ramp and CSV reporting
#
# Sends sustained HTTP load via `hey` and monitors HPA scale-up/scale-down
# behavior. Designed for periodic / pre-release testing (not CI).
#
# Context:
#   - Backend HPA: min=2, max=10, target=70% CPU
#   - Frontend HPA: min=2, max=8, target=70% CPU
#   - Helm release name: druppie
#   - Service names: druppie-backend, druppie-frontend
#
# Usage:
#   ./test-hpa-load.sh [OPTIONS]
#
# Options:
#   --namespace NS          Kubernetes namespace          (default: druppie)
#   --component COMP        backend|frontend              (default: backend)
#   --duration SECONDS      Load test duration             (default: 180)
#   --concurrency N         Concurrent requests            (default: 100)
#   --url URL               Override service URL (skip auto-detect)
#   -h, --help              Show this help message
#
# Exit codes:
#   0  Both scale-up and scale-down passed
#   1  Scale-up failed (or pre-flight)
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
DURATION=180
CONCURRENCY=100
SERVICE_URL=""
RELEASE_NAME="${RELEASE_NAME:-druppie}"
SCALE_DOWN_TIMEOUT=600

# ---------------------------------------------------------------------------
# CLI argument parsing
# ---------------------------------------------------------------------------
usage() {
  cat <<EOF
Usage: $(basename "$0") [OPTIONS]

Full HPA load test using hey with monitoring and CSV reporting.

Options:
  --namespace NS          Kubernetes namespace          (default: ${NAMESPACE})
  --component COMP        backend|frontend              (default: ${COMPONENT})
  --duration SECONDS      Load test duration             (default: ${DURATION})
  --concurrency N         Concurrent requests            (default: ${CONCURRENCY})
  --url URL               Override service URL (skip auto-detect)
  -h, --help              Show this help message

Requires: hey (https://github.com/rakyll/hey)
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
    --duration)
      DURATION="$2"
      shift 2
      ;;
    --concurrency)
      CONCURRENCY="$2"
      shift 2
      ;;
    --url)
      SERVICE_URL="$2"
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

# Derive HPA/deployment name and endpoint
HPA_NAME="${RELEASE_NAME}-${COMPONENT}"
case "${COMPONENT}" in
  backend)
    SERVICE_PORT=8000
    ENDPOINT="/api/sessions"
    ;;
  frontend)
    SERVICE_PORT=5173
    ENDPOINT="/"
    ;;
  *)
    log_fail "Unknown component '${COMPONENT}'. Must be 'backend' or 'frontend'."
    exit 1
    ;;
esac

# ---------------------------------------------------------------------------
# Dependency checks
# ---------------------------------------------------------------------------
if ! command -v hey &>/dev/null; then
  log_fail "'hey' is not installed"
  printf "  Install: go install github.com/rakyll/hey@latest\n"
  printf "       or: brew install hey\n"
  exit 1
fi

# ---------------------------------------------------------------------------
# Cleanup on exit — kill background monitor, remove temp files
# ---------------------------------------------------------------------------
MONITOR_PID=""
MONITOR_TMPFILE=""

cleanup() {
  local exit_code=$?
  # Kill background monitor if running
  if [[ -n "${MONITOR_PID}" ]] && kill -0 "${MONITOR_PID}" 2>/dev/null; then
    kill "${MONITOR_PID}" 2>/dev/null || true
    wait "${MONITOR_PID}" 2>/dev/null || true
  fi
  # Remove temp file
  if [[ -n "${MONITOR_TMPFILE}" ]] && [[ -f "${MONITOR_TMPFILE}" ]]; then
    rm -f "${MONITOR_TMPFILE}"
  fi
  exit "${exit_code}"
}
trap cleanup EXIT
trap 'cleanup; exit 130' INT TERM

# ---------------------------------------------------------------------------
# Auto-detect service URL if not provided
# ---------------------------------------------------------------------------
if [[ -z "${SERVICE_URL}" ]]; then
  SVC_NAME="${HPA_NAME}"

  # Try LoadBalancer IP
  LB_IP=$(kubectl get svc "${SVC_NAME}" -n "${NAMESPACE}" \
    -o jsonpath='{.status.loadBalancer.ingress[0].ip}' 2>/dev/null || true)
  if [[ -n "${LB_IP}" ]]; then
    SERVICE_URL="http://${LB_IP}:${SERVICE_PORT}"
  fi

  # Try LoadBalancer hostname
  if [[ -z "${SERVICE_URL}" ]]; then
    LB_HOST=$(kubectl get svc "${SVC_NAME}" -n "${NAMESPACE}" \
      -o jsonpath='{.status.loadBalancer.ingress[0].hostname}' 2>/dev/null || true)
    if [[ -n "${LB_HOST}" ]]; then
      SERVICE_URL="http://${LB_HOST}:${SERVICE_PORT}"
    fi
  fi

  # Try ingress host
  if [[ -z "${SERVICE_URL}" ]]; then
    INGRESS_HOST=$(kubectl get ingress -n "${NAMESPACE}" \
      -o jsonpath='{.items[0].spec.rules[0].host}' 2>/dev/null || true)
    if [[ -n "${INGRESS_HOST}" ]]; then
      TLS_SECRET=$(kubectl get ingress -n "${NAMESPACE}" \
        -o jsonpath='{.items[0].spec.tls[0].secretName}' 2>/dev/null || true)
      if [[ -n "${TLS_SECRET}" ]]; then
        SERVICE_URL="https://${INGRESS_HOST}"
      else
        SERVICE_URL="http://${INGRESS_HOST}"
      fi
    fi
  fi

  # Fallback: NodePort with first worker external IP
  if [[ -z "${SERVICE_URL}" ]]; then
    NODE_IP=$(kubectl get nodes \
      -o jsonpath='{.items[0].status.addresses[?(@.type=="ExternalIP")].address}' 2>/dev/null || true)
    NODE_PORT=$(kubectl get svc "${SVC_NAME}" -n "${NAMESPACE}" \
      -o jsonpath='{.spec.ports[0].nodePort}' 2>/dev/null || true)
    if [[ -n "${NODE_IP}" && -n "${NODE_PORT}" ]]; then
      SERVICE_URL="http://${NODE_IP}:${NODE_PORT}"
    fi
  fi

  if [[ -z "${SERVICE_URL}" ]]; then
    log_fail "Cannot auto-detect service URL for ${SVC_NAME}"
    printf "  Use --url to specify manually\n"
    exit 1
  fi
fi

# ---------------------------------------------------------------------------
# Results directory
# ---------------------------------------------------------------------------
RESULTS_DIR="${SCRIPT_DIR}/../results/autoscaling"
mkdir -p "${RESULTS_DIR}"
TIMESTAMP=$(date +%Y%m%d)
CSV_FILE="${RESULTS_DIR}/hpa-${COMPONENT}-${TIMESTAMP}.csv"

# ---------------------------------------------------------------------------
# Test execution
# ---------------------------------------------------------------------------
TARGET_URL="${SERVICE_URL}${ENDPOINT}"

printf "\n=== HPA Load Test ===\n"
printf "Component:    %s\n" "${COMPONENT}"
printf "Duration:     %ds | Concurrency: %d\n" "${DURATION}" "${CONCURRENCY}"
printf "URL:          %s\n\n" "${TARGET_URL}"

# --- [1/4] Pre-flight ---
printf "[1/4] Pre-flight...\n"

assert_hpa_exists "${NAMESPACE}" "${HPA_NAME}"

HPA_INFO=$(kubectl get hpa "${HPA_NAME}" -n "${NAMESPACE}" -o json \
  2>/dev/null)
HPA_MIN=$(echo "${HPA_INFO}" | jq -r '.spec.minReplicas // "?"')
HPA_MAX=$(echo "${HPA_INFO}" | jq -r '.spec.maxReplicas // "?"')
HPA_TARGET_CPU=$(echo "${HPA_INFO}" \
  | jq -r '.spec.metrics[0].resource.target.averageUtilization // "?"')
printf "  ✅ HPA: %s (min=%s, max=%s, target=%s%% CPU)\n" \
  "${HPA_NAME}" "${HPA_MIN}" "${HPA_MAX}" "${HPA_TARGET_CPU}"

assert_metrics_server
printf "  ✅ Metrics server running\n"

BASELINE_REPLICAS=$(get_hpa_replicas "${NAMESPACE}" "${HPA_NAME}")
printf "  ✅ Baseline: %s replicas\n\n" "${BASELINE_REPLICAS}"

# --- [2/4] Run load test with background monitoring ---
printf "[2/4] Running load test (%ds)...\n" "${DURATION}"
printf "  Sending %d concurrent requests to %s...\n\n" "${CONCURRENCY}" "${ENDPOINT}"

# Create temp file for monitor data
MONITOR_TMPFILE=$(mktemp /tmp/hpa-monitor.XXXXXX)

# Write CSV header
echo "timestamp,replicas,cpu_percent,worker_nodes,pending_pods" > "${MONITOR_TMPFILE}"

# Start background monitoring loop
(
  while true; do
    local_replicas
    local_replicas=$(kubectl get hpa "${HPA_NAME}" -n "${NAMESPACE}" \
      -o jsonpath='{.status.currentReplicas}' 2>/dev/null || echo "0")
    local_cpu
    local_cpu=$(kubectl get hpa "${HPA_NAME}" -n "${NAMESPACE}" \
      -o jsonpath='{.status.currentMetrics[0].resource.current.averageUtilization}' 2>/dev/null || echo "0")
    local_nodes
    local_nodes=$(kubectl get nodes \
      --selector='!node-role.kubernetes.io/control-plane' \
      --no-headers 2>/dev/null | wc -l | tr -d ' ')
    local_pending
    local_pending=$(kubectl get pods -n "${NAMESPACE}" \
      --field-selector=status.phase=Pending \
      --no-headers 2>/dev/null | wc -l | tr -d ' ')

    echo "$(date -u +%Y-%m-%dT%H:%M:%S),${local_replicas},${local_cpu:-0},${local_nodes},${local_pending}" \
      >> "${MONITOR_TMPFILE}"

    sleep 10
  done
) &
MONITOR_PID=$!

# Run hey
HEY_OUTPUT=$(hey -z "${DURATION}s" -c "${CONCURRENCY}" "${TARGET_URL}" 2>&1 || true)

# Stop the monitor
kill "${MONITOR_PID}" 2>/dev/null || true
wait "${MONITOR_PID}" 2>/dev/null || true
MONITOR_PID=""

# Print a few key hey results
printf "\n"
HEY_RPS=$(echo "${HEY_OUTPUT}" | grep -oP 'Requests/sec:\s+\K[\d.]+' || echo "?")
HEY_LATENCY_P95=$(echo "${HEY_OUTPUT}" | grep -oP '95%\s+in\s+\K[\d.]+' || echo "?")
printf "  hey results: %s req/s, p95 latency: %s\n\n" "${HEY_RPS}" "${HEY_LATENCY_P95}"

# --- [3/4] Monitor scale-down ---
printf "[3/4] Load stopped. Monitoring scale-down (%ds timeout)...\n" "${SCALE_DOWN_TIMEOUT}"

SCALE_DOWN_START=$(date +%s)
SCALE_DOWN_OK=false
PEAK_REPLICAS="${BASELINE_REPLICAS}"

# Find peak from monitor data
if [[ -f "${MONITOR_TMPFILE}" ]]; then
  DATA_PEAK=$(tail -n +2 "${MONITOR_TMPFILE}" | awk -F',' '{if($2>max) max=$2} END {print max+0}')
  if (( DATA_PEAK > PEAK_REPLICAS )); then
    PEAK_REPLICAS="${DATA_PEAK}"
  fi
fi

# If peak wasn't captured from CSV, check current as fallback
if (( PEAK_REPLICAS <= BASELINE_REPLICAS )); then
  # Scale-up never happened — check current state
  CURRENT_REPLICAS=$(get_hpa_replicas "${NAMESPACE}" "${HPA_NAME}")
  if (( CURRENT_REPLICAS > PEAK_REPLICAS )); then
    PEAK_REPLICAS="${CURRENT_REPLICAS}"
  fi
fi

# Determine time to first scale-up from CSV
SCALE_UP_TIME=""
if [[ -f "${MONITOR_TMPFILE}" ]]; then
  FIRST_SCALE_LINE=$(tail -n +2 "${MONITOR_TMPFILE}" | awk -F',' -v bl="${BASELINE_REPLICAS}" \
    '$2 > bl {print NR; exit}')
  if [[ -n "${FIRST_SCALE_LINE}" ]]; then
    FIRST_SCALE_TS=$(tail -n +2 "${MONITOR_TMPFILE}" | awk -F',' -v bl="${BASELINE_REPLICAS}" \
      '$2 > bl {print $1; exit}')
    if [[ -n "${FIRST_SCALE_TS}" ]]; then
      # Convert to relative seconds (rough: each line is ~10s apart)
      SCALE_UP_TIME=$(( FIRST_SCALE_LINE * 10 ))
    fi
  fi
fi

# Continue monitoring for scale-down (resume recording to CSV)
(
  while true; do
    local_replicas
    local_replicas=$(kubectl get hpa "${HPA_NAME}" -n "${NAMESPACE}" \
      -o jsonpath='{.status.currentReplicas}' 2>/dev/null || echo "0")
    local_cpu
    local_cpu=$(kubectl get hpa "${HPA_NAME}" -n "${NAMESPACE}" \
      -o jsonpath='{.status.currentMetrics[0].resource.current.averageUtilization}' 2>/dev/null || echo "0")
    local_nodes
    local_nodes=$(kubectl get nodes \
      --selector='!node-role.kubernetes.io/control-plane' \
      --no-headers 2>/dev/null | wc -l | tr -d ' ')
    local_pending
    local_pending=$(kubectl get pods -n "${NAMESPACE}" \
      --field-selector=status.phase=Pending \
      --no-headers 2>/dev/null | wc -l | tr -d ' ')

    echo "$(date -u +%Y-%m-%dT%H:%M:%S),${local_replicas},${local_cpu:-0},${local_nodes},${local_pending}" \
      >> "${MONITOR_TMPFILE}"

    sleep 10
  done
) &
MONITOR_PID=$!

while (( $(date +%s) - SCALE_DOWN_START < SCALE_DOWN_TIMEOUT )); do
  CURRENT_REPLICAS=$(get_hpa_replicas "${NAMESPACE}" "${HPA_NAME}") || CURRENT_REPLICAS="${PEAK_REPLICAS}"
  CURRENT_CPU=$(get_hpa_cpu "${NAMESPACE}" "${HPA_NAME}")

  printf "  %s | Replicas: %s | CPU: %s%%\n" \
    "$(date +%H:%M:%S)" "${CURRENT_REPLICAS}" "${CURRENT_CPU}"

  if (( CURRENT_REPLICAS <= BASELINE_REPLICAS )); then
    SCALE_DOWN_OK=true
    break
  fi

  sleep "${POLL_INTERVAL}"
done

SCALE_DOWN_ELAPSED=$(( $(date +%s) - SCALE_DOWN_START ))

# Stop the scale-down monitor
kill "${MONITOR_PID}" 2>/dev/null || true
wait "${MONITOR_PID}" 2>/dev/null || true
MONITOR_PID=""

# --- [4/4] Save report ---
printf "\n[4/4] Report saved to %s\n" "${CSV_FILE}"

# Copy collected data to final CSV
if [[ -f "${MONITOR_TMPFILE}" ]]; then
  cp "${MONITOR_TMPFILE}" "${CSV_FILE}"
fi

# --- Final results ---
FINAL_REPLICAS=$(get_hpa_replicas "${NAMESPACE}" "${HPA_NAME}") || FINAL_REPLICAS="${PEAK_REPLICAS}"

# Build scale-up time string
SCALE_UP_DISPLAY=""
if [[ -n "${SCALE_UP_TIME}" ]]; then
  SCALE_UP_DISPLAY="${SCALE_UP_TIME}s"
else
  SCALE_UP_DISPLAY="detected"
fi

printf "\n=== Results ===\n"
printf "  Baseline:     %s replicas\n" "${BASELINE_REPLICAS}"
printf "  Peak:         %s replicas (reached in %s)\n" "${PEAK_REPLICAS}" "${SCALE_UP_DISPLAY}"
printf "  Scale-down:   %s replicas (in %ds)\n" "${FINAL_REPLICAS}" "${SCALE_DOWN_ELAPSED}"

if (( PEAK_REPLICAS > BASELINE_REPLICAS )); then
  printf "  Scale-up:     ✅ PASS\n"
  if [[ "${SCALE_DOWN_OK}" == "true" ]]; then
    printf "  Scale-down:   ✅ PASS\n"
    exit 0
  else
    printf "  Scale-down:   ❌ FAIL (did not return to %s within %ds)\n" \
      "${BASELINE_REPLICAS}" "${SCALE_DOWN_TIMEOUT}"
    exit 2
  fi
else
  printf "  Scale-up:     ❌ FAIL (replicas never exceeded baseline of %s)\n" "${BASELINE_REPLICAS}"
  printf "  Hint: try increasing --concurrency or --duration\n"
  exit 1
fi
