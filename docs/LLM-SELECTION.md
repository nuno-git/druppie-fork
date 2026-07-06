# LLM Selectie en Configuratie

## Waarom Open Source Modellen

- **Data sovereignty** — Data blijft binnen eigen infrastructuur, geen externe API calls
- **Kosten** — Geen per-token kosten na initiële infrastructuur investering
- **Controle** — Volledige controle over model versies, updates, en configuratie
- **Compliance** — Voldoet aan overheids-eisen rondom data verwerking (BIO, AVG)
- **Beschikbaarheid** — Geen afhankelijkheid van externe diensten

## Selectiecriteria

Bij het kiezen van modellen voor het Druppie platform wegen we de volgende criteria:

| Criterium | Belang | Toelichting |
|-----------|--------|-------------|
| Tool calling support | Kritiek | Druppie agents werken uitsluitend via MCP tools |
| Nederlandse taal | Hoog | Functionele ontwerpen en communicatie zijn in het Nederlands |
| Context window | Hoog | Grote documenten en lange conversaties vereisen groot context window |
| Code generatie | Hoog | Builder agents genereren code in sandboxes |
| Reasoning | Hoog | Architect en BA agents moeten complexe afwegingen maken |
| Licentie | Medium | Moet commercieel gebruik toestaan |
| VRAM footprint | Medium | Moet passen op beschikbare GPU hardware |
| Snelheid | Medium | Interactieve agent loops vereisen redelijke response tijden |

## Candidate Modellen

### Momenteel geserveerd (LLMKube + vLLM op `ka-k8s-ai`)

> **Update 2026-07-06:** de eerdere "Ollama"-opzet is achterhaald. Het live serving-platform is
> **LLMKube (operator) + vLLM** op cluster `ka-k8s-ai`. Er draaien nu **twee** InferenceServices, elk op 1 GPU:
> `qwen-27b` = `nvidia/Qwen3.6-27B-NVFP4` (**NVFP4**-quantized, 256K context, image `vllm/vllm-openai:cu129-nightly`,
> endpoint `http://qwen-27b.llm.svc.cluster.local:8000/v1`) en `qwen-35b` = `qwen3-6-35b-a3b`
> (endpoint `http://qwen-35b.llm.svc.cluster.local:8000/v1`). Daarnaast zijn **10 `Model` CRs Ready**
> geregistreerd in ns `llm` (deepseek-v3-1, gemma-4-e4b, glm-4-6v, glm-5-1, gpt-oss-120b, qwen3-6-27b,
> qwen3-6-27b-mtp, qwen3-6-35b-a3b, qwen3-coder-480b-a35b, qwen3-coder-next-80b). Zie
> [`docs/LL-localllm-story.md`](LL-localllm-story.md) + [`docs/LOCAL-LLM-MODEL-EXPANSION-PLAN.md`](LOCAL-LLM-MODEL-EXPANSION-PLAN.md).
> NB: de eerder gebenchmarkte `Qwen/Qwen3.6-27B` (bfloat16) is een **andere variant** dan de nu geserveerde NVFP4-27B.

De onderstaande tabel is de historische kandidatenlijst (Ollama-tijdperk), bewaard als referentie:

| Model | Parameters | Context | Licentie | Sterke punten | Beperkingen |
|-------|-----------|---------|----------|---------------|-------------|
| GPT-OSS 120B | 120B | 32K | Open | Allround, goede tool calling | Groot, langzamer, beperkt context |
| GPT-OSS 20B | 20B | 32K | Open | Snel, efficiënt | Minder nauwkeurig dan grotere modellen |
| Qwen3 Coder 30B | 30B | 128K | Apache 2.0 | Code generatie, groot context window | Minder sterk in Nederlands |
| DeepSeek R1 32B | 32B | 128K | MIT | Chain-of-thought reasoning | Langzamer door thinking tokens |
| Gemma3 27B | 27B | 128K | Gemma | Multimodaal, efficiënt | Beperkte tool calling |

### Potentieel toe te voegen

| Model | Parameters | Context | Licentie | Overweging |
|-------|-----------|---------|----------|------------|
| Llama 3.3 70B | 70B | 128K | Llama 3.3 | Sterke allrounder, goede tool calling |
| Mistral Large 123B | 123B | 128K | Apache 2.0 | Sterk in Europese talen incl. Nederlands |
| Phi-4 14B | 14B | 16K | MIT | Zeer efficiënt, goed voor snelle taken |
| Command R 35B | 35B | 128K | CC-BY-NC | Geoptimaliseerd voor RAG en tool use |
| Qwen3 72B | 72B | 128K | Apache 2.0 | Grotere versie van Qwen3, sterker reasoning |

