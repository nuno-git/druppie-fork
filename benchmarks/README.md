# LLM Performance Benchmarks

Standalone performance benchmark runner voor het vergelijken van LLM modellen op Nutanix/Kubernetes infrastructuur. Geen applicatie dependencies — alleen `httpx` en `pyyaml`.

## Quick Start

```bash
# Vanuit de project root:
python -m benchmarks.runner --fetch-models qwen_ingress          # toon beschikbare modellen op endpoint
python -m benchmarks.runner --list                               # toon geconfigureerde modellen en scenarios
python -m benchmarks.runner --model Qwen/Qwen3.6-27B             # run alle scenarios tegen 1 model
python -m benchmarks.runner                                      # run alles
python -m benchmarks.runner --output results.json               # exporteer resultaten
```

> **Actieve endpoints.** In `config.yaml` zijn momenteel alleen `qwen_incluster`
> (`http://qwen.llm.svc.cluster.local:8000/v1` — alleen bereikbaar ván binnen het
> cluster of de Druppie backend) en `qwen_ingress` (`https://llm.rijnland.dev/v1` —
> bereikbaar vanaf elke laptop/CI) actief. De oude `ollama` / Azure Foundry
> endpoints staan uitgecommentarieerd. Gebruik `qwen_ingress` voor ad-hoc runs
> vanaf je laptop; de in-cluster Job (`k8s/`) gebruikt `qwen_incluster`.

## CLI Opties

| Optie | Beschrijving |
|-------|-------------|
| `--model MODEL` | Run alleen dit model (model ID, bijv. `gpt-oss:20b`) |
| `--category CAT` | Run alleen deze categorie (`latency`, `generation`, `context_scaling`, `tool_overhead`, `stress`) |
| `--scenario NAME` | Run alleen dit scenario (op naam) |
| `--runs N` | Aantal gemeten runs per scenario (overschrijft config) |
| `--warmup N` | Aantal warmup runs (overschrijft config) |
| `--timeout SEC` | Timeout per LLM call in seconden |
| `--output FILE` | Exporteer naar JSON (`.json`) of CSV (`.csv`) |
| `--no-stream` | Schakel streaming uit (geen TTFT meting) |
| `--list` | Toon geconfigureerde scenarios en modellen |
| `--fetch-models EP` | Haal beschikbare modellen op van een endpoint (Ollama/vLLM/OpenAI-compatible) |

## Scenario Categorieën

### Latency
Meet de totale response tijd bij verschillende input lengtes.
- `latency-50` — 50 tokens input
- `latency-200` — 200 tokens input
- `latency-500` — 500 tokens input
- `latency-1000` — 1000 tokens input

### Generation Speed
Meet hoeveel tokens per seconde het model genereert.
- `generate-100` — forceer ~100 tokens output
- `generate-500` — forceer ~500 tokens output
- `generate-1000` — forceer ~1000 tokens output
- `generate-2000` — forceer ~2000 tokens output

### Context Scaling
Meet hoe de performance schaalt met toenemende context lengte. Genereert automatisch filler text van de juiste lengte. Scenarios die groter zijn dan het model's `max_context` worden overgeslagen.
- `context-256` t/m `context-256k` (256 → 262144 tokens)

### Tool Calling Overhead
Meet de extra latency van tool calling vergeleken met reguliere prompts.
- `tool-call-3-tools` — 3 tools meegegeven
- `tool-call-10-tools` — 10 tools meegegeven

### Stress
Meet consistentie en stabiliteit bij herhaalde aanroepen.
- `repeated-50` — zelfde korte prompt 10x achter elkaar

## Gemeten Metrieken

| Metriek | Beschrijving |
|---------|-------------|
| `total_latency_ms` | Tijd van request tot volledige response |
| `time_to_first_token_ms` | Tijd tot eerste token (alleen bij streaming) |
| `prompt_tokens` | Aantal input tokens (van API response) |
| `completion_tokens` | Aantal output tokens |
| `tokens_per_second` | Generatiesnelheid (completion_tokens / latency) |
| `prompt_eval_rate` | Prompt processing snelheid (prompt_tokens / TTFT, alleen bij streaming) |

## Modellen Ontdekken

Gebruik `--fetch-models` om te zien welke modellen beschikbaar zijn op een endpoint. Geef de **endpoint-naam** uit `config.yaml` mee (niet de URL):

```bash
python -m benchmarks.runner --fetch-models qwen_ingress
```

Output:
```
Fetching models from qwen_ingress (https://llm.rijnland.dev/v1)...

Found 1 models:

  Qwen/Qwen3.6-27B  (27B, ...)
```

