# ADR-002: LLM Serving Stack — LLMKube + vLLM

| Field | Value |
|------|--------|
| **Status** | Accepted (implemented — live on `ka-k8s-ai`) |
| **Date** | 2026-07-07 |
| **Author** | Druppie Team |
| **Deciders** | Druppie architecture team |
| **References** | [LL-localllm-story.md](./LL-localllm-story.md) (LL1), [LLM-SERVING-RECOMMENDATION.md](./LLM-SERVING-RECOMMENDATION.md), [LLM-SELECTION.md](./LLM-SELECTION.md), [COMPARISON-MATRIX.md](../benchmarks/results-incluster/COMPARISON-MATRIX.md) |

> This ADR records **why** self-hosted LLM serving on `ka-k8s-ai` runs on **LLMKube (operator) + vLLM (engine)**.
> The choice was made and deployed in practice before this document; the ADR's job (per LL1) is to justify and
> record it, including the caveats hit along the way.

---

## Context

Druppie is a governance platform for AI agents. Agents act only through MCP tools and drive an LLM every step.
The platform currently defaults to a hosted provider (`zai`). We want the option to run inference **self-hosted**
on our own RKE2 GPU hardware, for two reasons:

1. **Data sovereignty** — agent prompts and tool traffic can carry sensitive project/organizational data. Keeping
   inference inside the `ka-k8s-ai` cluster boundary means that data never leaves our infrastructure.
2. **Cost** — a hosted per-token bill scales with agent activity. Owning the GPUs converts a variable per-token
   cost into a fixed capital/operational cost that is favorable at sustained agent volume.

Requirements for the serving stack:

- **OpenAI-compatible HTTP API** — Druppie's LLM client speaks the OpenAI/LiteLLM protocol; the serving stack must
  expose `/v1/chat/completions` etc.
- **Kubernetes-native** — declarative, GitOps-managed (Flux) on RKE2, not hand-run processes.
- **Tool calling + long context** — agents rely on function/tool calling and large contexts.
- **Fits the hardware** — 1 GPU node, 2× RTX PRO 6000 Blackwell (96 GB each, SM120), **no P2P** → serving is
  tensor-parallel = 1 (one model per GPU).

---

## Decision

Use the **LLMKube operator** to manage LLM serving, with **vLLM** as the inference engine.

- **LLMKube** (`inference.llmkube.dev`, v0.9.0) provides the Kubernetes-native control surface: `Model`,
  `InferenceService`, and `ModelRouter` CRDs. We declare a `Model` + `InferenceService` and the operator
  reconciles the vLLM Deployment, Service, and OpenAI endpoint. It integrates with Flux/GitOps and gives a clean
  declarative object per served model.
- **vLLM** (`vllm/vllm-openai:cu129-nightly`) is the engine LLMKube wraps: production-grade continuous batching,
  paged-attention KV cache, prefix caching, chunked prefill, fp8 KV cache, NVFP4 (ModelOpt) quantization, and an
  OpenAI-compatible server with tool-call parsing. The cu129 nightly is required for SM120 (Blackwell) support.

Live topology: two `InferenceService`s, one model per GPU — `qwen-35b` (`nvidia/Qwen3.6-35B-A3B-NVFP4`, MoE) and
`qwen-27b` (`nvidia/Qwen3.6-27B-NVFP4`, dense), each `runtime: generic`, weights served from a node-local `local`
PV cache. See [LLM-SERVING-RECOMMENDATION.md](./LLM-SERVING-RECOMMENDATION.md) for the model/workload guidance.

---

## Alternatives considered