## Infrastructuur

### Huidige Setup
> **Update 2026-07-06:** de live setup is **LLMKube + vLLM** op cluster `ka-k8s-ai` (rijnland RKE2), niet Ollama.
- **LLMKube** (operator) + **vLLM** als engine op de GPU-node `ka-k8s-ai-workers-gpu-xd4xn-fk5v2` (2× RTX PRO 6000 Blackwell)
- Twee InferenceServices, elk 1 GPU: `qwen-27b` (`nvidia/Qwen3.6-27B-NVFP4`, NVFP4, 256K, image `vllm/vllm-openai:cu129-nightly`) en `qwen-35b` (`qwen3-6-35b-a3b`)
- In-cluster OpenAI-compatible endpoints: `http://qwen-27b.llm.svc.cluster.local:8000/v1` en `http://qwen-35b.llm.svc.cluster.local:8000/v1`
- ⚠️ Nog geen persistente weight-cache (`hf-cache` PVC / prefetch Job niet actief) — cold starts halen gewichten opnieuw op
- _(Historisch: Ollama op `ollama.waterschap.org`, GGUF-quantized, OpenAI-compatible API — niet meer in gebruik.)_

### Toekomstige Setup (Nutanix/Kubernetes)
- **Nutanix** cluster met GPU nodes
- Serving opties:
  - **Ollama** — Simpel, breed model support, GGUF format
  - **vLLM** — Hoge throughput, PagedAttention, continuous batching
  - **TGI** (Text Generation Inference) — HuggingFace ecosystem, goede monitoring
- Alle opties bieden OpenAI-compatible API endpoints

## Inference Optimalisaties

De volgende optimalisaties kunnen de performance significant beïnvloeden. Documenteer altijd welke optimalisaties actief zijn bij benchmark resultaten.

### Quantization
Reduceert model grootte en VRAM gebruik ten koste van nauwkeurigheid.

| Methode | Bits | VRAM Reductie | Kwaliteitsverlies | Beschikbaarheid |
|---------|------|---------------|-------------------|-----------------|
| FP16 | 16-bit | Baseline | Geen | Alle frameworks |
| NVFP4 | 4-bit | ~75% | Minimaal | NVIDIA TensorRT-LLM |
| GPTQ | 4-bit | ~75% | Minimaal | vLLM, TGI |
| AWQ | 4-bit | ~75% | Minimaal | vLLM, TGI |
| Q4_K_M | 4-bit | ~75% | Laag | Ollama (llama.cpp) |
| Q5_K_M | 5-bit | ~69% | Zeer laag | Ollama (llama.cpp) |
| Q8_0 | 8-bit | ~50% | Verwaarloosbaar | Ollama (llama.cpp) |

### KV Cache Quantization
Reduceert geheugengebruik van de KV cache tijdens inference.

| Methode | Impact | Beschikbaarheid |
|---------|--------|-----------------|
| FP8 | Halveert KV cache geheugen, minimaal kwaliteitsverlies | vLLM |
| Q4 | 75% reductie, merkbaar kwaliteitsverlies bij lange context | Experimenteel |
| Q8 | 50% reductie, verwaarloosbaar kwaliteitsverlies | vLLM |

### Overige Optimalisaties

| Optimalisatie | Effect | Beschikbaarheid |
|---------------|--------|-----------------|
| Flash Attention | Snellere attention berekening, minder geheugen | Ollama, vLLM, TGI |
| Continuous Batching | Hogere throughput bij meerdere gelijktijdige requests | vLLM, TGI |
| Speculative Decoding | Snellere generatie met draft model | vLLM |
| Tensor Parallelism | Verdeel model over meerdere GPU's | vLLM, TGI |
| PagedAttention | Efficiënter geheugengebruik voor KV cache | vLLM |

**Let op:** Welke optimalisaties beschikbaar zijn hangt af van het Nutanix platform, de GPU hardware, en het gekozen serving framework.

## Wanneer Opnieuw Evalueren

- Bij release van nieuwe model versies
- Na infrastructuur upgrades (nieuwe GPU's, meer VRAM)
- Bij wijziging van quantization methode
- Bij overstap naar ander serving framework
- Als benchmark resultaten significant verslechteren na een update