Dit werkt met elk OpenAI-compatible endpoint (vLLM, Ollama, TGI). De endpoint naam moet geconfigureerd zijn in `config.yaml`. De enige actieve endpoints zijn nu `qwen_incluster` en `qwen_ingress` (zie de noot bij Quick Start); `ollama` staat uitgecommentarieerd.

## Configuratie

Bewerk `config.yaml` om endpoints en modellen te configureren.

### Endpoint toevoegen
```yaml
endpoints:
  mijn_endpoint:
    base_url: "https://mijn-server.internal/v1"
    api_key: "${MIJN_API_KEY}"      # env var referentie
    ssl_verify: true
```

### Model toevoegen
```yaml
models:
  - endpoint: mijn_endpoint
    model: llama3.3:70b
    display_name: "Llama 3.3 70B"
    max_context: 131072
    parameters: "70B"
    quantization: "GPTQ"
    kv_cache_quant: "FP8"
    flash_attention: true
    gpu_layers: -1
    notes: "4-bit GPTQ quantization, FP8 KV cache"
```

De optimalisatie-velden (`quantization`, `kv_cache_quant`, `flash_attention`, `gpu_layers`) worden opgeslagen in de resultaten zodat benchmarks reproduceerbaar zijn.

## Nieuw Scenario Toevoegen

Maak een YAML bestand in `scenarios/`:

```yaml
scenario:
  name: mijn-scenario
  description: "Beschrijving van wat dit test"
  category: latency                 # latency | generation | context_scaling | tool_overhead | stress

  system_prompt: "Je bent een assistent."
  user_prompt: "De vraag aan het model"

  # Optioneel:
  max_output_tokens: 500            # forceer output lengte
  context_tokens: 4096              # genereer filler context (voor context_scaling)
  repeat: 10                        # herhaal prompt N keer per run (voor stress)
  tools: [...]                      # OpenAI-format tool definities (voor tool_overhead)
```

## Output Formaten

### JSON
Bevat alle ruwe meetdata per run inclusief model configuratie. Geschikt voor verdere analyse.

### CSV
Flat tabel met 1 rij per run. Geschikt voor spreadsheet import en pivot tabellen.

---

# In-cluster automated sweep

The CLI runner above benchmarks **one** endpoint you point it at. The
**automated sweep** (`benchmarks/k8s/benchmark-all-models.sh`) benchmarks *every*
candidate model in the cluster in one run: it reads `benchmarks/candidates.yaml`,
benchmarks the models that fit (either the already-served ones in place, or by
temporarily standing up a bench model on a freed GPU), skips the ones that can't
fit with a recorded reason, rebuilds the comparison matrices, and auto-publishes
the results to aigit as a PR.

