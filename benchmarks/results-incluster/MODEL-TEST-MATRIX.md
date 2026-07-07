# Model Test Matrix

Self-updating backlog of LLM benchmark candidates. Regenerated every sweep by `benchmarks/update_test_matrix.py` from `benchmarks/candidates.yaml`; a model is **Tested** once `results-incluster/<slug>/report.txt` exists with real metrics, **Failed** when that report exists but every scenario errored (no usable metrics), or **Skipped** when the sweep records a reason (a runtime `results-incluster/<slug>/SKIPPED.txt`, or a static `skip_reason` in `candidates.yaml` for models too large / needing 2 GPUs).

**Legend** -- ✅ Tested: benchmarked, metrics parsed from its `report.txt`. ❌ Failed: attempted but every scenario errored -- no usable metrics (e.g. wrong/absent serving profile); reason in Notes. ⛔ Skipped: not benchmarked, reason in Notes (too large / needs a maintenance window / serving fast-failed). ⬜ To test: on the backlog, not yet attempted (`--` metrics).

**Progress:** 6 tested / 1 failed / 3 skipped / 21 total (14 local, 7 API).

Columns: TTFT (med) = median time-to-first-token over streaming scenarios; Decode tok/s = median generation throughput; Lat-500 = `latency-500` total latency; Ctx-64k TTFT = `context-64k` prefill; Tool Δ = `tool-call-10-tools` minus `tool-call-3-tools` latency; Stress σ = `repeated-50` latency stddev; Errors = errored runs. Per-run detail lives in `COMPARISON-MATRIX.md` and each per-model `report.txt`.

## Local models (downloadable weights, benchmarked in-cluster)

