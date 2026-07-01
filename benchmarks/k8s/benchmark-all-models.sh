#!/usr/bin/env bash
# =============================================================================
# benchmark-all-models.sh -- benchmark EVERY LLMKube model in the cluster.
#
# Generalizes the "benchmark one model" workflow (run-in-cluster.sh) to sweep
# all models declared as `models.inference.llmkube.dev` in namespace `llm`.
#
# For each discovered model it runs the standard in-cluster benchmark Job
# (benchmarks/k8s/job.yaml) pointed at that model's endpoint, saves the
# human-readable console report to benchmarks/results-incluster/<slug>/report.txt,
# then finally builds a cross-model comparison matrix and publishes everything to
# aigit.
#
# results-incluster/ holds ONLY .txt outputs (one per-model folder each) plus the
# text COMPARISON-MATRIX.md. The per-model result JSON is kept ONLY transiently in
# the script's temp WORKDIR: it feeds compare_models.py to build the matrix, then
# is discarded with the WORKDIR on exit. No .json / .csv is ever written into
# results-incluster.
#
# -----------------------------------------------------------------------------
# !!! IMPACT WARNING -- READ BEFORE RUNNING !!!
# -----------------------------------------------------------------------------
# The cluster has a fixed pool of GPUs. Prod `qwen` (Qwen3.6-27B) normally runs
# 2 replicas (2 GPUs). To benchmark a DIFFERENT model we must free a GPU, which
# means this script will TEMPORARILY:
#   * suspend the Flux `llm-models` Kustomization (so Flux won't fight our edits
#     or re-scale qwen back up mid-run), and
#   * scale the prod `qwen` InferenceService down to 1 replica (freeing 1 GPU),
#     then create a short-lived `bench-<model>` InferenceService on that GPU.
#
# During the run prod qwen serves at HALF capacity (1 replica). A trap ALWAYS
# restores qwen to its original replica count and resumes Flux on exit -- even
# on Ctrl-C or error. Still: run this in a maintenance window.
#
# The currently-served prod model is benchmarked in place (no serving change).
#
# -----------------------------------------------------------------------------
# USAGE
# -----------------------------------------------------------------------------
#   ./benchmarks/k8s/benchmark-all-models.sh            # interactive confirm
#   ./benchmarks/k8s/benchmark-all-models.sh --yes      # skip confirmation
#
# Requirements: kubectl (context pointed at the ka-k8s-ai / llm cluster),
# python3 (for the comparison matrix + config munging), and the in-cluster
# `aigit-publish` secret in ns llm for the publish step (optional -- skipped
# gracefully if absent, exactly like run-in-cluster.sh).
#
# This script does NOT edit any tracked file. It reuses job.yaml and
# publish_to_aigit.py verbatim, and generates per-model TEMP configs so the
# tracked benchmarks/config.yaml is never touched.
# =============================================================================
set -euo pipefail

# -----------------------------------------------------------------------------
# Constants
# -----------------------------------------------------------------------------
NS=llm
PROD_ISVC=qwen                       # prod InferenceService name (ns llm)
PROD_ORIGINAL_REPLICAS=2             # documented prod baseline; captured live below
FLUX_KUSTOMIZATION=llm-models        # Flux Kustomization that manages the models
FLUX_NS=flux-system                  # namespace the Kustomization lives in
JOB=llm-benchmark                    # Job name (matches job.yaml)
GPU_READY_TIMEOUT=5400               # 90 min: no weight cache, so a bench model's first serve downloads the FULL model from HF
# Benchmark-completion wait. Must be >= the Job's activeDeadlineSeconds (9000s in
# job.yaml): the full suite has scenarios that take 100-200s each, so 1800s is far
# too short. Match the Job deadline so we wait for the Job to finish (or hit its
# own deadline) rather than giving up early and losing results.
JOB_COMPLETE_TIMEOUT=9000
ISVC_YAML_CACHE=/tmp/ai-k8s2/clusters/llm-models/inferenceservice.yaml

# python3 is not present in every environment (e.g. Git-Bash only ships `python`).
# Auto-detect a usable interpreter once and use it everywhere below.
PYTHON="$(command -v python3 || command -v python || true)"

# Resolve repo root relative to this script so it works from anywhere.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
cd "${REPO_ROOT}"

