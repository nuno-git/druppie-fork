# LLM Serving Recommendation — ka-k8s-ai

> Status: recommendation grounded in the in-cluster benchmark run of **2026-07-07**.
> Companion documents: [`docs/ADR-LLM-SERVING-STACK.md`](ADR-LLM-SERVING-STACK.md) (why LLMKube + vLLM),
> [`benchmarks/results-incluster/COMPARISON-MATRIX.md`](../benchmarks/results-incluster/COMPARISON-MATRIX.md)
> (headline + concurrency data), and the per-model `report.txt` / `load-test.txt` under
> `benchmarks/results-incluster/`.
>
> All numbers below come from that benchmark work; they are the source of truth for this recommendation.

## TL;DR

- **Keep two NVFP4 models hot, one per GPU:** `qwen-35b` (`nvidia/Qwen3.6-35B-A3B-NVFP4`, MoE, ~A3B active)
  and `qwen-27b` (`nvidia/Qwen3.6-27B-NVFP4`, dense).
- **Default to the 35B-A3B MoE for concurrent agent workloads.** It is the throughput/concurrency winner
  by a wide margin — ~**2.5×** the aggregate throughput of the dense 27B under load (4,414 vs 1,658 tok/s at
  concurrency 128), *and* it is faster single-stream (~218 vs ~64 tok/s decode) with lower TTFT.
- **Reach for the dense 27B only when its output quality is specifically needed** (quality still to be validated —
  see Research next). On raw serving metrics the MoE dominates.
- **Both scale past 128 concurrent requests with 0 errors and without saturating.** There is throughput
  headroom above the swept range for both models.
- **On-demand multi-model serving is feasible** thanks to the node-local weight cache (~12 s warm load), either
  via an LLMKube `ModelRouter` (see the routing analysis) or by swapping `modelRef` in a maintenance window.

## Hardware & serving context

| Aspect | Value |
|---|---|
| Cluster | `ka-k8s-ai` (rijnland RKE2) |
| GPU node | 1 node, **2× NVIDIA RTX PRO 6000 Blackwell** (96 GB each = 192 GB total), SM120 |
| Interconnect | **No P2P** between the two cards → tensor-parallel = 1 (**one model per GPU**) |
| GPU quota | ns `llm` ResourceQuota hard = 2 (both cards normally held by the two live services) |
| Operator | **LLMKube** v0.9.0 wrapping **vLLM** (`vllm/vllm-openai:cu129-nightly`) |
| Weight cache | Node-local `local` PV `llm-model-weights` on the GPU node's disk (~700 GB, NOT Longhorn) |

The "no P2P → TP=1" constraint is the single most important design fact: you cannot shard one model across both
cards efficiently, so the fleet is always "N independent models, one per GPU". With 2 GPUs that means **two hot
models at a time**.

---

## Now: what to run

### Both NVFP4 models, one per GPU

| InferenceService | Model | Type | Role |
|---|---|---|---|
| `qwen-35b` | `nvidia/Qwen3.6-35B-A3B-NVFP4` | MoE (~A3B active), NVFP4 | **Default** for concurrent / agent workloads (throughput winner) |
| `qwen-27b` | `nvidia/Qwen3.6-27B-NVFP4` | Dense 27B, NVFP4 | Use when the dense model's output quality is specifically needed |

Both are quantized to NVFP4 (~16–20 GB weights), so each fits comfortably on one 96 GB card with generous room
for KV cache and a 256K context window.

### Why the 35B-A3B MoE is the default

Despite being the "larger" model by parameter count, the MoE only activates ~A3B parameters per token, so it is
**both faster single-stream and dramatically higher-throughput under load** than the dense 27B:

| Metric | Qwen3.6-27B-NVFP4 (dense) | Qwen3.6-35B-A3B-NVFP4 (MoE) |
|---|---|---|
| Single-stream decode | ~64 tok/s | **~218 tok/s** |
| Median TTFT | 191 ms | **99 ms** |
| latency-500 | 16.1 s | **4.7 s** |
| Aggregate tok/s @ concurrency 128 | 1,658 | **4,414** |

The MoE wins on every serving axis measured. The only reason to route to the dense 27B is if its **answer
quality** on a given task class is measurably better — that quality comparison has not yet been run (see below),
so today the recommendation is: **35B-A3B by default, 27B as a quality escape hatch.**

### Key vLLM settings to keep

The live NVFP4 services run with the following tuning; keep it:

