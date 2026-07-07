#!/usr/bin/env python3
"""Publish in-cluster benchmark results to aigit (Gitea) as a PR.

Pure-Python, depends only on httpx (already pip-installed by the benchmark Job).
aigit uses a private CA, so all API calls disable TLS verification (verify=False).

Env (from the aigit-publish secret, mapped to uppercase in the Job):
  AIGIT_API    - e.g. https://aigit.waterschap.org/api/v1
  AIGIT_REPO   - e.g. ai/druppie
  AIGIT_USER   - Gitea username (informational)
  AIGIT_TOKEN  - Gitea token with write:repository (empty -> graceful skip)
  AIGIT_BRANCH - target branch for results (default benchmarks/auto-results)
  AIGIT_BASE   - base branch to branch/PR from (default colab-dev)
  AIGIT_DIR    - stable base dir in the repo to publish under
                 (default benchmarks/results-incluster)
  RESULTS_DIR  - directory of files to publish (default /results)

Walks RESULTS_DIR recursively and uploads every file to AIGIT_DIR PRESERVING
its relative subdirectory structure, e.g. <RESULTS_DIR>/qwen3.6-27b/report.txt
-> benchmarks/results-incluster/qwen3.6-27b/report.txt and
<RESULTS_DIR>/COMPARISON-MATRIX.md -> benchmarks/results-incluster/COMPARISON-MATRIX.md.
Paths are STABLE (no timestamp/run-id): each publish OVERWRITES the same paths
via the Gitea contents API (create if missing, update-with-sha if present), so
the results tree always shows exactly one report per model + one matrix.

Publishes on AIGIT_BRANCH (created from AIGIT_BASE on first file if missing),
then ensures an open PR AIGIT_BRANCH -> AIGIT_BASE. Idempotent and non-fatal:
a missing token or an already-existing PR never fails the Job.
"""

import base64
import csv
import json
import os
import sys
from pathlib import Path

import httpx


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def json_to_csv(json_path: str, csv_path: str) -> int:
    """Flatten a runner results.json into a per-run CSV (no benchmark rerun)."""
    data = json.loads(Path(json_path).read_text(encoding="utf-8"))
    model_index = {m.get("display_name"): m for m in data.get("models", [])}
    rows = []
    for category, scenarios in data.get("results", {}).items():
        for scenario_name, model_results in scenarios.items():
            for model_name, runs in model_results.items():
                m = model_index.get(model_name, {})
                for i, r in enumerate(runs):
                    rows.append({
                        "category": category,
                        "scenario": scenario_name,
                        "model": model_name,
                        "endpoint": m.get("endpoint", ""),
                        "model_id": m.get("model", ""),
                        "parameters": m.get("parameters", ""),
                        "quantization": m.get("quantization", ""),
                        "kv_cache_quant": m.get("kv_cache_quant", ""),
                        "flash_attention": m.get("flash_attention", ""),
                        "run": i + 1,
                        "total_latency_ms": r.get("total_latency_ms"),
                        "ttft_ms": r.get("time_to_first_token_ms"),
                        "prompt_tokens": r.get("prompt_tokens"),
                        "completion_tokens": r.get("completion_tokens"),
                        "total_tokens": r.get("total_tokens"),
                        "tokens_per_second": r.get("tokens_per_second"),
                        "prompt_eval_rate": r.get("prompt_eval_rate"),
                        "error": r.get("error") or "",
                    })
    if not rows:
        print("json-to-csv: no result rows found")
        return 0
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    print(f"json-to-csv: wrote {len(rows)} rows to {csv_path}")
    return 0