RESULTS_DIR="${REPO_ROOT}/benchmarks/results-incluster"
CONFIG_SRC="${REPO_ROOT}/benchmarks/config.yaml"
JOB_YAML="${REPO_ROOT}/benchmarks/k8s/job.yaml"
COMPARE_PY="${REPO_ROOT}/benchmarks/compare_models.py"

# Workspace for temp configs / manifests -- cleaned up on exit.
WORKDIR="$(mktemp -d)"

# -----------------------------------------------------------------------------
# State captured at startup (used by the restore trap). Defaults are safe so a
# trap firing before capture still does something sane.
# -----------------------------------------------------------------------------
CAPTURED_QWEN_REPLICAS="${PROD_ORIGINAL_REPLICAS}"
CAPTURED_FLUX_SUSPENDED="false"      # was Flux already suspended before we started?
FLUX_TOUCHED="false"                 # did WE change the suspend state?
QWEN_TOUCHED="false"                 # did WE scale qwen?
declare -a TEMP_ISVCS=()             # bench-* InferenceServices we created

# -----------------------------------------------------------------------------
# restore() -- ALWAYS runs on EXIT/INT/TERM. Idempotent and tolerant of partial
# state: every step is guarded and never aborts the others (we clear -e here).
# -----------------------------------------------------------------------------
restore() {
  local exit_code=$?
  set +e
  echo ""
  echo ">> [restore] Cleaning up (exit code ${exit_code})..."

  # 1. Delete any temp bench-* InferenceServices we created. Also do a
  #    belt-and-braces sweep for anything named bench-* in case a name wasn't
  #    tracked (e.g. crash right after create).
  for isvc in "${TEMP_ISVCS[@]:-}"; do
    [ -n "${isvc}" ] || continue
    echo ">> [restore] Deleting temp InferenceService ${isvc}..."
    kubectl delete inferenceservice "${isvc}" -n "${NS}" --ignore-not-found --wait=false
  done
  # Sweep any stray bench-* left behind.
  local strays
  strays="$(kubectl get inferenceservice -n "${NS}" -o name 2>/dev/null | grep '/bench-' || true)"
  if [ -n "${strays}" ]; then
    echo ">> [restore] Removing stray bench-* InferenceServices:"
    echo "${strays}"
    echo "${strays}" | xargs -r kubectl delete -n "${NS}" --ignore-not-found --wait=false
  fi

  # 2. Restore prod qwen replicas to the captured original (only if we scaled).
  if [ "${QWEN_TOUCHED}" = "true" ]; then
    echo ">> [restore] Restoring ${PROD_ISVC} to ${CAPTURED_QWEN_REPLICAS} replica(s)..."
    kubectl patch inferenceservice "${PROD_ISVC}" -n "${NS}" --type merge \
      -p "{\"spec\":{\"replicas\":${CAPTURED_QWEN_REPLICAS}}}" || \
      echo ">> [restore] WARNING: failed to restore ${PROD_ISVC} replicas -- check manually!"
  fi

  # 3. Resume Flux to its ORIGINAL suspend state (only if we changed it).
  if [ "${FLUX_TOUCHED}" = "true" ]; then
    echo ">> [restore] Restoring Flux ${FLUX_KUSTOMIZATION} suspend=${CAPTURED_FLUX_SUSPENDED}..."
    kubectl patch kustomization "${FLUX_KUSTOMIZATION}" -n "${FLUX_NS}" --type merge \
      -p "{\"spec\":{\"suspend\":${CAPTURED_FLUX_SUSPENDED}}}" || \
      echo ">> [restore] WARNING: failed to restore Flux suspend state -- check manually!"
  fi

  # 4. Best-effort: delete the benchmark Job so it doesn't linger.
  kubectl delete job "${JOB}" -n "${NS}" --ignore-not-found --wait=false >/dev/null 2>&1 || true

  # 5. Local workspace.
  rm -rf "${WORKDIR}" 2>/dev/null || true

  echo ">> [restore] Done."
  # Preserve the original exit code.
  exit "${exit_code}"
}
trap restore EXIT INT TERM

# -----------------------------------------------------------------------------
# confirm() -- require explicit go-ahead given the impact.
# -----------------------------------------------------------------------------
confirm() {
  if [ "${1:-}" = "--yes" ]; then
    echo ">> --yes supplied; skipping interactive confirmation."
    return 0
  fi
  echo ""
  echo "This will temporarily scale prod ${PROD_ISVC} to 1 replica and suspend"
  echo "Flux ${FLUX_KUSTOMIZATION} to free a GPU for benchmarking other models."
  echo "A trap restores everything on exit."
  printf "Type 'yes' to proceed: "
  read -r reply
  if [ "${reply}" != "yes" ]; then
    echo "Aborted."
    exit 1
  fi
}