| Setting | Why |
|---|---|
| **Prefix caching** (`--enable-prefix-caching`) | Agent loops re-send large, stable system/tool prompts every step. Prefix caching turns those repeated prefixes into cache hits, so TTFT stays low even at big contexts (measured: sub-second prefill across the whole 256K range). |
| **fp8 KV cache** (`--kv-cache-dtype fp8`) | Halves KV-cache memory vs fp16, letting more concurrent sequences fit in VRAM → higher achievable batch size and throughput on the same card. |
| **Chunked prefill** | Interleaves prefill and decode so a big prompt doesn't stall in-flight decodes; keeps TTFT and inter-token latency stable under mixed load. |
| **`--max-num-seqs` / `--max-num-batched-tokens`** | These bound the continuous-batching scheduler. Because both models were still climbing at concurrency 128 (not saturated), these should be set high enough not to be the artificial ceiling — see capacity guidance. |
| **NVFP4 (`--quantization modelopt`)** | 4-bit weights (~2.5–3.5× smaller than bf16) are what make both models fit one card each with 256K context, and enable the two-hot-models design. |
| Tool-call parser (`--enable-auto-tool-choice --tool-call-parser qwen3_xml`) | Druppie agents act only through MCP tools; tool calling must stay on. Measured tool-call overhead is small (~0.5 s for the MoE). |

> **Caveat — SM120 Marlin MoE fallback.** On the RTX PRO 6000 Blackwell (SM120) cards, vLLM does not yet have a
> native NVFP4 MoE kernel, so the 35B-A3B falls back to the **Marlin** kernel. The MoE is already the throughput
> winner *despite* this fallback — there is a further upside once native SM120 NVFP4-MoE kernels land upstream.

---

## Capacity guidance (from the concurrency data)

Concurrency sweep (each level keeps N streaming requests in flight; ~258 input tokens, `max_tokens=256`,
streaming). Cells are **aggregate** decode throughput (tok/s), summed across all concurrent requests.

| Concurrency | 27B dense — Agg tok/s | 27B p95 lat | 27B p95 TTFT | 35B-A3B MoE — Agg tok/s | MoE p95 lat | MoE p95 TTFT |
|---|---|---|---|---|---|---|
| 1 | 64 | 4.0 s | 99 ms | 219 | 1.2 s | 63 ms |
| 8 | 409 | 5.5 s | 1.1 s | 1,059 | 2.4 s | 918 ms |
| 32 | 1,094 | 7.7 s | 1.9 s | 2,475 | 4.3 s | 1.9 s |
| 64 | 1,434 | 11.9 s | 3.9 s | 3,072 | 5.6 s | 2.0 s |
| 128 | **1,658** | 20.7 s | 6.2 s | **4,414** | 7.6 s | 2.2 s |

**0 errors across the entire sweep for both models.** Neither model's throughput had flattened at concurrency
128 — both were still rising, so **128 is not the saturation point, it's just the top of the swept range.**

Practical envelope:

- **35B-A3B MoE** — comfortable production concurrency well past 128. At 128 concurrent it holds **p95 latency
  7.6 s / p95 TTFT 2.2 s** while pushing 4,414 tok/s aggregate. TTFT stays around ~2 s even at 128, which is
  the metric that matters for interactive agent responsiveness. This is the model to point sustained,
  many-agent workloads at.
- **27B dense** — usable under concurrency but with a much steeper latency cost: at 128 concurrent p95 latency
  is **20.7 s** and p95 TTFT **6.2 s**, at ~40% of the MoE's aggregate throughput. Keep its concurrent load
  lower, or prefer it only for lower-volume / quality-sensitive traffic.

Because both models were still scaling at 128, treat these numbers as a **floor** on capacity, not a ceiling.
Sizing autoscaling / admission limits off "128 concurrent is fine, 0 errors" is safe; the true knee is higher
and needs a wider sweep (below).

---

## Multi-model / "run them all" design

The fleet is bounded by GPUs, not by disk: 2 cards = **2 hot models at a time**, but the node-local weight cache
holds many more models on ~700 GB of fast local disk. The design that follows from this:

1. **Keep the two workhorses hot** — `qwen-35b` (default) and `qwen-27b` (quality escape hatch), one per GPU.
2. **Load anything else on-demand from the local cache.** Warm load from the node-local `local` PV is **~12 s**
   (no HF download, no network pull). That fast local cache is precisely what makes on-demand swapping practical —
   a cold pull of tens of GB over the network would not be.

Two concrete mechanisms for the on-demand part:

