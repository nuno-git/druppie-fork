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
# The cluster has ONE GPU node with TWO GPUs. Prod serves TWO NVFP4 models, one
# per GPU: `qwen-27b` (nvidia/Qwen3.6-27B-NVFP4) and `qwen-35b`
# (nvidia/Qwen3.6-35B-A3B-NVFP4), each replicas:1, both GitOps-managed by the
# Flux `llm-models` Kustomization and both mounting the shared `llm-models-cache`
# PVC (cached HF weights + vLLM compile cache -> fast warm starts). The ns `llm`
# GPU ResourceQuota is hard=2, so both GPUs are normally occupied.
#
# To benchmark a DIFFERENT (not-yet-served) model we must free ONE GPU, so this
# script will TEMPORARILY:
#   * suspend the Flux `llm-models` (child) AND `ai-k8s` (parent) Kustomizations
#     (so Flux won't fight our edits or re-scale the served model back up), and
#   * scale ONE served InferenceService (FREE_SERVICE, default `qwen-35b`) down
#     to 0 replicas (freeing 1 GPU), then create a short-lived `bench-<model>`
#     InferenceService on that GPU. The bench isvc ALSO mounts llm-models-cache,
#     so any already-cached weights load fast.
#
# During the run the FREE_SERVICE model is OFFLINE (0 replicas); the OTHER served
# model keeps running. A trap ALWAYS restores FREE_SERVICE to its original
# replica count and resumes Flux on exit -- even on Ctrl-C or error. Still: run
# this in a maintenance window.
#
# A model that is ALREADY served (qwen-27b / qwen-35b) is benchmarked in place
# (no serving change, no scaling).
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
# NEW dual-NVFP4 topology: two GitOps-managed InferenceServices, one model per
# GPU, each replicas:1, both mounting the shared cache PVC. To free a GPU we
# scale ONE of them (FREE_SERVICE) to 0 for the duration of the run; the other
# served model keeps running.
FREE_SERVICE="${FREE_SERVICE:-qwen-35b}"          # served isvc to scale 0 to free a GPU
SERVED_MATCH_GLOB="${SERVED_MATCH_GLOB:-qwen-*}"  # name-glob to discover served isvcs
FREE_SERVICE_DEFAULT_REPLICAS=1                    # documented per-service baseline; captured live below
SHARED_CACHE_PVC="${SHARED_CACHE_PVC:-llm-models-cache}"       # RWO PVC both serving pods + bench pod mount (same node)
DEFAULT_BENCH_IMAGE="${DEFAULT_BENCH_IMAGE:-vllm/vllm-openai:cu129-nightly}"  # bench isvc image (profile-overridable)
FLUX_KUSTOMIZATION=llm-models        # Flux Kustomization that manages the models
# The PARENT Flux Kustomization that reconciles (and re-applies) the child
# `llm-models` on a ~1-min interval. Suspending ONLY the child is not enough:
# the parent re-applies the child and resets replicas within ~1 min, undoing our
# scale-down. We suspend BOTH and restore BOTH on exit.
PARENT_FLUX_KUSTOMIZATION=ai-k8s     # parent Kustomization (ns flux-system)
FLUX_NS=flux-system                  # namespace both Kustomizations live in
# Job naming: the sweep uses a UNIQUE per-model Job name `llm-benchmark-<slug>`
# so it can never collide with a MANUAL `llm-benchmark` Job (which the startup
# collision-guard checks for). MANUAL_JOB is that reserved manual name.
JOB_PREFIX=llm-benchmark             # sweep Job name prefix (per-model: llm-benchmark-<slug>)
MANUAL_JOB=llm-benchmark             # reserved name for a manual/parallel run (collision guard)
# Ready-wait budget. A bench model's first serve may download the FULL model from
# HF -- BUT the shared llm-models-cache PVC often already holds the weights + the
# vLLM compile cache (warm start), so this is usually fast. We ALSO fast-fail the
# moment the bench pod crashloops / errors (see wait_isvc_ready), so a broken
# model no longer burns the whole budget. Overridable via the environment.
GPU_READY_TIMEOUT="${GPU_READY_TIMEOUT:-2400}"   # 40 min serve budget (cached weights => usually faster)
# Benchmark-completion wait. Must be >= the Job's activeDeadlineSeconds (9000s in
# job.yaml): the full suite has scenarios that take 100-200s each, so 1800s is far
# too short. Match the Job deadline so we wait for the Job to finish (or hit its
# own deadline) rather than giving up early and losing results.
JOB_COMPLETE_TIMEOUT="${JOB_COMPLETE_TIMEOUT:-9000}"

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
CANDIDATES_YAML="${REPO_ROOT}/benchmarks/candidates.yaml"  # fit-class + serving profiles

# Workspace for temp configs / manifests -- cleaned up on exit.
WORKDIR="$(mktemp -d)"

# -----------------------------------------------------------------------------
# State captured at startup (used by the restore trap). Defaults are safe so a
# trap firing before capture still does something sane.
# -----------------------------------------------------------------------------
CAPTURED_FREE_REPLICAS="${FREE_SERVICE_DEFAULT_REPLICAS}"  # FREE_SERVICE's original replicas
CAPTURED_FLUX_SUSPENDED="false"      # was the CHILD (llm-models) already suspended?
CAPTURED_PARENT_FLUX_SUSPENDED="false"  # was the PARENT (ai-k8s) already suspended?
FLUX_TOUCHED="false"                 # did WE change either suspend state?
FREE_TOUCHED="false"                 # did WE scale FREE_SERVICE?
declare -a TEMP_ISVCS=()             # bench-* InferenceServices we created
declare -a TEMP_MODELS=()            # bench-model-* Model CRs we created (CR-less candidates)
declare -a TEMP_JOBS=()              # llm-benchmark-<slug> Jobs we created

