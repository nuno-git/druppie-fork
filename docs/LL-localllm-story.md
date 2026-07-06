# User Story: Lokale LLMs op Kubernetes

> Status: ingevuld op basis van de **live cluster-staat** (`ka-k8s-ai`, rijnland RKE2) op 2026-06-30.
> Serving-stack = **LLMKube** (operator), met **vLLM** als backend-engine.
> Legenda: `[x]` = draait/aanwezig in cluster of repo · `[ ]` = nog te doen · ⚠️ = gap/risico.

## Geverifieerde cluster-staat (`ka-k8s-ai`)

| Onderdeel | Status | Bron (cluster) |
|---|---|---|
| GPU-node | `[x]` `ka-k8s-ai-workers-gpu-xd4xn`, 2× NVIDIA GPU (compute 12.0, Blackwell-class), taint `gpu=true:NoSchedule` | `kubectl get nodes` |
| NVIDIA GPU Operator | `[x]` namespace `gpu-operator`: driver, device-plugin, **DCGM + dcgm-exporter**, GPU-feature-discovery, container-toolkit | node labels `nvidia.com/gpu.deploy.*` |
| Serving-operator | `[x]` **LLMKube** in `llmkube-system` (controller-manager + webhook); CRDs `models`/`inferenceservices`/`modelrouters` in `inference.llmkube.dev` | `kubectl get crd` |
| Backend-engine | `[x]` **vLLM** `vllm/vllm-openai:v0.20.0` | InferenceService `qwen` spec |
| Draaiend model | `[x]` InferenceService `qwen` = `Ready`, **2 replicas** op GPU-node, model `Qwen/Qwen3.6-27B` | `kubectl get inferenceservices -A` |
| Tweede model | `[~]` `Model/qwen3-6-35b-a3b` (MoE) = `Ready` maar **geen InferenceService** (staged, niet geserveerd) | `kubectl get models -A` |
| In-cluster OpenAI-endpoint | `[x]` `http://qwen.llm.svc.cluster.local:8000/v1` (ClusterIP, poort 8000) | Service `qwen` in ns `llm` |
| Tool calling | `[x]` aan in vLLM (`--enable-auto-tool-choice --tool-call-parser qwen3_xml`) | InferenceService spec |
| Long context | `[x]` `--max-model-len 131072` (128K), `bfloat16`, fp8 KV-cache, prefix-caching, chunked-prefill | InferenceService spec |
| GPU-autoscaling | `[ ]` ⚠️ **geen HPA, geen KEDA** (replicas vast op 2; `scaledobject` CRD niet geïnstalleerd) | `kubectl get hpa -n llm` |
| Druppie wijst naar lokaal endpoint | `[ ]` ⚠️ backend ConfigMap nog `LLM_PROVIDER: zai`, geen `qwen`/`llm.svc`-referentie | ConfigMap ns `druppie` |
| Token streaming in LLM-client | `[ ]` ⚠️ niet geïmplementeerd (`druppie/llm/base.py` heeft alleen `chat`/`achat`) | repo |
| Benchmark framework | `[x]` `benchmarks/` (20 scenarios, 5 categorieën), gemerged; in-cluster Job-definitie in `benchmarks/k8s/` | repo |
| Benchmark uitgevoerd | `[x]` als in-cluster Job `llm-benchmark` (ns `llm`) op 2026-06-30, `runs=2 + warmup=1`; resultaten in `benchmarks/results-incluster/` | `kubectl get job -n llm` |
| Agent-kwaliteit benchmark | `[x]` BA evaluation tests (`testing/agents/`, tag `business_analyst`) | repo |

---

## LL1: Inferentie-stack keuze + ADR

De keuze is in de praktijk al gemaakt en gedeployed: **LLMKube** als Kubernetes-native serving-operator, met **vLLM** als engine. De spike verschuift daarmee van "opties evalueren en kiezen" naar **"de gemaakte keuze onderbouwen en vastleggen"**.