# -----------------------------------------------------------------------------
# sanitize() -- turn a model source/name into a DNS-safe, filename-safe slug.
# e.g. "Qwen/Qwen3.6-35B-A3B" -> "qwen3.6-35b-a3b" (lowercased, path stripped,
# non [a-z0-9.-] collapsed to '-'). Used for bench-<slug> and results-<slug>.
# -----------------------------------------------------------------------------
sanitize() {
  local raw="$1"
  # take last path segment, lowercase, replace invalid chars, trim dashes
  echo "${raw##*/}" \
    | tr '[:upper:]' '[:lower:]' \
    | sed -E 's/[^a-z0-9.-]+/-/g; s/^-+//; s/-+$//'
}

# =============================================================================
# 0. PARSE FLAGS
# =============================================================================
# --yes                 skip the interactive confirmation
# --only slug1,slug2    benchmark only models whose NAME contains one of the
#                       (comma-separated) tokens, e.g. --only 27b,35b-a3b
YES_FLAG=""
ONLY_FILTER=""
while [ $# -gt 0 ]; do
  case "$1" in
    --yes)     YES_FLAG="--yes"; shift ;;
    --only)    ONLY_FILTER="${2:-}"; shift 2 ;;
    --only=*)  ONLY_FILTER="${1#--only=}"; shift ;;
    *)         echo "Unknown argument: $1" >&2; exit 1 ;;
  esac
done

# =============================================================================
# 1. CONFIRM
# =============================================================================
confirm "${YES_FLAG}"

command -v kubectl >/dev/null || { echo "kubectl not found"; exit 1; }
[ -n "${PYTHON}" ] || { echo "python3/python not found"; exit 1; }
mkdir -p "${RESULTS_DIR}"

# =============================================================================
# 2. DISCOVER models + capture current prod state
# =============================================================================
echo ">> Discovering models (models.inference.llmkube.dev -n ${NS})..."
MODELS_JSON="$(kubectl get models.inference.llmkube.dev -n "${NS}" -o json)"

# Parse into "name<TAB>source" lines. `source` is the HF/registry model id used
# as the vLLM --model arg; we fall back through the common CRD spec fields.
MODEL_LINES="$(printf '%s' "${MODELS_JSON}" | "${PYTHON}" -c '
import json, sys
doc = json.load(sys.stdin)
for item in doc.get("items", []):
    name = item.get("metadata", {}).get("name", "")
    spec = item.get("spec", {}) or {}
    # Try the likely source fields in priority order.
    source = (spec.get("source") or spec.get("model") or spec.get("modelId")
              or spec.get("uri") or spec.get("repo") or name)
    print(f"{name}\t{source}")
')"

# Apply the optional --only filter: keep a model if its NAME contains any of the
# comma-separated tokens (substring match, so "27b" matches "qwen3-6-27b").
if [ -n "${ONLY_FILTER}" ]; then
  KEPT=""
  while IFS=$'\t' read -r _mname _msrc; do
    [ -n "${_mname}" ] || continue
    IFS=',' read -ra _toks <<< "${ONLY_FILTER}"
    for _t in "${_toks[@]}"; do
      [ -n "${_t}" ] || continue
      case "${_mname}" in *"${_t}"*) KEPT+="${_mname}"$'\t'"${_msrc}"$'\n'; break ;; esac
    done
  done <<< "${MODEL_LINES}"
  MODEL_LINES="$(printf '%s' "${KEPT}" | sed '/^$/d')"
  echo ">> --only '${ONLY_FILTER}': narrowed to $(printf '%s\n' "${MODEL_LINES}" | grep -c . || true) model(s)."
fi

if [ -z "${MODEL_LINES}" ]; then
  echo "No models discovered. Nothing to do."
  exit 0
fi
echo ">> Discovered models:"
printf '%s\n' "${MODEL_LINES}" | sed 's/^/   - /'

# Capture prod qwen's current replicas + which model it currently serves, so we
# can (a) benchmark that model in place and (b) restore replicas afterwards.
echo ">> Capturing prod ${PROD_ISVC} state..."
CAPTURED_QWEN_REPLICAS="$(kubectl get inferenceservice "${PROD_ISVC}" -n "${NS}" \
  -o jsonpath='{.spec.replicas}' 2>/dev/null || true)"
