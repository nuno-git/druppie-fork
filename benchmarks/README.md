# LLM Performance Benchmarks

Standalone performance benchmark runner voor het vergelijken van LLM modellen op Nutanix/Kubernetes infrastructuur. Geen applicatie dependencies — alleen `httpx` en `pyyaml`.

## Quick Start

```bash
# Vanuit de project root:
python -m benchmarks.runner --fetch-models ollama         # toon beschikbare modellen op endpoint
python -m benchmarks.runner --list                        # toon geconfigureerde modellen en scenarios
python -m benchmarks.runner --model gpt-oss:20b           # run alle scenarios tegen 1 model
python -m benchmarks.runner                               # run alles
python -m benchmarks.runner --output results.json         # exporteer resultaten
```

## CLI Opties

| Optie | Beschrijving |
|-------|-------------|
| `--model MODEL` | Run alleen dit model (model ID, bijv. `gpt-oss:20b`) |
| `--category CAT` | Run alleen deze categorie (`latency`, `generation`, `context_scaling`, `tool_overhead`, `stress`) |
| `--scenario NAME` | Run alleen dit scenario (op naam) |
| `--runs N` | Aantal gemeten runs per scenario (overschrijft config) |
| `--warmup N` | Aantal warmup runs (overschrijft config) |
| `--timeout SEC` | Timeout per LLM call in seconden |
| `--output FILE` | Exporteer naar JSON (`.json`) of CSV (`.csv`) |
| `--no-stream` | Schakel streaming uit (geen TTFT meting) |
| `--list` | Toon geconfigureerde scenarios en modellen |
| `--fetch-models EP` | Haal beschikbare modellen op van een endpoint (Ollama/vLLM/OpenAI-compatible) |

## Scenario Categorieën

### Latency
Meet de totale response tijd bij verschillende input lengtes.
- `latency-50` — 50 tokens input
- `latency-200` — 200 tokens input
- `latency-500` — 500 tokens input
- `latency-1000` — 1000 tokens input

### Generation Speed
Meet hoeveel tokens per seconde het model genereert.
- `generate-100` — forceer ~100 tokens output
- `generate-500` — forceer ~500 tokens output
- `generate-1000` — forceer ~1000 tokens output
- `generate-2000` — forceer ~2000 tokens output

### Context Scaling
Meet hoe de performance schaalt met toenemende context lengte. Genereert automatisch filler text van de juiste lengte. Scenarios die groter zijn dan het model's `max_context` worden overgeslagen.
- `context-256` t/m `context-256k` (256 → 262144 tokens)

### Tool Calling Overhead
Meet de extra latency van tool calling vergeleken met reguliere prompts.
- `tool-call-3-tools` — 3 tools meegegeven
- `tool-call-10-tools` — 10 tools meegegeven

### Stress
Meet consistentie en stabiliteit bij herhaalde aanroepen.
- `repeated-50` — zelfde korte prompt 10x achter elkaar

## Gemeten Metrieken

| Metriek | Beschrijving |
|---------|-------------|
| `total_latency_ms` | Tijd van request tot volledige response |
| `time_to_first_token_ms` | Tijd tot eerste token (alleen bij streaming) |
| `prompt_tokens` | Aantal input tokens (van API response) |
| `completion_tokens` | Aantal output tokens |
| `tokens_per_second` | Generatiesnelheid (completion_tokens / latency) |
| `prompt_eval_rate` | Prompt processing snelheid (prompt_tokens / latency) |

## Modellen Ontdekken

Gebruik `--fetch-models` om te zien welke modellen beschikbaar zijn op een endpoint:

```bash
python -m benchmarks.runner --fetch-models ollama
```

Output:
```
Fetching models from ollama (https://ollama.waterschap.org/v1)...

Found 5 models:

  gpt-oss:120b  (120B, Q4_K_M, gpt-oss)
  gpt-oss:20b  (20B, Q4_K_M, gpt-oss)
  qwen3-coder:30b  (30B, Q4_K_M, qwen3)
  ...
```

Dit werkt met elk OpenAI-compatible endpoint (Ollama, vLLM, TGI). De endpoint naam moet geconfigureerd zijn in `config.yaml`.

## Configuratie

Bewerk `config.yaml` om endpoints en modellen te configureren.

### Endpoint toevoegen
```yaml
endpoints:
  mijn_endpoint:
    base_url: "https://mijn-server.internal/v1"
    api_key: "${MIJN_API_KEY}"      # env var referentie
    ssl_verify: true
```

### Model toevoegen
```yaml
models:
  - endpoint: mijn_endpoint
    model: llama3.3:70b
    display_name: "Llama 3.3 70B"
    max_context: 131072
    parameters: "70B"
    quantization: "GPTQ"
    kv_cache_quant: "FP8"
    flash_attention: true
    gpu_layers: -1
    notes: "4-bit GPTQ quantization, FP8 KV cache"
```

De optimalisatie-velden (`quantization`, `kv_cache_quant`, `flash_attention`, `gpu_layers`) worden opgeslagen in de resultaten zodat benchmarks reproduceerbaar zijn.

## Nieuw Scenario Toevoegen

Maak een YAML bestand in `scenarios/`:

```yaml
scenario:
  name: mijn-scenario
  description: "Beschrijving van wat dit test"
  category: latency                 # latency | generation | context_scaling | tool_overhead | stress

  system_prompt: "Je bent een assistent."
  user_prompt: "De vraag aan het model"

  # Optioneel:
  max_output_tokens: 500            # forceer output lengte
  context_tokens: 4096              # genereer filler context (voor context_scaling)
  repeat: 10                        # herhaal prompt N keer per run (voor stress)
  tools: [...]                      # OpenAI-format tool definities (voor tool_overhead)
```

## Output Formaten

### JSON
Bevat alle ruwe meetdata per run inclusief model configuratie. Geschikt voor verdere analyse.

### CSV
Flat tabel met 1 rij per run. Geschikt voor spreadsheet import en pivot tabellen.