**Acceptatiecriteria**
- [x] Serving-stack gekozen en draaiend: LLMKube + vLLM (geen losse vergelijking vLLM/Ollama/TGI/KubeAI meer nodig — LLMKube wrapt vLLM)
- [ ] **ADR schrijven en goedkeuren** — `docs/ADR-LLM-SERVING-STACK.md` (Status/Context/Decision/Consequences, volg `docs/ADR-KUBERNETES.md`): waarom LLMKube boven raw vLLM-chart / KubeAI / TGI; wat de consequenties zijn (o.a. autoscaling zelf inrichten — zie LL2)
- [ ] `docs/LLM-SELECTION.md` bijwerken: huidige "Ollama currently configured" is achterhaald; werkelijke setup = LLMKube/vLLM met `Qwen3.6-27B` op `ka-k8s-ai`. In sync brengen met `benchmarks/config.yaml`
- [x] Spike-documentatie in `/docs` — `LLM-SELECTION.md` + `BENCHMARKING.md` aanwezig

---

## LL2: GPU-node + stack deployen + provider registreren

Grotendeels **al gerealiseerd** in het cluster. Resterend werk = autoscaling, Druppie-koppeling en streaming.

**Acceptatiecriteria**
- [x] GPU-node beschikbaar (`ka-k8s-ai-workers-gpu-xd4xn`, 2× GPU, taint `gpu=true:NoSchedule`)
- [x] NVIDIA GPU Operator actief (incl. dcgm-exporter voor metrics)
- [x] Stack draaiend via operator/Helm: LLMKube serveert `Qwen3.6-27B` via vLLM, 2 replicas op de GPU-node, tolerations `gpu=true:NoSchedule`, `gpu: 1` per replica
- [x] In-cluster OpenAI-compatible Service bereikbaar: `http://qwen.llm.svc.cluster.local:8000/v1`
- [ ] **Autoscaling op GPU-utilization** — nu vaste 2 replicas. Inrichten via **KEDA** (al patroon in `helm/druppie`: `keda-scaledobject-backend.yaml`) met Prometheus-scaler op `DCGM_FI_DEV_GPU_UTIL` (dcgm-exporter staat al), óf HPA + Prometheus Adapter. Let op: KEDA/`scaledobject` CRD is nog niet op `ka-k8s-ai` geïnstalleerd
- [ ] **Winnaar registreren als provider in Druppie**:
  - entry in `PROVIDER_CONFIGS` (`druppie/llm/litellm_provider.py:171`): `prefix: openai`, `default_base_url: http://qwen.llm.svc.cluster.local:8000/v1`, `default_model: Qwen/Qwen3.6-27B`, `api_key_optional: true`
  - toevoegen aan `LLMService.PROVIDERS` (`druppie/llm/service.py:42`)
  - via Helm wiren: `values-rijnland.yaml` → `configmap.yaml` zet `LLM_PROVIDER` (nu nog `zai`) of een profiel in `druppie/agents/definitions/llm_profiles.yaml`
- [ ] End-to-end op het lokale model:
  - [x] **tool calling** — vLLM heeft `--enable-auto-tool-choice` + `qwen3_xml` parser; Druppie-client `supports_native_tools=True`
  - [x] **long context** — vLLM `--max-model-len 131072` (128K). NB: Druppie-client cap't output op 16384 (hard cap 32768, `_build_kwargs`); input-context wordt server-side door vLLM bepaald
  - [ ] ⚠️ **token streaming** — niet geïmplementeerd in `BaseLLM`/`ChatLiteLLM`; vereist `astream` + `stream=True` + plumbing in `druppie/agents/loop.py`. **Aparte taak**
- [ ] (Optioneel) tweede model `qwen3-6-35b-a3b` daadwerkelijk serveren via een InferenceService voor vergelijk in LL3

---

## LL3: Performance benchmark op onze hardware

Framework staat klaar; het lokale endpoint draait. **Benchmark is uitgevoerd op 2026-06-30 als in-cluster Kubernetes Job** → zie [`docs/LLM-BENCHMARK-RESULTS.md`](LLM-BENCHMARK-RESULTS.md) (ruwe data: `benchmarks/results-incluster/results-qwen3.6-27b.json` + `.csv` + `report-qwen3.6-27b.txt`; Job-definitie: `benchmarks/k8s/`).