[ -n "${CAPTURED_QWEN_REPLICAS}" ] || CAPTURED_QWEN_REPLICAS="${PROD_ORIGINAL_REPLICAS}"

# The model currently served by prod qwen. `modelRef` links the InferenceService
# to a models.inference.llmkube.dev object; we compare BY NAME against discovery.
PROD_MODEL_REF="$(kubectl get inferenceservice "${PROD_ISVC}" -n "${NS}" \
  -o jsonpath='{.spec.modelRef.name}' 2>/dev/null || true)"
[ -n "${PROD_MODEL_REF}" ] || PROD_MODEL_REF="$(kubectl get inferenceservice "${PROD_ISVC}" \
  -n "${NS}" -o jsonpath='{.spec.modelRef}' 2>/dev/null || true)"

echo "   prod replicas : ${CAPTURED_QWEN_REPLICAS}"
echo "   prod modelRef : ${PROD_MODEL_REF:-<unknown>}"

# Capture Flux suspend state so restore returns it to exactly what it was.
CAPTURED_FLUX_SUSPENDED="$(kubectl get kustomization "${FLUX_KUSTOMIZATION}" -n "${FLUX_NS}" \
  -o jsonpath='{.spec.suspend}' 2>/dev/null || true)"
[ -n "${CAPTURED_FLUX_SUSPENDED}" ] || CAPTURED_FLUX_SUSPENDED="false"
echo "   flux suspended: ${CAPTURED_FLUX_SUSPENDED}"

# =============================================================================
# Helpers for the per-model loop
# =============================================================================

# suspend_flux() -- suspend the llm-models Kustomization so Flux won't undo our
# temporary scaling / temp InferenceService. Records that WE touched it.
suspend_flux() {
  if [ "${FLUX_TOUCHED}" != "true" ]; then
    echo ">> Suspending Flux ${FLUX_KUSTOMIZATION} (was suspend=${CAPTURED_FLUX_SUSPENDED})..."
    kubectl patch kustomization "${FLUX_KUSTOMIZATION}" -n "${FLUX_NS}" --type merge \
      -p '{"spec":{"suspend":true}}'
    FLUX_TOUCHED="true"
  fi
}

# scale_qwen_to() -- scale prod qwen; record that WE touched it so restore acts.
scale_qwen_to() {
  local n="$1"
  echo ">> Scaling prod ${PROD_ISVC} to ${n} replica(s) to free a GPU..."
  kubectl patch inferenceservice "${PROD_ISVC}" -n "${NS}" --type merge \
    -p "{\"spec\":{\"replicas\":${n}}}"
  QWEN_TOUCHED="true"
}

# wait_free_gpu() -- wait until at least one GPU is allocatable-but-unused in the
# llm nodes. Simple proxy: wait for qwen's scaled-down pods to actually leave so
# the freed GPU is released before we schedule the temp InferenceService.
wait_free_gpu() {
  echo ">> Waiting for scaled-down ${PROD_ISVC} pod(s) to terminate (GPU release)..."
  for _ in $(seq 1 60); do
    local running
    running="$(kubectl get pods -n "${NS}" -l "serving.llmkube.dev/inferenceservice=${PROD_ISVC}" \
      --field-selector=status.phase=Running -o name 2>/dev/null | wc -l | tr -d ' ')"
    # Also try the generic app label as a fallback selector.
    if [ "${running}" = "0" ]; then
      running="$(kubectl get pods -n "${NS}" -l "app=${PROD_ISVC}" \
        --field-selector=status.phase=Running -o name 2>/dev/null | wc -l | tr -d ' ')"
    fi
    echo "   running prod pods: ${running} (target <= 1)"
    [ "${running}" -le 1 ] && { echo "   GPU should be free."; return 0; }
    sleep 5
  done
  echo "   WARNING: timed out waiting for GPU release; proceeding anyway."
}

