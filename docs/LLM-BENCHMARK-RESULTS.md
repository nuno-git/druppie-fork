# LLM Benchmark Resultaten — Qwen3.6-27B (LL3)

> Status: **uitgevoerd op 2026-06-30** als **in-cluster Kubernetes Job** (geen tunnel) tegen het live model.
> Hoort bij user story **LL3** (`docs/LL-localllm-story.md`).
> Ruwe data van deze run: `benchmarks/results-incluster/results-qwen3.6-27b.json` + `.csv`, volledig console-rapport in `benchmarks/results-incluster/report-qwen3.6-27b.txt`.
> Job-definitie + draaiscript: `benchmarks/k8s/` (`job.yaml`, `run-in-cluster.sh`).
>
> ⚠️ **Update 2026-07-06 — serving is inmiddels gewijzigd.** Deze benchmark mat de toenmalige enkele `qwen`
> InferenceService: `Qwen/Qwen3.6-27B` (**bfloat16**), image `vllm/vllm-openai:v0.20.0`, 2 replicas,
> `--max-model-len 131072` (128K). De **nu draaiende** setup is anders: twee InferenceServices op de GPU-node,
> `qwen-27b` = `nvidia/Qwen3.6-27B-NVFP4` (**NVFP4**-variant, 256K context, image `vllm/vllm-openai:cu129-nightly`)
> + `qwen-35b` = `qwen3-6-35b-a3b`, elk 1 GPU. De NVFP4-27B is een **andere modelvariant** dan het hier
> gebenchmarkte bfloat16-model — verwar de twee niet. Deze cijfers gelden dus voor de oude bfloat16-serving.

## Run-context

| Veld | Waarde |
|---|---|
| Datum | 2026-06-30 |
| Cluster | `ka-k8s-ai` (rijnland RKE2) |
| **Meetmethode** | **In-cluster Kubernetes Job** `llm-benchmark` (ns `llm`), op een normale worker. Het verkeer naar `qwen.llm.svc.cluster.local:8000` blijft volledig binnen het cluster-netwerk — **geen port-forward, geen ingress, geen internet-round-trip**. |
| Model | `Qwen/Qwen3.6-27B` (reasoning-model, lange "thinking"-output) |
| Serving | LLMKube + vLLM, InferenceService `qwen` (ns `llm`) |
| Endpoint (test) | `http://qwen.llm.svc.cluster.local:8000/v1` (in-cluster DNS, ClusterIP) |
| Runner | `benchmarks/runner.py` als Job — `--runs 2 --warmup 1 --timeout 600` |
| Statistiek | **2 gemeten runs per scenario + 1 warmup** (warmup niet meegerekend). `repeated-50` levert 20 metingen. |
| Scope | alle 5 categorieën, 20 scenario's |

### Hardware-context

| Veld | Waarde |
|---|---|
| GPU's | **2× NVIDIA RTX PRO 6000 Blackwell** (96 GB elk), **geen P2P/NVLink** tussen de twee kaarten |
| Serving-topologie | **tensor-parallel = 1, 2 replicas** — één volledige modelkopie per GPU (geen cross-GPU sharding, want geen P2P) |
| Gewichten | `bfloat16` |
| KV-cache | `fp8` |
| Optimalisaties | prefix-caching aan, chunked-prefill aan |
| Context-venster | `--max-model-len 131072` (128K) |
| Tool calling | aan (`--enable-auto-tool-choice --tool-call-parser qwen3_xml`) |

> De keuze TP=1 + 2 replicas volgt rechtstreeks uit "geen P2P": tensor-parallel over twee kaarten zonder snelle interconnect zou de inter-GPU-communicatie tot bottleneck maken. Twee onafhankelijke replicas (één per GPU) leveren daarom hier de beste doorzet.

### Belangrijke caveats bij interpretatie

