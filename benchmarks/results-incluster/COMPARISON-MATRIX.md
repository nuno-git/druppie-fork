# Model Comparison Matrix

Generated from 2 result file(s), 2 model(s).

## Headline metrics

| Model | Params | Quant | Median TTFT (ms) | Median decode (tok/s) | latency-500 (s) | context-64k TTFT (ms) | tool 10-3 delta (s) | stress stddev (ms) | Errors |
|---|---|---|---|---|---|---|---|---|---|
| Qwen3.6-27B (vLLM/LLMKube, ka-k8s-ai) | 27B | bfloat16 | 154 | 26.1 | 166.5 | 2,218 | 2.79 | 981 | 1 |
| Qwen3.6-35B-A3B (vLLM/LLMKube) | 35B-A3B | bfloat16 | 107 | 148.4 | 34.1 | 223 | 0.54 | 446 | 1 |

**Column notes**

- **Median TTFT (ms)** -- median time-to-first-token over all streaming runs (latency + generation + context_scaling). Lower is better.
- **Median decode (tok/s)** -- median steady-state generation throughput over generation scenarios. Higher is better.
- **latency-500 (s)** -- median total latency of the `latency-500` scenario (representative single-call latency).
- **context-64k TTFT (ms)** -- prefill cost at ~64k prompt tokens (`context-64k`); measures context scaling.
- **tool 10-3 delta (s)** -- `tool-call-10-tools` minus `tool-call-3-tools` median latency; cost of extra tool schemas.
- **stress stddev (ms)** -- latency stddev over `repeated-50`; consistency under repeated calls (lower = steadier).
- **Errors** -- count of errored runs across all scenarios (e.g. context exceeding the model's max).

## Per-category throughput

| Category (median tok/s) | Qwen3.6-27B (vLLM/LLMKube, ka-k8s-ai) | Qwen3.6-35B-A3B (vLLM/LLMKube) |
|---|---|---|
| latency | 26.1 | 149.6 |
| generation | 26.1 | 148.4 |
| context_scaling | 25.7 | 142.2 |
| tool_overhead | 25.5 | 133.6 |
| stress | 25.9 | 144.3 |

## Source files

- `C:\Users\rdonker\dev\druppie-fork\benchmarks\results-incluster\results-qwen3.6-27b.json`
- `C:\Users\rdonker\dev\druppie-fork\benchmarks\results-incluster\results-qwen3.6-35b-a3b.json`