- **Option A — LLMKube `ModelRouter` (preferred once operationalized).** The `modelrouters.inference.llmkube.dev`
  CRD (v1alpha1) exists in-cluster and gives a single OpenAI-compatible endpoint that dispatches to multiple
  backends by rules. It can **route by model name** (glob-matched against the request's `model` field, or
  `defaultRouteStrategy: BackendNameMatch`), fan out across multiple in-cluster `InferenceService` backends
  **and** external providers (Anthropic/OpenAI/LiteLLM) as fallback tiers, do capability/latency-SLO/complexity
  routing, and enforce per-team auth and budgets.
  **Important limitation:** the ModelRouter is a **router/proxy, not a lifecycle manager.** Its spec has no
  field to *load or unload* a model, and no scale-to-zero. It routes across backends that already exist; it does
  not create or wake them. So it does not by itself give "load others on-demand" — it gives clean
  **routing/failover across whatever backends are up**. On-demand loading still needs a separate step (swapping
  an InferenceService's `modelRef`, or an external controller). See the ModelRouter analysis appendix for the
  full field breakdown. **No ModelRouters are currently deployed** (`kubectl get modelrouters -A` → none).
- **Option B — swap `modelRef` in a maintenance window (available today).** To serve a third model, scale one of
  the two hot services to free a GPU and point a bench/temporary `InferenceService` at the desired model via a
  `pvc://` source into the local cache. This is exactly how the benchmark rotations served 80B / 120B models. It
  is a maintenance-window operation (it takes one of the two hot models offline), but it needs no new component.

A pragmatic path: use **Option B** now for occasional third-model needs, and stand up a **ModelRouter** (Option A)
to give a stable single endpoint with name-based routing + external-provider fallback in front of the two hot
services. Combine the ModelRouter (routing) with a thin controller or operator step that flips `modelRef` /
scales services (lifecycle) if true automatic on-demand loading becomes a requirement.

---

## Research next

1. **Higher-concurrency sweep (256 / 512).** Both models were still climbing at 128 with 0 errors — the true
   saturation knee and the safe max concurrency are above the swept range and unknown. Extend the sweep to find
   where p95 TTFT/latency actually breaks and where aggregate throughput flattens.
2. **Prefix-aware load balancing across replicas.** If/when a model gets more than one replica (multi-GPU or
   future multi-node), naive round-robin throws away prefix-cache hits. Prefix-aware routing (route requests with
   a shared system/tool prompt to the same replica) preserves the cache wins that keep TTFT low.
3. **Native SM120 NVFP4-MoE kernels.** The 35B-A3B currently runs on the Marlin fallback on SM120. Track upstream
   vLLM for native SM120 NVFP4-MoE support and re-benchmark — expect a throughput uplift on the model that is
   already the throughput winner.
4. **Quality / accuracy validation of the quantized models.** All the above is *serving* performance. The
   NVFP4 quantization's effect on answer quality has not been validated. Run the BA evaluation suite
   (`testing/agents/`, tag `business_analyst`) against both NVFP4 models vs the `zai` baseline before locking the
   "35B-A3B by default, 27B for quality" routing policy — the quality escape-hatch assumption depends on it.

---

## Appendix — LLMKube ModelRouter analysis (read-only)

Investigated via `kubectl explain modelrouters.inference.llmkube.dev` and the CRD JSON schema. Group
`inference.llmkube.dev`, version **v1alpha1**. Description: *"exposes a single OpenAI-compatible HTTP endpoint
that dispatches requests across multiple InferenceService backends and external providers per declarative routing
rules"* (Phase 1).

**What it CAN do:**

- **Route by model name** — `rules[].match.models` glob-matches the OpenAI `model` field (e.g. `qwen3-*`);
  `defaultRouteStrategy: BackendNameMatch` resolves the request's model name to a backend by its `displayName`.
- **Multiple backends** — `spec.backends[]` lists candidates. Each is either an in-cluster `inferenceServiceRef`
  or an `external` provider (`anthropic`, `openai`, `bedrock`, `vertex_ai`, `litellm`, …) with a
  `credentialsSecretRef`. So local models and cloud providers can sit behind one endpoint.
- **Routing strategies** — per rule: `primary-fallback`, `weighted`, `shadow`. Rules match on model, headers,
  `requiredCapabilities` (e.g. `tools`, `vision`, `long-context`), `latencySLOMs` (P95 first-token target),
  `taskComplexity` (`simple`/`moderate`/`complex`), and `dataClassification`. First matching rule wins;
  `defaultRoute` / `defaultRouteStrategy` handle the no-match case. `failClosed` + backend health probes give
  automatic failover.
- **Governance** — `policy` block: JWT auth (Keycloak-style), per-team model allowlists, token/USD budgets over
  rolling windows, request classification, and audit logging. `dataPlane: Proxy` (managed router-proxy
  Deployment) or `Gateway` (Envoy AI Gateway).
- **Status surface** — per-backend health (`status.backends[].healthy/address/lastProbeTime`), budget
  utilization, conditions, and a coarse `phase` (`Pending`/`Provisioning`/`Ready`/`Degraded`/`Failed`).

**What it CANNOT do (relevant to "keep 2 hot, load others on-demand"):**

- **No on-demand model load/unload.** There is no spec field to load, unload, or warm a model. It routes to
  backends that already exist and are healthy; it does not create, wake, or tear them down.
- **No scale-to-zero.** No idle/scale-down behavior. (A backend that is scaled to zero simply shows unhealthy and
  is skipped / fails closed.)
- **It is a router/proxy, not a lifecycle manager.** Lifecycle (which model is loaded on which GPU) stays with
  the `InferenceService` objects and whatever flips their `modelRef` / replica count.

**Deployed?** `kubectl get modelrouters -A` → **No resources found.** The CRD is installed (LLMKube v0.9.0) but
no ModelRouter is currently in use.

**Bottom line for the "run them all" design:** a ModelRouter is the right tool for a **stable single endpoint
with name-based routing, capability/SLO rules, and cloud-provider fallback** in front of the two hot models. It
does **not** by itself deliver on-demand load/unload — that still requires swapping an `InferenceService`
`modelRef` (Option B) or an external controller driving it.
