---
name: rag-patterns
description: >
  This skill should be used when designing an application that contains
  large-document retrieval, knowledge-base search, citation-backed Q&A,
  or any other doc-heavy use-case. It covers when an in-app LLM + RAG
  pipeline is a valid building block, how to choose chunking, retrieval,
  embedding, vector store, re-ranking and advanced patterns, which NFRs
  to put in the TD, and how to reference module-rag.
---

# RAG-patronen voor doc-heavy applicaties

RAG (Retrieval-Augmented Generation) is een **eerste-klas bouwblok** in Druppie. Net zoals je `module-data-access` of `module-llm` inzet als bouwsteen, mag je RAG via `module-rag` inzetten in een ontwerp. Wees je hiervan bewust: als een use-case grote of veel documenten betreft, is RAG vaak het juiste antwoord — niet zelf de inhoud van die documenten in een prompt proppen, en niet de gebruiker dwingen zelf te zoeken.

## Wanneer RAG inzetten

Pak RAG als minimaal één van deze waar is:
- Het corpus is **te groot voor de prompt-context** (meerdere documenten, of één document van >20 pagina's).
- De gebruiker stelt **vragen waarvan het antwoord verspreid in documenten staat**.
- De toepassing moet **antwoord met bronverwijzing** geven (juridisch, compliance, beleid, klantcontact in regulated domeinen).
- Het corpus **muteert vaker dan een release-cyclus** — fine-tuning zou achterlopen.

**Pak géén RAG als:**
- Het corpus past in één LLM-context-window en muteert zelden → gewoon meegeven in de prompt is goedkoper en exacter.
- De use-case is een **classificatie of structured extraction** zonder open-eind vraag — RAG voegt complexiteit toe zonder kwaliteitswinst.
- De vraag is een **single-fact lookup in een gestructureerde bron** (database, API) — `module-data-access` is dan de juiste keuze, niet RAG.

## Stop — verzin niet zelf de RAG-logica

Verwijs naar `module-rag` (zie [module-rag-spec](../../../docs/RAG/module-rag-spec.md)) in plaats van zelf chunking-, embedding- of vector-search-componenten te ontwerpen. De keuzes hieronder zijn platform-defaults; de architect motiveert in de TD welke laag eventueel afwijkt en waarom.

## Platform-default-stack

Begin elk RAG-ontwerp met deze defaults. Wijk alleen af met een expliciete trigger uit de decision-guides hieronder.

| Laag | Default | Wanneer afwijken |
|---|---|---|
| Chunking | Recursive 512-token, 10–20% overlap | Lange gestructureerde docs → parent-document; anafoor-zware tekst → late chunking |
| Retrieval | Hybrid (BM25 + dense) met RRF k=60 | Pure-vector alleen tijdelijk; ColBERT bij gemeten gat op out-of-domain |
| BM25-analyzer | Postgres `to_tsvector('<corpus-taal>')` per veld | Mixed-language corpus → analyzer per veld of multilingual analyzer |
| Metadata-filter | SQL-filter op `doc_type`, `datum`, `status`, `tenant_id` | n.v.t. — verplicht zodra er meer dan één doctype is |
| Embedding | `multilingual-e5-large-instruct` (MIT, CPU-haalbaar) | ≥8 GB GPU-budget + kwaliteitseis → Qwen3-Embedding-4B |
| Vector-store | pgvector (in `module-rag`'s eigen Postgres) | >10M chunks of hard p95-eis filtered ANN → escape naar Qdrant via v2 |
| Re-ranking | BGE-reranker-v2-m3 self-hosted (in `module-rag`) | Use-case-gold-set ≥5 nDCG-punten beter met Cohere → switch (Bedrock EU) |
| Query-transformatie | Query expansion + classifier-gated decomposition | HyDE bij korte/vage queries met stijlverschil |
| GraphRAG | **Niet default** | ≥30% van queries multi-entity/synthesis → LightRAG als parallelle retriever |
| Agentic loop | **Niet default** | Adaptive Router als eerste agentic-stap; Self-RAG alleen in synthesis-pad |
| Citaties | Content-hash chunk-IDs + page/paragraph + parent-section-titel; footnote-style in formele output | Juridische precisie → sentence-level span-tracking (Claude Citations API) |

## Decision-guides per laag

### Chunking
- **Recursive 512** is de safe default — 2026-benchmarks zetten dit consistent op #1 van token-based strategieën. Gebruik tiktoken-encoder, niet character-count.
- **Parent-document/hierarchical** zodra antwoorden kloppen maar citaten ofwel te smal ("halve zin uit context") ofwel te breed ("hele sectie als bron") zijn.
- **Late chunking** bij documenten met veel verwijswoorden ("dit besluit", "voornoemde partij") — vereist long-context embedding-model (8K+ tokens).
- **Mijd fixed-size** in productie tenzij het corpus echt homogeen is (logs, transcripts).

### Retrieval
- **Hybrid is de defensieve default.** Pure dense laat in formele/technische tekst structureel jargon liggen.
- **Configureer een taal-specifieke BM25-analyzer per corpus-taal.** Zonder NL/EN-analyzer levert lexical maar de helft van zijn waarde.
- **Metadata-filtering altijd toevoegen** zodra het corpus meer dan één doctype, jaar of categorie bevat.
- **ColBERT/multi-vector** alleen bij gemeten gat op out-of-domain queries én opslag-budget; voor de meeste use-cases is hybrid+rerank goedkoper en effectiever.

### Embedding-model
Selectiecriteria in volgorde:
1. Brede multilingual coverage (NL én EN minimaal).
2. Self-host-haalbaarheid (data-residency); API-only is een blocker tenzij EU-gehost en juridisch afgedekt.
3. Permissieve licentie (MIT of Apache 2.0). Non-commercial (jina-v3) is een blocker.
4. Bewezen kwaliteit op multilingual en taal-specifieke benchmarks.

- **Default**: `multilingual-e5-large-instruct` — MIT, ~2 GB, CPU-haalbaar, brede coverage.
- **Upgrade**: Qwen3-Embedding-4B als ≥8 GB GPU-budget; BGE-M3 als hybrid-met-één-model voorkeur.
- **Vermijd**: OpenAI text-embedding-3-* (zwak NL + API-only), mxbai/nomic-v2 (EN-only), jina-v3 (non-commercial license).

### Vector-store
- **Default = pgvector via `module-rag`.** Postgres draait al in de Druppie-stack; tot ~10M chunks geeft dit sub-100ms search-latency met SQL-filtering en transactionele consistentie.
- **Schuif naar Qdrant** zodra: corpus >10M chunks, hard p95-eis op filtered ANN, of native ColBERT/sparse vereist. Dit is een v2-pad voor `module-rag`; bouw je MCP-interface zo dat deze migratie geen embedding-rebuild forceert.
- **Weaviate / Milvus / Chroma / LanceDB**: alleen overwegen met expliciete use-case-driver (multimodal, miljarden vectors, embedded-only). Geen default.

### Re-ranking
- **Default aan** in `module-rag` met BGE-reranker-v2-m3 — gratis, soeverein, brede taaldekking.
- **Switch naar Cohere Rerank** (Bedrock EU) zodra een use-case-gold-set ≥5 nDCG-punten verschil laat zien én data-egress acceptabel is.
- **Schakel uit** als latency-budget <500ms p95 en je geen GPU hebt, óf recall@10 al >85% zonder rerank.
- **Kandidaten**: standaard N=50 → top-5..8; lange docs N=80–100; latency-kritisch N=30 → top-3.

### Query-transformatie
- **Query expansion** is de cheap default — een project-glossary met domein-jargon/synoniemen.
- **Decomposition** alleen wanneer een lichte classifier conjuncties detecteert ("en", "verschil tussen", "hoe verhoudt zich"). Cap op N=3 sub-vragen.
- **HyDE** alleen bij korte/vage queries met stijlverschil naar het corpus.
- **Step-back** als optionele stap binnen een agentic-loop bij hyper-specifieke vragen.
- **Anti-patroon**: multi-query + decomposition tegelijk → latency-explosie zonder meerwaarde.

### Geavanceerde patronen
- **GraphRAG niet default.** Voeg toe (LightRAG als parallelle retriever in een Adaptive Router) zodra ≥30% van de queries multi-entity/synthesis-vragen zijn. Volledig Microsoft GraphRAG alleen bij expliciete corpus-brede synthese-projecten.
- **Agentic loop niet default.** Stappenplan: (1) baseline + rerank werkend → (2) Adaptive Router (3-4 klassen classifier) → (3) Self-RAG/CRAG in synthesis-pad → (4) Plan-and-execute alleen voor research-vragen. Altijd met hard cap op iteraties + latency-circuit-breaker.

## Citaties

Voor doc-heavy applicaties waar gebruikers de bron moeten kunnen verifiëren is citatie-tracking **geen feature maar een eis**. Verplicht in de pipeline:

1. **Content-hash chunk-IDs** (`source_id + version + hash(span_text)`) — stabiel over re-indexering.
2. **Page/paragraph metadata** — gebruikers moeten naar de bron-passage kunnen springen.
3. **Parent-section-titel** als metadata bij hierarchical chunking — context-rijke citaten.
4. **Footnote-style in formele Markdown-output** + parallel **anchor-tags** (`<cite chunk_id="..." span="...">tekst</cite>`) voor interactieve UI met klikbare bron-preview.
5. **Sentence-level span-tracking** als juridische/compliance-precisie nodig is — Claude Citations API of post-hoc matching.

Citaten verifiëren dat de **bron bestaat**, niet dat de **claim klopt**. Houd die scheiding helder in UX en in evaluatie.

## NFRs voor RAG in de TD

Plak deze TR-xx requirements in elke RAG-TD. Volledige tabel met defaults per archetype staat in [rag-patterns research → Default-NFR-tabel](../../../docs/RAG/rag-patterns.md#default-nfr-tabel). Verplicht minimaal:

| TR | Onderwerp | Default-archetype gebruiken |
|---|---|---|
| TR-RAG-01/02 | Retrieval-latency P95 / P99 | LS / HS / Batch |
| TR-RAG-03/04/05 | Recall@10, nDCG@5, MRR op gold-set | LS / HS / Batch |
| TR-RAG-06 | Faithfulness (claim-support) | ≥0.85 LS, ≥0.90 HS |
| TR-RAG-07 | Citation precision | ≥0.85 LS, ≥0.95 HS |
| TR-RAG-08 | Hallucination-rate | ≤10% LS, ≤3% HS |
| TR-RAG-09/10/11 | Freshness SLA per decay-tier | per content-type |
| TR-RAG-12 | Named content owner per domein | verplicht |
| TR-RAG-13/14 | End-to-end latency (TTC, TTFT) | LS / HS / Batch |
| TR-RAG-15 | Pipeline-uptime | 99.5% LS, 99.9% HS |
| TR-RAG-19 | CI-gate op faithfulness en latency-regressies | verplicht |
| TR-RAG-21 | PII / classificatie-tagging vóór indexing | verplicht |
| TR-RAG-22 | Lineage per chunk (`source_id`, `version`, `ingested_at`) | verplicht |

**Archetypes:**
- **LS (Low-stakes interactief)**: chatbot, FAQ, snelle Q&A.
- **HS (High-stakes interactief)**: bestuurlijk advies, juridisch, compliance, regulated klantcontact.
- **B (Batch)**: nightly digests, research-summaries.

Kies één archetype als basis en pas waar nodig aan per requirement.

## Hoe je dit in een TD verwerkt

In de Technical Design van een RAG-projekt:

1. **Sectie "Oplossingsrichting"** — verwijs expliciet naar `module-rag` als bouwblok en motiveer waarom RAG (i.p.v. classificatie, in-prompt context, of gestructureerde DB-query).
2. **Sectie "Architectuur"** — toon de pipeline-stappen: ingest → chunk → embed → store → search → rerank → generate. Markeer welke stappen `module-rag` doet, welke `module-llm`, welke de applicatie zelf.
3. **Sectie "Keuzes per laag"** — vermeld voor chunking, retrieval, embedding, vector-store, rerank, query-transformatie en geavanceerde patronen of je de platform-default volgt, en zo niet: welke afwijking en met welke trigger.
4. **Sectie "Citatie-strategie"** — beschrijf welke citation-style in de output verschijnt, welke metadata in de index, en wat de gebruiker in de UI ziet.
5. **Sectie "Non-functional requirements"** — neem de TR-RAG-XX requirements op met use-case-specifieke targets (kies archetype, pas zo nodig aan).
6. **Sectie "Open vraagstukken / out-of-scope"** — wat doe je in v1 niet (geavanceerde patronen, multi-tenant fysieke separatie, fancy reranking) en wat zou een v2-trigger zijn.

## Anti-patronen om te herkennen in een ontwerp

- **"We gebruiken RAG"** zonder te benoemen welke pipeline-stappen, embedding-model of vector-store. Onder-spec; vraagt om TD-revisie.
- **Pure-vector search** als enige retrieval-strategie in productie — laat structureel jargon en eigennamen liggen.
- **GraphRAG of agentic RAG** zonder bewezen probleem dat het oplost — voegt latency en kosten toe zonder kwaliteitswinst.
- **Eigen vector-store-keuze** (Qdrant, Weaviate, etc.) zonder concrete trigger uit de decision-guide. Default = pgvector via `module-rag`.
- **Citaties als "bronnenlijst onderaan"** in plaats van per-claim-binding — voor regulated use-cases een blocker.
- **Embedding-model-keuze gebaseerd op MTEB-EN-leaderboard** zonder te kijken naar NL/multilingual benchmarks en licentie.
- **Document-extractie verstoppen in `module-rag`** — caller is verantwoordelijk voor PDF/Word → tekst; `module-rag` accepteert pre-extraheerde text+metadata.

## Referenties

- Research-fundament met volledige vergelijking + trade-off-tabellen: [`docs/RAG/rag-patterns.md`](../../../docs/RAG/rag-patterns.md)
- Module-spec (tool-surface + datamodel): [`docs/RAG/module-rag-spec.md`](../../../docs/RAG/module-rag-spec.md)
- Platform-standards RAG-sectie (defaults voor nieuwe projecten): [`docs/specs/platform-standards.md`](../../../docs/specs/platform-standards.md) — RAG-sectie