| Option | Pros | Cons | Verdict |
|---|---|---|---|
| **LLMKube + vLLM** (chosen) | K8s-native CRDs (`Model`/`InferenceService`/`ModelRouter`); wraps vLLM's best-in-class throughput; declarative + GitOps-friendly; built-in ModelRouter for routing/failover/governance; supports NVFP4 + tool calling + long context | Young project (v0.x, v1alpha1 CRDs); thin abstraction leaks (needed the `generic`-runtime workaround, no `volumes`/`volumeMounts` on the CRD); small community | **Chosen** — best fit of K8s-native management + vLLM performance |
| **Raw vLLM Deployments** (hand-written Deployment/Service/HPA) | Maximum control over every vLLM flag; no operator abstraction to fight; well-understood | Everything is bespoke YAML per model (Deployment + Service + probes + scaling); no model-catalog abstraction; no built-in routing/governance; more to maintain and keep consistent across models | Rejected — LLMKube gives the same engine with a managed control surface; we can still override args when needed |
| **KServe** | CNCF, mature, model-mesh, canary/traffic-split, autoscaling (Knative) | Heavy footprint (Knative/Istio or equivalent); complex for a single 2-GPU node; opinionated around its own runtimes; overkill for our scale | Rejected — operational weight not justified for one GPU node |
| **KubeAI** | Purpose-built for LLMs on K8s; OpenAI-compatible; built-in autoscaling incl. scale-to-zero; model catalog | Also young; abstracts the engine (less direct vLLM tuning control); less proven on bleeding-edge SM120/NVFP4/cu129 nightly path we needed | Rejected for now — LLMKube's direct vLLM arg control was decisive given the SM120 workarounds; KubeAI's scale-to-zero remains attractive to revisit |
| **Ollama** | Trivial to run; great DX; wide model support via GGUF | Not built for high-concurrency production serving; weaker continuous batching/throughput vs vLLM; GGUF quant path not aligned with our NVFP4 weights; not the concurrency winner we measured vLLM to be | Rejected — fine for laptops/dev, not for concurrent agent workloads |
| **vLLM production-stack** (the `vllm-project` reference K8s stack: router + Helm) | Same engine; adds a prefix-aware router and Helm packaging from the vLLM project itself | Helm/router stack rather than a reconciling operator + CRDs; less of a declarative object model; would duplicate what LLMKube's ModelRouter targets | Rejected as the base — but its **prefix-aware router** is a concept worth borrowing (see Research next in the recommendation) |

---

## Consequences

### Positive

- **Declarative, GitOps-managed serving** — a `Model` + `InferenceService` per model, reconciled by the operator,
  managed through Flux like the rest of the cluster.
- **vLLM performance** — measured 0-error concurrency to 128 with headroom, high aggregate throughput
  (35B-A3B MoE ~4,414 tok/s @128), sub-second prefill across 256K context via prefix caching + chunked prefill.
- **Routing path exists** — the `ModelRouter` CRD is available for a future single-endpoint, name-based routing +
  external-provider fallback layer (not yet deployed).

### Caveats / workarounds we hit

- **`generic` runtime workaround.** The live `qwen-27b`/`qwen-35b` services run `runtime: generic` (not
  `runtime: vllm`). The `vllm` runtime auto-injects `--enable-metrics`, which the cu129 nightly image **rejects**;
  `generic` lets us supply a clean `command`/args set without that flag. (The benchmark rotations used
  `runtime: vllm` + a full `command` override + a `pvc://` source instead — both paths work, but the live
  services settled on `generic`.)
- **No `volumes` / `volumeMounts` on the CRD.** The `InferenceService` spec exposes no arbitrary volume mounting;
  the model weight cache is wired **only** via `modelCache.claimName` / a `pvc://` source. This constrains how the
  node-local `local` PV (`llm-model-weights`) is attached and is why the cache is surfaced through the model
  source rather than a generic mount.
- **TP=1 by design.** No P2P between the two Blackwell cards → tensor-parallel across them would bottleneck on
  inter-GPU communication. The architecture is therefore **N independent models, one per GPU** (2 hot models max),
  and scaling means more GPUs/replicas, not larger tensor-parallel.
- **SM120 Marlin MoE fallback.** vLLM has no native NVFP4 MoE kernel for SM120 yet, so MoE models (incl.
  35B-A3B) fall back to the slower **Marlin** kernel. It is still the throughput winner today; native SM120
  NVFP4-MoE kernels would add further upside.
- **Young project.** LLMKube is v0.x with v1alpha1 CRDs; API churn and rough edges (the above) are expected. The
  mitigation is that we retain direct vLLM arg control through the `generic` runtime / command override, so we are
  never blocked by the operator's abstraction.

### Follow-ups

- Autoscaling on GPU utilization (KEDA/HPA on the DCGM metric) — currently fixed replicas (see LL2).
- Register the local endpoint as a Druppie provider + Helm wiring (LL2).
- Higher-concurrency sweep, prefix-aware load balancing, native SM120 NVFP4-MoE, and quantized-model quality
  validation — see [LLM-SERVING-RECOMMENDATION.md → Research next](./LLM-SERVING-RECOMMENDATION.md#research-next).

---

## TODO: incorporate @nuno's prior research (shared in chat)

> **Placeholder.** @nuno did prior research on the serving-stack choice that was shared in chat and is **not
> available to the author of this ADR**. This section is a deliberate stub so it is not forgotten — do **not**
> treat the below as filled in.
>
> When incorporating, capture at least:
> - Which stacks/engines @nuno evaluated and the criteria used.
> - Any findings that confirm or contradict the alternatives table above (esp. KServe / KubeAI / vLLM
>   production-stack).
> - Any benchmark or operational data @nuno gathered that should be cross-referenced here.
> - Whether any of @nuno's conclusions change the "Decision" or the "Consequences" sections.
>
> Until this section is filled in from the actual chat content, the alternatives analysis above reflects only the
> author's assessment, not @nuno's research.