# -----------------------------------------------------------------------------
# restore() -- ALWAYS runs on EXIT/INT/TERM. Idempotent and tolerant of partial
# state: every step is guarded and never aborts the others (we clear -e here).
# -----------------------------------------------------------------------------
restore() {
  local exit_code=$?
  set +e
  echo ""
  echo ">> [restore] Cleaning up (exit code ${exit_code})..."

  # 1. Delete any temp bench-* InferenceServices we created, WAITING for each to
  #    go away (--wait=true) so its GPU is actually released BEFORE we scale
  #    FREE_SERVICE back up in step 2 -- otherwise FREE_SERVICE's replica is
  #    quota-rejected (the `llm` GPU ResourceQuota is hard=2 and the bench pod
  #    still holds one). Also do a belt-and-braces sweep for anything named
  #    bench-* in case a name wasn't tracked (e.g. crash right after create).
  for isvc in "${TEMP_ISVCS[@]:-}"; do
    [ -n "${isvc}" ] || continue
    echo ">> [restore] Deleting temp InferenceService ${isvc} (waiting for GPU release)..."
    kubectl delete inferenceservice "${isvc}" -n "${NS}" --ignore-not-found --wait=true
  done
  # Sweep any stray bench-* left behind (also wait, same GPU-release reasoning).
  local strays
  strays="$(kubectl get inferenceservice -n "${NS}" -o name 2>/dev/null | grep '/bench-' || true)"
  if [ -n "${strays}" ]; then
    echo ">> [restore] Removing stray bench-* InferenceServices:"
    echo "${strays}"
    echo "${strays}" | xargs -r kubectl delete -n "${NS}" --ignore-not-found --wait=true
  fi

  # 1b. Delete any temp Model CRs we created for CR-less candidates (Case B).
  #     Done AFTER their bench InferenceService is gone (step 1) since the isvc
  #     modelRef references the Model. Model CRs hold no GPU, so no quota concern.
  #     Also sweep any stray bench-model-* left behind by a crash mid-create.
  for m in "${TEMP_MODELS[@]:-}"; do
    [ -n "${m}" ] || continue
    echo ">> [restore] Deleting temp Model CR ${m}..."
    kubectl delete models.inference.llmkube.dev "${m}" -n "${NS}" --ignore-not-found --wait=false >/dev/null 2>&1 || true
  done
  local model_strays
  model_strays="$(kubectl get models.inference.llmkube.dev -n "${NS}" -o name 2>/dev/null | grep '/bench-model-' || true)"
  if [ -n "${model_strays}" ]; then
    echo ">> [restore] Removing stray bench-model-* Model CRs:"
    echo "${model_strays}"
    echo "${model_strays}" | xargs -r kubectl delete -n "${NS}" --ignore-not-found --wait=false >/dev/null 2>&1 || true
  fi

  # 2. Restore FREE_SERVICE replicas to the captured original (only if we scaled).
  #    Runs AFTER the bench GPU is released (step 1) so the replica schedules.
  if [ "${FREE_TOUCHED}" = "true" ]; then
    echo ">> [restore] Restoring ${FREE_SERVICE} to ${CAPTURED_FREE_REPLICAS} replica(s)..."
    kubectl patch inferenceservice "${FREE_SERVICE}" -n "${NS}" --type merge \
      -p "{\"spec\":{\"replicas\":${CAPTURED_FREE_REPLICAS}}}" || \
      echo ">> [restore] WARNING: failed to restore ${FREE_SERVICE} replicas -- check manually!"
  fi

  # 3. Resume BOTH Flux Kustomizations to their ORIGINAL suspend states (only if
  #    we changed them). Restore the PARENT (ai-k8s) too -- it is what re-applies
  #    the child and would otherwise reconcile qwen back regardless.
  if [ "${FLUX_TOUCHED}" = "true" ]; then
    echo ">> [restore] Restoring Flux ${FLUX_KUSTOMIZATION} suspend=${CAPTURED_FLUX_SUSPENDED}..."
    kubectl patch kustomization "${FLUX_KUSTOMIZATION}" -n "${FLUX_NS}" --type merge \
      -p "{\"spec\":{\"suspend\":${CAPTURED_FLUX_SUSPENDED}}}" || \
      echo ">> [restore] WARNING: failed to restore Flux ${FLUX_KUSTOMIZATION} suspend -- check manually!"
    echo ">> [restore] Restoring Flux ${PARENT_FLUX_KUSTOMIZATION} suspend=${CAPTURED_PARENT_FLUX_SUSPENDED}..."
    kubectl patch kustomization "${PARENT_FLUX_KUSTOMIZATION}" -n "${FLUX_NS}" --type merge \
      -p "{\"spec\":{\"suspend\":${CAPTURED_PARENT_FLUX_SUSPENDED}}}" || \
      echo ">> [restore] WARNING: failed to restore Flux ${PARENT_FLUX_KUSTOMIZATION} suspend -- check manually!"
  fi

  # 4. Best-effort: delete any per-model benchmark Jobs WE created so they don't
  #    linger. Only our tracked `llm-benchmark-<slug>` Jobs -- never a manual
  #    `llm-benchmark` Job (we abort on that rather than touch it).
  for j in "${TEMP_JOBS[@]:-}"; do
    [ -n "${j}" ] || continue
    kubectl delete job "${j}" -n "${NS}" --ignore-not-found --wait=false >/dev/null 2>&1 || true
  done

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
  echo "This will temporarily scale served ${FREE_SERVICE} to 0 replicas and"
  echo "suspend Flux ${FLUX_KUSTOMIZATION}/${PARENT_FLUX_KUSTOMIZATION} to free a GPU"
  echo "for benchmarking other models. The OTHER served model keeps running."
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
# 1b. COLLISION GUARD -- never clobber a manual/parallel benchmark run.
# =============================================================================
# If a manual `llm-benchmark` Job is currently RUNNING in ns llm (someone kicked
# off a single-model run in parallel), ABORT NOW -- BEFORE scaling or suspending
# anything -- so we can't corrupt their run or double-book a GPU. Our own sweep
# Jobs are named `llm-benchmark-<slug>` (unique per model) and never match this
# reserved name, so a running sweep will not trip its own guard.
echo ">> Collision guard: checking for a RUNNING ${MANUAL_JOB} Job in ns ${NS}..."
MANUAL_ACTIVE="$(kubectl get job "${MANUAL_JOB}" -n "${NS}" \
  -o jsonpath='{.status.active}' 2>/dev/null || true)"
if [ -n "${MANUAL_ACTIVE}" ] && [ "${MANUAL_ACTIVE}" != "0" ]; then
  echo "ERROR: a manual '${MANUAL_JOB}' Job is active (${MANUAL_ACTIVE} pod(s)) in ns ${NS}." >&2
  echo "       Refusing to run the sweep so we don't clobber it. Nothing was scaled." >&2
  exit 1
fi
echo "   no active manual ${MANUAL_JOB} Job; proceeding."

# =============================================================================
# 2. LOAD candidates + DISCOVER served services / cluster CRDs + capture state
# =============================================================================
# The sweep is driven by the LOCAL candidate list (candidates.yaml), NOT by
# whatever Model CRDs happen to already exist in the cluster. This is what makes
# "benchmark all models" actually true: a candidate that has no manually-
# registered CRD still gets a temp Model CR + bench InferenceService created for
# it (Case B), and candidates that cannot run on this 1-node/2-GPU topology
# (too-large / needs-2gpu / API-only) are recorded as skips up front WITHOUT
# touching the cluster. Cluster Model CRDs are still discovered below, but ONLY
# as a lookup table (to reuse an existing CR as the bench modelRef, and to detect
# which candidates are already served -> Case A benchmark-in-place).
echo ">> Loading candidates from ${CANDIDATES_YAML}..."
# CANDIDATE_LINES: one TAB-separated record per candidate --
#   name<TAB>source<TAB>slug<TAB>category<TAB>fit
CANDIDATE_LINES="$(CAND_FILE="${CANDIDATES_YAML}" "${PYTHON}" - <<'PY' || true
import os, sys
try:
    import yaml
except ImportError:
    sys.stderr.write("PyYAML required to read candidates.yaml\n")
    sys.exit(2)
try:
    doc = yaml.safe_load(open(os.environ["CAND_FILE"], encoding="utf-8")) or {}
except Exception as exc:  # noqa: BLE001
    sys.stderr.write("Failed to parse candidates.yaml: %s\n" % exc)
    sys.exit(2)
for m in doc.get("models") or []:
    name = (m.get("name") or "").strip()
    source = (m.get("source") or "").strip()
    slug = (m.get("slug") or "").strip()
    category = (m.get("category") or "").strip().lower()
    fit = (m.get("fit") or "").strip().lower()
    if not (name or source or slug):
        continue
    # Fields never contain tabs, so TAB is a safe separator.
    print("\t".join([name, source, slug, category, fit]))
PY
)"

