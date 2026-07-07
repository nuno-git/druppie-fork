# Model Comparison Matrix

10 registered model(s) tracked; 4 benchmarked (from 4 committed report.txt + 0 live result JSON(s)). Models that are not (yet) benchmarked still appear, with a `Status / Note` explaining why (fits/pending, needs a maintenance window, or too large for this hardware).

## Headline metrics

| Model | Params | Quant / size | Median TTFT (ms) | Median decode (tok/s) | latency-500 (s) | context-64k TTFT (ms) | tool 10-3 delta (s) | stress stddev (ms) | Errors | Status / Note |
|---|---|---|---|---|---|---|---|---|---|---|
| Gemma 4 E4B (gemma-4-E4B-it) | ~4B (E4B eff.) | GGUF ~4-8GB | -- | -- | -- | -- | -- | -- | -- | Pending -- gated (HF token not in vault). |
| Qwen3.6-27B-NVFP4 | 27B (dense) | NVFP4 ~22GB | 191 | 64.0 | 16.1 | 443 | -0.20 | 6,700 | 0 | Served in prod (isvc qwen-27b); benchmarked IN PLACE from local-disk cache, TP=1, 256K ctx OK. |
| Qwen3.6-27B-MTP (GGUF) | 27B (+MTP head) | GGUF ~16-30GB | -- | -- | -- | -- | -- | -- | -- | Not benchmarked -- GGUF, not staged. |
| Qwen3.6-35B-A3B-NVFP4 (MoE) | 35B MoE (3B act.) | NVFP4 ~22GB | 99 | 216.5 | 4.7 | 251 | 0.00 | 900 | 0 | Served in prod (isvc qwen-35b); benchmarked IN PLACE from local-disk cache, TP=1, 256K ctx OK. SM120 Marlin MoE fallback. |
| Qwen3-Coder-Next-80B-NVFP4 (MoE) | 80B MoE | NVFP4 ~47GB | 197 | 139.5 | 7.3 | 3,200 | 0.10 | 0 | 0 | Benchmarked from local-disk cache via runtime:vllm + command override, TP=1, 256K ctx OK (TTFT 30.8s@256k). SM120 Marlin MoE fallback. |
| gpt-oss-120b (MoE) | 120B MoE | MXFP4 ~63GB | 480 | 176.5 | 5.8 | -- | 0.00 | 100 | 5 | Benchmarked from local-disk cache via runtime:vllm + command override, TP=1. Served at max-model-len 8192, so the 16k+ context scenarios are out-of-range BY CONFIG (not a model limit) and are the errored runs; 0 errors on the 15 in-range scenarios. SM120 Marlin MoE fallback. |
| Qwen3-Coder-480B-A35B (MoE) | 480B (35B act.) | ~270GB @Q4 / ~960GB bf16 | -- | -- | -- | -- | -- | -- | -- | Too large -- >192GB total. |
| DeepSeek-V3.1 (GGUF, MoE) | 671B (37B act.) | ~380GB @Q4 GGUF | -- | -- | -- | -- | -- | -- | -- | Too large -- >192GB total. |
| GLM-5.1 (GGUF, MoE) | 744B (40B act.) | ~220-236GB @2-bit | -- | -- | -- | -- | -- | -- | -- | Too large -- >192GB total. |
| GLM-4.6V (GGUF, vision) | 106B | GGUF ~60GB @Q4 | -- | -- | -- | -- | -- | -- | -- | Not benchmarked -- vision GGUF, not staged. |

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

## Source files

- `C:\Users\rdonker\dev\druppie-fork\benchmarks\results-incluster\qwen3.6-27b-nvfp4\report.txt` (committed report.txt)
- `C:\Users\rdonker\dev\druppie-fork\benchmarks\results-incluster\qwen3.6-35b-a3b-nvfp4\report.txt` (committed report.txt)
- `C:\Users\rdonker\dev\druppie-fork\benchmarks\results-incluster\qwen3-coder-next-nvfp4\report.txt` (committed report.txt)
- `C:\Users\rdonker\dev\druppie-fork\benchmarks\results-incluster\gpt-oss-120b\report.txt` (committed report.txt)