- **Echte in-cluster meting.** De suite liep als Job in dezelfde ns als de Service, zonder tunnel. De **absolute** latency is dus representatief voor wat de Druppie-backend in-cluster zou zien (eerdere port-forward-run had een kleine constante proxy-overhead). De cijfers in dit document vervangen die eerdere `runs=1`-meting.
- **`runs=2 + warmup=1`, gemiddeld.** Elk scenario is 2× gemeten (warmup vooraf, niet meegeteld) en de waarden hieronder zijn het **gemiddelde** van die 2 runs; waar zinvol staat de spreiding (±) erbij. Met 2 metingen is de spreiding indicatief, niet statistisch hard — behalve `repeated-50` (20 metingen).
- **Reasoning-model zonder output-cap = lange responses.** De `latency`-scenario's zetten géén `max_output_tokens`. Qwen3.6 genereert dan eerst een lang thinking-blok in `content`, dus die responses lopen door tot ~440–5300 completion-tokens. De **totale latency in de `latency`-categorie weerspiegelt dus generatielengte, niet input-grootte** — voor interactieve latency is **TTFT** daar de juiste metric.

> NB: de regel "Runs per test: 3" bovenaan `report-qwen3.6-27b.txt` is de configdefault uit `config.yaml`; de Job draaide met de CLI-override `--runs 2` (zie de regel "Running 20 scenarios x 1 models (2 runs each, 1 warmup)" en de 2 metingen per scenario in de CSV).

---

## Resultaten per categorie

> Alle waarden zijn het gemiddelde over 2 gemeten runs (n=2), tenzij anders vermeld. TTFT = time-to-first-token (uit de SSE-stream). Decode = `tokens/sec` (completion-tokens / totale latency). Prefill = `prompt_eval_rate` (prompt-tokens / TTFT).

### Latency (totale responstijd)

> Geen output-cap → totale latency wordt gedomineerd door de lengte van de reasoning-output, niet door de input. Lees TTFT als de echte "tijd-tot-reactie".

| Scenario | Input-tokens | TTFT | Completion-tokens | tokens/sec | Totale latency (±sd) |
|---|---|---|---|---|---|
| latency-50 | ~45 | **0,1 s** | ~438 | 26 | 16,8 s (±2,3) |
| latency-200 | ~184 | 0,1 s | ~2.965 | 26 | 113,5 s (±32,4) |
| latency-500 | ~389 | 0,1 s | ~4.322 | 26 | 166,5 s (±3,3) |
| latency-1000 | ~856 | 0,2 s | ~5.296 | 26 | 203,1 s (±12,4) |

**Waarneming:** TTFT is uitstekend en blijft onder ~0,2 s tot ~850 input-tokens. De grote verschillen in totale latency komen volledig door verschil in output-lengte (de reasoning-loop), niet door input.

### Generation Speed

> Hier wél een output-cap (`max_output_tokens`), dus tokens/sec is zuiver te lezen.

| Scenario | Output-cap | TTFT | Completion-tokens | tokens/sec | Totale latency |
|---|---|---|---|---|---|
| generate-100 | ~100 | 0,1 s | ~100 | 26 | 3,9 s |
| generate-500 | ~500 | 0,1 s | ~500 | 26 | 19,2 s |
| generate-1000 | ~1000 | 0,1 s | ~1.000 | 26 | 38,3 s |
| generate-2000 | ~2000 | 0,1 s | ~2.000 | 26 | 76,6 s |

**Waarneming:** doorvoer is opvallend **constant op ~26 tokens/sec** voor 1 stream, ongeacht de outputlengte. De latency schaalt lineair met het aantal gegenereerde tokens. De TTFT-uitschieters uit de eerdere single-run meting zijn nu verdwenen — de in-cluster meting met warmup geeft een veel schoner beeld.

### Context Scaling (latency bij toenemende context)

| Scenario | Input-tokens | TTFT (≈ prefill) | prompt-eval-rate (tok/s) | tokens/sec (decode) | Totale latency (±sd) |
|---|---|---|---|---|---|
| context-256 | ~239 | 0,1 s | ~2.000 | 26 | 32,6 s (±15,8) |
| context-1k | ~782 | 0,2 s | ~4.190 | 26 | 12,4 s (±0,3) |
| context-4k | ~2.965 | 0,3 s | ~11.121 | 26 | 45,9 s (±6,1) |
| context-8k | ~5.874 | 0,5 s | ~14.674 | 26 | 42,9 s (±21,7) |
| context-16k | ~11.695 | 1,2 s | ~30.468 | 24 | 31,0 s (±16,7) |
| context-32k | ~23.332 | 1,0 s | ~38.695 | 25 | 40,4 s (±22,9) |
| context-64k | ~46.606 | 2,2 s | ~57.350 | 24 | 40,5 s (±1,4) |
| context-128k | ~93.158 | 0,6 s | ~165.207 | 25 | 48,3 s (±4,8) |
| context-256k | 262.144 | — | — | — | **SKIPPED** |