# Apply the optional --only filter: keep a candidate whose NAME, slug, or source
# last-segment EXACTLY equals one of the comma-separated tokens. Exact (not
# substring) so e.g. "qwen3.6-27b" does not also match "qwen3.6-27b-nvfp4".
if [ -n "${ONLY_FILTER}" ]; then
  KEPT=""
  while IFS=$'\t' read -r _cname _csrc _cslug _ccat _cfit; do
    [ -n "${_cname}${_cslug}" ] || continue
    _cseg="$(sanitize "${_csrc:-$_cname}")"
    IFS=',' read -ra _toks <<< "${ONLY_FILTER}"
    for _t in "${_toks[@]}"; do
      [ -n "${_t}" ] || continue
      if [ "${_cname}" = "${_t}" ] || [ "${_cslug}" = "${_t}" ] || [ "${_cseg}" = "${_t}" ]; then
        KEPT+="${_cname}"$'\t'"${_csrc}"$'\t'"${_cslug}"$'\t'"${_ccat}"$'\t'"${_cfit}"$'\n'; break
      fi
    done
  done <<< "${CANDIDATE_LINES}"
  CANDIDATE_LINES="$(printf '%s' "${KEPT}" | sed '/^$/d')"
  echo ">> --only '${ONLY_FILTER}': narrowed to $(printf '%s\n' "${CANDIDATE_LINES}" | grep -c . || true) candidate(s)."
fi

if [ -z "${CANDIDATE_LINES}" ]; then
  echo "No candidates found in ${CANDIDATES_YAML} (or none matched --only). Nothing to do." >&2
  exit 0
fi
echo ">> Candidates to process (name / source / slug / category / fit):"
printf '%s\n' "${CANDIDATE_LINES}" | sed 's/^/   - /'

echo ">> Discovering cluster Model CRDs (models.inference.llmkube.dev -n ${NS}) for modelRef lookup..."
MODELS_JSON="$(kubectl get models.inference.llmkube.dev -n "${NS}" -o json 2>/dev/null || echo '{}')"

# CLUSTER_MODEL_LINES: "name<TAB>source" for each registered Model CR. Used ONLY
# as a lookup (cluster_crd_for_source) -- NOT iterated. `source` is the
# HF/registry model id; we fall back through the common CRD spec fields.
CLUSTER_MODEL_LINES="$(printf '%s' "${MODELS_JSON}" | "${PYTHON}" -c '
import json, sys
try:
    doc = json.load(sys.stdin)
except Exception:
    doc = {}
for item in doc.get("items", []) or []:
    name = item.get("metadata", {}).get("name", "")
    spec = item.get("spec", {}) or {}
    # Try the likely source fields in priority order.
    source = (spec.get("source") or spec.get("model") or spec.get("modelId")
              or spec.get("uri") or spec.get("repo") or name)
    print(f"{name}\t{source}")
' || true)"
echo "   registered Model CRs (name<TAB>source):"
printf '%s\n' "${CLUSTER_MODEL_LINES}" | sed '/^$/d; s/^/     /' 2>/dev/null || true

# Discover the currently-SERVED InferenceServices (one model per GPU). Match by
# name-glob (SERVED_MATCH_GLOB, default qwen-*) OR any Flux-owned isvc (labelled
# kustomize.toolkit.fluxcd.io/name). Their modelRefs tell us which discovered
# models are ALREADY served (-> benchmark in place, Case A, no scaling).
echo ">> Discovering served InferenceServices (${SERVED_MATCH_GLOB} or Flux-owned) in ns ${NS}..."
SERVED_ISVCS="$(kubectl get inferenceservice -n "${NS}" -o json 2>/dev/null | "${PYTHON}" -c '
import fnmatch, json, os, sys
glob = os.environ.get("SERVED_MATCH_GLOB", "qwen-*")
try:
    doc = json.load(sys.stdin)
except Exception:
    doc = {}
for it in doc.get("items", []) or []:
    meta = it.get("metadata", {}) or {}
    name = meta.get("name", "")
    if not name:
        continue
    labels = meta.get("labels", {}) or {}
    flux_owned = "kustomize.toolkit.fluxcd.io/name" in labels
    if fnmatch.fnmatch(name, glob) or flux_owned:
        spec = it.get("spec", {}) or {}
        ref = spec.get("modelRef")
        if isinstance(ref, dict):
            ref = ref.get("name", "")
        reps = spec.get("replicas", 1)
        # The model the isvc ACTUALLY serves is its vLLM --served-model-name (the
        # OpenAI model id clients query with), else args[0] (the vLLM --model).
        # This is the SOURCE of truth for served detection: the prod qwen CRs carry
        # the bf16 HF repo as spec.source but SERVE the NVFP4 build via args, so
        # matching a candidate against the CR spec.source misses them.
        args = spec.get("args") or []
        served_id = ""
        for i, a in enumerate(args):
            if a == "--served-model-name" and i + 1 < len(args):
                served_id = str(args[i + 1]); break
        if not served_id:
            for a in args:
                if not str(a).startswith("-"):
                    served_id = str(a); break
        print("%s\t%s\t%s\t%s" % (name, ref or "", reps, served_id))
' || true)"
echo "   served services (name<TAB>modelRef<TAB>replicas<TAB>servedModelId):"
printf '%s\n' "${SERVED_ISVCS}" | sed '/^$/d; s/^/     /' 2>/dev/null || true

# served_isvc_for_model() -- echo the served isvc name whose modelRef == $1
# (empty if none). Used to detect Case A (already-served -> benchmark in place).
served_isvc_for_model() {
  local want="$1"
  [ -n "${want}" ] || return 0
  printf '%s\n' "${SERVED_ISVCS}" | while IFS=$'\t' read -r s_name s_ref s_reps s_served; do
    [ -n "${s_name}" ] || continue
    if [ "${s_ref}" = "${want}" ]; then echo "${s_name}"; return 0; fi
  done
}

# served_isvc_for_source() -- echo the served isvc name whose ACTUAL served model
# id (its --served-model-name / args[0]) matches candidate source $1 (empty if
# none). This is the authoritative Case-A check: prod serves the NVFP4 build via
# args while the modelRef CR's spec.source is the bf16 base repo, so the served
# NVFP4 candidates only resolve by what is actually served, not by CR spec.source.
#   $1 = candidate source (e.g. nvidia/Qwen3.6-27B-NVFP4)
served_isvc_for_source() {
  local want="$1"
  [ -n "${want}" ] || return 0
  local want_seg; want_seg="$(sanitize "${want}")"
  printf '%s\n' "${SERVED_ISVCS}" | while IFS=$'\t' read -r s_name s_ref s_reps s_served; do
    [ -n "${s_name}" ] || continue
    [ -n "${s_served}" ] || continue
    if [ "${s_served}" = "${want}" ] || [ "$(sanitize "${s_served}")" = "${want_seg}" ]; then
      echo "${s_name}"; return 0
    fi
  done
}

# cluster_crd_for_source() -- echo the name of an EXISTING cluster Model CR that
# corresponds to a candidate `source` (empty if none). Matches by exact source,
# by the sanitized last-segment of the CR's source, or by the CR name equalling
# the wanted token. Used to (a) reuse a registered CR as the bench modelRef and
# (b) drive Case-A served detection (served isvc modelRef == this CR name).
#   $1 = candidate source (e.g. nvidia/Qwen3.6-27B-NVFP4)
cluster_crd_for_source() {
  local want="$1"
  [ -n "${want}" ] || return 0
  local want_seg; want_seg="$(sanitize "${want}")"
  printf '%s\n' "${CLUSTER_MODEL_LINES}" | while IFS=$'\t' read -r c_name c_src; do
    [ -n "${c_name}" ] || continue
    if [ "${c_src}" = "${want}" ] \
       || [ "$(sanitize "${c_src:-$c_name}")" = "${want_seg}" ] \
       || [ "${c_name}" = "${want}" ]; then
      echo "${c_name}"; return 0
    fi
  done
}

# Capture FREE_SERVICE's current replicas so restore returns it exactly.
echo ">> Capturing FREE_SERVICE (${FREE_SERVICE}) state..."
CAPTURED_FREE_REPLICAS="$(kubectl get inferenceservice "${FREE_SERVICE}" -n "${NS}" \
  -o jsonpath='{.spec.replicas}' 2>/dev/null || true)"
