# Model Comparison Matrix

21 registered model(s) tracked; 6 benchmarked (from 6 committed report.txt + 0 live result JSON(s)). Models that are not (yet) benchmarked still appear, with a `Status / Note` explaining why (fits/pending, needs a maintenance window, or too large for this hardware).

## Headline metrics

| Model | Params | Quant / size | Median TTFT (ms) | Median decode (tok/s) | latency-500 (s) | context-64k TTFT (ms) | tool 10-3 delta (s) | stress stddev (ms) | Errors | Status / Note |
|---|---|---|---|---|---|---|---|---|---|---|
| Gemma-4-26B-A4B | 26B (MoE, ~A4B active) | ~52GB bf16 / ~13GB NVFP4 | -- | -- | -- | -- | -- | -- | -- | Skipped -- Attempted in-cluster 2026-07-07 -- the vLLM InferenceService came up but ALL 20 scenarios errored (context/generate/latency/tool-call/stress); no usable numbers. Root cause: launched with qwen's serving args/profile -- gemma needs its OWN vLLM profile. Evidence kept in report-FAILED-all-errors.txt. |
| Qwen3.6-35B-A3B (bf16) | 35B (MoE, A3B active, bf16) | ~70GB bf16 (tight on one 96GB card) | -- | -- | -- | -- | -- | -- | -- | Full-precision variant; SUPERSEDED in prod by the served NVFP4 build (nvidia/Qwen3.6-35B-A3B-NVFP4, isvc qwen-35b). Benchmarkable as Case B if you want a bf16-vs-NVFP4 comparison. |
| Qwen3.6-27B (bf16) | 27B (bf16) | ~54GB bf16 | 158 | 26.0 | 189.4 | 463 | -0.10 | 2,800 | 1 | Benchmarked. |
| Qwen3.6-27B-NVFP4 | 27B (NVFP4) | ~16GB (NVFP4 4-bit) | 191 | 64.0 | 16.1 | 443 | -0.20 | 6,700 | 0 | Served in prod (isvc qwen-27b); benchmarked IN PLACE from local-disk cache, TP=1, 256K ctx OK. |
| Qwen3.6-35B-A3B-NVFP4 | 35B MoE A3B (NVFP4) | ~20GB (NVFP4 4-bit) | 99 | 216.5 | 4.7 | 251 | 0.00 | 900 | 0 | Served in prod (isvc qwen-35b); benchmarked IN PLACE from local-disk cache, TP=1, 256K ctx OK. SM120 Marlin MoE fallback. |
| Gemma-4-31B | 31B | ~62GB bf16 / ~16GB NVFP4 | -- | -- | -- | -- | -- | -- | -- | backlog only (no registered CR); fit informational. No confirmed nvidia/*-NVFP4 build; kept as the bf16 HF repo (already fits at bf16). |
| GLM-5.1 | 744B (MoE, 40B active) | ~220-236GB @2-bit GGUF / ~372GB NVFP4 | -- | -- | -- | -- | -- | -- | -- | Not benchmarked -- exceeds VRAM (744B MoE, still ~372GB at NVFP4 4-bit > 192GB total; needs RAM/MoE offload or multi-node). No confirmed nvidia/*-NVFP4 build. |
| Qwen3-Coder-Next-80B-A3B (NVFP4) | 80B (A3B active, NVFP4) | ~44GB NVFP4 (80B @4-bit + KV cache; fits one 96GB card) | 197 | 139.5 | 7.3 | 3,200 | 0.10 | 0 | 0 | Benchmarked from local-disk cache via runtime:vllm + command override, TP=1, 256K ctx OK (TTFT 30.8s@256k). SM120 Marlin MoE fallback. |
| GPT-OSS-120B | 120B (MoE) | ~63GB (native MXFP4) | 480 | 176.5 | 5.8 | -- | 0.00 | 100 | 5 | Benchmarked from local-disk cache via runtime:vllm + command override, TP=1. Served at max-model-len 8192, so the 16k+ context scenarios are out-of-range BY CONFIG (not a model limit) and are the errored runs; 0 errors on the 15 in-range scenarios. SM120 Marlin MoE fallback. |
| Qwen3-Coder-480B-A35B-Instruct (NVFP4) | 480B (A35B active, NVFP4) | ~240-270GB NVFP4 (~3.5x smaller than ~960GB bf16, still > 192GB total) | -- | -- | -- | -- | -- | -- | -- | Not benchmarked -- still exceeds VRAM even at NVFP4 (~240-270GB > 192GB total, and far > one 96GB freed card; needs multi-node). CONFIRMED source: nvidia/Qwen3-Coder-480B-A35B-Instruct-NVFP4. |
| GLM-4.6V | 106B (vision) | ~53GB NVFP4 / ~60GB @Q4 GGUF | -- | -- | -- | -- | -- | -- | -- | Not benchmarked -- vision GGUF, not staged. |
| Qwen3.6-27B-MTP | 27B (MTP) | ~16-30GB GGUF quant | -- | -- | -- | -- | -- | -- | -- | Not benchmarked -- GGUF, not staged. |
| Gemma-4-E4B-it | E4B | ~4-8GB GGUF | 37 | 117.5 | 8.7 | -- | -- | 0 | 9 | Benchmarked. |
| DeepSeek-V3.1 | 671B (37B active) | ~335GB NVFP4 / ~380GB @Q4 GGUF (only q1 UD-TQ1_0 fits) | -- | -- | -- | -- | -- | -- | -- | Not benchmarked -- exceeds VRAM (671B MoE, still ~335GB at NVFP4 4-bit > 192GB total; needs multi-node). No confirmed nvidia/*-NVFP4 build for V3.1. |
| MiniMax-M2.7 | NVFP4 | -- | -- | -- | -- | -- | -- | -- | -- | SGlang + B12x optimization |
| DeepSeek-V4-Flash | -- | -- | -- | -- | -- | -- | -- | -- | -- |  |
| Hy3 | -- | -- | -- | -- | -- | -- | -- | -- | -- |  |
| Owl-Alpha | -- | -- | -- | -- | -- | -- | -- | -- | -- |  |
| Nemotron-3-Super | -- | -- | -- | -- | -- | -- | -- | -- | -- |  |
| Kimi-K2.6 | -- | -- | -- | -- | -- | -- | -- | -- | -- |  |
| Step-3.5-Flash | -- | -- | -- | -- | -- | -- | -- | -- | -- |  |

**Column notes**

- **Median TTFT (ms)** -- median time-to-first-token over all streaming runs (latency + generation + context_scaling). Lower is better.
- **Median decode (tok/s)** -- median steady-state generation throughput over generation scenarios. Higher is better.
- **latency-500 (s)** -- median total latency of the `latency-500` scenario (representative single-call latency).
- **context-64k TTFT (ms)** -- prefill cost at ~64k prompt tokens (`context-64k`); measures context scaling.
- **tool 10-3 delta (s)** -- `tool-call-10-tools` minus `tool-call-3-tools` median latency; cost of extra tool schemas.
- **stress stddev (ms)** -- latency stddev over `repeated-50`; consistency under repeated calls (lower = steadier).
- **Errors** -- count of errored runs across all scenarios (e.g. context exceeding the model's max). `--` = not benchmarked.
- **Status / Note** -- for un-benchmarked rows, why there are no metrics (see fit classes below). Sizes are ESTIMATES (~).

## Fit classes & hardware constraint

Hardware: 1 GPU node, 2x NVIDIA RTX PRO 6000 Blackwell (96GB each = 192GB total). No P2P between cards, so serving is tensor-parallel=1 (one model per GPU). The `llm` namespace GPU ResourceQuota is hard=2, and both GPUs are normally held by the live `qwen` service. A benchmark run frees at most ONE GPU (qwen 2->1); using both (TP=2) takes prod fully down. All sizes are ESTIMATES (~).

- **`served`** -- Currently served in prod; benchmarked in place (no serving change).
- **`fits-1gpu`** -- Fits one RTX PRO 6000 (<=~90GB usable). Benchmarkable now by freeing 1 GPU (qwen 2->1).
- **`needs-2gpu`** -- Needs both GPUs (tensor-parallel 2, ~160GB). Testable only in a full maintenance window -- it takes prod fully down.
- **`too-large`** -- Exceeds 192GB total even quantized. Not testable on this hardware (needs multi-node / RAM-MoE offload).

## Methodology

All benchmarked models were served in-cluster (ka-k8s-ai) from a LOCAL-DISK model cache (`pvc://` volume, no per-run HF download) via the vLLM runtime (`runtime: vllm`) with a per-model command/args override (see the `profile` blocks in `benchmarks/candidates.yaml`), tensor-parallel=1, on 2026-07-07. On the SM120 (RTX PRO 6000 Blackwell) cards, native NVFP4/MXFP4 MoE kernels fall back to Marlin (slower) for the MoE models (Qwen3.6-35B-A3B-NVFP4, Qwen3-Coder-Next-80B-NVFP4, gpt-oss-120b). gpt-oss-120b was served at max-model-len 8192, so its 16k+ context scenarios are out-of-range BY CONFIG (not a model limit) and are counted as errors. Headline metrics here are parsed from each model's committed `results-incluster/<slug>/report.txt` (the per-run JSONs are transient), so re-running `compare_models.py` reproduces this matrix deterministically.

## Per-category throughput

_Per-category tok/s breakdown needs the transient per-run result JSON (kept only in the sweep's WORKDIR, not committed). The reproducible headline metrics above are parsed from each model's committed `report.txt`; see `MODEL-TEST-MATRIX.md` and the per-model `report.txt` for the full per-scenario detail._

## Concurrency / throughput under load

This measures the production-relevant CONCURRENT workload -- N streaming requests kept in flight at once -- and is distinct from the single-stream headline table above (which sends one request at a time). *Aggregate tok/s* is the total decode rate summed across all concurrent requests. MoE models (e.g. Qwen3.6-35B-A3B, only ~A3B params active per token) sustain far higher aggregate throughput under load than the dense 27B, despite comparable single-stream decode speeds.

_Cells = aggregate throughput (tok/s) at that concurrency level (higher is better)._

| Concurrency | Qwen3.6-27B-NVFP4 | Qwen3.6-35B-A3B-NVFP4 |
|---|---|---|
| 1 | 64 | 219 |
| 8 | 409 | 1,059 |
| 32 | 1,094 | 2,475 |
| 64 | 1,434 | 3,072 |
| 128 | 1,658 | 4,414 |

**Per-model summary**

- **Qwen3.6-27B-NVFP4** -- peak **1,658 tok/s** @ concurrency 128; at max concurrency 128: p95 latency 20.7s, p95 TTFT 6.2s, 0 error(s). Throughput had NOT saturated within the swept range (still rising at concurrency 128).
- **Qwen3.6-35B-A3B-NVFP4** -- peak **4,414 tok/s** @ concurrency 128; at max concurrency 128: p95 latency 7.6s, p95 TTFT 2.2s, 0 error(s). Throughput had NOT saturated within the swept range (still rising at concurrency 128).

## Source files

- `benchmarks/results-incluster/qwen3.6-27b/report.txt` (committed report.txt)
- `benchmarks/results-incluster/qwen3.6-27b-nvfp4/report.txt` (committed report.txt)
- `benchmarks/results-incluster/qwen3.6-35b-a3b-nvfp4/report.txt` (committed report.txt)
- `benchmarks/results-incluster/qwen3-coder-next-nvfp4/report.txt` (committed report.txt)
- `benchmarks/results-incluster/gpt-oss-120b/report.txt` (committed report.txt)
- `benchmarks/results-incluster/gemma-4-e4b-it-gguf/report.txt` (committed report.txt)
- `benchmarks/results-incluster/qwen3.6-27b-nvfp4/load-test.json` (committed load-test.json)
- `benchmarks/results-incluster/qwen3.6-35b-a3b-nvfp4/load-test.json` (committed load-test.json)

