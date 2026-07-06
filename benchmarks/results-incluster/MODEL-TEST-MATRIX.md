# Model Test Matrix

Self-updating backlog of LLM benchmark candidates. Regenerated every sweep by `benchmarks/update_test_matrix.py` from `benchmarks/candidates.yaml`; a model is **Tested** once `results-incluster/<slug>/report.txt` exists.

**Legend** -- ✅ Tested: benchmarked, metrics parsed from its `report.txt`. ⬜ To test: on the backlog, not yet benchmarked (`--` metrics).

**Progress:** 1 tested / 19 total (12 local, 7 API).

Columns: TTFT (med) = median time-to-first-token over streaming scenarios; Decode tok/s = median generation throughput; Lat-500 = `latency-500` total latency; Ctx-64k TTFT = `context-64k` prefill; Tool Δ = `tool-call-10-tools` minus `tool-call-3-tools` latency; Stress σ = `repeated-50` latency stddev; Errors = errored runs. Per-run detail lives in `COMPARISON-MATRIX.md` and each per-model `report.txt`.

## Local models (downloadable weights, benchmarked in-cluster)

| Model | Source | Params | Status | TTFT (med) | Decode tok/s | Lat-500 | Ctx-64k TTFT | Tool Δ | Stress σ | Errors | Notes |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Qwen3.6-27B | `Qwen/Qwen3.6-27B` | 27B | ✅ Tested | 158 ms | 26.0 t/s | 189.4 s | 463 ms | -0.10 s | 2,800 ms | 1 | reasoning model, already benchmarked |
| Gemma-4-26B-A4B | `google/gemma-4-26B-A4B` | 26B (MoE, ~A4B active) | ⬜ To test | -- | -- | -- | -- | -- | -- | -- |  |
| Qwen3.6-35B-A3B | `Qwen/Qwen3.6-35B-A3B` | 35B (MoE, A3B active) | ⬜ To test | -- | -- | -- | -- | -- | -- | -- |  |
| Gemma-4-31B | `google/gemma-4-31B` | 31B | ⬜ To test | -- | -- | -- | -- | -- | -- | -- |  |
| GLM-5.1 | `(GGUF, IQ3_KS quant)` | quantized IQ3_KS | ⬜ To test | -- | -- | -- | -- | -- | -- | -- | CPU/GPU hybrid, 2x RTX 6000 Pro reference |
| Qwen3-Coder-Next-80B-A3B | `Qwen3-Coder-Next-80B` | 80B (A3B active) | ⬜ To test | -- | -- | -- | -- | -- | -- | -- |  |
| GPT-OSS-120B | `gpt-oss-120b` | 120B | ⬜ To test | -- | -- | -- | -- | -- | -- | -- |  |
| Qwen3-Coder-480B-A35B-Instruct | `Qwen3-Coder-480B-A35B-Instruct` | 480B (A35B active) | ⬜ To test | -- | -- | -- | -- | -- | -- | -- |  |
| GLM-4.6V | `unsloth/GLM-4.6V-GGUF` | vision | ⬜ To test | -- | -- | -- | -- | -- | -- | -- | multimodal/vision |
| Qwen3.6-27B-MTP | `unsloth/Qwen3.6-27B-MTP-GGUF` | 27B (MTP) | ⬜ To test | -- | -- | -- | -- | -- | -- | -- | multi-token-prediction speed variant of Qwen3.6-27B |
| Gemma-4-E4B-it | `unsloth/gemma-4-E4B-it-GGUF` | E4B | ⬜ To test | -- | -- | -- | -- | -- | -- | -- | extreme-speed small variant |
| DeepSeek-V3.1 | `unsloth/DeepSeek-V3.1-GGUF` | quantized (only q1 UD-TQ1_0 fits) | ⬜ To test | -- | -- | -- | -- | -- | -- | -- | fits only at q1 |

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

