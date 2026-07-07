#!/usr/bin/env bash
# =============================================================================
# run-load-test.sh -- CONCURRENCY / load benchmark against the LIVE in-cluster
# LLM endpoints. Complements the single-stream suite (run-in-cluster.sh): that
# measures one request at a time; this fires many concurrent streaming requests
# to find where aggregate throughput saturates and where latency knees.
#
# NON-DISRUPTIVE: it ONLY sends load to the live Services. It never scales,
# suspends Flux, or creates/patches any InferenceService/Deployment. The only
# cluster objects it creates are a `loadtest-<slug>` Job + a `loadtest-pkg`
# configmap, both cleaned up after each target.
#
# For each target it runs `python -m benchmarks.load_test` in-cluster and scrapes
# the ===REPORT_TXT_START/END=== / ===RESULTS_JSON_START/END=== marker blocks out
# of the Job logs into:
#   benchmarks/results-incluster/<slug>/load-test.txt
#   benchmarks/results-incluster/<slug>/load-test.json
#
# These are kept SEPARATE from the single-stream report.txt/results.json.
# It does NOT publish to aigit and does NOT edit any tracked config file.
#
# Usage: ./benchmarks/k8s/run-load-test.sh
# Env overrides: CONCURRENCY, MAX_TOKENS, REQ_MULTIPLIER, WINDOW_SECONDS,
#                JOB_COMPLETE_TIMEOUT
# =============================================================================
set -euo pipefail

NS=llm
CONCURRENCY="${CONCURRENCY:-1,8,32,64,128}"
MAX_TOKENS="${MAX_TOKENS:-256}"
REQ_MULTIPLIER="${REQ_MULTIPLIER:-3}"
WINDOW_SECONDS="${WINDOW_SECONDS:-45}"
JOB_COMPLETE_TIMEOUT="${JOB_COMPLETE_TIMEOUT:-3600}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
cd "${REPO_ROOT}"

RESULTS_DIR="${REPO_ROOT}/benchmarks/results-incluster"
JOB_TMPL="${SCRIPT_DIR}/load-test-job.yaml"
WORKDIR="$(mktemp -d)"

# Targets: "slug|base_url|model_id|display_name". slug MUST match the existing
# results-incluster/<slug> dirs so load-test.* land next to the single-stream
# report.txt for that model.
TARGETS=(
  "qwen3.6-27b-nvfp4|http://qwen-27b.llm.svc.cluster.local:8000/v1|nvidia/Qwen3.6-27B-NVFP4|Qwen3.6-27B-NVFP4 (in-cluster, concurrency)"
  "qwen3.6-35b-a3b-nvfp4|http://qwen-35b.llm.svc.cluster.local:8000/v1|nvidia/Qwen3.6-35B-A3B-NVFP4|Qwen3.6-35B-A3B-NVFP4 (in-cluster, concurrency)"
)

cleanup() {
  set +e
  echo ">> Cleaning up any loadtest Jobs + configmaps..."
  kubectl delete job -n "${NS}" -l app=llm-loadtest --ignore-not-found --wait=false >/dev/null 2>&1
  kubectl delete configmap loadtest-pkg -n "${NS}" --ignore-not-found >/dev/null 2>&1
  rm -rf "${WORKDIR}" 2>/dev/null
}
trap cleanup EXIT INT TERM

command -v kubectl >/dev/null || { echo "kubectl not found" >&2; exit 1; }