> **This touches prod / test-cluster impact — read the [GPU-freeing mechanism](#gpu-freeing-mechanism--test-cluster-impact) before running.** The sweep temporarily takes one served model offline and suspends Flux.

## Prerequisites

- **`kubectl`** with its context pointed at the **`ka-k8s-ai`** cluster and access
  to namespace **`llm`** (patch InferenceServices, patch Flux Kustomizations in
  `flux-system`, create/delete Jobs + configmaps).
- **`python3`** (or `python`) locally with **PyYAML** installed — used to parse
  `candidates.yaml`, munge the per-model temp config, and build the matrices.
  Without PyYAML the fit-class / profile lookups behave as "no data" (every model
  is attempted with generic default args), so install it: `pip install pyyaml`.
- The **`aigit-publish`** secret in ns `llm` for the publish step (optional — the
  sweep skips publishing gracefully if the secret or its token is absent).

## Running it

```bash
# Interactive — prints the impact and asks you to type 'yes':
./benchmarks/k8s/benchmark-all-models.sh

# Non-interactive (CI / scripted):
./benchmarks/k8s/benchmark-all-models.sh --yes

# Only specific models (comma-separated CRD names OR slugs, EXACT match):
./benchmarks/k8s/benchmark-all-models.sh --only qwen3-6-27b,qwen3.6-35b-a3b-nvfp4
```

| Flag | Effect |
|------|--------|
| `--yes` | Skip the interactive confirmation prompt. |
| `--only slug1,slug2` | Benchmark only models whose CRD **name** or **slug** exactly equals one of the comma-separated tokens (exact, not substring — so `qwen3.6-27b` does not also match `qwen3.6-27b-mtp`). |

### What it does per model

The sweep **iterates the candidates in `candidates.yaml`**: models that fit are
benchmarked (against a registered `models.inference.llmkube.dev` CRD, or a
temporary one), models that are too large / need 2 GPUs / are API-only are skipped
with a recorded reason. For each candidate:

1. **Already served** (`fit: served` — its model backs a running `qwen-*` /
   Flux-owned InferenceService) → **benchmark in place** against that service's
   endpoint. No scaling, no serving change.
2. **Size-skip** (`fit` is `too-large` or `needs-2gpu`) → **never touches the
   cluster**: writes the candidate's `skip_reason` to
   `results-incluster/<slug>/SKIPPED.txt` and moves on (prod stays intact).
3. **API-only** (`fit: api`, `category: api`) → **skipped with a recorded reason**
   (OpenRouter-hosted, not cluster-downloadable).
4. **Fits, not yet served** (`fits-1gpu`) → **free a GPU**: suspend Flux, scale
   `FREE_SERVICE` to 0, spin up a short-lived `bench-<slug>` InferenceService on
   the freed GPU (args come from the candidate's `profile:` block or a generic
   default), wait for it to serve (fast-failing on a crashloop with a captured
   reason), run the Job, then tear the bench service down and restore
   `FREE_SERVICE`.

> **Note (target vs current).** The behavior above is the intended
> candidates.yaml-driven model. The current script still *discovers* the models to
> benchmark from the registered `models.inference.llmkube.dev` CRDs in ns `llm` and
> uses `candidates.yaml` for the fit-class / profile lookup; the iteration is being
> moved to be fully candidates-driven (creating a temporary CRD for a candidate
> that has none). `candidates.yaml` is the control surface either way.

Every benchmarked model writes its human-readable console report to
`benchmarks/results-incluster/<slug>/report.txt` (the committed source of truth).
The per-run result JSON is kept **only transiently** in the script's temp WORKDIR
to feed the comparison matrix, then discarded — no `.json`/`.csv` is written into
`results-incluster/`.

### Tunable env knobs

All overridable from the environment; defaults read from the script:

| Env var | Default | Purpose |
|---------|---------|---------|
| `FREE_SERVICE` | `qwen-35b` | The served InferenceService scaled 1→0 to free a GPU for bench models. |
| `SERVED_MATCH_GLOB` | `qwen-*` | Name-glob used to discover the served InferenceServices (Flux-owned isvcs also match regardless). |
| `SHARED_CACHE_PVC` | `llm-models-cache` | RWO PVC (cached HF weights + vLLM compile cache) mounted by both serving pods and the bench pod for fast warm starts. |
| `DEFAULT_BENCH_IMAGE` | `vllm/vllm-openai:cu129-nightly` | Container image for the bench InferenceService (overridable per-model via a profile's `image`). |
| `GPU_READY_TIMEOUT` | `2400` (40 min) | Max seconds to wait for a bench model to serve (`/v1/models` → 200). Fast-fails earlier on a crashloop. |
| `JOB_COMPLETE_TIMEOUT` | `9000` | Max seconds to wait for a benchmark Job to finish. Matches the Job's `activeDeadlineSeconds` in `job.yaml`. |

A **collision guard** aborts up front (before scaling/suspending anything) if a
manual `llm-benchmark` Job is already running in ns `llm`. The sweep's own Jobs
are named `llm-benchmark-<slug>` so a running sweep never trips its own guard.

## GPU-freeing mechanism / test-cluster impact

> **Running this degrades prod.** One served model is offline for the duration of
> the run. The `ka-k8s-ai` GPU cluster is a first-sprint test environment, so it is
> fine to test directly — but know what you are taking down.

- **Topology.** The cluster has **one GPU node with two GPUs**. Prod serves two
  NVFP4 models, one per GPU: `qwen-27b` (`nvidia/Qwen3.6-27B-NVFP4`) and `qwen-35b`
  (`nvidia/Qwen3.6-35B-A3B-NVFP4`), each `replicas: 1`, both GitOps-managed by the
  Flux `llm-models` Kustomization and both mounting the shared `llm-models-cache`
  PVC. There is **no P2P between the cards**, so serving is tensor-parallel=1 (one
  model per GPU).
- **ResourceQuota.** The ns `llm` GPU ResourceQuota is `hard=2`, so both GPUs are
  normally occupied — there is no free GPU for a bench model until we free one.
- **Freeing a GPU.** The sweep scales `FREE_SERVICE` (default `qwen-35b`) **1→0**,
  freeing one GPU. That model is **OFFLINE** for the run; the other served model
  keeps serving.
- **Parent + child Flux suspend.** Suspending only the child `llm-models`
  Kustomization is **not enough**: the **parent `ai-k8s`** Kustomization (ns
  `flux-system`) reconciles on a ~1-min interval and re-applies the child, resetting
  the scaled-down replica within a minute. The sweep therefore suspends **BOTH**
  `ai-k8s` (parent) and `llm-models` (child), and restores both to their captured
  original suspend states on exit.
- **Restore trap.** An `EXIT`/`INT`/`TERM` trap **always** runs on completion,
  Ctrl-C, or error: it deletes any temp `bench-*` InferenceServices (waiting for
  the GPU to actually release), restores `FREE_SERVICE` to its captured replica
  count, resumes both Flux Kustomizations, and cleans up Jobs + the temp WORKDIR.

## aigit auto-publish

After the sweep it publishes the text artifacts to aigit (Gitea) via
`benchmarks/k8s/publish_to_aigit.py`, reusing the same script the single-model Job
uses. Setup:

- Create the **`aigit-publish`** secret in ns `llm` with lowercase keys
  **`api`**, **`repo`**, **`user`**, **`token`** (mapped to `AIGIT_API` /
  `AIGIT_REPO` / `AIGIT_USER` / `AIGIT_TOKEN`). The token needs `write:repository`.
- **Without a token, publish is silently skipped** (prints `publish skipped (no token)`
  and returns 0) — the local results are still written.
- Publishes to target branch **`benchmarks/auto-results`** (created from
  **`colab-dev`** on first file), then opens/updates a **PR into `colab-dev`**.
- aigit uses a **private CA**, so all API calls run with **`verify=False`**
  (TLS verification disabled — egress is restricted to the trusted in-cluster aigit
  endpoint).
- Paths are **stable, per-slug, and overwritten** each run: every file under the
  staged results dir is uploaded to `benchmarks/results-incluster/<slug>/…`
  preserving its subdirectory (e.g. `qwen3.6-27b/report.txt`), plus the two
  matrices. No timestamp/run-id dirs — the tree always shows exactly one report
  per model + one matrix.

## Control surface: `candidates.yaml`

`benchmarks/candidates.yaml` is the **single control surface** for the sweep and
the [MODEL-TEST-MATRIX](results-incluster/MODEL-TEST-MATRIX.md). To add or skip a
model, edit that file — no script changes needed:

- **Add a model** → add an entry with `slug`, `source`, `category: local`, and a
  `fit` class.
- **`fit` class drives the size-skip.** `too-large` / `needs-2gpu` models are
  skipped with their `skip_reason` (never touch the cluster). `fits-1gpu` models
  are benchmarked by freeing a GPU. `served` models are benchmarked in place.
  `api` models are OpenRouter-hosted and not cluster-benchmarkable.
- **`profile:` block overrides serving args** for non-qwen families (the generic
  default args mirror prod's qwen NVFP4 block, which crashes other families).
  `profile.vllm_args` is the COMPLETE vLLM arg list (element 0 is the `--model`);
  `profile.image` overrides the container image.
- **NVFP4 / modelopt models MUST set `--quantization modelopt`** in `vllm_args`
  and use their `nvidia/*-NVFP4` (or other modelopt) source as `vllm_args[0]`.

## Related scripts

- `benchmarks/k8s/run-in-cluster.sh` — the single-model in-cluster Job (against the
  currently-served `qwen` endpoint). The sweep generalizes this to all candidates.
- `benchmarks/k8s/job.yaml` — the Job manifest both scripts apply (the sweep gives
  it a unique per-model name `llm-benchmark-<slug>`).
- `benchmarks/k8s/job-gpunode.yaml` — a **manual, node-colocated** variant (see its
  header comment); not wired into either script.

---

# Quantization glossary (NVFP4 / MXFP4)

The comparison matrix uses two 4-bit formats. They are not interchangeable:

- **NVFP4** — NVIDIA's 4-bit floating-point format, produced by **ModelOpt**
  quantization. Chosen for the prod qwen models because it is ~2.5–3.5× smaller
  than bf16 with minimal quality loss, letting a 27B/35B model fit one 96GB card
  with room for a 256K KV cache. Serve NVFP4 weights with **`--quantization modelopt`**
  (see the candidate `profile:` blocks); the source must be an `nvidia/*-NVFP4`
  (or other modelopt) repo.
- **MXFP4** — the **native** 4-bit format `gpt-oss` ships in (OCP Microscaling FP4).
  It loads **without** an extra `--quantization` flag. We keep gpt-oss on native
  MXFP4 rather than re-quantizing to NVFP4 because it already fits and avoids a
  double-quantization step.
- **SM120 Marlin MoE fallback.** The GPUs are **RTX PRO 6000 Blackwell (compute
  capability SM120)**. On these cards vLLM has no native NVFP4/MXFP4 **MoE** kernel,
  so mixture-of-experts models (Qwen3.6-35B-A3B-NVFP4, Qwen3-Coder-Next-80B-NVFP4,
  gpt-oss-120b) fall back to the **Marlin** MoE kernel — correct but slower than a
  native path would be. This is the "SM120 Marlin MoE fallback" the matrix
  Methodology refers to; dense models (e.g. Qwen3.6-27B-NVFP4) are unaffected.