# make_temp_isvc() -- write a temp InferenceService manifest for a bench model.
# Bases it on the prod InferenceService (from the tracked YAML cache if present,
# else live `kubectl get -o yaml`), then rewrites name/modelRef/model-source and
# forces replicas=1, gpu=1, the gpu=true:NoSchedule toleration, ClusterIP:8000.
#   $1 = bench isvc name (bench-<slug>)   $2 = models CRD name   $3 = model source
make_temp_isvc() {
  local bench_name="$1" model_crd="$2" model_source="$3"
  local base_yaml="${WORKDIR}/prod-isvc.yaml"
  local out_yaml="${WORKDIR}/${bench_name}.yaml"

  if [ -f "${ISVC_YAML_CACHE}" ]; then
    echo ">> Using cached prod InferenceService manifest: ${ISVC_YAML_CACHE}" >&2
    cp "${ISVC_YAML_CACHE}" "${base_yaml}"
  else
    echo ">> Reading live prod InferenceService ${PROD_ISVC} as template..." >&2
    kubectl get inferenceservice "${PROD_ISVC}" -n "${NS}" -o yaml > "${base_yaml}"
  fi

  # Transform the base manifest with Python (robust YAML edit, no fragile sed).
  # NOTE: patched to match the ACTUAL inference.llmkube.dev/v1alpha1 CRD layout
  # observed on ka-k8s-ai (modelRef is a STRING; model source is args[0]; gpu is
  # a scalar spec.resources.gpu; the service block is spec.endpoint not spec.service).
  BENCH_NAME="${bench_name}" MODEL_CRD="${model_crd}" MODEL_SOURCE="${model_source}" \
  "${PYTHON}" - "${base_yaml}" "${out_yaml}" <<'PY'
import os, sys
try:
    import yaml
except ImportError:
    sys.stderr.write("PyYAML required to template the InferenceService.\n")
    sys.exit(1)

src, dst = sys.argv[1], sys.argv[2]
bench = os.environ["BENCH_NAME"]
model_crd = os.environ["MODEL_CRD"]
model_source = os.environ["MODEL_SOURCE"]

doc = yaml.safe_load(open(src))
# Strip server-managed fields so apply is clean.
meta = doc.setdefault("metadata", {})
meta["name"] = bench
for k in ("resourceVersion", "uid", "creationTimestamp", "generation",
          "managedFields", "annotations", "ownerReferences", "labels"):
    meta.pop(k, None)
doc.pop("status", None)

spec = doc.setdefault("spec", {})
spec["replicas"] = 1

# modelRef is a STRING on this CRD -> just set the target model CRD name.
spec["modelRef"] = model_crd

# The vLLM model id is args[0] on this CRD. Rewrite it to the bench model source
# so vLLM actually serves the model we're benchmarking (not prod's 27B).
args = spec.get("args")
if isinstance(args, list) and args:
    args[0] = model_source
else:
    # Fallback: build a minimal args list if the base had none.
    spec["args"] = [model_source, "--host", "0.0.0.0", "--port", "8000"]

# Force single-GPU footprint. On this CRD, gpu is a scalar under spec.resources
# (alongside cpu/memory). Preserve cpu/memory; just pin gpu=1.
res = spec.setdefault("resources", {})
res["gpu"] = 1

# GPU node toleration (already present on prod; keep idempotent).
tolerations = spec.setdefault("tolerations", [])
gpu_tol = {"key": "gpu", "operator": "Equal", "value": "true",
           "effect": "NoSchedule"}
if gpu_tol not in tolerations:
    tolerations.append(gpu_tol)

# endpoint block: ClusterIP:8000 with the chat path (already correct on prod).
ep = spec.get("endpoint")
if isinstance(ep, dict):
    ep.setdefault("type", "ClusterIP")
    ep.setdefault("port", 8000)

yaml.safe_dump(doc, open(dst, "w"), sort_keys=False)
print(f"   wrote temp InferenceService manifest: {dst}", file=sys.stderr)
PY
  # ONLY the manifest path goes to stdout -- it is captured by the caller via
  # command substitution. All diagnostics above are redirected to stderr so they
  # don't pollute the captured path (regression fixed 2026-07-01).
  echo "${out_yaml}"
}