**Waarneming:** prefill (TTFT) blijft **opmerkelijk laag over het hele bereik** — zelfs bij ~93k input-tokens (128k-scenario) zit de TTFT rond ~0,6 s, dankzij prefix-caching/chunked-prefill en de snelle Blackwell-prefill. De prompt-eval-rate loopt netjes op met de prompt-grootte (tot ~165k tok/s prefill-doorzet bij 128k). De totale latency in deze categorie wordt vooral bepaald door de (ongecapte) decode-output, vandaar de spreiding bij de kleinere context-scenario's. Decode-snelheid blijft constant ~24–26 tok/s tot het grootste werkbare scenario.

### Tool Calling Overhead

> Tool-scenario's draaien non-streaming (vLLM tool-parsing), dus geen TTFT.

| Scenario | Tools | Input-tokens | Completion-tokens | tokens/sec | Totale latency (±sd) |
|---|---|---|---|---|---|
| tool-call-3-tools | 3 | ~464 | ~100 | 26 | **3,9 s** (±0,1) |
| tool-call-10-tools | 10 | ~1.120 | ~170 | 25 | **6,7 s** (±0,1) |

**Waarneming:** tool calling werkt en is snel en stabiel (zeer lage spreiding). Het verschil 3→10 tools (+656 input-tokens, iets meer output) kost **~2,8 s extra** — grotendeels prefill + langere completion. Overhead is acceptabel voor agent-loops.

### Stress / Consistentie (`repeated-50`, 20 metingen)

| Metric | Waarde |
|---|---|
| Aantal calls | 20 (2 runs × 10 herhalingen) |
| Totale latency | gemiddeld **5,9 s (±1,0 s)** |
| TTFT | ~0,1 s (zeer stabiel) |
| tokens/sec | ~26 (zeer stabiel) |
| Completion-tokens | ~154 gemiddeld (variabel → verklaart de latency-spreiding) |
| Fouten | 0 |

**Waarneming:** zeer stabiel onder herhaling. De beperkte latency-spreiding (±1,0 s) komt door variërende output-lengte van de reasoning-loop, niet door instabiliteit van de serving — TTFT en tokens/sec zijn vrijwel constant. Geen fouten over 20 calls.

---

## Overgeslagen / mislukte scenario's

| Scenario | Reden |
|---|---|
| `context-256k` | Input van 262.144 tokens > `max_model_len` 131.072. De runner skipt dit automatisch (`Context 262144 exceeds model max 131072`). **Verwacht en correct** — het past niet binnen het 128K-venster van dit model. |

Alle overige 19 scenario's draaiden zonder fouten. Geen timeouts (per-request limiet 600 s niet geraakt; de langste was `latency-1000` op ~203 s).

---

## Aanbeveling

**Is Qwen3.6-27B op deze hardware bruikbaar voor Druppie agent-workloads? — Ja, met een kanttekening over de reasoning-output.**

**Sterke punten (data-onderbouwd, in-cluster gemeten):**

- **TTFT is uitstekend voor interactieve agents.** Tot ~850 input-tokens reageert het model in ~0,1–0,2 s, en zelfs bij ~93k tokens blijft de prefill rond ~0,6 s. Dat is ruim binnen wat een agent-loop nodig heeft om responsief aan te voelen — en het is bewezen zónder tunnel-overhead.
- **Tool calling werkt, is snel én consistent** (3,9–6,7 s, spreiding ±0,1 s). Cruciaal, want Druppie-agents handelen uitsluitend via MCP-tools. De overhead van meer tools is bescheiden (~2,8 s voor 3→10 tools).
- **Context scaling is gezond.** Prefill blijft over het hele 128K-bereik laag dankzij prefix-caching/chunked-prefill op de Blackwell-kaarten; de prompt-eval-rate schaalt voorspelbaar mee. Voor typische agent-context (tot tienduizenden tokens) is dit prima.
- **Stabiel en consistent.** Over 20 opeenvolgende calls geen fouten en constante TTFT/throughput; ook de generation-categorie is met warmup veel schoner dan de eerdere single-run meting.