[ -n "${CAPTURED_FREE_REPLICAS}" ] || CAPTURED_FREE_REPLICAS="${FREE_SERVICE_DEFAULT_REPLICAS}"
echo "   ${FREE_SERVICE} replicas: ${CAPTURED_FREE_REPLICAS}"

# Capture BOTH Flux Kustomizations' suspend state so restore returns each to
# exactly what it was (child llm-models AND parent ai-k8s).
CAPTURED_FLUX_SUSPENDED="$(kubectl get kustomization "${FLUX_KUSTOMIZATION}" -n "${FLUX_NS}" \
  -o jsonpath='{.spec.suspend}' 2>/dev/null || true)"
[ -n "${CAPTURED_FLUX_SUSPENDED}" ] || CAPTURED_FLUX_SUSPENDED="false"
CAPTURED_PARENT_FLUX_SUSPENDED="$(kubectl get kustomization "${PARENT_FLUX_KUSTOMIZATION}" -n "${FLUX_NS}" \
  -o jsonpath='{.spec.suspend}' 2>/dev/null || true)"
[ -n "${CAPTURED_PARENT_FLUX_SUSPENDED}" ] || CAPTURED_PARENT_FLUX_SUSPENDED="false"
echo "   flux suspended: ${FLUX_KUSTOMIZATION}=${CAPTURED_FLUX_SUSPENDED} ${PARENT_FLUX_KUSTOMIZATION}=${CAPTURED_PARENT_FLUX_SUSPENDED}"

# =============================================================================
# Helpers for the per-model loop
# =============================================================================

# suspend_flux() -- suspend BOTH the child (llm-models) AND parent (ai-k8s)
# Kustomizations so Flux won't undo our temporary scaling / temp InferenceService.
# Suspending only the child is insufficient: the parent reconciles on a ~1-min
# interval and re-applies the child, resetting qwen to replicas:2 within a minute.
# Records that WE touched Flux so restore returns both to their captured states.
suspend_flux() {
  if [ "${FLUX_TOUCHED}" != "true" ]; then
    echo ">> Suspending Flux ${PARENT_FLUX_KUSTOMIZATION} (parent, was suspend=${CAPTURED_PARENT_FLUX_SUSPENDED})..."
    kubectl patch kustomization "${PARENT_FLUX_KUSTOMIZATION}" -n "${FLUX_NS}" --type merge \
      -p '{"spec":{"suspend":true}}'
    echo ">> Suspending Flux ${FLUX_KUSTOMIZATION} (child, was suspend=${CAPTURED_FLUX_SUSPENDED})..."
    kubectl patch kustomization "${FLUX_KUSTOMIZATION}" -n "${FLUX_NS}" --type merge \
      -p '{"spec":{"suspend":true}}'
    FLUX_TOUCHED="true"
  fi
}

# scale_free_service_to() -- scale FREE_SERVICE; record that WE touched it so
# restore acts. Scaling to 0 frees its GPU for a bench InferenceService.
scale_free_service_to() {
  local n="$1"
  echo ">> Scaling served ${FREE_SERVICE} to ${n} replica(s)..."
  kubectl patch inferenceservice "${FREE_SERVICE}" -n "${NS}" --type merge \
    -p "{\"spec\":{\"replicas\":${n}}}"
  FREE_TOUCHED="true"
}

# wait_free_gpu() -- wait until FREE_SERVICE's GPU is released. Simple proxy:
# wait for FREE_SERVICE's scaled-down pods to actually leave (target 0) so the
# freed GPU is available before we schedule the temp InferenceService.
wait_free_gpu() {
  echo ">> Waiting for scaled-down ${FREE_SERVICE} pod(s) to terminate (GPU release)..."
  for _ in $(seq 1 60); do
    local running
    running="$(kubectl get pods -n "${NS}" -l "serving.llmkube.dev/inferenceservice=${FREE_SERVICE}" \
      --field-selector=status.phase=Running -o name 2>/dev/null | wc -l | tr -d ' ')"
    echo "   running ${FREE_SERVICE} pods: ${running} (target 0)"
    [ "${running}" -le 0 ] && { echo "   GPU should be free."; return 0; }
    sleep 5
  done
  echo "   WARNING: timed out waiting for GPU release; proceeding anyway."
}

# candidate_field() -- read a single field for a model from candidates.yaml,
# matching by slug (primary) or the last path segment of `source` (fallback).
# Emits the field's value (empty if the model or field is absent). Fields:
#   fit | skip_reason   -> plain string
#   profile             -> compact JSON ("{}" when there is no profile)
#   $1 = field   $2 = slug   $3 = source
candidate_field() {
  local field="$1" slug="$2" source="$3"
  [ -f "${CANDIDATES_YAML}" ] || { [ "${field}" = "profile" ] && echo "{}"; return 0; }
  CAND_FILE="${CANDIDATES_YAML}" CAND_FIELD="${field}" CAND_SLUG="${slug}" CAND_SRC="${source}" \
  "${PYTHON}" - <<'PY'
import json, os, sys
try:
    import yaml
except ImportError:
    # No PyYAML -> behave as "no data" (profile => {}), never abort the sweep.
    print("{}" if os.environ["CAND_FIELD"] == "profile" else "")
    sys.exit(0)

field = os.environ["CAND_FIELD"]
slug = os.environ["CAND_SLUG"].strip().lower()
src = os.environ["CAND_SRC"].strip().lower()
src_seg = src.rsplit("/", 1)[-1]

def norm(v):
    return (v or "").strip().lower()

doc = {}
try:
    doc = yaml.safe_load(open(os.environ["CAND_FILE"], encoding="utf-8")) or {}
except Exception:
    doc = {}

match = None
for m in doc.get("models") or []:
    m_slug = norm(m.get("slug"))
    m_src_seg = norm(m.get("source")).rsplit("/", 1)[-1]
    if slug and (slug == m_slug or (src_seg and src_seg == m_src_seg) or slug == m_src_seg):
        match = m
        break

if field == "profile":
    print(json.dumps((match or {}).get("profile") or {}))
else:
    print(((match or {}).get(field) or "").strip() if isinstance((match or {}).get(field), str)
          else ((match or {}).get(field) or ""))
PY
}

# record_skip() -- persist a one-line skip/failure REASON for a model so it lands
# in BOTH matrices (compare_models.py + update_test_matrix.py read SKIPPED.txt).
#   $1 = slug   $2 = reason
record_skip() {
  local slug="$1" reason="$2"
  local dir="${RESULTS_DIR}/${slug}"
  mkdir -p "${dir}"
  printf '%s\n' "${reason}" > "${dir}/SKIPPED.txt"
  # CRITICAL: drop any prior GOOD report.txt. Otherwise update_test_matrix.py /
  # compare_models.py still see a report and mark the model "Tested" with STALE
  # numbers, masking a regression (a model that used to pass but now skips/fails).
  # A skip must win over a stale report -- mirror what clear_skip does in reverse.
  rm -f "${dir}/report.txt" 2>/dev/null || true
  echo ">> [skip] ${slug}: ${reason}"
}

# clear_skip() -- drop any stale SKIPPED.txt once a model actually produces a
# report (Tested wins over Skipped).
#   $1 = slug
clear_skip() {
  local slug="$1"
  rm -f "${RESULTS_DIR}/${slug}/SKIPPED.txt" 2>/dev/null || true
}