| Model | Source | Params | Status | TTFT (med) | Decode tok/s | Lat-500 | Ctx-64k TTFT | Tool Δ | Stress σ | Errors | Notes |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Qwen3.6-27B (bf16) | `Qwen/Qwen3.6-27B` | 27B (bf16) | ✅ Tested | 158 ms | 26.0 t/s | 189.4 s | 463 ms | -0.10 s | 2,800 ms | 1 | Full-precision variant; SUPERSEDED in prod by the served NVFP4 build (nvidia/Qwen3.6-27B-NVFP4, isvc qwen-27b). Existing results-incluster/qwen3.6-27b/ report.txt is this bf16 build. Benchmarkable as Case B (frees 1 GPU). |
| Qwen3.6-27B-NVFP4 | `nvidia/Qwen3.6-27B-NVFP4` | 27B (NVFP4) | ✅ Tested | 191 ms | 64.0 t/s | 16.1 s | 443 ms | -0.20 s | 6,700 ms | 0 | SERVED in prod by isvc qwen-27b (modelRef qwen3-6-27b); benchmarked IN PLACE, no scaling. In-cluster live 2026-07-06 (256K, cu129-nightly). |
| Qwen3.6-35B-A3B-NVFP4 | `nvidia/Qwen3.6-35B-A3B-NVFP4` | 35B MoE A3B (NVFP4) | ✅ Tested | 99 ms | 216.5 t/s | 4.7 s | 251 ms | 0.00 s | 900 ms | 0 | SERVED in prod by isvc qwen-35b (modelRef qwen3-6-35b-a3b); benchmarked IN PLACE, no scaling. This is the DEFAULT FREE_SERVICE (scaled 1->0 to free a GPU for other bench models). In-cluster live 2026-07-06 (256K, cu129-nightly). |
| Qwen3-Coder-Next-80B-A3B (NVFP4) | `Cirrascale/Qwen3-Coder-Next-NVFP4` | 80B (A3B active, NVFP4) | ✅ Tested | 197 ms | 139.5 t/s | 7.3 s | 3,200 ms | 0.10 s | 0 ms | 0 | RECLASSIFIED needs-2gpu -> fits-1gpu at NVFP4 (~2.5-3.5x smaller than the ~160GB bf16). Source is a COMMUNITY NVFP4 quant (Cirrascale/Qwen3-Coder-Next-NVFP4); the OFFICIAL nvidia NVFP4 for the *coder-next* 80B is NOT confirmed (nvidia ships Qwen3-Next-80B-A3B-Instruct-NVFP4, a non-coder sibling). May fast-fail if the community repo layout/param-count differs -- captured as a reason. |
| GPT-OSS-120B | `gpt-oss-120b` | 120B (MoE) | ✅ Tested | 480 ms | 176.5 t/s | 5.8 s | -- | 0.00 s | 100 ms | 5 | ships native MXFP4 (loads without extra quant); needs gpt-oss serving config, NOT qwen3_xml. An NVFP4 modelopt quant EXISTS (community shanjiaz/gpt-oss-120b-nvfp4-modelopt) but we keep NATIVE MXFP4: it already fits, and on our SM120 (RTX PRO 6000 Blackwell) cards NVFP4/MXFP4 native MoE kernels fall back to Marlin (slower) -- native MXFP4 is the safer path. |
| Gemma-4-E4B-it | `unsloth/gemma-4-E4B-it-GGUF` | E4B | ✅ Tested | 37 ms | 117.5 t/s | 8.7 s | -- | -- | 0 ms | 9 | extreme-speed small variant; served from the SAFETENSORS repo google/gemma-4-E4B-it (natively supported by vLLM) |
| Gemma-4-26B-A4B | `google/gemma-4-26B-A4B` | 26B (MoE, ~A4B active) | ❌ Failed | -- | -- | -- | -- | -- | -- | -- | Failed -- Attempted in-cluster 2026-07-07 -- the vLLM InferenceService came up but ALL 20 scenarios errored (context/generate/latency/tool-call/stress); no usable numbers. Root cause: launched with qwen's serving args/profile -- gemma needs its OWN vLLM profile. (backlog only (no registered CR); fit informational. No confirmed nvidia/*-NVFP4 build; kept as the bf16 HF repo (already fits at bf16, so NVFP4 not required).) |
| GLM-5.1 | `unsloth/GLM-5.1-GGUF` | 744B (MoE, 40B active) | ⛔ Skipped | -- | -- | -- | -- | -- | -- | -- | Skipped -- Not benchmarked -- exceeds VRAM (744B MoE, still ~372GB at NVFP4 4-bit > 192GB total; needs RAM/MoE offload or multi-node). No confirmed nvidia/*-NVFP4 build. (NVFP4 does NOT rescue this: 744B @4-bit is still > 192GB. No NVFP4 source confirmed; kept as GGUF. CPU/GPU hybrid or multi-node required; not attempted.) |
| Qwen3-Coder-480B-A35B-Instruct (NVFP4) | `nvidia/Qwen3-Coder-480B-A35B-Instruct-NVFP4` | 480B (A35B active, NVFP4) | ⛔ Skipped | -- | -- | -- | -- | -- | -- | -- | Skipped -- Not benchmarked -- still exceeds VRAM even at NVFP4 (~240-270GB > 192GB total, and far > one 96GB freed card; needs multi-node). CONFIRMED source: nvidia/Qwen3-Coder-480B-A35B-Instruct-NVFP4. (Official NVFP4 quant EXISTS (nvidia/Qwen3-Coder-480B-A35B-Instruct-NVFP4, ~3.5x memory reduction) but 480B @4-bit is still too big for the single freed GPU / 192GB total. Kept too-large.) |
| DeepSeek-V3.1 | `unsloth/DeepSeek-V3.1-GGUF` | 671B (37B active) | ⛔ Skipped | -- | -- | -- | -- | -- | -- | -- | Skipped -- Not benchmarked -- exceeds VRAM (671B MoE, still ~335GB at NVFP4 4-bit > 192GB total; needs multi-node). No confirmed nvidia/*-NVFP4 build for V3.1. (NVFP4 does NOT rescue this: 671B @4-bit is still > 192GB. No NVFP4 source confirmed; kept as GGUF. Fits only at q1; not attempted.) |
| Qwen3.6-35B-A3B (bf16) | `Qwen/Qwen3.6-35B-A3B` | 35B (MoE, A3B active, bf16) | ⬜ To test | -- | -- | -- | -- | -- | -- | -- | Full-precision variant; SUPERSEDED in prod by the served NVFP4 build (nvidia/Qwen3.6-35B-A3B-NVFP4, isvc qwen-35b). Benchmarkable as Case B if you want a bf16-vs-NVFP4 comparison. |
| Gemma-4-31B | `google/gemma-4-31B` | 31B | ⬜ To test | -- | -- | -- | -- | -- | -- | -- | backlog only (no registered CR); fit informational. No confirmed nvidia/*-NVFP4 build; kept as the bf16 HF repo (already fits at bf16). |
| GLM-4.6V | `unsloth/GLM-4.6V-GGUF` | 106B (vision) | ⬜ To test | -- | -- | -- | -- | -- | -- | -- | multimodal/vision -- fits one 96GB card. No confirmed nvidia/*-NVFP4 build for this vision model; kept as GGUF. Vision serving on vLLM is unverified; likely fast-fails with a captured reason. |
| Qwen3.6-27B-MTP | `unsloth/Qwen3.6-27B-MTP-GGUF` | 27B (MTP) | ⬜ To test | -- | -- | -- | -- | -- | -- | -- | multi-token-prediction speed variant of Qwen3.6-27B; GGUF -- no confirmed nvidia/*-NVFP4 build (MTP is a speculative-decode variant), kept as GGUF. Attempted with the generic default args (profile-less); may fast-fail on GGUF handling -- captured as a reason. |

## API models (OpenRouter-hosted, API-only)

| Model | Source | Params | Status | TTFT (med) | Decode tok/s | Lat-500 | Ctx-64k TTFT | Tool Δ | Stress σ | Errors | Notes |
|---|---|---|---|---|---|---|---|---|---|---|---|
| MiniMax-M2.7 | `openrouter/minimax-m2.7` | NVFP4 | ⬜ To test | -- | -- | -- | -- | -- | -- | -- | SGlang + B12x optimization |
| DeepSeek-V4-Flash | `openrouter/deepseek-v4-flash` | -- | ⬜ To test | -- | -- | -- | -- | -- | -- | -- |  |
| Hy3 | `openrouter/hy3-preview` | -- | ⬜ To test | -- | -- | -- | -- | -- | -- | -- |  |
| Owl-Alpha | `openrouter/owl-alpha` | -- | ⬜ To test | -- | -- | -- | -- | -- | -- | -- |  |
| Nemotron-3-Super | `openrouter/nemotron-3-super` | -- | ⬜ To test | -- | -- | -- | -- | -- | -- | -- |  |
| Kimi-K2.6 | `openrouter/kimi-k2.6` | -- | ⬜ To test | -- | -- | -- | -- | -- | -- | -- |  |
| Step-3.5-Flash | `openrouter/step-3.5-flash` | -- | ⬜ To test | -- | -- | -- | -- | -- | -- | -- |  |

