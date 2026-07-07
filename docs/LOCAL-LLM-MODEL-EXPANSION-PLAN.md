# Local LLM — Model Expansion & Weight-Cache Plan

> Status: draft plan, 2026-07-01.
> Companion to [`docs/LL-localllm-story.md`](LL-localllm-story.md) (K8s-native serving story) and
> [`docs/LLM-BENCHMARK-RESULTS.md`](LLM-BENCHMARK-RESULTS.md) (Qwen3.6-27B benchmark).
> Serving stack = **LLMKube** (operator) + **vLLM** / **llama.cpp** backends on `ka-k8s-ai`.
> Legend: `[x]` = done · `[ ]` = to do · ⚠️ = gap/risk · `[VERIFY]` = HF repo id/quant filename must be confirmed on HuggingFace (future/hypothetical model versions, beyond assistant knowledge cutoff).

This plan expands the served model set beyond the single `Qwen3.6-27B` and — critically — fixes the
**missing persistent weight cache** that currently blocks multi-model benchmarking.

---

## Current state (as of 2026-07-06)

> **Update 2026-07-06:** de serving-topologie is gewijzigd. De oude enkele `qwen` InferenceService
> (`Qwen/Qwen3.6-27B`, bfloat16, 2 replicas, image `v0.20.0`, `--max-model-len 131072`) is **vervangen**
> door **twee** InferenceServices — `qwen-27b` (NVFP4-variant) en `qwen-35b` — die elk **1 GPU** claimen.
> Beide GPUs op de node zijn dus nu bezet (1 elk). De `hf-cache` PVC en `hf-prefetch` Job uit PR#1 zijn
> **niet actief** in het cluster. Zie de detailtabel + "Weight-storage gap" hieronder.

| Item | Value |
|---|---|
| Cluster | `ka-k8s-ai` (rijnland RKE2) |
| GPU node | `ka-k8s-ai-workers-gpu-xd4xn-fk5v2` — **2× NVIDIA RTX PRO 6000 Blackwell Server Edition, 96 GB each = 192 GB VRAM total**, ~251 GB system RAM. Other workers are CPU-only. |
| GPU allocation | ⚠️ **both GPUs 100% allocated** — nu door **twee** InferenceServices: `qwen-27b` (1 GPU) + `qwen-35b` (1 GPU) op node `ka-k8s-ai-workers-gpu-xd4xn-fk5v2` (starten op / laden gewichten per 2026-07-06 ~14:54 UTC) |
| Serving — 27B | `qwen-27b`: model `nvidia/Qwen3.6-27B-NVFP4` (**NVFP4-quantized**, ≠ de eerder gebenchmarkte `Qwen/Qwen3.6-27B` bfloat16). Args o.a. `--quantization modelopt --max-model-len 262144 --max-num-seqs 256 --max-num-batched-tokens 16384 --enable-chunked-prefill --enable-prefix-caching --gpu-memory-utilization 0.95 --enable-auto-tool-choice --tool-call-parser qwen3_xml`. Image `vllm/vllm-openai:cu129-nightly`, 1 GPU. Endpoint `http://qwen-27b.llm.svc.cluster.local:8000/v1` |
| Serving — 35B | `qwen-35b`: model `qwen3-6-35b-a3b`, 1 GPU. Endpoint `http://qwen-35b.llm.svc.cluster.local:8000/v1` |
| Registered models | **10 `Model` CRs Ready in ns `llm`**: deepseek-v3-1, gemma-4-e4b, glm-4-6v, glm-5-1, gpt-oss-120b, qwen3-6-27b, qwen3-6-27b-mtp, qwen3-6-35b-a3b, qwen3-coder-480b-a35b, qwen3-coder-next-80b |
| Serving stack | **LLMKube** (`inference.llmkube.dev/v1alpha1`), CRDs `Model` / `InferenceService` / `ModelRouter` |
| InferenceService runtimes | `vllm` \| `llamacpp` \| `tgi` \| `personaplex` \| `generic` |
| Model formats | `gguf` \| `mlx` \| `safetensors` \| `pytorch` \| `custom` |
| Notable knobs | `moeCPUOffload` / `moeCPULayers` / `tensorOverrides` (CPU/GPU hybrid), `mmproj` (vision), `speculativeDecoding` (MTP), `autoscaling`, `cacheTypeK`/`cacheTypeV` (KV quant) |
| vLLM image | `vllm/vllm-openai:cu129-nightly` (27B); was `v0.20.0` op de oude enkele `qwen` isvc |