**Aandachtspunten:**

- **Decode-snelheid is ~24–26 tokens/sec per stream.** Dat is bescheiden en de hoofdbottleneck. Voor een reasoning-model dat eerst een lang thinking-blok produceert, betekent dit dat "simpele" prompts zonder output-cap alsnog 0,5–3,5 min kunnen duren (zie `latency`-categorie: ~440–5.300 tokens gegenereerd). **Advies: cap de output bewust** (`max_tokens`) per agent-stap en/of stuur het thinking-budget aan — anders domineert de reasoning-loop de end-to-end latency.
- **Single-stream throughput, 2 replicas (TP=1, geen P2P).** Elke replica bedient één GPU; onder gelijktijdige agent-load deelt het verkeer de 2 replicas. Deze run mat geen parallelle belasting. Voor productie is een **concurrency-/load-test** nodig, plus de nog ontbrekende **GPU-autoscaling** (KEDA/HPA op DCGM-metric — zie LL2). Omdat er geen P2P is, blijft de architectuur 2× TP=1; opschalen betekent méér GPU's/replicas, niet grotere tensor-parallel.

**Conclusie:** Qwen3.6-27B op LLMKube/vLLM (ka-k8s-ai, 2× RTX PRO 6000 Blackwell, TP=1 + 2 replicas) is een **valide kandidaat** voor Druppie's agent-workloads — snelle TTFT, werkende en consistente tool-calling, gezonde context-scaling en stabiel gedrag, nu in-cluster bevestigd. De aanbeveling is om het model te gebruiken **met een expliciete output-cap per agent-stap** en om vóór de definitieve keuze (1) een concurrency-/load-test te doen en (2) de **agent-kwaliteit** te valideren via de BA-evaluation suite tegen de `zai`-baseline. Pas daarna de cijfers vastleggen in de LLM-serving ADR.

---

## Reproduceren

```bash
# Draai de volledige suite als in-cluster Kubernetes Job (ns llm).
# Idempotent: ruimt vorige Job + configmaps op, maakt ze opnieuw, en tailt de logs.
./benchmarks/k8s/run-in-cluster.sh

# Resultaten ophalen uit de Job-logs (tussen de RESULTS_JSON-markers):
kubectl logs job/llm-benchmark -n llm
```

De Job (`benchmarks/k8s/job.yaml`) monteert de runner + scenario's via twee ConfigMaps
(`bench-pkg`, `bench-scenarios`), assembleert ze in een init-container tot een schrijfbare
package-dir, en draait `python -m benchmarks.runner --runs 2 --warmup 1 --timeout 600`.
Het model-endpoint staat in `benchmarks/config.yaml` op `qwen_incluster`
(`http://qwen.llm.svc.cluster.local:8000/v1`).

---

## GPU-node (colocated) run — 2026-06-30

> Status: **uitgevoerd op 2026-06-30** als in-cluster Kubernetes Job, maar deze keer **vastgepind op de GPU-node** `ka-k8s-ai-workers-gpu-xd4xn-fk5v2`, dezelfde node waar de vLLM `qwen`-pods draaien. Doel: nagaan of **colocatie** van de benchmark-client met het model meetbaar iets verandert t.o.v. de oorspronkelijke run op een normale worker.
> Ruwe data: `benchmarks/results-incluster/results-qwen3.6-27b-gpunode.json` + `.csv`, volledig console-rapport in `benchmarks/results-incluster/report-qwen3.6-27b-gpunode.txt`.
> Job-definitie: `benchmarks/k8s/job-gpunode.yaml` (Job `llm-benchmark-gpunode`, configmaps `bench-pkg-gpunode` / `bench-scenarios-gpunode`).

### Run-context (verschillen t.o.v. de baseline)