# bench_pod_failure_reason() -- inspect the bench pod and, IF it is unhealthy
# (CrashLoopBackOff / restartCount>=2 / Error / ImagePull*/ Failed), echo a
# concise REASON (status + the last meaningful log error line). Echoes NOTHING
# when the pod is absent or still legitimately progressing (Pending/Running).
#   $1 = bench isvc name (bench-<slug>)
bench_pod_failure_reason() {
  local bench_name="$1"
  local pod
  pod="$(kubectl get pods -n "${NS}" -l "serving.llmkube.dev/inferenceservice=${bench_name}" \
    -o name 2>/dev/null | head -n1)"
  [ -n "${pod}" ] || pod="$(kubectl get pods -n "${NS}" -l "app=${bench_name}" \
    -o name 2>/dev/null | head -n1)"
  [ -n "${pod}" ] || return 0            # no pod yet -> not a failure
  local podname="${pod#*/}"

  local podjson
  podjson="$(kubectl get "${pod}" -n "${NS}" -o json 2>/dev/null)"
  [ -n "${podjson}" ] || return 0

  # Let python classify the pod status; it echoes a short verdict token (e.g.
  # "CrashLoopBackOff" / "restartCount=3" / "phase=Failed") ONLY when unhealthy.
  local verdict
  verdict="$(printf '%s' "${podjson}" | "${PYTHON}" -c '
import json, sys
doc = json.load(sys.stdin)
st = doc.get("status", {}) or {}
if st.get("phase") == "Failed":
    print("phase=Failed"); sys.exit(0)
bad_wait = {"CrashLoopBackOff", "ImagePullBackOff", "ErrImagePull",
            "Error", "CreateContainerError", "RunContainerError",
            "InvalidImageName", "CreateContainerConfigError"}
for cs in st.get("containerStatuses", []) or []:
    state = cs.get("state", {}) or {}
    waiting = state.get("waiting") or {}
    wr = waiting.get("reason", "")
    term = state.get("terminated") or {}
    tr = term.get("reason", "")
    rc = cs.get("restartCount", 0) or 0
    if wr in bad_wait:
        print(wr); sys.exit(0)
    if tr and tr != "Completed":
        print("terminated=%s" % tr); sys.exit(0)
    if rc >= 2:
        print("restartCount=%d" % rc); sys.exit(0)
' 2>/dev/null)"

  [ -n "${verdict}" ] || return 0        # healthy / still progressing

  # Pull the last meaningful error line from the (previous, then current) logs.
  local errpat='ValueError|RuntimeError|AssertionError|OSError|KeyError|Traceback|Exception|[Ee]rror:|CUDA|not supported|out of memory'
  local logline
  logline="$(kubectl logs "${podname}" -n "${NS}" --previous --tail=200 2>/dev/null \
    | grep -E "${errpat}" | tail -n1)"
  [ -n "${logline}" ] || logline="$(kubectl logs "${podname}" -n "${NS}" --tail=200 2>/dev/null \
    | grep -E "${errpat}" | tail -n1)"
  logline="$(printf '%s' "${logline}" | tr -d '\r' | sed -E 's/^[[:space:]]+//; s/[[:space:]]+$//' | cut -c1-300)"

  if [ -n "${logline}" ]; then
    echo "Serving failed (${verdict}): ${logline}"
  else
    echo "Serving failed (${verdict}); no error line in pod logs -- inspect ${podname}."
  fi
}

# make_temp_model_crd() -- write a MINIMAL temp Model CR manifest for a candidate
# that has NO registered cluster Model CR (e.g. the bf16 Qwen variants, gemma bf16
# repos). The bench InferenceService's modelRef must resolve to a Model, so we
# create a throwaway `bench-model-<slug>` Model CR pointing at the candidate's
# source. Serving details (image/args/quant) all live on the InferenceService
# (skipModelInit=True, source in args[0]); the Model CR is essentially just the
# reference target, so we keep its spec minimal (source + inferred format).
#   $1 = model CR name (bench-model-<slug>)   $2 = model source
make_temp_model_crd() {
  local crd_name="$1" model_source="$2"
  local out_yaml="${WORKDIR}/model-${crd_name}.yaml"
  BENCH_MODEL_NAME="${crd_name}" MODEL_SOURCE="${model_source}" BENCH_NS="${NS}" \
  "${PYTHON}" - "${out_yaml}" <<'PY'
import os, sys
try:
    import yaml
except ImportError:
    sys.stderr.write("PyYAML required to template the Model CR.\n")
    sys.exit(1)

dst = sys.argv[1]
name = os.environ["BENCH_MODEL_NAME"]
source = os.environ["MODEL_SOURCE"]
ns = os.environ.get("BENCH_NS", "llm")

# Infer a format from the source string. The InferenceService overrides serving,
# so this is only a best-effort hint for the Model CR.
lower = source.lower()
if "gguf" in lower:
    fmt = "gguf"
elif "mlx" in lower:
    fmt = "mlx"
else:
    fmt = "safetensors"

doc = {
    "apiVersion": "inference.llmkube.dev/v1alpha1",
    "kind": "Model",
    "metadata": {"name": name, "namespace": ns},
    "spec": {"source": source, "format": fmt},
}
yaml.safe_dump(doc, open(dst, "w"), sort_keys=False)
sys.stderr.write("   wrote temp Model CR manifest: %s (format=%s)\n" % (dst, fmt))
PY
  echo "${out_yaml}"
}