# wait_isvc_ready() -- poll the temp service's /v1/models until HTTP 200. First
# serve downloads weights from HuggingFace, so allow up to GPU_READY_TIMEOUT.
# $1 = in-cluster base host (e.g. bench-foo.llm.svc.cluster.local)
wait_isvc_ready() {
  local host="$1"
  local deadline=$(( $(date +%s) + GPU_READY_TIMEOUT ))
  echo ">> Waiting for ${host}:8000/v1/models to return 200 (up to ${GPU_READY_TIMEOUT}s)..."
  while [ "$(date +%s)" -lt "${deadline}" ]; do
    # Probe from inside the cluster with a throwaway pod (curl image).
    if kubectl run "bench-probe-$$" -n "${NS}" --rm -i --restart=Never \
        --image=curlimages/curl:8.10.1 --quiet -- \
        -sf -o /dev/null -w '%{http_code}' \
        "http://${host}:8000/v1/models" 2>/dev/null | grep -q '^200'; then
      echo "   endpoint is up."
      return 0
    fi
    echo "   not ready yet; sleeping 15s..."
    sleep 15
  done
  echo "   ERROR: ${host} did not become ready within ${GPU_READY_TIMEOUT}s."
  return 1
}

# run_benchmark_job() -- run the standard in-cluster benchmark Job against a
# given endpoint+model, writing the result JSON to a destination file.
#
# We reuse job.yaml and publish_to_aigit.py VERBATIM. The only thing that must
# change per model is the endpoint URL + model id the runner reads from
# config.yaml. Rather than edit the tracked config.yaml, we generate a per-model
# TEMP config (copy + sed the base_url + model + display_name) and build the
# `bench-pkg` configmap from THAT temp file. This mirrors run-in-cluster.sh's
# configmap+Job mechanism but with the endpoint override injected via the temp
# config -- job.yaml itself is applied unchanged.
#
#   $1 = base_url (http://host:8000/v1)   $2 = model id   $3 = display_name
#   $4 = destination result JSON path (TRANSIENT, in the temp WORKDIR)
#   $5 = destination report.txt path (in benchmarks/results-incluster/<slug>/)
run_benchmark_job() {
  local base_url="$1" model_id="$2" display="$3" dest_json="$4" dest_report="$5"
  local tmp_config="${WORKDIR}/config-$(sanitize "${model_id}").yaml"

  echo ">> Building per-model temp config -> ${tmp_config}"
  # Start from the tracked config, then override the single active endpoint's
  # base_url and the single active model's id/display_name. sed targets the
  # `qwen_incluster` endpoint block's base_url and the first model entry.
  cp "${CONFIG_SRC}" "${tmp_config}"
  # Override the in-cluster endpoint URL.
  sed -i -E "s|base_url: \"http://qwen\.llm\.svc\.cluster\.local:8000/v1\"|base_url: \"${base_url}\"|" "${tmp_config}"
  # Override the active model id + display name (first `model:`/`display_name:`).
  sed -i -E "0,/^    model: .*/s||    model: ${model_id}|" "${tmp_config}"
  sed -i -E "0,/^    display_name: .*/s||    display_name: \"${display}\"|" "${tmp_config}"

  echo ">> Cleaning up any prior benchmark Job + configmaps..."
  kubectl delete job "${JOB}" -n "${NS}" --ignore-not-found
  kubectl delete configmap bench-pkg bench-scenarios bench-publish -n "${NS}" --ignore-not-found

  echo ">> Creating configmap bench-pkg (with per-model temp config)..."
  kubectl create configmap bench-pkg -n "${NS}" \
    --from-file=__init__.py=benchmarks/__init__.py \
    --from-file=runner.py=benchmarks/runner.py \
    --from-file=llm_client.py=benchmarks/llm_client.py \
    --from-file=reporter.py=benchmarks/reporter.py \
    --from-file=config.yaml="${tmp_config}"

  echo ">> Creating configmap bench-scenarios..."
  kubectl create configmap bench-scenarios -n "${NS}" \
    --from-file=benchmarks/scenarios/

  echo ">> Creating configmap bench-publish (unchanged publish script)..."
  kubectl create configmap bench-publish -n "${NS}" \
    --from-file=publish_to_aigit.py=benchmarks/k8s/publish_to_aigit.py

  echo ">> Applying Job (job.yaml, unchanged)..."
  kubectl apply -f "${JOB_YAML}"

  echo ">> Waiting for benchmark Job to complete..."
  # Wait for either Complete or Failed; then capture the result JSON + console
  # report out of the pod logs (the Job prints ===RESULTS_JSON_START/END=== and
  # ===REPORT_TXT_START/END=== markers).
  kubectl wait --for=condition=complete "job/${JOB}" -n "${NS}" \
    --timeout="${JOB_COMPLETE_TIMEOUT}s" || \
    kubectl wait --for=condition=failed "job/${JOB}" -n "${NS}" --timeout=30s || true

  # Grab the Job logs ONCE, then scrape both marker blocks out of them.
  local job_logs="${WORKDIR}/joblogs-$(sanitize "${model_id}").txt"
  kubectl logs "job/${JOB}" -n "${NS}" 2>/dev/null > "${job_logs}" || true

  echo ">> Extracting result JSON from Job logs -> ${dest_json} (transient)"
  # Pull the JSON between the markers the Job emits on stdout. Kept only in the
  # temp WORKDIR: it feeds the comparison matrix, never lands in results-incluster.
  awk '/===RESULTS_JSON_START===/{f=1;next} /===RESULTS_JSON_END===/{f=0} f' \
    "${job_logs}" > "${dest_json}" || true

  echo ">> Extracting console report from Job logs -> ${dest_report}"
  # Pull the human-readable report between its markers into the per-model folder.
  mkdir -p "$(dirname "${dest_report}")"
  awk '/===REPORT_TXT_START===/{f=1;next} /===REPORT_TXT_END===/{f=0} f' \
    "${job_logs}" > "${dest_report}" || true

  if [ ! -s "${dest_json}" ]; then
    echo "   WARNING: no result JSON captured for ${display}. Job logs:"
    tail -40 "${job_logs}" 2>/dev/null || true
  else
    echo "   saved JSON $(wc -c < "${dest_json}") bytes (transient)."
  fi
  if [ ! -s "${dest_report}" ]; then
    echo "   WARNING: no console report captured for ${display}."
  else
    echo "   saved report $(wc -c < "${dest_report}") bytes -> ${dest_report}"
  fi

  # Clean up the Job before the next model.
  kubectl delete job "${JOB}" -n "${NS}" --ignore-not-found >/dev/null 2>&1 || true
}