run_target() {
  local slug="$1" base_url="$2" model_id="$3" display="$4"
  local k8s_slug; k8s_slug="$(printf '%s' "${slug}" | tr '.' '-')"
  local job_name="loadtest-${k8s_slug}"
  local dest_dir="${RESULTS_DIR}/${slug}"
  local dest_txt="${dest_dir}/load-test.txt"
  local dest_json="${dest_dir}/load-test.json"
  local tmp_job="${WORKDIR}/${job_name}.yaml"

  echo ""
  echo "==============================================================="
  echo ">> LOAD TEST: ${display}"
  echo "   slug=${slug}  endpoint=${base_url}  model=${model_id}"
  echo "==============================================================="

  echo ">> Verifying endpoint /v1/models ..."
  local ids
  ids="$(kubectl run "loadtest-probe-$$" -n "${NS}" --rm -i --restart=Never \
    --image=curlimages/curl:8.10.1 --quiet -- \
    -s "${base_url}/models" 2>/dev/null || true)"
  echo "   ${ids}"
  case "${ids}" in
    *"${model_id}"*) echo "   OK: model id present." ;;
    *) echo "   WARNING: '${model_id}' not found in /v1/models response; proceeding anyway." ;;
  esac

  echo ">> Cleaning up any prior loadtest Job + configmap..."
  kubectl delete job "${job_name}" -n "${NS}" --ignore-not-found
  kubectl delete configmap loadtest-pkg -n "${NS}" --ignore-not-found

  echo ">> Creating configmap loadtest-pkg..."
  kubectl create configmap loadtest-pkg -n "${NS}" \
    --from-file=__init__.py=benchmarks/__init__.py \
    --from-file=load_test.py=benchmarks/load_test.py

  echo ">> Templating Job ${job_name}..."
  sed -e "s|__JOB_NAME__|${job_name}|g" \
      -e "s|__BASE_URL__|${base_url}|g" \
      -e "s|__MODEL_ID__|${model_id}|g" \
      -e "s|__DISPLAY_NAME__|${display}|g" \
      -e "s|__CONCURRENCY__|${CONCURRENCY}|g" \
      -e "s|__MAX_TOKENS__|${MAX_TOKENS}|g" \
      -e "s|__REQ_MULTIPLIER__|${REQ_MULTIPLIER}|g" \
      -e "s|__WINDOW_SECONDS__|${WINDOW_SECONDS}|g" \
      "${JOB_TMPL}" > "${tmp_job}"

  echo ">> Applying Job..."
  kubectl apply -f "${tmp_job}"

  echo ">> Waiting for Job to complete (up to ${JOB_COMPLETE_TIMEOUT}s)..."
  kubectl wait --for=condition=complete "job/${job_name}" -n "${NS}" \
    --timeout="${JOB_COMPLETE_TIMEOUT}s" || \
    kubectl wait --for=condition=failed "job/${job_name}" -n "${NS}" --timeout=30s || true

  local job_logs="${WORKDIR}/joblogs-${k8s_slug}.txt"
  kubectl logs "job/${job_name}" -n "${NS}" 2>/dev/null > "${job_logs}" || true

  mkdir -p "${dest_dir}"
  echo ">> Extracting report -> ${dest_txt}"
  awk '/===REPORT_TXT_START===/{f=1;next} /===REPORT_TXT_END===/{f=0} f' \
    "${job_logs}" > "${dest_txt}" || true
  echo ">> Extracting JSON -> ${dest_json}"
  awk '/===RESULTS_JSON_START===/{f=1;next} /===RESULTS_JSON_END===/{f=0} f' \
    "${job_logs}" > "${dest_json}" || true

  if [ -s "${dest_txt}" ]; then
    echo "   report $(wc -c < "${dest_txt}") bytes"
    echo "----------------------------------------------------------------"
    cat "${dest_txt}"
    echo "----------------------------------------------------------------"
  else
    echo "   WARNING: no report captured. Last 60 log lines:"
    tail -n 60 "${job_logs}" 2>/dev/null || true
  fi

  echo ">> Deleting Job + configmap for ${job_name}..."
  kubectl delete job "${job_name}" -n "${NS}" --ignore-not-found >/dev/null 2>&1 || true
  kubectl delete configmap loadtest-pkg -n "${NS}" --ignore-not-found >/dev/null 2>&1 || true
}

mkdir -p "${RESULTS_DIR}"
for t in "${TARGETS[@]}"; do
  IFS='|' read -r slug base_url model_id display <<< "${t}"
  run_target "${slug}" "${base_url}" "${model_id}" "${display}"
done

echo ""
echo ">> All load tests complete."