### GitOps

Models are managed by a **Flux Kustomization `llm-models`** (ns `flux-system`) ← GitRepository `ai-k8s`
= `https://aigit.waterschap.org/ai/k8s.git` (branch `main`), path `./clusters/llm-models`.
`Model` CRs live in `models.yaml`; serving in `inferenceservice.yaml`.

> ⚠️ Direct `kubectl apply` **drifts and gets reverted** by Flux. All changes go via **PR to that repo**.

### Weight-storage gap (root cause of the pain)

> **Update 2026-07-06:** ondanks dat PR#1 (die de `hf-cache` PVC + prefetch declareert) is **gemerged**,
> is er **nog steeds geen live weight-cache** — er is op dit moment **geen `hf-cache` PVC** in het cluster
> en **geen `hf-prefetch` Job**. De opvolg-PR#2 die dit moest 'unfaulten'/resizen is **CLOSED, niet gemerged**.
> De onderstaande gap staat dus nog volledig open.

There is **NO persistent weight cache**:

- No PVC in ns `llm`; `Model` CRs show `SIZE=0`.
- `Model.spec.source` is a HuggingFace repo id, "runtime-resolved" — vLLM downloads weights from HF into
  **ephemeral pod storage at pod start**.
- No `HF_TOKEN` on the cluster.

Consequence: every cold start re-downloads weights. The 35B benchmark's temp pod **never became ready
within its 30-min window** because it had to pull ~70 GB from HF into an empty pod.

---

## Benchmark tooling (already in this branch)

- `benchmarks/k8s/benchmark-all-models.sh` sweeps every `Model` CR. The currently-served model is
  benchmarked in place; for an **unserved** model it: suspends Flux `llm-models`, scales `qwen` to 1 replica
  (⚠️ **prod at HALF capacity**), spins a temp `bench-<slug>` InferenceService on the freed GPU, benchmarks,
  then a `trap` restores qwen replicas + Flux on exit. Disruptive — **run in a maintenance window**.
- Results layout (just refactored): `benchmarks/results-incluster/<slug>/report.txt` per model +
  `COMPARISON-MATRIX.md`. Txt-only (csv/json dropped; per-model JSON is transient, used only to build the matrix).
- Last sweep: 27B benchmarked OK; **35B-A3B timed out** (no cached weights) — so multi-model numbers are
  **incomplete until the cache exists**.

---

## Model wishlist + feasibility

Budget: **192 GB VRAM total; single GPU = 96 GB**. Two feasibility tiers (see below the table).

