#!/usr/bin/env bash
# Run the LLM benchmark as an in-cluster Kubernetes Job (ns llm).
#
# Idempotent: deletes any prior Job/configmaps first, recreates the configmaps
# from the local benchmarks/ source tree, applies the Job, and tails the logs.
#
# On completion the Job auto-publishes its results (JSON + CSV + console report)
# to aigit under benchmarks/results-incluster/auto/<runid>/ on branch
# benchmarks/auto-results and ensures an open PR into colab-dev. This uses the
# `aigit-publish` secret in ns llm; without it publishing is silently skipped.
#
# Usage: ./benchmarks/k8s/run-in-cluster.sh
set -euo pipefail

NS=llm
JOB=llm-benchmark

# Resolve repo root relative to this script so it works from anywhere.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
cd "${REPO_ROOT}"

echo ">> Cleaning up any prior run..."
kubectl delete job "${JOB}" -n "${NS}" --ignore-not-found
kubectl delete configmap bench-pkg bench-scenarios bench-publish -n "${NS}" --ignore-not-found

echo ">> Creating configmap bench-pkg (top-level package files)..."
# Only the importable package files + config — keep the configmap small and clean.
kubectl create configmap bench-pkg -n "${NS}" \
  --from-file=__init__.py=benchmarks/__init__.py \
  --from-file=runner.py=benchmarks/runner.py \
  --from-file=llm_client.py=benchmarks/llm_client.py \
  --from-file=reporter.py=benchmarks/reporter.py \
  --from-file=config.yaml=benchmarks/config.yaml

echo ">> Creating configmap bench-scenarios..."
kubectl create configmap bench-scenarios -n "${NS}" \
  --from-file=benchmarks/scenarios/

echo ">> Creating configmap bench-publish (aigit auto-publish script)..."
kubectl create configmap bench-publish -n "${NS}" \
  --from-file=publish_to_aigit.py=benchmarks/k8s/publish_to_aigit.py

echo ">> Applying Job..."
kubectl apply -f benchmarks/k8s/job.yaml

echo ">> Waiting for pod to be created..."
for _ in $(seq 1 30); do
  POD=$(kubectl get pods -n "${NS}" -l app=llm-benchmark -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || true)
  [ -n "${POD}" ] && break
  sleep 2
done
echo ">> Pod: ${POD:-<none>}"

echo ">> Tailing logs (Ctrl-C to detach; the Job keeps running)..."
kubectl logs -f "job/${JOB}" -n "${NS}" || true
