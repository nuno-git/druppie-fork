# Model Comparison Matrix

10 registered model(s) tracked; **4 benchmarked** (NVFP4/MXFP4, served from the GPU-node local-disk weight cache, TP=1, 2026-07-07). Models not (yet) benchmarked still appear with a `Status / Note` (pending/gated, or too large for this hardware).

## Headline metrics

| Model | Params | Quant / size | Median TTFT (ms) | Median decode (tok/s) | latency-500 (s) | context-64k TTFT (ms) | tool 10-3 delta (s) | Errors | Status / Note |
|---|---|---|---|---|---|---|---|---|---|
| **Qwen3.6-27B-NVFP4** | 27B (dense) | NVFP4 ~22GB | ~95 | ~64 | 16.1 | 443 | -0.2 | 0 | ✅ Benchmarked — served as `qwen-27b`, loaded from local-disk cache; 256k ctx ✅ |
| **Qwen3.6-35B-A3B-NVFP4** | 35B (3B act., MoE) | NVFP4 ~22GB | ~80 | ~218 | 4.7 | 173 | ~0.0 | 0 | ✅ Benchmarked — served as `qwen-35b`, from cache; 256k ctx ✅; SM120 Marlin MoE fallback |
| **gpt-oss-120b** | 120B (MoE) | MXFP4 ~63GB VRAM (~183GB on disk) | ~284 | ~176 | 5.8 | n/a¹ | ~0.1 | 0² | ✅ Benchmarked — MXFP4, from cache |
| **Qwen3-Coder-Next-80B-NVFP4** | 80B (MoE) | NVFP4 ~47GB | ~138 | ~140 | 7.3 | 3,200 | ~0.1 | 0 | ✅ Benchmarked — Cirrascale NVFP4, from cache; 256k ctx ✅ (TTFT 30.8s@256k); SM120 Marlin MoE fallback |
| Gemma 4 E4B | ~4B (E4B eff.) | GGUF ~4-8GB | -- | -- | -- | -- | -- | -- | ⏳ Pending — **gated** (HF token not yet in vault) |
| Qwen3.6-27B-MTP (GGUF) | 27B (+MTP head) | GGUF ~16-30GB | -- | -- | -- | -- | -- | -- | Not benchmarked — GGUF, not staged |
| GLM-4.6V (GGUF, vision) | 106B | GGUF ~60GB @Q4 | -- | -- | -- | -- | -- | -- | Not benchmarked — vision/GGUF, not staged (vLLM support unverified) |
| Qwen3-Coder-480B-A35B (MoE) | 480B (35B act.) | ~270GB @NVFP4 | -- | -- | -- | -- | -- | -- | ❌ Too large — >192GB total (needs multi-node) |
| DeepSeek-V3.1 (MoE) | 671B (37B act.) | ~380GB @Q4 | -- | -- | -- | -- | -- | -- | ❌ Too large — >192GB total (needs multi-node) |
| GLM-5.1 (MoE) | 744B (40B act.) | ~220-236GB @2-bit | -- | -- | -- | -- | -- | -- | ❌ Too large — >192GB total (needs RAM/MoE offload or multi-node) |

¹ gpt-oss was served at `--max-model-len 8192` for the run, so the 16k/32k/64k/128k/256k context scenarios were **out of range (config choice, not a model limit)** — TTFT at low context ~200-500 ms.
² 0 errors on the 15 in-range scenarios (incl. both tool-calling scenarios); the 5 over-8k context scenarios were N/A per ¹.

**Column notes**

- **Median TTFT (ms)** — median time-to-first-token over streaming runs. Lower is better.
- **Median decode (tok/s)** — median steady-state generation throughput. Higher is better. Note the MoE models (35B-A3B, gpt-oss, coder-next) decode far faster than the dense 27B because only a few B params are active per token.
- **latency-500 (s)** — total latency of the `latency-500` scenario (a fixed-output single call); scales inversely with decode tok/s, so it's comparable across models.
- **context-64k TTFT (ms)** — prefill cost at ~64k prompt tokens.
- **tool 10-3 delta (s)** — `tool-call-10-tools` minus `tool-call-3-tools`; cost of extra tool schemas (≈0 = negligible).
- **Errors** — errored runs across all scenarios. `--` = not benchmarked.

## Methodology & serving

All benchmarked models were served **from the persistent weight cache** (a `local` PersistentVolume on the GPU node's disk, `pvc://llm-model-weights/<model>`) via `runtime: vllm` on `vllm/vllm-openai:cu129-nightly` with a `command` override (to drop the auto-injected `--enable-metrics` that this image rejects), TP=1, KV-cache fp8. Each was benchmarked with the standard 20-scenario suite (`--runs 2 --warmup 1 --timeout 600`). The two served models (27B, 35B-A3B) were benchmarked against their live prod endpoints (non-disruptive); gpt-oss and coder-next were rotated onto a freed GPU (scale `qwen-35b`→0, serve from cache, benchmark, restore) — `qwen-27b` stayed serving throughout.

**SM120 caveat:** the NVFP4 **MoE** models (35B-A3B, coder-next) log `Using 'MARLIN' NvFp4 MoE backend` on the RTX PRO 6000 Blackwell (SM120) — the Marlin fallback kernel, not the faster FLASHINFER/CUTLASS backends — so their decode throughput has upside once vLLM enables native SM120 NVFP4-MoE kernels.

## Fit classes & hardware constraint

Hardware: 1 GPU node, 2× NVIDIA RTX PRO 6000 Blackwell (96GB each = 192GB total), no P2P → TP=1 (one model per GPU). ns `llm` GPU ResourceQuota hard=2, both GPUs held by the two live `qwen-*` services. A benchmark run frees at most ONE GPU. Sizes are ESTIMATES (~).

- **`served`** — currently served in prod; benchmarked against the live endpoint.
- **`fits-1gpu`** — fits one card (≤~90GB); benchmarkable by freeing 1 GPU (rotation).
- **`too-large`** — exceeds 192GB total even quantized; not testable on this hardware.

## Per-model reports

Full per-scenario reports: `benchmarks/results-incluster/<model>/report.txt` (27B-NVFP4 and 35B-A3B committed; gpt-oss and coder-next captured during their rotation runs).