# make_temp_isvc() -- write a temp InferenceService manifest for a bench model,
# built FROM SCRATCH to mirror the NEW dual-NVFP4 prod shape:
#   runtime: generic, image: cu129-nightly (profile-overridable), skipModelInit,
#   modelCache -> shared llm-models-cache PVC (cached weights => fast warm start),
#   tolerations nvidia.com/gpu Exists NoSchedule, resources.gpu 1, endpoint
#   {port:8000,type:ClusterIP}, and per-model args from its candidates.yaml
#   profile (or a generic default arg set when profile-less).
# We NO LONGER clone the old prod manifest: the served models are NVFP4 with
# qwen-specific args (--quantization modelopt, --tool-call-parser qwen3_xml) that
# crash other families, so those come ONLY from a per-model profile.
#   $1 = bench isvc name (bench-<slug>)   $2 = models CRD name   $3 = model source
make_temp_isvc() {
  local bench_name="$1" model_crd="$2" model_source="$3"
  local out_yaml="${WORKDIR}/${bench_name}.yaml"

  # Per-model serving profile from candidates.yaml (JSON, "{}" when absent).
  local profile_json
  profile_json="$(candidate_field profile "$(sanitize "${model_source:-$model_crd}")" "${model_source}")"
  [ -n "${profile_json}" ] || profile_json="{}"
  if [ "${profile_json}" != "{}" ]; then
    echo ">> Applying per-model serving profile for ${bench_name}." >&2
  fi

  # Emit the manifest with Python (robust, no fragile sed). Args come from the
  # profile's vllm_args VERBATIM when present (element 0 is the vLLM --model),
  # else a generic default arg set mirroring the prod NVFP4 block MINUS the
  # model-specific bits (source is args[0]; --quantization modelopt is
  # NVFP4-specific; --tool-call-parser qwen3_xml is qwen-specific -> profiles only).
  BENCH_NAME="${bench_name}" MODEL_CRD="${model_crd}" MODEL_SOURCE="${model_source}" \
  BENCH_NS="${NS}" DEFAULT_BENCH_IMAGE="${DEFAULT_BENCH_IMAGE}" SHARED_CACHE_PVC="${SHARED_CACHE_PVC}" \
  PROFILE_JSON="${profile_json}" \
  "${PYTHON}" - "${out_yaml}" <<'PY'
import json, os, sys
try:
    import yaml
except ImportError:
    sys.stderr.write("PyYAML required to template the InferenceService.\n")
    sys.exit(1)

dst = sys.argv[1]
bench = os.environ["BENCH_NAME"]
model_crd = os.environ["MODEL_CRD"]
model_source = os.environ["MODEL_SOURCE"]
ns = os.environ.get("BENCH_NS", "llm")
default_image = os.environ.get("DEFAULT_BENCH_IMAGE", "vllm/vllm-openai:cu129-nightly")
cache_pvc = os.environ.get("SHARED_CACHE_PVC", "llm-models-cache")
try:
    profile = json.loads(os.environ.get("PROFILE_JSON") or "{}") or {}
except ValueError:
    profile = {}

prof_args = profile.get("vllm_args")
if isinstance(prof_args, list) and prof_args:
    args = [str(a) for a in prof_args]
else:
    # Generic default: mirrors the prod NVFP4 block minus model-specific bits.
    args = [
        model_source,
        "--host", "0.0.0.0",
        "--port", "8000",
        "--tensor-parallel-size", "1",
        "--max-model-len", "262144",
        "--max-num-seqs", "256",
        "--max-num-batched-tokens", "16384",
        "--enable-chunked-prefill",
        "--enable-prefix-caching",
        "--gpu-memory-utilization", "0.95",
    ]

spec = {
    # modelRef is a STRING on this CRD -> the target model CRD name.
    "modelRef": model_crd,
    "runtime": "generic",
    "image": profile.get("image") or default_image,
    "replicas": 1,
    # skipModelInit: weights come from args[0] + the shared modelCache PVC, not a
    # model-init download step.
    "skipModelInit": True,
    "args": args,
    "endpoint": {"port": 8000, "type": "ClusterIP"},
    "tolerations": [
        {"key": "nvidia.com/gpu", "operator": "Exists", "effect": "NoSchedule"},
    ],
    "resources": {"gpu": 1, "cpu": "1500m", "memory": "6Gi"},
    # Shared cache PVC: cached HF weights + vLLM compile cache -> fast warm start.
    # RWO is fine because the bench pod lands on the same single GPU node.
    "modelCache": {"claimName": cache_pvc},
}

meta = {"name": bench, "namespace": ns}
# extra_pip is advisory: the stock vLLM image does not pip-install at startup,
# so we only surface it as an annotation for operators (models needing it will
# generally fast-fail with a captured reason). Never silently drop the info.
if profile.get("extra_pip"):
    meta["annotations"] = {
        "bench.druppie/extra-pip": ",".join(str(p) for p in profile["extra_pip"]),
    }

doc = {
    "apiVersion": "inference.llmkube.dev/v1alpha1",
    "kind": "InferenceService",
    "metadata": meta,
    "spec": spec,
}
yaml.safe_dump(doc, open(dst, "w"), sort_keys=False)
sys.stderr.write("   wrote temp InferenceService manifest: %s\n" % dst)
PY
  # ONLY the manifest path goes to stdout -- it is captured by the caller via
  # command substitution. All diagnostics above are redirected to stderr so they
  # don't pollute the captured path.
  echo "${out_yaml}"
}