**Acceptatiecriteria**
- [x] Framework draait tegen OpenAI-compatible endpoints (`benchmarks/`)
- [x] `benchmarks/config.yaml` gericht op het lokale vLLM-endpoint met model `Qwen/Qwen3.6-27B` (endpoint `qwen_incluster` → `http://qwen.llm.svc.cluster.local:8000/v1`). Azure-Foundry-entry inactief gemaakt
- [x] Benchmark uitgevoerd **als Kubernetes Job** in ns `llm` (Job `llm-benchmark`, zelfde cluster-netwerk als de Service → representatieve latency, **geen tunnel**). Definitie + idempotent draaiscript in `benchmarks/k8s/` (`job.yaml`, `run-in-cluster.sh`); resultaten uit de Job-logs gehaald (RESULTS_JSON-markers) → `benchmarks/results-incluster/`. Gedraaid met `--runs 2 --warmup 1 --timeout 600` (2 metingen + warmup, gemiddeld)
- [x] Volledige scenario-suite uitgevoerd (latency, generation, context scaling tot 128K, tool overhead, stress) — 19/20 scenario's OK; `context-256k` automatisch geskipt (262.144 > `max_model_len` 131.072)
- [x] Metrics verzameld: TTFT (SSE), tokens/sec, latency, prompt-eval-rate; output JSON + CSV + console → `benchmarks/results-incluster/results-qwen3.6-27b.{json,csv}` + `report-qwen3.6-27b.txt`
- [ ] **Agent-kwaliteit**: BA evaluation suite (`testing/agents/`, tag `business_analyst`) tegen het lokale model via `LLM_FORCE_PROVIDER`/`LLM_FORCE_MODEL`, vaste judge/HITL (`glm-5`), 5×=55 runs; vergelijken met `zai`-baseline (`testing/results/ba-baseline-2026-04-23.md`)
- [x] Documentatie met aanbeveling → [`docs/LLM-BENCHMARK-RESULTS.md`](LLM-BENCHMARK-RESULTS.md) (Qwen3.6-27B is bruikbaar voor agent-workloads; uitstekende TTFT ~0,1–0,6 s over het hele 128K-bereik, werkende/stabiele tool-calling, gezonde context-scaling; let op decode-snelheid ~24–26 tok/s + cap reasoning-output)
- [ ] Definitieve keuze vastleggen in de ADR (LL1) met de LL3-cijfers

---

## Definition of Done (Nederlandse bullets → status)

- [x] Generieke LLM-benchmarks gedefinieerd → `benchmarks/`
- [x] Benchmark-scenario klaar → BA evaluation tests (55-run protocol, vaste judge/HITL)
- [x] Lijst met te testen LLMs → momenteel Qwen3.6-27B live + 35b-a3b staged; `docs/LLM-SELECTION.md` bijwerken naar werkelijke set
- [x] Meest geschikte LLMs gebenchmarked → Qwen3.6-27B gebenchmarked op 2026-06-30 (`docs/LLM-BENCHMARK-RESULTS.md`); 35b-a3b nog staged/niet geserveerd
- [x] Documentatie van gebruik + resultaten → gebruik én resultaten gedocumenteerd (`docs/LLM-BENCHMARK-RESULTS.md` + `benchmarks/results-qwen3.6-27b.{json,csv}`)

---

## Open beslissingen / risico's

1. **Autoscaling ontbreekt.** Replicas vast op 2; geen HPA/KEDA en `scaledobject` CRD niet geïnstalleerd op `ka-k8s-ai`. dcgm-exporter is er wél, dus de metric-bron is aanwezig — alleen de scaler moet nog. Beslis: KEDA installeren vs. HPA+Prometheus-Adapter.
2. **Druppie staat nog op `zai`.** De backend gebruikt het lokale model nog niet; provider-registratie + Helm-wiring is de schakel die LL2 "end-to-end" maakt.
3. **Token streaming is een eigen feature.** Raakt `base.py`, `litellm_provider.py`, `agents/loop.py`. Benchmark-TTFT werkt al (benchmark-client streamt zelf).
4. **Context-cap in de client.** vLLM kan 128K input, maar de Druppie-client cap't output op 16384/32768 — bewust kiezen of dit omhoog moet voor agent-workloads.
5. **27B vs 35b-a3b.** Tweede model staat staged maar wordt niet geserveerd; LL3 kan beide vergelijken als er een tweede InferenceService bijkomt.

## Aanbevolen volgorde (resterend werk)

1. Provider registreren in Druppie + Helm-wiring → backend praat met `qwen.llm.svc`.
2. ~~Benchmark-Job draaien~~ — **gedaan** (in-cluster Job 2026-06-30, `benchmarks/k8s/` + `benchmarks/results-incluster/`).
3. BA-eval tegen het lokale model vs. `zai`-baseline.
4. GPU-autoscaling (KEDA/HPA op DCGM-metric) inrichten.
5. (Apart) token-streaming implementeren.
6. ADR + `LLM-SELECTION.md` finaliseren met de resultaten.