# =============================================================================
# 3. PER-MODEL LOOP
# =============================================================================
echo ""
echo ">> Starting per-model benchmark sweep..."
while IFS=$'\t' read -r model_name model_source; do
  [ -n "${model_name}" ] || continue
  slug="$(sanitize "${model_source:-$model_name}")"
  # Result JSON is TRANSIENT (temp WORKDIR): it only feeds the comparison matrix.
  # The human-readable report is the sole per-model artifact in results-incluster,
  # under a per-model folder: results-incluster/<slug>/report.txt.
  dest_json="${WORKDIR}/results-${slug}.json"
  dest_report="${RESULTS_DIR}/${slug}/report.txt"

  echo ""
  echo "==============================================================="
  echo ">> MODEL: ${model_name}  (source: ${model_source})  slug: ${slug}"
  echo "==============================================================="

  if [ -n "${PROD_MODEL_REF}" ] && [ "${model_name}" = "${PROD_MODEL_REF}" ]; then
    # --- Case A: already served by prod qwen -> benchmark in place. ----------
    echo ">> This model is already served by prod ${PROD_ISVC}; benchmarking in"
    echo "   place against http://${PROD_ISVC}.${NS}.svc.cluster.local:8000/v1"
    echo "   (no serving change, prod stays at full ${CAPTURED_QWEN_REPLICAS} replicas)."
    run_benchmark_job \
      "http://${PROD_ISVC}.${NS}.svc.cluster.local:8000/v1" \
      "${model_source}" \
      "${model_name} (prod, in-place)" \
      "${dest_json}" \
      "${dest_report}"
  else
    # --- Case B: not served -> free a GPU, spin up a temp InferenceService. --
    bench_isvc="bench-${slug}"
    bench_host="${bench_isvc}.${NS}.svc.cluster.local"

    suspend_flux                       # stop Flux from fighting us
    scale_qwen_to 1                    # free 1 GPU (prod now HALF capacity!)
    wait_free_gpu                      # wait until the GPU is actually released

    echo ">> Creating temp InferenceService ${bench_isvc}..."
    manifest="$(make_temp_isvc "${bench_isvc}" "${model_name}" "${model_source}")"
    # Idempotent: delete any stray same-named bench-* first so a prior partial run
    # (or a leftover from a crash) doesn't cause AlreadyExists / stale-spec issues.
    # --wait=true ensures the old one (and its GPU claim) is gone before we apply.
    kubectl delete inferenceservice "${bench_isvc}" -n "${NS}" --ignore-not-found --wait=true
    TEMP_ISVCS+=("${bench_isvc}")      # track for the restore trap (before create)
    kubectl apply -f "${manifest}"

    # Wait for it to serve (first serve downloads weights -> long timeout).
    if wait_isvc_ready "${bench_host}"; then
      run_benchmark_job \
        "http://${bench_host}:8000/v1" \
        "${model_source}" \
        "${model_name} (bench, single-GPU)" \
        "${dest_json}" \
        "${dest_report}"
    else
      echo ">> Skipping benchmark for ${model_name}: endpoint never became ready."
    fi

    # Tear down the temp InferenceService before the next model (frees its GPU).
    echo ">> Deleting temp InferenceService ${bench_isvc}..."
    kubectl delete inferenceservice "${bench_isvc}" -n "${NS}" --ignore-not-found --wait=true
    # Drop it from the tracked list (already deleted).
    TEMP_ISVCS=("${TEMP_ISVCS[@]/${bench_isvc}}")

    # Restore prod to full capacity between models so it isn't degraded during
    # the gaps. (The trap also does this on exit; doing it here is a courtesy.)
    scale_qwen_to "${CAPTURED_QWEN_REPLICAS}"
  fi