# wait_isvc_ready() -- poll the temp service's /v1/models until HTTP 200. First
# serve downloads weights from HuggingFace, so allow up to GPU_READY_TIMEOUT --
# BUT fast-fail the instant the bench pod crashloops / errors so a broken model
# does not burn the whole budget while prod runs at half capacity. On failure it
# sets LAST_FAIL_REASON to a concise, matrix-ready reason and returns non-zero.
#   $1 = in-cluster base host (e.g. bench-foo.llm.svc.cluster.local)
#   $2 = bench isvc name (bench-<slug>) -- used to locate the pod for health checks
LAST_FAIL_REASON=""
wait_isvc_ready() {
  local host="$1" bench_name="$2"
  LAST_FAIL_REASON=""
  local deadline=$(( $(date +%s) + GPU_READY_TIMEOUT ))
  echo ">> Waiting for ${host}:8000/v1/models to return 200 (up to ${GPU_READY_TIMEOUT}s; fast-fails on crash)..."
  while [ "$(date +%s)" -lt "${deadline}" ]; do
    # Probe from inside the cluster with a throwaway pod (curl image).
    if kubectl run "bench-probe-$$" -n "${NS}" --rm -i --restart=Never \
        --image=curlimages/curl:8.10.1 --quiet -- \
        -sf -o /dev/null -w '%{http_code}' \
        "http://${host}:8000/v1/models" 2>/dev/null | grep -q '^200'; then
      echo "   endpoint is up."
      return 0
    fi

    # Fast-fail: if the bench pod has crashlooped / errored, stop NOW (don't wait
    # out the full download budget on a model that will never serve).
    local fail_reason
    fail_reason="$(bench_pod_failure_reason "${bench_name}")"
    if [ -n "${fail_reason}" ]; then
      LAST_FAIL_REASON="${fail_reason}"
      echo "   FAST-FAIL: ${fail_reason}"
      return 1
    fi

    echo "   not ready yet; sleeping 15s..."
    sleep 15
  done
  LAST_FAIL_REASON="Endpoint never became ready within ${GPU_READY_TIMEOUT}s (serving did not come up -- e.g. weight download stalled)."
  echo "   ERROR: ${LAST_FAIL_REASON}"
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
#   $6 = Job name (UNIQUE per model: llm-benchmark-<slug>) so a manual
#        `llm-benchmark` Job can never collide with the sweep.
run_benchmark_job() {
  local base_url="$1" model_id="$2" display="$3" dest_json="$4" dest_report="$5" job_name="$6"
  local tmp_config="${WORKDIR}/config-$(sanitize "${model_id}").yaml"
  local tmp_job="${WORKDIR}/job-$(sanitize "${model_id}").yaml"

  echo ">> Building per-model temp config -> ${tmp_config}"
  # Start from the tracked config, then override the single active endpoint's
  # base_url and the single active model's id/display_name. The FIRST endpoint
  # (qwen_incluster) is the active one; target its base_url generically so this
  # works regardless of the tracked default (qwen-27b.llm... today).
  cp "${CONFIG_SRC}" "${tmp_config}"
  # Override the first endpoint's base_url (the active in-cluster endpoint).
  sed -i -E "0,/^    base_url: .*/s||    base_url: \"${base_url}\"|" "${tmp_config}"
  # Override the active model id + display name (first `model:`/`display_name:`).
  sed -i -E "0,/^    model: .*/s||    model: ${model_id}|" "${tmp_config}"
  sed -i -E "0,/^    display_name: .*/s||    display_name: \"${display}\"|" "${tmp_config}"

  # Per-model Job manifest: UNIQUE name (llm-benchmark-<slug>) so it can never
  # collide with a manual `llm-benchmark` Job. Only metadata.name changes; the
  # `app:` labels stay as-is. job.yaml is otherwise applied unchanged.
  cp "${JOB_YAML}" "${tmp_job}"
  sed -i -E "0,/^  name: ${MANUAL_JOB}$/s||  name: ${job_name}|" "${tmp_job}"
  # Gate OFF the in-pod publish for sweep-driven Jobs: the sweep does ONE clean
  # per-slug publish at the end (section 4). Leaving the in-pod publish on would
  # make every per-model Job upload a FLAT results.json + report.txt to the
  # results-incluster root (no <slug>/ subdir), clobbering across models and
  # refreshing the PR once per model. job.yaml defaults SKIP_INPOD_PUBLISH to ""
  # (publish ON, for a standalone single Job run); here we flip it to "1". The
  # sed finds the env var's `name:` line, then rewrites the `value:` on the NEXT
  # line, so it can't accidentally match any other value.
  sed -i '/name: SKIP_INPOD_PUBLISH/{n;s|value: .*|value: "1"|;}' "${tmp_job}"

  echo ">> Cleaning up any prior benchmark Job + configmaps..."
  kubectl delete job "${job_name}" -n "${NS}" --ignore-not-found
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

  echo ">> Applying Job (${job_name}, from job.yaml with unique name)..."
  kubectl apply -f "${tmp_job}"
  TEMP_JOBS+=("${job_name}")            # track for the restore trap

  echo ">> Waiting for benchmark Job to complete..."
  # Wait for either Complete or Failed; then capture the result JSON + console
  # report out of the pod logs (the Job prints ===RESULTS_JSON_START/END=== and
  # ===REPORT_TXT_START/END=== markers).
  kubectl wait --for=condition=complete "job/${job_name}" -n "${NS}" \
    --timeout="${JOB_COMPLETE_TIMEOUT}s" || \
    kubectl wait --for=condition=failed "job/${job_name}" -n "${NS}" --timeout=30s || true

  # Grab the Job logs ONCE, then scrape both marker blocks out of them.
  local job_logs="${WORKDIR}/joblogs-$(sanitize "${model_id}").txt"
  kubectl logs "job/${job_name}" -n "${NS}" 2>/dev/null > "${job_logs}" || true

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
  kubectl delete job "${job_name}" -n "${NS}" --ignore-not-found >/dev/null 2>&1 || true
  # Drop it from the tracked list (already deleted).
  TEMP_JOBS=("${TEMP_JOBS[@]/${job_name}}")
}

# =============================================================================
# 3. PER-MODEL LOOP
# =============================================================================
echo ""
echo ">> Starting per-model benchmark sweep..."
while IFS=$'\t' read -r cand_name cand_source cand_slug cand_category cand_fit; do
  [ -n "${cand_name}${cand_slug}" ] || continue
  # The candidate's slug is authoritative: it is EXACTLY the key that
  # update_test_matrix.py / compare_models.py look for under results-incluster/,
  # so per-model artifacts MUST use it verbatim. Fall back to sanitize(source)
  # only for a malformed candidate with no slug.
  slug="${cand_slug:-$(sanitize "${cand_source:-$cand_name}")}"
  # k8s resource names must be RFC-1035 labels (no dots): the candidate slug can
  # contain dots (e.g. qwen3.6-27b), which would break a Service/InferenceService
  # name and its in-cluster DNS. Derive a dot-free variant for cluster resources
  # (bench isvc, temp Model CR, Job); the results dir still uses the real slug.
  k8s_slug="$(printf '%s' "${slug}" | tr '.' '-')"
  # Result JSON is TRANSIENT (temp WORKDIR): it only feeds the comparison matrix.
  # The human-readable report is the sole per-model artifact in results-incluster,
  # under a per-model folder: results-incluster/<slug>/report.txt.
  dest_json="${WORKDIR}/results-${k8s_slug}.json"
  dest_report="${RESULTS_DIR}/${slug}/report.txt"
  job_name="${JOB_PREFIX}-${k8s_slug}"  # UNIQUE per-model Job (never collides with manual)

  echo ""
  echo "==============================================================="
  echo ">> CANDIDATE: ${cand_name}  (source: ${cand_source})"
  echo "   slug: ${slug}  category: ${cand_category:-?}  fit: ${cand_fit:-?}"
  echo "==============================================================="

  # --- Gate 1: API-only candidates. Not cluster-downloadable weights, so we do
  #     NOT serve them in-cluster. Record a tracked skip so they still appear in
  #     the matrix (tracked-but-not-benchmarked). ------------------------------
  if [ "${cand_category}" = "api" ] || [ "${cand_fit}" = "api" ]; then
    record_skip "${slug}" "API model -- not benchmarked in-cluster (hosted API, no local weights to serve)."
    continue
  fi

  # --- Gate 2: does-not-fit candidates. candidates.yaml classes it too-large /
  #     needs-2gpu; record its skip_reason and move on WITHOUT touching the
  #     cluster (never degrade prod for a model that cannot fit). --------------
  if [ "${cand_fit}" = "too-large" ] || [ "${cand_fit}" = "needs-2gpu" ]; then
    skip_reason="$(candidate_field skip_reason "${slug}" "${cand_source}")"
    [ -n "${skip_reason}" ] || skip_reason="Not benchmarked -- fit class '${cand_fit}' does not fit this hardware (1 freed GPU, ~96GB)."
    echo ">> Size-skip (${cand_fit}): NOT creating a bench InferenceService for ${cand_name}."
    record_skip "${slug}" "${skip_reason}"
    continue
  fi

  # --- Gate 3: unclassified guard. Only `served` and `fits-1gpu` are runnable on
  #     this topology. Anything else (empty / unknown fit) is skipped with a
  #     reason rather than attempted -- so an un-triaged (possibly giant) model
  #     can never OOM-crashloop and degrade prod / waste the GPU budget. --------
  if [ "${cand_fit}" != "served" ] && [ "${cand_fit}" != "fits-1gpu" ]; then
    record_skip "${slug}" "Unclassified fit '${cand_fit:-<none>}' -- not attempted (guard against OOM / wasted GPU time; classify it in candidates.yaml to run)."
    continue
  fi

  # Resolve to an existing cluster Model CR (for modelRef reuse + served
  # detection). A candidate is ALREADY SERVED when its matching CR is the
  # modelRef of a running prod InferenceService (qwen-27b / qwen-35b).
  crd_name="$(cluster_crd_for_source "${cand_source}")"
  # Served detection is authoritative on what the isvc ACTUALLY serves (its
  # --served-model-name / args[0] model id), NOT the modelRef CR's spec.source:
  # the prod qwen CRs carry the bf16 HF repo as spec.source but SERVE the NVFP4
  # build via args, so a spec.source match misses the served NVFP4 candidates.
  # Match candidate source to the served model id first; fall back to the legacy
  # modelRef-based check for any served model whose id isn't discoverable in args.
  serving_isvc="$(served_isvc_for_source "${cand_source}")"
  if [ -z "${serving_isvc}" ] && [ -n "${crd_name}" ]; then
    serving_isvc="$(served_isvc_for_model "${crd_name}")"
  fi

  if [ -n "${serving_isvc}" ]; then
    # --- Case A: already served -> benchmark in place (no serving change). ----
    echo ">> Served by ${serving_isvc} (modelRef ${crd_name}); benchmarking in"
    echo "   place against http://${serving_isvc}.${NS}.svc.cluster.local:8000/v1"
    echo "   (no serving change, no scaling)."
    run_benchmark_job \
      "http://${serving_isvc}.${NS}.svc.cluster.local:8000/v1" \
      "${cand_source}" \
      "${cand_name} (served, in-place)" \
      "${dest_json}" \
      "${dest_report}" \
      "${job_name}"
    if [ -s "${dest_report}" ]; then
      clear_skip "${slug}"
    else
      record_skip "${slug}" "Served model produced no report (see cluster Job logs for ${job_name})."
    fi
    continue
  fi

  # --- Case B: not served -> free a GPU (scale FREE_SERVICE to 0), spin up a
  #     temp InferenceService on that freed GPU (mounts the shared cache PVC).
  #     If the candidate has NO registered cluster Model CR, create a throwaway
  #     bench-model-<slug> Model CR first so the isvc's modelRef resolves. ------
  bench_isvc="bench-${k8s_slug}"
  bench_host="${bench_isvc}.${NS}.svc.cluster.local"

  suspend_flux                         # stop Flux from fighting us / reverting our CRs

  # Create a temp Model CR when no registered CR matches this candidate.
  if [ -z "${crd_name}" ]; then
    crd_name="bench-model-${k8s_slug}"
    echo ">> No registered Model CR for ${cand_source}; creating temp CR ${crd_name}..."
    model_manifest="$(make_temp_model_crd "${crd_name}" "${cand_source}")"
    kubectl delete models.inference.llmkube.dev "${crd_name}" -n "${NS}" --ignore-not-found --wait=true >/dev/null 2>&1 || true
    TEMP_MODELS+=("${crd_name}")       # track for the restore trap (before create)
    if ! kubectl apply -f "${model_manifest}"; then
      # Nothing GPU-side created yet (we only suspended Flux, which the trap
      # restores at exit), so a plain skip + continue is safe here.
      record_skip "${slug}" "Could not create temp Model CR ${crd_name} (apply failed -- check the Model CRD schema)."
      continue
    fi
  fi

  scale_free_service_to 0              # free 1 GPU (FREE_SERVICE now OFFLINE)
  wait_free_gpu                        # wait until the GPU is actually released

  echo ">> Creating temp InferenceService ${bench_isvc} (modelRef ${crd_name})..."
  manifest="$(make_temp_isvc "${bench_isvc}" "${crd_name}" "${cand_source}")"
  # Idempotent: delete any stray same-named bench-* first so a prior partial run
  # (or a leftover from a crash) doesn't cause AlreadyExists / stale-spec issues.
  # --wait=true ensures the old one (and its GPU claim) is gone before we apply.
  kubectl delete inferenceservice "${bench_isvc}" -n "${NS}" --ignore-not-found --wait=true
  TEMP_ISVCS+=("${bench_isvc}")        # track for the restore trap (before create)
  kubectl apply -f "${manifest}"

  # Wait for it to serve (cached weights via the shared PVC usually make this
  # fast; a cold model downloads from HF -> long budget), but fast-fail on a
  # crashloop/error and record a matrix-ready reason.
  if wait_isvc_ready "${bench_host}" "${bench_isvc}"; then
    run_benchmark_job \
      "http://${bench_host}:8000/v1" \
      "${cand_source}" \
      "${cand_name} (bench, single-GPU)" \
      "${dest_json}" \
      "${dest_report}" \
      "${job_name}"
    if [ -s "${dest_report}" ]; then
      clear_skip "${slug}"
    else
      record_skip "${slug}" "Serving came up but the benchmark Job produced no report (see cluster Job logs)."
    fi
  else
    # wait_isvc_ready set LAST_FAIL_REASON (crashloop / error / never-ready).
    record_skip "${slug}" "${LAST_FAIL_REASON:-Endpoint never became ready.}"
  fi

  # Tear down the temp InferenceService before the next model (frees its GPU).
  echo ">> Deleting temp InferenceService ${bench_isvc}..."
  kubectl delete inferenceservice "${bench_isvc}" -n "${NS}" --ignore-not-found --wait=true
  # Drop it from the tracked list (already deleted).
  TEMP_ISVCS=("${TEMP_ISVCS[@]/${bench_isvc}}")

  # Delete the temp Model CR too (if we created one) now its isvc is gone.
  if [ "${crd_name}" = "bench-model-${k8s_slug}" ]; then
    echo ">> Deleting temp Model CR ${crd_name}..."
    kubectl delete models.inference.llmkube.dev "${crd_name}" -n "${NS}" --ignore-not-found --wait=false >/dev/null 2>&1 || true
    TEMP_MODELS=("${TEMP_MODELS[@]/${crd_name}}")
  fi

  # Restore FREE_SERVICE between models so it isn't offline during the gaps.
  # (The trap also does this on exit; doing it here is a courtesy.) The bench
  # isvc above was deleted with --wait=true, so its GPU is free before we scale
  # FREE_SERVICE back up (avoids a quota rejection).
  scale_free_service_to "${CAPTURED_FREE_REPLICAS}"
done <<< "${CANDIDATE_LINES}"

# =============================================================================
# 4. COMPARISON MATRIX + PUBLISH
# =============================================================================
echo ""
echo ">> Building comparison matrix from all (transient) result JSONs..."
MATRIX_MD="${RESULTS_DIR}/COMPARISON-MATRIX.md"
MATRIX_TEST_MD="${RESULTS_DIR}/MODEL-TEST-MATRIX.md"
MATRIX_PY="${REPO_ROOT}/benchmarks/update_test_matrix.py"
# The per-model result JSONs live ONLY in the temp WORKDIR (never in
# results-incluster). Glob them from there to feed compare_models.py, then let
# the EXIT trap discard them with the WORKDIR.
shopt -s nullglob
RESULT_JSONS=("${WORKDIR}"/results-*.json)
shopt -u nullglob

# ALWAYS regenerate the matrices -- even when zero models benchmarked (all skipped).
# compare_models.py renders every registered model from its known-models registry,
# and --results-dir lets it read the per-slug SKIPPED.txt this run wrote so each
# skipped/failed model shows `Skipped -- <reason>` instead of a bare "--". Likewise
# update_test_matrix.py folds those reasons into MODEL-TEST-MATRIX.md.
echo ">> Building COMPARISON-MATRIX.md (${#RESULT_JSONS[@]} benchmarked; skip reasons from ${RESULTS_DIR})..."
"${PYTHON}" "${COMPARE_PY}" "${RESULT_JSONS[@]:-}" --output "${MATRIX_MD}" --results-dir "${RESULTS_DIR}" || \
  echo ">> compare_models step returned non-zero (continuing; matrix may be stale)."
echo ">> Matrix written to ${MATRIX_MD}"

# Regenerate the self-updating model test matrix (candidates + tested/skipped
# status). Non-fatal: a matrix error must never abort the sweep/publish.
echo ">> Updating model test matrix (${MATRIX_TEST_MD})..."
"${PYTHON}" "${MATRIX_PY}" || \
  echo ">> update_test_matrix step returned non-zero (continuing; matrix may be stale)."

# Publish the text artifacts to aigit, reusing publish_to_aigit.py at RUNTIME
# (not edited). It walks RESULTS_DIR recursively and uploads to STABLE,
# model-named paths under benchmarks/results-incluster (each publish OVERWRITES
# the same paths), then opens/updates a PR. It reads credentials from AIGIT_*
# env / the aigit-publish secret; without a token it prints "publish skipped"
# and returns 0. We point RESULTS_DIR at a staging dir that MIRRORS the desired
# aigit tree: per-model <slug>/report.txt (+ SKIPPED.txt) subdirs + the two
# matrices -- NO json/csv, and only the artifacts from THIS run (no stale files).
echo ">> Publishing per-model report.txt/SKIPPED.txt + matrices to aigit (reusing publish_to_aigit.py)..."
STAGE="${WORKDIR}/publish"
mkdir -p "${STAGE}"
cp "${MATRIX_MD}" "${STAGE}/COMPARISON-MATRIX.md" 2>/dev/null || true
cp "${MATRIX_TEST_MD}" "${STAGE}/MODEL-TEST-MATRIX.md" 2>/dev/null || true
# Mirror each per-model report AND skip reason into <slug>/ so the publisher
# preserves the per-model folder structure (stable paths, overwritten each run).
shopt -s nullglob
for report in "${RESULTS_DIR}"/*/report.txt; do
  slug_dir="$(basename "$(dirname "${report}")")"
  mkdir -p "${STAGE}/${slug_dir}"
  cp "${report}" "${STAGE}/${slug_dir}/report.txt" 2>/dev/null || true
done
for skipped in "${RESULTS_DIR}"/*/SKIPPED.txt; do
  slug_dir="$(basename "$(dirname "${skipped}")")"
  mkdir -p "${STAGE}/${slug_dir}"
  cp "${skipped}" "${STAGE}/${slug_dir}/SKIPPED.txt" 2>/dev/null || true
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

echo ""
echo ">> Benchmark sweep complete. Local results in ${RESULTS_DIR}."
echo ">> (Restore trap will now run to return ${FREE_SERVICE} + Flux to their original state.)"
# The EXIT trap (restore) handles teardown/restore from here.