| Model | Type | Recommended quant | ~VRAM | GPUs | Runtime | Status |
|---|---|---|---|---|---|---|
| gemma-4-26B-A4B | MoE 26B / 4A | FP8 | ~30 GB | 1 GPU | vllm | GATED (skipped) |
| Qwen3.6-35B-A3B | MoE 35B / 3A | BF16/FP8 | ~40–70 GB | 1 GPU | vllm | registered |
| Qwen3.6-27B | dense | BF16 | ~54 GB | 1 GPU | vllm | **SERVED now** |
| gemma-4-31B | dense | BF16 | ~62 GB | 1 GPU | vllm | GATED (skipped) |
| GPT-OSS-120B | MoE ~117B / 5A | native MXFP4 | ~63 GB | 1 GPU | vllm | registered (PR) |
| Qwen3-Coder-Next-80B | MoE 80B / 3A | Q4/FP8 | ~42–80 GB | 1 GPU | vllm | registered (PR) `[VERIFY]` repo id |
| GLM-4.6V | MoE ~106B, vision | Q4 GGUF + mmproj | ~60–65 GB | 1 GPU | llamacpp | registered (PR) |
| Qwen3.6-27B-MTP | dense + MTP | Q4–Q8 GGUF | ~16–29 GB | 1 GPU | llamacpp | registered (PR) |
| gemma-4-E4B | ~4B eff | Q4 GGUF | ~3–4 GB | 1 GPU | llamacpp | registered (PR) |
| GLM-5.1 | MoE ~355B | IQ3_KS GGUF | ~150 GB | 2 GPU + CPU offload | llamacpp | register-only (PR) `[VERIFY]` |
| Qwen3-Coder-480B-A35B | MoE 480B / 35A | IQ2/Q2 GGUF | ~150–240 GB | 2 GPU + CPU offload | llamacpp | register-only (PR) `[VERIFY]` |
| DeepSeek-V3.1 | MoE 671B | UD-TQ1_0 GGUF | ~160–170 GB | 2 GPU + heavy CPU offload | llamacpp | register-only (PR) `[VERIFY]` |

### Two feasibility tiers

- **Tier A — fits on one GPU (≤96 GB):** gemma-4-26B-A4B, Qwen3.6-35B-A3B, Qwen3.6-27B, gemma-4-31B,
  GPT-OSS-120B, Qwen3-Coder-Next-80B, GLM-4.6V, Qwen3.6-27B-MTP, gemma-4-E4B. Can run **1–2 side by side**
  (one per GPU) or via **autoscaling / ModelRouter** on demand.
- **Tier B — whole-node exclusive:** GLM-5.1, Qwen3-Coder-480B-A35B, DeepSeek-V3.1. Require **both GPUs +
  CPU/MoE offload into the 251 GB RAM**. **Mutually exclusive** — the served `27B` must be **evicted** to run any of them.

---

## Done (Phase 0 — Foundations)

- [x] Fixed `benchmark-all-models.sh` temp-isvc generator to match the real `v1alpha1` CRD layout:
  `modelRef` is a string; model source is `args[0]`; gpu is scalar `spec.resources.gpu`; service block is
  `spec.endpoint`. (Committed on this branch.)
- [x] Refactored results to per-model txt folders: `benchmarks/results-incluster/<slug>/report.txt` +
  `COMPARISON-MATRIX.md`. (Committed on this branch.)
