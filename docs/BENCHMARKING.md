# LLM Performance Benchmarking

Tool voor het meten en vergelijken van LLM performance op onze Nutanix/Kubernetes infrastructuur.

## Overzicht

Standalone CLI tool die performance metrieken meet van LLM modellen via OpenAI-compatible APIs (Ollama, vLLM, TGI). Geen applicatie dependencies — alleen `httpx` en `pyyaml`.

## Scenario Categorieën

| Categorie | Wat het meet | Wanneer relevant |
|-----------|-------------|------------------|
| **latency** | Totale response tijd bij verschillende input lengtes | Interactieve agent loops, gebruikerservaring |
| **generation** | Token generatie snelheid (tokens/sec) | Lange output generatie (code, documenten) |
| **context_scaling** | Performance degradatie bij groter context (256 → 256K tokens) | Grote documenten, lange conversaties |
| **tool_overhead** | Extra latency door tool calling | Druppie agents die via MCP tools werken |
| **stress** | Consistentie bij herhaalde aanroepen | Productie stabiliteit |

## Hoe te Runnen

Zie [benchmarks/README.md](../benchmarks/README.md) voor CLI documentatie.

```bash
# Snelle test met 1 model
python -m benchmarks.runner --model gpt-oss:20b --category latency --runs 1

# Volledige benchmark suite
python -m benchmarks.runner --runs 3 --output results.json

# Alleen context scaling
python -m benchmarks.runner --category context_scaling
```

## Configuratie

Alle configuratie staat in `benchmarks/config.yaml`:
- **endpoints** — OpenAI-compatible API endpoints
- **models** — Te testen modellen met optimalisatie details
- **settings** — Runs per test, warmup, timeout

Zie [LLM-SELECTION.md](LLM-SELECTION.md) voor model keuze overwegingen en optimalisatie opties.

## Resultaten Interpreteren

### Latency
- Lagere waarde = beter
- Let op standaard deviatie (±) — hoge variatie duidt op instabiliteit
- Vergelijk modellen bij dezelfde input lengte

### Generation Speed (tokens/sec)
- Hogere waarde = beter
- Belangrijk voor taken met lange output (code generatie, documenten)
- Kijk of de snelheid stabiel blijft bij langere output

### Context Scaling
- Kijk naar de verhouding latency bij context-256 vs context-32k
- Lineaire scaling is ideaal, exponentiële scaling is problematisch
- Modellen met Flash Attention schalen doorgaans beter

### TTFT (Time to First Token)
- Belangrijk voor interactieve ervaring
- Lage TTFT = snellere start van het antwoord
- Onafhankelijk van totale generatie snelheid

### Tool Calling Overhead
- Vergelijk met vergelijkbare latency scenario zonder tools
- Meer tools = meer overhead (model moet langere system prompt verwerken)
- Relevant voor agent-based systemen waar modellen via tools werken