def main() -> int:
    # Standalone converter mode used by the Job to derive CSV from JSON.
    if len(sys.argv) >= 4 and sys.argv[1] == "--json-to-csv":
        return json_to_csv(sys.argv[2], sys.argv[3])

    api = _env("AIGIT_API").rstrip("/")
    repo = _env("AIGIT_REPO")
    user = _env("AIGIT_USER")
    token = _env("AIGIT_TOKEN")
    branch = _env("AIGIT_BRANCH", "benchmarks/auto-results")
    base = _env("AIGIT_BASE", "colab-dev")
    aigit_dir = _env("AIGIT_DIR", "benchmarks/results-incluster").strip("/")
    results_dir = Path(_env("RESULTS_DIR", "/results"))

    if not token:
        print("publish skipped (no token)")
        return 0

    if not api or not repo:
        print(f"publish skipped (missing AIGIT_API/AIGIT_REPO): api={api!r} repo={repo!r}")
        return 0

    # Walk RESULTS_DIR recursively, preserving the relative subdir structure so
    # e.g. <RESULTS_DIR>/qwen3.6-27b/report.txt -> <aigit_dir>/qwen3.6-27b/report.txt.
    files = sorted(p for p in results_dir.rglob("*") if p.is_file())
    if not files:
        print(f"publish skipped (no files in {results_dir})")
        return 0

    # aigit is served behind a private CA. There is no CA bundle available in
    # the stock python:3.12-slim image and egress is restricted to the trusted
    # in-cluster aigit endpoint, so TLS verification is intentionally disabled.
    # Held in a variable (not a literal) so intent is explicit and centralized.
    tls_verify = False

    headers = {
        "Authorization": f"token {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    dest_dir = aigit_dir

    print(f"Publishing {len(files)} file(s) as {user} to {repo}")
    print(f"  target branch: {branch}  base: {base}  dir: {dest_dir}")

    # tls_verify is False: aigit uses a private CA (see note above).
    with httpx.Client(verify=tls_verify, timeout=60.0, headers=headers) as client:
        # Does the target branch already exist?
        r = client.get(f"{api}/repos/{repo}/branches/{branch}")
        branch_exists = r.status_code == 200
        if r.status_code not in (200, 404):
            print(f"  WARNING: unexpected status checking branch: {r.status_code} {r.text[:200]}")
        print(f"  branch '{branch}' exists: {branch_exists}")

        for i, f in enumerate(files):
            content_b64 = base64.b64encode(f.read_bytes()).decode()
            # Preserve the file's path relative to RESULTS_DIR under the stable dir.
            rel = f.relative_to(results_dir).as_posix()
            path = f"{dest_dir}/{rel}"
            body = {
                "content": content_b64,
                "message": f"benchmark auto-publish {rel}",
            }
            if branch_exists:
                body["branch"] = branch
                # Stable paths OVERWRITE: the contents API rejects a create-PUT if
                # the file already exists, so look it up first and, if present,
                # include its blob sha to turn this into an update.
                get = client.get(
                    f"{api}/repos/{repo}/contents/{path}",
                    params={"ref": branch},
                )
                if get.status_code == 200:
                    sha = (get.json() or {}).get("sha")
                    if sha:
                        body["sha"] = sha
                elif get.status_code != 404:
                    print(f"  WARNING: unexpected status checking {path}: "
                          f"{get.status_code} {get.text[:200]}")
            else:
                # First PUT creates the branch from base via new_branch. The branch
                # does not exist yet, so nothing to overwrite -> plain create.
                body["new_branch"] = branch
                body["branch"] = base

            resp = client.put(
                f"{api}/repos/{repo}/contents/{path}",
                json=body,
            )
            if resp.status_code in (200, 201):
                verb = "updated" if "sha" in body else "created"
                print(f"  [{i + 1}/{len(files)}] PUT {path} -> {resp.status_code} ({verb})")
                # Branch now exists; subsequent files target it directly.
                branch_exists = True
            else:
                print(f"  ERROR PUT {path} -> {resp.status_code} {resp.text[:300]}")
                return 1

        # Ensure an open PR branch -> base.
        pr_number = None
        pr_url = None
        pr_body = {
            "head": branch,
            "base": base,
            "title": "Automated benchmark results",
            "body": "Auto-published benchmark runs from the in-cluster Job.",
        }
        pr_resp = client.post(f"{api}/repos/{repo}/pulls", json=pr_body)
        if pr_resp.status_code in (200, 201):
            data = pr_resp.json()
            pr_number = data.get("number")
            pr_url = data.get("html_url")
            print(f"  created PR #{pr_number}: {pr_url}")
        elif pr_resp.status_code in (409, 422):
            print(f"  PR already exists (status {pr_resp.status_code}); locating it...")
            list_resp = client.get(
                f"{api}/repos/{repo}/pulls",
                params={"state": "open", "type": "pulls"},
            )
            if list_resp.status_code == 200:
                for pr in list_resp.json():
                    head = (pr.get("head") or {}).get("ref")
                    base_ref = (pr.get("base") or {}).get("ref")
                    if head == branch and base_ref == base:
                        pr_number = pr.get("number")
                        pr_url = pr.get("html_url")
                        break
            print(f"  existing PR #{pr_number}: {pr_url}")
        else:
            print(f"  WARNING: could not ensure PR: {pr_resp.status_code} {pr_resp.text[:300]}")

    branch_url = f"{api.rsplit('/api/', 1)[0]}/{repo}/src/branch/{branch}/{dest_dir}"
    print("---")
    print(f"branch: {branch}")
    print(f"branch_url: {branch_url}")
    print(f"pr_number: {pr_number}")
    print(f"pr_url: {pr_url}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