done <<< "${MODEL_LINES}"

# =============================================================================
# 4. COMPARISON MATRIX + PUBLISH
# =============================================================================
echo ""
echo ">> Building comparison matrix from all (transient) result JSONs..."
MATRIX_MD="${RESULTS_DIR}/COMPARISON-MATRIX.md"
# The per-model result JSONs live ONLY in the temp WORKDIR (never in
# results-incluster). Glob them from there to feed compare_models.py, then let
# the EXIT trap discard them with the WORKDIR.
shopt -s nullglob
RESULT_JSONS=("${WORKDIR}"/results-*.json)
shopt -u nullglob
if [ "${#RESULT_JSONS[@]}" -eq 0 ]; then
  echo ">> No result JSONs found; skipping matrix + publish."
else
  # Matrix is text -> keep it as COMPARISON-MATRIX.md in results-incluster.
  "${PYTHON}" "${COMPARE_PY}" "${RESULT_JSONS[@]}" --output "${MATRIX_MD}"
  echo ">> Matrix written to ${MATRIX_MD}"

  # Publish ONLY the text artifacts to aigit, reusing publish_to_aigit.py at
  # RUNTIME (not edited). It uploads every file in RESULTS_DIR -> aigit and
  # opens/updates a PR. It reads credentials from AIGIT_* env / the aigit-publish
  # secret; without a token it prints "publish skipped" and returns 0. We point
  # RESULTS_DIR at a staging dir holding just the per-model <slug>/report.txt
  # files + the COMPARISON-MATRIX.md -- NO json/csv, and no stale artifacts.
  echo ">> Publishing per-model report.txt + matrix to aigit (reusing publish_to_aigit.py)..."
  STAGE="${WORKDIR}/publish"
  mkdir -p "${STAGE}"
  cp "${MATRIX_MD}" "${STAGE}/" 2>/dev/null || true
  # Stage each per-model report as <slug>-report.txt so filenames stay unique in
  # the flat upload dir the publish script uses (it globs RESULTS_DIR top-level).
  shopt -s nullglob
  for report in "${RESULTS_DIR}"/*/report.txt; do
    slug_dir="$(basename "$(dirname "${report}")")"
    cp "${report}" "${STAGE}/${slug_dir}-report.txt" 2>/dev/null || true
  done
  shopt -u nullglob

  # Pull aigit-publish secret values into env if present (mirrors job.yaml's
  # mapping). Non-fatal if the secret is absent -> publish skips gracefully.
  get_secret() {
    kubectl get secret aigit-publish -n "${NS}" \
      -o jsonpath="{.data.$1}" 2>/dev/null | base64 -d 2>/dev/null || true
  }
  export AIGIT_API="$(get_secret api)"
  export AIGIT_REPO="$(get_secret repo)"
  export AIGIT_USER="$(get_secret user)"
  export AIGIT_TOKEN="$(get_secret token)"
  export RESULTS_DIR="${STAGE}"

  "${PYTHON}" "${REPO_ROOT}/benchmarks/k8s/publish_to_aigit.py" || \
    echo ">> publish step returned non-zero (continuing; results are saved locally)."
fi

echo ""
echo ">> Benchmark sweep complete. Local results in ${RESULTS_DIR}."
echo ">> (Restore trap will now run to return prod + Flux to their original state.)"
# The EXIT trap (restore) handles teardown/restore from here.