- [x] **PR [ai/k8s#1](https://aigit.waterschap.org/ai/k8s/pulls/1)** — "feat(llm): register expanded
  model set + HF weight cache + prefetch job": 8 `Model` CRs + `hf-cache` PVC (Longhorn
  `longhorn-distributed`, RWX, 500Gi) + one-shot `hf-prefetch` Job (small/mid models) + README. Gemma left
  commented-out (gated). ✅ **MERGED (2026-07-06).**
  > **Update 2026-07-06:** ⚠️ Ondanks de merge is de cache-declaratie in de praktijk **niet actief**: er is
  > op dit moment **géén `hf-cache` PVC** in het cluster en **géén `hf-prefetch` Job** die draait — cold
  > starts halen gewichten dus nog steeds opnieuw op. De opvolg-PR die dit had moeten repareren,
  > **PR [ai/k8s#2](https://aigit.waterschap.org/ai/k8s/pulls/2)** ("fix(llm): hf-cache 200Gi + trim
  > prefetch (unfault the cache)"), is **CLOSED en NIET gemerged** → de 'unfault'/resize-fix is niet geland.
  > Dit blijft een open follow-up.
- [x] Benchmark-resultaten gepubliceerd via **PR [ai/druppie#2](https://aigit.waterschap.org/ai/druppie/pulls/2)**
  — "Automated benchmark results" — **MERGED**.

---

## The Plan (phased)

### Phase 1 — Register + cache

Verify the `[VERIFY]` entries, land the registration/cache PR, and prime the cache.

- [ ] Verify the **4 `[VERIFY]`** repo ids / quant filenames on HF (Qwen3-Coder-Next-80B, GLM-5.1,
  Qwen3-Coder-480B-A35B, DeepSeek-V3.1) — these are future/hypothetical versions and may 404.
- [x] Merge PR [ai/k8s#1](https://aigit.waterschap.org/ai/k8s/pulls/1). ✅ **MERGED 2026-07-06.**
- [x] Confirm Flux reconciles the 8 `Model` CRs. **10 `Model` CRs Ready in ns `llm`** (2026-07-06):
  deepseek-v3-1, gemma-4-e4b, glm-4-6v, glm-5-1, gpt-oss-120b, qwen3-6-27b, qwen3-6-27b-mtp,
  qwen3-6-35b-a3b, qwen3-coder-480b-a35b, qwen3-coder-next-80b.
- [ ] ⚠️ `hf-cache` PVC reconciled — **NIET actief**: geen `hf-cache` PVC in het cluster (2026-07-06).
  Opvolg-PR [ai/k8s#2](https://aigit.waterschap.org/ai/k8s/pulls/2) (unfault/resize) is **CLOSED, niet gemerged**.
- [ ] ⚠️ Run the `hf-prefetch` Job — **geen prefetch Job draait** (2026-07-06).
- [ ] Confirm weights land in the `hf-cache` PVC — geblokkeerd door bovenstaande.

**Exit:** `hf-prefetch` Job `Complete`; cache populated for the small/mid set.

### Phase 2 — Make serving use the cache + re-benchmark

- [ ] Mount `hf-cache` at `/cache` (set `HF_HOME=/cache`) in `inferenceservice.yaml` so serving pods stop
  re-downloading.
- [ ] Re-run the sweep so 35B-A3B (and other cached models) actually complete.

**Exit:** full comparison matrix (`COMPARISON-MATRIX.md`) with **no timeouts**.

### Phase 3 — Multi-model serving strategy

- [ ] Decide GPU allocation: keep both GPUs on 27B vs. free one for rotation.
- [ ] Evaluate LLMKube `autoscaling` / scale-to-zero and `ModelRouter` for hosting several 1-GPU (Tier A)
  models on demand.

**Exit:** a documented serving policy + at least one additional model servable on demand.

### Phase 4 — Giant models (Tier B)

- [ ] Configure the `llamacpp` runtime with `moeCPUOffload` / `tensorOverrides` for GLM-5.1 /
  Qwen-480B / DeepSeek-V3.1. Whole-node exclusive, **maintenance-window only**.

**Exit:** one giant model demonstrably served (even if slow).

### Phase 5 — Gated models (Gemma)

- [ ] Create an `HF_TOKEN` secret and wire it into pods.
- [ ] Un-comment the Gemma `Model` CRs.

**Exit:** a Gemma model registered + cacheable.

---

## Open decisions / risks

| # | Item | Note |
|---|---|---|
| 1 | HF token provisioning | Who provides it, how it is stored (secret). Blocks Phase 5 and gated/large downloads. |
| 2 | GPU allocation policy | Both GPUs hot on 27B vs. free one for rotation (Phase 3). |
| 3 | Hot vs. on-demand set | Which models stay resident vs. autoscaled/scale-to-zero. |
| 4 | Cache sizing | ⚠️ 500 Gi covers mid models; **giants need multiple TB** → separate/expanded PVC. |
| 5 | RWX Longhorn throughput | Read throughput for large weight loads from `longhorn-distributed` (RWX) is unproven. |
| 6 | Prod at half capacity | Sweeps scale `qwen` to 1 replica — maintenance-window only. |
| 7 | Unverified repo ids | `[VERIFY]` entries are future/hypothetical model versions beyond the assistant knowledge cutoff; repo ids/filenames **must be confirmed on HF** or pods will 404. |
