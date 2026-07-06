# Model Comparison Matrix

10 registered model(s) tracked; 1 benchmarked from 1 result file(s). Models that are not (yet) benchmarked still appear, with a `Status / Note` explaining why (fits/pending, needs a maintenance window, or too large for this hardware).

## Headline metrics

| Model | Params | Quant / size | Median TTFT (ms) | Median decode (tok/s) | latency-500 (s) | context-64k TTFT (ms) | tool 10-3 delta (s) | stress stddev (ms) | Errors | Status / Note |
|---|---|---|---|---|---|---|---|---|---|---|
| Gemma 4 E4B (gemma-4-E4B-it) | ~4B (E4B eff.) | GGUF ~4-8GB | -- | -- | -- | -- | -- | -- | -- | Pending -- fits 1 GPU easily (~4-8GB GGUF), not yet run. |
| Qwen3.6-27B | 27B | bfloat16 | 2,424 | 21.2 | 155.0 | 4,571 | 3.11 | 1,538 | 1 | Benchmarked in place -- prod, no serving change (see qwen3.6-27b/report.txt). |
| Qwen3.6-27B-MTP (GGUF) | 27B (+MTP head) | GGUF ~16-30GB | -- | -- | -- | -- | -- | -- | -- | Pending -- fits 1 GPU (~16-30GB GGUF quant), not yet run. |
| Qwen3.6-35B-A3B (MoE) | 35B (3B act.) | bf16 ~70GB | -- | -- | -- | -- | -- | -- | -- | Pending -- fits 1 GPU (~70GB bf16, tight). Prior run failed on HF download timeout, NOT VRAM. |
| Qwen3-Coder-Next-80B | 80B | bf16 ~160GB | -- | -- | -- | -- | -- | -- | -- | Needs 2 GPUs (TP=2, ~160GB bf16) -- testable only in a full maintenance window (or with quantization). |
| gpt-oss-120b | 120B (MoE) | MXFP4 ~63GB (native) | -- | -- | -- | -- | -- | -- | -- | Pending -- fits 1 GPU (~63GB, ships native MXFP4), not yet run. |
| Qwen3-Coder-480B-A35B (MoE) | 480B (35B act.) | ~270GB @Q4 / ~960GB bf16 | -- | -- | -- | -- | -- | -- | -- | Not benchmarked -- exceeds VRAM (~270GB @Q4 / ~960GB bf16 > 192GB total; needs multi-node). |
| DeepSeek-V3.1 (GGUF, MoE) | 671B (37B act.) | ~380GB @Q4 GGUF | -- | -- | -- | -- | -- | -- | -- | Not benchmarked -- exceeds VRAM (671B MoE, ~380GB @Q4 GGUF > 192GB total; needs multi-node). |
| GLM-5.1 (GGUF, MoE) | 744B (40B act.) | ~220-236GB @2-bit | -- | -- | -- | -- | -- | -- | -- | Not benchmarked -- exceeds VRAM (744B MoE, ~220-236GB even @2-bit dynamic GGUF > 192GB total; needs RAM/MoE offload or multi-node). |
| GLM-4.6V (GGUF, vision) | 106B | GGUF ~60GB @Q4 | -- | -- | -- | -- | -- | -- | -- | Pending (uncertain) -- ~60GB @Q4 GGUF fits 1 GPU, but vision/multimodal serving on vLLM needs verification; bf16 (~212GB) would not fit. |

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

## Per-category throughput

_Benchmarked models only._

| Category (median tok/s) | Qwen3.6-27B (vLLM/LLMKube, ka-k8s-ai) |
|---|---|
| latency | 25.9 |
| generation | 21.2 |
| context_scaling | 24.3 |
| tool_overhead | 23.2 |
| stress | 23.6 |

## Source files

- `C:\Users\rdonker\dev\druppie-fork\benchmarks\results-qwen3.6-27b.json`