| Veld | Baseline | GPU-node-run |
|---|---|---|
| Job | `llm-benchmark` | `llm-benchmark-gpunode` |
| Node van de **client** | normale worker (`ka-k8s-ai-workers-skbh7-d4qwl`) | **GPU-node** `ka-k8s-ai-workers-gpu-xd4xn-fk5v2` (zelfde node als de `qwen`-pods) |
| Pinning | geen | `nodeSelector` op hostname + `toleration` voor taint `gpu=true:NoSchedule` |
| GPU-request | geen | **geen** (client vraagt geen GPU; alleen CPU 500m–2 / 1–2Gi) |
| Runner-config | `--runs 2 --warmup 1 --timeout 600` | **identiek** (`--runs 2 --warmup 1 --timeout 600`) |
| Model / endpoint | `qwen_incluster` | **identiek** |

De benchmark-pod (`llm-benchmark-gpunode-...`) is bevestigd **op de GPU-node geschedulet** (`kubectl get pod -n llm -o wide` → node `ka-k8s-ai-workers-gpu-xd4xn-fk5v2`). De `qwen` vLLM-pods bleven gedurende de hele run gezond (`1/1 Running`, 0 restarts).

### Vergelijking: colocatie vs. normale worker

> Beide runs zijn al **in-cluster** (geen tunnel/ingress), dus het netwerk-pad client→Service was in beide gevallen kort. De vraag is of colocatie op dezelfde node nog een extra meetbaar effect heeft. Cijfers zijn gemiddelden over 2 gemeten runs (n=2), behalve `repeated-50` (20 metingen). `±sd` voor n=2 is indicatief.

**TTFT (time-to-first-token) — geaggregeerd over alle streaming-scenario's**

| Metric | Baseline (normale worker) | GPU-node (colocated) |
|---|---|---|
| Mediaan TTFT | **101 ms** | **100 ms** |
| Gemiddelde TTFT | 306 ms | **160 ms** |

De **mediaan** is praktisch identiek (~100 ms) — voor het typische geval maakt colocatie geen verschil; het netwerk was al geen bottleneck. Het **gemiddelde** daalt wel fors (306→160 ms), maar dat komt door enkele "koude" TTFT-uitschieters in de baseline bij grote contexten, niet door een systematisch netwerk-effect:

| Scenario | TTFT baseline | TTFT GPU-node |
|---|---|---|
| context-16k | 1.237 ms | **201 ms** |
| context-32k | 1.022 ms | **377 ms** |
| context-64k | 2.218 ms | **469 ms** |
| context-8k | 545 ms | 276 ms |
| context-128k | 565 ms | 549 ms |
| context-1k | 187 ms | 186 ms |
| context-256 | 120 ms | 99 ms |

De grootste TTFT-verschillen zitten in de grote-context-scenario's. Dat zijn precies de runs waar prefill-cache/scheduling-variatie domineert (prefix-caching, chunked-prefill, gelijktijdige load op de twee replicas), niet de netwerk-RTT. Met n=2 zijn deze TTFT-pieken meet-ruis, geen reproduceerbaar colocatie-voordeel. De kleine, cache-vriendelijke contexten (context-256/1k/128k) zijn in beide runs vrijwel gelijk.

**Decode-doorvoer (tokens/sec)**

| Metric | Baseline | GPU-node |
|---|---|---|
| Mediaan tokens/sec | **25,91** | **25,93** |
| Gemiddelde tokens/sec | 25,70 | 25,81 |

**Vrijwel identiek (~26 t/s).** Decode is GPU-bound en niet gevoelig voor waar de client draait — zoals verwacht. Colocatie verandert hier niets.

**Per-categorie totale latency (gemiddelde over 2 runs, seconden)**

| Scenario | Baseline | GPU-node | Opmerking |
|---|---|---|---|
| generate-100 / 500 / 1000 / 2000 | 3,9 / 19,2 / 38,3 / 76,6 | 3,9 / 19,2 / 38,3 / 76,6 | **Identiek** — gecapte output → zuivere meting |
| latency-50 | 16,8 | 28,0 | output-lengte-ruis (geen cap) |
| latency-200 | 113,5 | 96,0 | output-lengte-ruis (geen cap) |
| latency-500 | 166,5 | 180,1 | output-lengte-ruis (geen cap) |
| latency-1000 | 203,1 | 207,8 | output-lengte-ruis (geen cap) |
| context-* | 12–48 | 20–51 | gedomineerd door ongecapte decode-lengte |

