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
# Snelle test met 1 model (gebruik een model uit config.yaml)
python -m benchmarks.runner --model Qwen/Qwen3.6-27B --category latency --runs 1

# Volledige benchmark suite
python -m benchmarks.runner --runs 3 --output results.json

# Alleen context scaling
python -m benchmarks.runner --category context_scaling
```

## In-cluster automated sweep

Naast de CLI-runner (die één endpoint meet) is er een **geautomatiseerde sweep**
die *alle* kandidaat-modellen in het cluster in één run benchmarkt, de
vergelijkingsmatrices herbouwt en de resultaten als PR naar aigit publiceert:
`benchmarks/k8s/benchmark-all-models.sh`.

De volledige runbook — prerequisites, `--yes` / `--only` flags, de tunable
env-knoppen, de **GPU-vrijmaak-impact op prod** (één served model 1→0, parent +
child Flux suspend, restore-trap), de aigit auto-publish setup, en
`candidates.yaml` als control surface — staat in
[benchmarks/README.md → In-cluster automated sweep](../benchmarks/README.md#in-cluster-automated-sweep).

> ⚠️ **Test-cluster impact.** De sweep zet tijdelijk één geserveerd model offline
> en suspendt Flux. Lees de impact-sectie in de README vóór het draaien.

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