De `generate-*`-scenario's (de enige met een output-cap) zijn **tot op de seconde identiek** tussen beide runs. De verschillen in `latency-*` en `context-*` komen volledig door de variërende lengte van de ongecapte reasoning-output (zie caveats bovenaan), niet door client-plaatsing.

**Tool-calling overhead**

| Scenario | Baseline | GPU-node |
|---|---|---|
| tool-call-3-tools | 3,89 s | 3,92 s |
| tool-call-10-tools | 6,68 s | **4,34 s** |

3-tools is identiek. De 10-tools-meting is in de GPU-node-run lager (4,3 s vs. 6,7 s), maar beide scenario's draaien non-streaming en hebben n=2 met variabele completion-lengte — dit valt binnen de meet-ruis, niet toe te schrijven aan colocatie.

**Stress / consistentie (`repeated-50`, 20 metingen)**

| Metric | Baseline | GPU-node |
|---|---|---|
| Gemiddelde latency | 5,93 s (±0,98) | 6,95 s (±2,95) |
| Gemiddelde TTFT | 93 ms | 92 ms |
| Fouten | 0 | 0 |

TTFT is identiek en stabiel; de iets hogere gemiddelde latency + spreiding in de GPU-node-run komt door langere/variabelere reasoning-output in die 20 calls (geen output-cap), niet door instabiliteit — beide runs: 0 fouten.

### Overgeslagen scenario's

| Scenario | Reden |
|---|---|
| `context-256k` | Input van 262.144 tokens > `max_model_len` 131.072 → automatisch geskipt (`Context 262144 exceeds model max 131072`). **Verwacht en correct**, identiek aan de baseline. |

Alle overige 19 scenario's draaiden zonder fouten; geen timeouts (langste: `latency-1000` op ~208 s, ruim onder de 600 s-limiet).

### Conclusie: hielp colocatie?

**Nee — colocatie op de GPU-node levert geen meetbaar latency-voordeel op.** De relevante metrics die níet door ongecapte output-lengte vertroebeld worden, zijn tussen de twee runs vrijwel identiek:

- **Mediaan TTFT** ~100 ms in beide runs.
- **Decode-doorvoer** ~26 t/s in beide runs.
- **`generate-*`** (de enige gecapte, dus zuivere latency-meting) **exact gelijk**.

Dat is precies wat te verwachten is: beide runs liepen al in-cluster, dus het netwerk-pad client→Service was in beide gevallen verwaarloosbaar t.o.v. de prefill- en decode-tijd op de GPU. De client wacht hoofdzakelijk op het model; waar die wachtende client draait, maakt niet uit. De zichtbare verschillen (gemiddelde-TTFT-daling, latency-schommelingen, de 10-tools-meting) zijn meet-ruis door n=2 en ongecapte reasoning-output, geen systematisch colocatie-effect.

**Praktische gevolgtrekking:** de benchmark-client (en bij uitbreiding de Druppie-backend) hoeft **niet** op de GPU-node te draaien voor latency-redenen; een normale worker volstaat. De GPU-node-capaciteit blijft zo beschikbaar voor de modellen zelf. Voor een hardere uitspraak is, net als bij de baseline, een concurrency-/load-test met meer runs nodig.

### Reproduceren (GPU-node-variant)

```bash
# Configmaps uit de huidige benchmarks/-bron + de gepinde Job aanmaken:
kubectl create configmap bench-pkg-gpunode -n llm \
  --from-file=__init__.py=benchmarks/__init__.py \
  --from-file=runner.py=benchmarks/runner.py \
  --from-file=llm_client.py=benchmarks/llm_client.py \
  --from-file=reporter.py=benchmarks/reporter.py \
  --from-file=config.yaml=benchmarks/config.yaml
kubectl create configmap bench-scenarios-gpunode -n llm --from-file=benchmarks/scenarios/
kubectl apply -f benchmarks/k8s/job-gpunode.yaml

# Bevestig dat de pod op de GPU-node landt:
kubectl get pod -n llm -l app=llm-benchmark-gpunode -o wide

# Resultaten uit de Job-logs (tussen de RESULTS_JSON-markers):
kubectl logs job/llm-benchmark-gpunode -n llm
```
