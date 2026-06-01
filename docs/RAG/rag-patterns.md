# Technisch Onderzoek — RAG-patronen als platform-bouwblok

> Status: Research-fundament voor de skill `rag-patterns`, het bestaande
> `module-vectorstore`-primitive (v1 — `druppie/mcp-servers/module-vectorstore/`),
> en de MODULE_SPEC `module-rag` (Story B-orchestrator — zie `module-rag-spec.md`).
> Onderdeel van Story A — RAG als ontwerp-bouwblok voor de Architect.
> Datum: 2026-06-01.

## Inleiding

### Onderwerp

Retrieval-Augmented Generation (RAG) als generiek platform-bouwblok in Druppie. Bedoeld om door de Architect-agent ingezet te worden in elke doc-heavy applicatie die we bouwen — kennisbanken, juridische zoek, compliance-search, klantcontact-Q&A, interne docs, beleidsteksten, productdocumentatie, enzovoort. Use-cases verschillen per project in taal, schaal, query-type en stakes; het bouwblok moet die variatie aankunnen.

De **HDSR-notas use-case** wordt later in dit traject (Story A's e2e-test en Story B) gebruikt als één validatie-scenario dat een lastige combinatie raakt: lange documenten, Nederlandstalig, bestuurlijke stakes, harde citatie-eis. Het is een goede smoke-test, **geen design-driver**.

### Onderzoeksvraag

Welke keuzes — chunking-strategie, retrieval-patroon, citatie-tracking, embedding-model, vector-store, geavanceerde patronen (re-ranking, query-rewriting, GraphRAG, agentic), en RAG-specifieke NFRs — moet de Architect-agent kunnen verantwoorden in een TD voor een willekeurige doc-heavy applicatie in Druppie, en welke defaults rechtvaardigen we als platform-standaard?

### Uitgangspunten

- **Multilingual is een harde eis.** Use-cases per project verschillen in taal (NL, EN, mix, soms breder). Het platform moet daar uit-de-doos mee omgaan; geen taal-specifieke pipelines per project.
- **Greenfield** — geen bestaande RAG-keuzes in Druppie om aan vast te zitten.
- **Postgres draait al** in de Druppie-stack als primaire datastore (geen JSON/JSONB-conventie). Een nieuwe stateful service moet zichzelf rechtvaardigen.
- **Modules zijn containerized MCP-servers** volgens de `module-convention` skill. RAG hoort als `module-rag` ingestoken te worden, niet als applicatie-bibliotheek.
- **Self-hosted heeft voorkeur** voor data-residency. API-only oplossingen zijn een blocker tenzij in EU-regio gehost en juridisch afgedekt — gegeven dat veel Druppie-klanten publieke organen zijn.
- **Pragmatisch boven academisch** — de Architect kiest, hij hoeft niet alles te begrijpen.
- **Format**: dit document volgt hybride `technical-research-format`. Omdat RAG meerdere onafhankelijke keuze-assen heeft, krijgt elke as een eigen vergelijking + trade-off-tabel + decision-guide. De **Eindaanbeveling** consolideert tot platform-defaults plus expliciete afwijkings-triggers per use-case.

---

## Chunking-strategieën

Chunking bepaalt hoe een brondocument wordt opgedeeld in stukken die los geëmbed, geïndexeerd en geciteerd worden. Voor lange, gestructureerde documenten (rapporten, contracten, beleidsteksten, jaarverslagen, juridische dossiers) is dit de hefboom met de grootste impact op zowel retrieval-kwaliteit als citatie-precisie — meer dan welk embedding-model dan ook. Het kost weinig om mis te slaan: een naïeve split verliest 9% recall op identieke corpora, en in domeinen met sterke structurele grenzen loopt de kloof op tot tientallen procenten ([Vecta-benchmark feb 2026](https://futureagi.com/blog/evaluating-rag-chunking-strategies-2026/), [Digital Applied 2026 playbook](https://www.digitalapplied.com/blog/rag-chunking-strategies-2026-retrieval-quality-playbook)).

### Vergelijking

#### Fixed-size
Het document wordt geknipt in stukken van een vast aantal tokens (bv. 512), met eventueel een vaste overlap. Geen besef van zinnen, paragrafen of secties.
- **Wanneer:** alleen voor prototypes en zeer homogene tekst (logs, transcripts). Niet voor gestructureerde documenten.
- **Trade-offs:** snelste indexering en simpelste code, maar breekt zinnen en koppen midden in een definitie. Een peer-reviewed studie (MDPI Bioengineering, nov 2025) liet zien dat fixed-size 13% accuracy haalde tegenover 87% voor topic-aware op gestructureerde tekst — significant met p=0.001 ([Firecrawl 2026](https://www.firecrawl.dev/blog/best-chunking-strategies-rag)).
- **NL:** zin- en alineagrenzen gaan verloren; verwijswoorden ("deze maatregel", "het college") komen los van hun antecedent.

#### Sliding-window
Variant op fixed-size: knippen op vaste lengte, maar met grote overlap (bv. 50%). Elke zin komt zo in meerdere chunks voor.
- **Wanneer:** als je een fixed-size baseline wilt redden voor query's waar context net buiten de chunk valt; ook nuttig bij sentence-window retrieval (LlamaIndex).
- **Trade-offs:** verbetert recall, maar verdubbelt index-grootte en geeft duplicated citations (dezelfde passage in twee chunks → ambigu citaat).
- **NL:** geen specifieke effecten.

#### Recursive
Splitst hiërarchisch: eerst op dubbele newlines (paragrafen), dan single newlines, dan zinnen, dan woorden, tot het past in de chunk-budget. LangChain's `RecursiveCharacterTextSplitter` is de de-facto default.
- **Wanneer:** veilige startoptie voor vrijwel alles, inclusief lange gestructureerde documenten in willekeurige taal. Vecta's februari-2026 benchmark plaatste recursive 512 als nr. 1 over 7 strategieën (69% accuracy) ([Vecta via FutureAGI](https://futureagi.com/blog/evaluating-rag-chunking-strategies-2026/)).
- **Trade-offs:** 80% van semantic-kwaliteit voor 5% van de kosten. Let op de bekende valkuil: LangChain's splitter telt **karakters**, niet tokens. Gebruik `from_tiktoken_encoder()` voor tokenaccuraat splitsen ([Digital Applied](https://www.digitalapplied.com/blog/rag-chunking-strategies-2026-retrieval-quality-playbook)).
- **NL:** werkt zoals in het Engels — paragraaf- en zinscheidingen zijn dezelfde tekens.

#### Semantic (sentence-/paragraph-/topic-aware)
Splitst op betekenis: opeenvolgende zinnen die semantisch dichtbij elkaar liggen worden samengevoegd; bij een drempelwaarde (cosine-afstand) wordt geknipt. Varianten: `SemanticChunker` (embedding-driftbased), `LLMSemanticChunker` (LLM bepaalt grenzen).
- **Wanneer:** als recursive aantoonbaar onder de norm scoort en het type document baat heeft bij betekenisclusters (lange essays, wetenschappelijke teksten).
- **Trade-offs:** LLM-semantic haalt 0.919 recall (vs. 0.881–0.895 voor recursive 400-token), maar is ~14× trager dan token-based ([Chonkie-benchmarks via Firecrawl](https://www.firecrawl.dev/blog/best-chunking-strategies-rag)). Recente benchmarks zijn gemengd: Vecta zag semantic onderpresteren omdat de chunks te kort werden (avg 43 tokens).
- **NL:** afhankelijk van een goede zin-detectie. spaCy's `nl_core_news_lg` en NLTK's Punkt Dutch zijn solide voor moderne tekst; voor formele beleidstaal werkt **Frog** (KU Leuven/Tilburg) robuuster bij afkortingen ("art.", "lid", "jo.") ([spaCy NL](https://spacy.io/models/nl/), [Frog](http://languagemachines.github.io/frog/)).

#### Parent-document / hierarchical (small-to-big)
Twee niveaus: kleine kindchunks (zinnen, 128–256 tokens) worden geëmbed voor retrieval; bij een hit wordt de **ouder**chunk (sectie of paragraaf, 1024–2048 tokens) aan het LLM gegeven. LlamaIndex's `HierarchicalNodeParser` heeft default [2048, 512, 128].
- **Wanneer:** sterke fit voor lange documenten met genummerde secties (rapporten, beleidsteksten, contracten, jaarverslagen). Antwoorden moeten precies de relevante zin vinden ("welke datum is besloten?") maar context-rijk worden geciteerd ("§3.2 van [bron-document]").
- **Trade-offs:** dubbele opslag (kind + ouder), iets complexere ingestie. Levert duidelijk betere antwoorden bij lange documenten; arXiv 2503.02401 (HRR) liet +25% MRR zien ten opzichte van flat recursive.
- **NL:** geen specifieke risico's, mits zin-detectie voor de kindlaag goed is.

#### Late chunking
De volgorde wordt omgedraaid: eerst wordt het hele (lange) document door een long-context embedding-model gehaald om contextueel rijke **token**-embeddings te krijgen; pas daarna worden chunks gevormd door mean-pooling binnen grenzen. Bedacht door Jina (2024); inmiddels in jina-embeddings-v3 en geïntegreerd in Weaviate, Elastic, Milvus.
- **Wanneer:** lange documenten met veel anaforen en cross-referenties ("dit besluit", "voornoemde commissie", "de hierboven genoemde partij"). Hoe langer het document, hoe groter de winst. Typisch sterk in juridische, beleids- en contract-corpora.
- **Trade-offs:** vereist een long-context embedding-model (8k+ tokens). Implementatie is minimaal (~30 regels op de pooling-stap), maar je verbruikt meer tokens per ingest. Combineert goed met parent-document. Jina rapporteert hogere similarity-scores op anafoor-zware passages; Anthropic's Contextual Retrieval (een verwante techniek) cut top-20 retrieval failures met 67% ([Jina](https://jina.ai/news/late-chunking-in-long-context-embedding-models/), [Weaviate](https://weaviate.io/blog/late-chunking)).
- **Taal:** hangt af van taalondersteuning van het long-context model (jina-v3 en bge-m3 dekken een brede set talen incl. NL goed).

### Trade-off-tabel

| Strategie | Complexiteit | Retrieval-kwaliteit | Citatie-precisie | Operationele kosten | Fit lange docs (50+p) |
|---|---|---|---|---|---|
| Fixed-size | Laag | Laag | Laag (breekt zinnen) | Zeer laag | Slecht |
| Sliding-window | Laag | Middel | Middel (duplicates) | Laag-middel | Middel |
| Recursive | Laag | Goed | Goed | Laag | Goed |
| Semantic | Middel | Hoog | Hoog | Middel (~14× recursive) | Goed |
| Parent-document | Middel | Hoog | Zeer hoog (sectie-anker) | Middel (2× opslag) | Zeer goed |
| Late chunking | Middel-hoog | Zeer hoog | Hoog | Middel (long-ctx model) | Zeer goed |

### Decision-guide

1. **Begin met recursive 512-token** met tiktoken-encoder en 10–20% overlap. Dit is de safe default uit alle 2026-benchmarks, ongeacht use-case of taal.
2. **Stap naar parent-document/hierarchical** zodra antwoorden kloppen maar citaten te smal of te breed zijn — typisch bij lange gestructureerde documenten met genummerde secties.
3. **Voeg late chunking toe** bij documenten met veel verwijswoorden ("deze maatregel", "voornoemde partij") waar baseline-retrieval naar de verkeerde paragraaf wijst. Vereist long-context embedding-model.
4. **Overweeg semantic** alleen als je een gemeten kwaliteitsgat ziet dat parent+late niet dichten; de 14× compute-overhead is reëel.
5. **Mijd fixed-size** in productie tenzij je corpus echt homogeen is.

---

## Retrieval & Search-patronen

Retrieval bepaalt welke chunks aan het LLM worden gevoerd. In doc-heavy applicaties is dit lastiger dan het lijkt: gebruikers stellen zowel natuurlijke vragen ("wat is de policy over X?") als jargon-vragen (artikel-/clausule-referenties, dossiernummers, productcodes) — twee retrieval-regimes die elkaars zwakte zijn.

### Vergelijking

#### Pure vector search (dense)
Query en chunks worden geëmbed; cosine/dot-product similarity bepaalt de top-k. ANN-indexen (HNSW, IVF) houden het schaalbaar.
- **Wanneer:** natuurlijke taal, parafrasering, synoniemen. Goede default voor onverwachte query-formuleringen.
- **Trade-offs:** struikelt over zeldzame termen (jargon, eigennamen, dossiernummers, artikelreferenties). Voor "Watervergunning 2024-WV-0451" is dense zoekwoorden vrijwel zinloos; vector vindt iets "in de buurt" wat fout is.
- **NL:** sterk afhankelijk van NL-coverage van het model. Multilingual modellen (BGE-M3, jina-v3, multilingual-e5) presteren stevig op NL; ada-002 verliest ~5–10% nDCG op NL vs. EN.

#### Lexical / BM25
Klassieke sparse keyword retrieval gebaseerd op term-frequency × inverse document-frequency. Geen embeddings nodig.
- **Wanneer:** exacte termen, codes, namen, jargon. Onmisbaar voor artikel-/clausule-referenties, IBAN's, dossier-/productnummers, geciteerde tekst.
- **Trade-offs:** mist synonymie en morfologische variaties. Solide, voorspelbaar, goedkoop.
- **Taal:** vraagt om een **taal-specifieke analyzer** (stemmer + stopwoordenlijst) per corpus-taal. Postgres `to_tsvector('<taal>', ...)` en Elasticsearch leveren dit out-of-the-box voor alle gangbare Europese talen incl. NL en EN. Voor multilingual corpora: een analyzer per taal-veld of een multilingual analyzer.

#### Hybrid (vector + BM25 met RRF of weighted fusion)
Beide retrievers draaien parallel; hun ranglijsten worden samengevoegd. **Reciprocal Rank Fusion (RRF)** is dominant in 2026: score = Σ 1/(k + rank), met k=60 als veilige default (k=20–30 als je top-resultaten zwaarder wilt wegen). RRF werkt op **ranks**, niet scores, dus geen normalisatie nodig ([Microsoft Learn](https://learn.microsoft.com/en-us/azure/search/hybrid-search-ranking)).
- **Wanneer:** vrijwel altijd, in productie. BEIR-benchmarks en Anthropic-rapportages laten consistent +5–15% nDCG zien tegenover de beste van de twee alleen ([Digital Applied 2026](https://www.digitalapplied.com/blog/hybrid-search-bm25-vector-reranking-reference-2026)).
- **Trade-offs:** twee indexen onderhouden (vector + inverted index), twee query-paden. Operationeel iets complexer; ParadeDB, Weaviate, Qdrant, Elasticsearch 8.13+, en Azure AI Search bieden dit native.
- **Taal:** werkt taal-onafhankelijk mits de BM25-analyzer per taal correct staat. Combineert het beste van twee werelden — BM25 vangt exacte termen, vector vangt parafraseringen en synoniemen.

#### Metadata-filtered search
Filter op gestructureerde velden (doc_type=nota, datum>2023-01-01, status=vastgesteld) vóór, tijdens of na de vector-stap.
- **Wanneer:** altijd zodra je meer dan één doctype, jaar of categorie hebt — vrijwel elke productie-RAG.
- **Trade-offs:** drie strategieën: **pre-filter** (filter eerst, dan ANN) garandeert k resultaten maar breekt HNSW-graphconnectiviteit bij lage cardinaliteit; **post-filter** is simpel maar levert soms <k resultaten; **in-graph filtering** (Qdrant filterable HNSW, Milvus, Weaviate) is de moderne standaard en lost beide problemen op ([Qdrant](https://qdrant.tech/articles/vector-search-filtering/)).
- **Taal:** niet taal-afhankelijk; cruciaal voor citatie-precisie ("alleen passages uit status=vastgesteld, datum=2024").

#### Multi-vector / ColBERT-stijl (late interaction)
In plaats van één vector per chunk slaat het model per token een vector op. Bij scoring wordt voor elk query-token het maximum vergeleken met alle document-tokens (MaxSim).
- **Wanneer:** out-of-domain corpora waar single-vector dense het laat afweten; lange documenten met fijnkorrelige matches; multilingual scenario's. ColBERTv2/PLAID is productie-rijp.
- **Trade-offs:** ~10× opslag (ColBERTv2 brengt dit terug naar ~2× met residual quantization), hogere index-complexiteit. Voor Druppie-schaal (10⁴–10⁶ chunks) zijn de kosten beheersbaar. ColPali (visual ColBERT) breidt dit uit naar PDF-pagina's direct.
- **Taal:** taal-specifieke late-interaction modellen zijn schaars; de multilingual variant (`jina-colbert-v2-multilingual`) dekt een brede taalset incl. NL redelijk. Voor de meeste use-cases is hybrid+rerank voldoende en goedkoper.

### Trade-off-tabel

| Patroon | Relevantie short queries | Relevantie long queries | Jargon/eigennamen | Operationele complexiteit | NL-fit |
|---|---|---|---|---|---|
| Pure vector | Middel | Hoog | Laag | Laag | Goed (mits multilingual model) |
| BM25 | Hoog (exact) | Middel | Zeer hoog | Laag | Goed (met taal-analyzer) |
| Hybrid (RRF) | Hoog | Hoog | Hoog | Middel | Zeer goed |
| Metadata-filtered | n.v.t. (modifier) | n.v.t. (modifier) | n.v.t. | Laag-middel | n.v.t. |
| Multi-vector / ColBERT | Hoog | Zeer hoog | Hoog | Hoog | Middel (taal-modellen schaars) |

### Decision-guide

1. **Begin met hybrid (BM25 + dense, RRF k=60).** Het is in 2026 de defensieve default; pure dense laat in formele/technische teksten structureel jargon liggen.
2. **Configureer een taal-specifieke analyzer voor de BM25-kant** per corpus-taal (Postgres `to_tsvector('<taal>', ...)`, Elasticsearch language analyzers). Voor multilingual corpora: analyzer-per-veld of een multilingual analyzer. Zonder dit levert lexical maar de helft van zijn waarde.
3. **Voeg altijd metadata-filtering toe** op doctype, datum, status, tenant. Vrijwel elke vraag is zonder context-filter inefficiënt.
4. **Pak ColBERT/late-interaction** alleen als je een gemeten gat ziet op out-of-domain query's en je het opslag-/index-budget kunt dragen.
5. **Pure vector** is een redelijke baseline als je tijdsdruk hebt, maar laat zichtbaar geld liggen — niet de eindstand.

---

## Citatie-tracking

Voor doc-heavy applicaties waar gebruikers de bron moeten kunnen verifiëren (juridisch, beleid, compliance, klantcontact, medisch, financieel) is citatie-tracking geen feature maar een eis: een uitspraak zonder verifieerbare bron is voor die domeinen onbruikbaar. De keten loopt van chunk-metadata in de index → context-injectie in de prompt → output-formattering → UI-rendering. Elke schakel kan informatie weglekken.

### Vergelijking

#### Chunk-ID + source-document-ID
Elke chunk krijgt een stabiel ID (`doc_id + version + hash(span_text)`) en een verwijzing naar het originele document.
- **Wanneer:** absolute baseline. Zonder dit kun je niets traceren.
- **Trade-offs:** content-hashing maakt ID's stabiel over reindexing — anders breken citaten bij elke ingest ([Visively](https://visively.com/kb/ai/llm-rag-retrieval-ranking)). Triviaal te implementeren; alleen disciplinaire kosten.

#### Page / paragraph / offset
Naast IDs sla je positie-metadata op: pagina-nummer (PDF), sectie-titel, paragraaf-index, character-offsets in het origineel.
- **Wanneer:** zodra gebruikers naar de bron moeten kunnen springen ("toon die zin op pagina 23"). Essentieel voor formele documenten met paginering.
- **Trade-offs:** PDF-extractie moet positie behouden (Tensorlake, Unstructured, AWS Textract met `geometry`); bounding boxes voegen ~10–15% opslag toe maar maken inline preview mogelijk ([Tensorlake](https://www.tensorlake.ai/blog/rag-citations)). Pagina + paragraaf is robuuster dan character-offset; offsets veranderen bij kleine document-edits, paginanummers zelden.

#### Span-tracking binnen chunks
Niet alleen "deze chunk", maar "tekens 412–587 in deze chunk" — de daadwerkelijk geciteerde zin.
- **Wanneer:** voor sentence-level highlights in de UI, of als input voor Anthropic's Citations API (die character-level provenance teruggeeft, 0-indexed met exclusive end).
- **Trade-offs:** hoogste precisie, mooiste UX. Implementatie iets complexer: of de LLM produceert spans (kwetsbaar voor hallucinatie), of je matcht de gegenereerde zin post-hoc terug naar de bron (kost wat compute). De Citations API doet dit gratis voor je als je Claude gebruikt ([Claude Citations docs](https://platform.claude.com/docs/en/build-with-claude/citations)).

#### Parent-document-IDs (bij hierarchical chunking)
De kind-chunk wordt geciteerd voor de match, maar het citaat toont de **ouder**-sectie (en geeft de gebruiker zicht op de context waarin de zin staat).
- **Wanneer:** verplicht zodra je parent-document-chunking gebruikt. Een naakte kind-citatie is misleidend — een halve zin uit context.
- **Trade-offs:** UX-wens (toon sectie-titel + omringende zinnen) versus prompt-budget (je voegt meer tokens toe). Goede compromis: toon parent als context in UI, niet in prompt.

#### Citation styles in output
- **Inline numerieke markers** (`[1]`, `[2]`): vertrouwd, leest als academische tekst. Goed voor formele schriftelijke output.
- **Anchor-based** (`<cite chunk_id="..." span="...">tekst</cite>`): machine-parsbaar, ideaal voor interactieve UI met hover/click.
- **Footnotes** (`tekst¹` met voetnoot onderaan): hoogste leesbaarheid voor formele documenten.
- **Appended source list**: simpelste vorm — antwoord eerst, daarna "Bronnen: [lijst]". Werkt, maar mist binding tussen zin en bron, wat juist het probleem is dat citaten moeten oplossen.

Twee generatie-patronen:
1. **Single-pass:** LLM produceert antwoord en citaties tegelijk in één call (Anthropic's aanpak; lijkt op intern gebruik bij Claude Citations).
2. **Two-step verify:** LLM schrijft draft → tweede LLM-pass verifieert claims tegen passages → finale output met geverifieerde citaten. Trager, robuuster tegen hallucinatie ([Particula](https://particula.tech/blog/fix-rag-citations)).

### Trade-off-tabel

| Patroon | Traceerbaarheidsprecisie | UX | Implementatie-complexiteit | Fit lange documenten |
|---|---|---|---|---|
| Chunk-ID + doc-ID | Document-niveau | Basis | Triviaal | Onvoldoende alleen |
| Page / paragraph / offset | Paragraaf-niveau | Goed (jump-to-source) | Laag-middel | Zeer goed |
| Span-tracking | Zin-/tekenniveau | Uitstekend (highlight) | Middel | Zeer goed |
| Parent-document-IDs | Sectie + zin | Uitstekend (context) | Middel (bij hierarchical) | Verplicht bij hierarchical |
| Inline [1] style | Hangt van anker af | Vertrouwd | Laag | Goed |
| Anchor-based tags | Hoog | Interactief | Middel | Goed |
| Footnotes | Hangt van anker af | Formeel, leesbaar | Laag-middel | Zeer goed |
| Appended list | Laag (geen binding) | Slecht voor audit | Triviaal | Onvoldoende |

### Decision-guide

1. **Begin met chunk-ID + doc-ID + page/paragraph als verplichte metadata** in de index. Gebruik content-hash-based ID's (`doc_id + version + hash(span)`), niet positionele indexen, anders breekt elke reindex je citaten.
2. **Voeg parent-section-titel toe** als metadata zodra je hierarchical chunking inzet — toon dit in de UI ("[Bron-document], §3.2 [Sectietitel], p.18").
3. **Voor formele schriftelijke output: kies footnote-style** in de gegenereerde Markdown. Leesbaar bij export naar Word/PDF, past in academische en bestuurlijke stijlen.
4. **Voor interactieve UI**: voeg parallel anchor-tags toe (`<cite>...</cite>`) die de footnote-nummers koppelen aan een klikbare bron-preview met page-jump.
5. **Sentence-level span-tracking** is de upgrade als juridische of compliance-precisie nodig is. Als je Claude gebruikt: laat de Citations API het werk doen ([Claude docs](https://platform.claude.com/docs/en/build-with-claude/citations)). Anders: instrueer de LLM om sentence-tags af te leveren en parse die post-hoc.
6. **Two-step verify** alleen als hallucinatie-risico's hoog scoren in evaluatie. Voor de meeste use-cases is single-pass + sentence-level anchors voldoende. Onthoud: citaten verifiëren dat de bron *bestaat*, niet dat de claim *klopt* — die scheiding moet in UX en evaluatie helder zijn.

---

## Embedding-modellen

### Vergelijking

#### BGE-M3 (BAAI)
- **Wat**: Open multilingual embedding model van Beijing Academy of AI (jan 2024, nog steeds production-standaard begin 2026). Gebouwd op XLM-RoBERTa-large.
- **Hosting**: Self-hosted (HuggingFace) of via providers (DeepInfra, IONOS, Zilliz). 568M parameters.
- **Dimensies**: 1024 dense, plus native sparse en multi-vector (ColBERT) output uit één forward pass — uniek.
- **Max input**: 8192 tokens — past goed bij lange documenten (in combinatie met chunking).
- **NL-performance**: Op MTEB-NL (Banar et al., sept 2025) **AvgT 63.1, retrieval 60.0** — solide maar niet top. Wordt verslagen door multilingual-e5-large-instruct (66.9) en Qwen3-Embedding-4B (69.2). ([arXiv 2509.12340](https://arxiv.org/abs/2509.12340))
- **Licentie**: MIT — volledig commercieel inzetbaar.
- **Ops**: ~2.3 GB FP32, draait op CPU (langzaam) of single consumer GPU. Past in een MCP-container met 4-6 GB RAM.
- **Sterkte voor Druppie**: Native dense+sparse+ColBERT in één pass maakt hybrid search met één model haalbaar ([BAAI/bge-m3 HuggingFace](https://huggingface.co/BAAI/bge-m3)).

#### multilingual-e5-large-instruct (Microsoft)
- **Wat**: Instruct-versie van de E5-familie (Microsoft Research, 2024). 560M parameters.
- **Hosting**: Self-hosted, MIT-licentie.
- **Dimensies**: 1024 (geen Matryoshka).
- **Max input**: 512 tokens — dit is een echte beperking voor lange documenten; vraagt strikter chunken.
- **NL-performance**: **Hoogste algemene score op MTEB-NL onder niet-NL-specifieke modellen: AvgT 66.9, retrieval 61.4, clustering 46.0** ([MTEB-NL paper](https://arxiv.org/html/2509.12340v1)).
- **Licentie**: MIT.
- **Ops**: 2.2 GB FP32, vergelijkbaar met BGE-M3.
- **Kanttekening**: Vereist instruction-prefixes ("query: ..." / "passage: ...") — pipeline moet dat enforcen of accuracy zakt merkbaar.

#### E5-NL (Universiteit Antwerpen, sept 2025)
- **Wat**: NL-specifieke E5-variant met getrimde tokenizer, getraind door Banar et al. Small/base/large.
- **Hosting**: Self-hosted (HuggingFace).
- **Dimensies**: 1024 (large), 768 (base), 384 (small).
- **NL-performance**: **State-of-the-art onder non-instruct modellen op MTEB-NL**; e5-large-trm-nl is de top non-instruct. Voor pure NL-RAG sterker dan BGE-M3, vergelijkbaar met multilingual-e5-large-instruct maar parameter-efficiënter.
- **Licentie**: MIT.
- **Kanttekening**: NL-only — multilingual capability is geofferd voor NL-precisie. Slecht voor mixed NL/EN corpora.

#### Qwen3-Embedding (Alibaba, juni 2025)
- **Wat**: 0.6B / 4B / 8B varianten op Qwen3 foundation. Apache 2.0.
- **Hosting**: Self-hosted, ook via Ollama beschikbaar (0.6B is 639 MB GGUF).
- **Dimensies**: Custom dimensies (MRL support).
- **Max input**: 32K (0.6B/4B), 128K (8B).
- **NL-performance**: **Qwen3-Embedding-4B: MTEB-NL AvgT 69.2 — hoogste van alle geteste open modellen op Dutch**. 0.6B haalt 62.6. 8B ranked #1 op multilingual MTEB v1 (70.58) ([Qwen3 Embedding blog](https://qwenlm.github.io/blog/qwen3-embedding/)).
- **Licentie**: Apache 2.0.
- **Ops**: 0.6B CPU-only; 4B vereist ~8 GB GPU VRAM; 8B vereist 16+ GB GPU.

#### jina-embeddings-v3 (Jina AI)
- **Wat**: 570M parameters, XLM-RoBERTa-basis met task-specifieke LoRA-adapters.
- **Hosting**: Self-hosted én Jina API.
- **Dimensies**: 1024 default, MRL down to 32 (behoudt 92% retrieval bij 64 dims).
- **Max input**: 8192 tokens (RoPE).
- **NL-performance**: MTEB-NL **AvgT 62.7** — vergelijkbaar met BGE-M3.
- **Licentie**: **CC BY-NC 4.0 — niet-commercieel**. Voor productie via API of commerciële licentie. **Belangrijke disqualifier voor self-hosted commercial Druppie-deployment** ([jina-v3 announcement](https://jina.ai/news/jina-embeddings-v3-a-frontier-multilingual-embedding-model/)).

#### Cohere embed-v4
- **Wat**: Commerciële multilingual+multimodal (text + image), 2025.
- **Hosting**: **API-only** (ook via AWS Bedrock, Azure, Oracle).
- **Dimensies**: Matryoshka 256/512/1024/1536, native int8/binary quantization.
- **Max input**: **128K tokens** — grootste van alle commerciële embedding-modellen.
- **NL-performance**: Cohere is historisch leider op multilingual retrieval; v4 wordt consistent gerapporteerd als top voor 100+ talen. Geen MTEB-NL-score gepubliceerd.
- **Licentie/kosten**: API ~$0.10–$0.12 per 1M tokens.
- **Probleem voor Druppie**: API-only conflicteert met data-residency. Bedrock-deployment in EU-regio is een uitweg.

#### OpenAI text-embedding-3-large / -small
- **Hosting**: API-only.
- **Max input**: 8191 tokens.
- **NL-performance**: text-embedding-3-large is sterk op MTEB EN, maar **multiple 2026 sources rapporteren consistente underperformance op European languages incl. NL** ([PE Collective](https://pecollective.com/tools/best-embedding-models/)).
- **Disqualifier**: data-residency + zwakkere NL.

#### mxbai-embed-large, nomic-embed-text-v2
Beide effectief Engelstalig in benchmarks — **niet geschikt voor NL** ([Tiger Data](https://www.tigerdata.com/blog/finding-the-best-open-source-embedding-model-for-rag), [PE Collective](https://pecollective.com/tools/best-embedding-models/)).

### Trade-off-tabel

| Model | NL-perf (MTEB-NL AvgT) | Multilingual breedte | Dims | Max input | Self-host | GPU-eis | Licentie | Kosten |
|---|---|---|---|---|---|---|---|---|
| **Qwen3-Embedding-4B** | **69.2** | 100+ talen | MRL flex | 32K | Ja | ~8 GB VRAM | Apache 2.0 | Compute-only |
| multilingual-e5-large-instruct | 66.9 | ~94 talen | 1024 fixed | 512 | Ja | CPU mogelijk / 2 GB VRAM | MIT | Compute-only |
| **E5-NL-large** | SOTA non-instruct (>67 est.) | NL-only | 1024 | 512 | Ja | CPU/laag VRAM | MIT | Compute-only |
| BGE-M3 | 63.1 | 100+ talen | 1024 + sparse + ColBERT | 8192 | Ja | CPU/4 GB VRAM | MIT | Compute-only |
| jina-embeddings-v3 | 62.7 | 32 talen (NL inbegrepen) | 1024 MRL | 8192 | Ja, **niet-commercieel** | 4 GB VRAM | CC BY-NC 4.0 | API of commerciële licentie |
| Qwen3-Embedding-0.6B | 62.6 | 100+ talen | MRL flex | 32K | Ja | CPU OK | Apache 2.0 | Compute-only |
| Cohere embed-v4 | onbekend, sterk multilingual | 100+ talen | MRL 256–1536 | **128K** | Nee | n.v.t. | proprietary | $0.10–0.12/1M |
| OpenAI 3-large | zwak EU/NL | beperkt | MRL 256–3072 | 8191 | Nee | n.v.t. | proprietary | $0.13/1M |
| mxbai-embed-large | bijna nul cross-lingual | EN-only | 1024 | 512 | Ja | 2 GB VRAM | Apache 2.0 | Compute-only |
| nomic-embed-v2 | R@1<0.16 multilingual | EN-only feitelijk | 768 MRL | 8192 | Ja | CPU | Apache 2.0 | Compute-only |

### Decision-guide

**Selectiecriteria (in volgorde van gewicht voor de platform-default):**
1. **Brede multilingual coverage** — moet uit-de-doos werken voor minimaal NL en EN, bij voorkeur breder. Druppie-use-cases verschillen per project.
2. **Self-host-haalbaarheid** — moet kunnen draaien in een MCP-container zonder dure GPU-vereiste. Data-residency: API-only is een blocker tenzij EU-gehost en juridisch afgedekt.
3. **Permissieve licentie** — MIT of Apache 2.0. Non-commercial licenties zijn een blocker.
4. **Bewezen kwaliteit** — solide scores op multilingual MTEB en taal-specifieke benchmarks zoals MTEB-NL (om te bevestigen dat NL niet wegvalt).
5. **Ops-footprint** — geheugen en latency moeten voorspelbaar zijn.

**Platform-default: `multilingual-e5-large-instruct`** — sterke multilingual baseline (94 talen), MIT-licentie, CPU-haalbaar (~2 GB), en bewezen kwaliteit op zowel multilingual MTEB als MTEB-NL (66.9 AvgT). De 512-token-limiet is geen blocker voor RAG omdat chunking sowieso onder die grens valt.

**Upgrade-paden, alleen met expliciete trigger:**
- **Qwen3-Embedding-4B** als kwaliteit het zwaarste criterium is en je ≥8 GB GPU-budget hebt in een MCP-container. Apache 2.0, MTEB multilingual #1-rank, MRL, 32K context. Trigger: meetbare ondergrens op een use-case-specifieke gold-set die de default niet haalt.
- **Qwen3-Embedding-0.6B** als je nog steeds CPU-only wilt maar de extra coverage van Qwen-foundation wilt benutten. Apache 2.0, 32K context.
- **BGE-M3** als je hybrid retrieval centraal stelt en dense + sparse + ColBERT in één model wilt voor pipeline-eenvoud. MIT, 8K context. Iets lagere multilingual scores dan e5-instruct, maar architectuur-winst kan dat compenseren.
- **E5-NL** alleen voor projecten die expliciet aangeven dat de corpus NL-only is én blijft. Verlies multilingual = lock-in op één taal; ongeschikt als platform-default.

**Bij twijfel**: `multilingual-e5-large-instruct`. Bouw de pipeline **model-agnostisch** (stabiele content-hash chunk-IDs, embedding-generation achter een MCP-interface) zodat schuiven naar Qwen3-4B of een ander model later mogelijk is zonder breaking changes.

**Disqualifiers voor de platform-default:**
- OpenAI text-embedding-3-*: API-only + zwakker op niet-Engels Europese talen.
- mxbai-embed-large, nomic-embed-text-v2: effectief Engelstalig in benchmarks — geen multilingual default.
- jina-embeddings-v3: CC BY-NC 4.0 blokkeert commerciële self-host. Alleen via Jina-API/marketplace inzetbaar, en daarmee data-residency-blocker.
- Cohere embed-v4: API-only; bruikbaar via Bedrock EU-regio als data-residency afgedekt is, anders disqualifier.

---

## Vector-stores

### Vergelijking

#### pgvector (Postgres extension)
- **Wat**: Postgres-extensie (sinds 2021, v0.9 begin 2026). Vectors als kolomtype `vector`, met HNSW/IVFFlat/DiskANN indices.
- **Architectuur**: Geen extra service — onderdeel van bestaande Postgres-instance.
- **Hybrid search**: **Niet native end-to-end** — `tsvector` (Postgres FTS) combineren met vector-search via RRF/manual fusion (~100 regels Python). v0.9 voegt sparse vector support toe maar er is nog steeds geen high-quality BM25 in core Postgres. ParadeDB's `pg_search` extension is een serieuze poging ([ParadeDB Hybrid Search](https://www.paradedb.com/blog/hybrid-search-in-postgresql-the-missing-manual)).
- **Metadata-filter**: Volledig SQL — joins met andere tabellen, ACL via row-level security, transactionele consistentie. Sterke kant.
- **Schaling**: Verticaal (HNSW moet in RAM passen). **Performance degradeert merkbaar voorbij 10M vectors** — bij 50M vectors: 41 QPS vs Qdrant's 471 QPS @ 99% recall ([Layerbase](https://layerbase.com/blog/vector-databases-compared-2026), [CallSphere](https://callsphere.ai/blog/vector-database-benchmarks-2026-pgvector-qdrant-weaviate-milvus-lancedb)).
- **Ops**: Nul nieuwe service. Backups, replicatie, monitoring werken meteen.
- **Licentie**: PostgreSQL License.

#### Qdrant
- **Wat**: Rust-native standalone vector engine. Single-binary.
- **Architectuur**: Aparte service (REST + gRPC). Past goed in MCP-container pattern.
- **Hybrid search**: **Native server-side via Query API** (sinds v1.10). Dense + sparse (BM25 via FastEmbed of native sparse vectors) + miniCOIL + ColBERT-style late interaction, gefuseerd met RRF of DBSF. Multi-stage reranking is first-class ([Qdrant Hybrid Queries](https://qdrant.tech/documentation/search/hybrid-queries/)).
- **Metadata-filter**: **Filterable HNSW** — filters tijdens graph traversal, niet erna. Filtered queries @ 500K vectors p50 ~6ms vs pgvector ~25ms ([Markaicode pgvector vs qdrant](https://markaicode.com/vs/pgvector-vs-qdrant/)).
- **Schaling**: Verticaal sterk; horizontaal via sharding + replicas. Sub-10ms p95 op 10M+ vectors.
- **Ops**: Eén Rust-binary. **Sync-tax**: als Postgres je source-of-truth is, moet je outbox/CDC bouwen om vectors gesynchroniseerd te houden.
- **Licentie**: Apache 2.0.

#### Weaviate
- **Wat**: Open-source vector DB, Go-based runtime.
- **Hybrid search**: **Beste native hybrid search in de markt** — BM25 + dense + metadata filters in één query, modular vectorizer-modules embedden tekst inline.
- **Metadata-filter**: Sterk, met multi-tenancy (namespaces).
- **Ops**: Zwaarder dan Qdrant; ~16 GB RAM aanbevolen; GraphQL learning curve.
- **Licentie**: BSD-3 (core).

#### Milvus
- **Architectuur**: Drie deployment modes: Lite (embedded), Standalone (3 containers: Milvus + etcd + MinIO), Distributed (7–10 microservices op K8s).
- **Hybrid search**: Native dense + sparse hybrid sinds 2.4; integreert mooi met BGE-M3's sparse output.
- **Schaling**: **Designed voor miljarden vectors**. Storage Format V2 maakt 10B+ haalbaar op object storage.
- **Ops**: Standalone haalbaar voor één engineer; **Distributed vereist platform-engineering investering**. Break-even voor Distributed: ~50–100M vectors of >1M req/dag ([Zilliz deployment guide](https://zilliz.com/blog/choose-the-right-milvus-deployment-mode-ai-applications)).
- **Licentie**: Apache 2.0.

#### Chroma
- **Architectuur**: Embedded of standalone server. **2025 Rust rewrite** gaf 4× snellere writes/queries.
- **Hybrid search**: Beperkt — geen native BM25.
- **Schaling**: Goed tot ~1M vectors op single VPS; daarboven limieten. Geen multi-tenancy.
- **Beste fit**: prototyping. Productie-deployments migreren meestal naar Qdrant of pgvector.

#### LanceDB
- **Architectuur**: Embedded vector DB op Lance columnar storage format. Mindshare-groei 6.7% → 9.6% YoY in 2026.
- **Hybrid search**: Native full-text + vector + multi-modal.
- **Schaling**: Sterk op groot corpus met frequente updates.
- **Beste fit**: image+text pipelines, agent memory stores. Voor doc-heavy NL-RAG mid-tier.

### Trade-off-tabel

| Store | Hybrid-search native | Ops-complexiteit voor Druppie | Schaling | Metadata-filter | Volwassenheid | Licentie |
|---|---|---|---|---|---|---|
| **pgvector** | Manual (FTS + RRF) | **Nul** — al onderdeel van Druppie's Postgres | Tot ~10M vectors solide | Excellent (SQL joins, RLS) | Zeer hoog | PostgreSQL License |
| **Qdrant** | **Excellent** (BM25 + dense + miniCOIL + ColBERT in Query API) | Laag (1 binary, 1 container) + sync-tax met Postgres | Sub-10ms p95 @ 10M+; horizontaal | Excellent (filterable HNSW) | Hoog | Apache 2.0 |
| Weaviate | **Best in class** (BM25+dense+filters in 1 query) | Medium (16 GB RAM, GraphQL) | Horizontaal via sharding | Sterk + namespaces | Hoog | BSD-3 |
| Milvus | Native dense+sparse | Standalone laag / Distributed hoog (K8s + etcd + MinIO + Kafka) | Miljarden vectors | Sterk + partitions | Hoog | Apache 2.0 |
| Chroma | Beperkt | Zeer laag | Tot ~1M vectors | Basic | Medium | Apache 2.0 |
| LanceDB | Native FTS + vector + multimodal | Zeer laag (embedded) | Sterk op groot corpus met updates | Sterk | Groeiend, jonger | Apache 2.0 |

### Decision-guide

**Default voor Druppie: pgvector**, om de volgende evidence-based redenen:

1. **Postgres draait al** — pgvector toevoegen is een `CREATE EXTENSION`, géén nieuwe container, geen extra failure mode. Past in Druppie's normalisatie-conventie als gewone kolom.
2. **Schaal-realiteit van Druppie-RAG**: de meeste doc-heavy use-cases (kennisbanken, juridische zoek, compliance-search, klantcontact-Q&A, beleidsdocumenten) zitten tussen 10⁴ en 10⁶ chunks. **Ruim binnen pgvector's effectieve range (<10M vectors)**. Qdrant-voordelen materialiseren pas voorbij dat punt.
3. **Transactionele consistentie**: bij doc-upload schrijft Druppie metadata, ACL, en chunks tegelijk; pgvector laat dit in één transactie gebeuren. Met een dedicated store hebben we een sync-probleem dat outbox/CDC vereist.
4. **SQL voor permissies**: Druppie's domeinmodel is rijk (sessions, agents, approvals). Search-time filtering op user-roles, tenant, doc-status laat zich natuurlijk uitdrukken in SQL joins.
5. **Ops-budget**: Druppie is een platform, niet een vector-search SaaS. Elk extra service moet zichzelf rechtvaardigen.

**Wanneer afwijken van pgvector — schuif naar Qdrant** zodra:
- Filtered ANN p95 wordt een hard requirement (>25ms onacceptabel), bv. multi-tenant SaaS-modus.
- Corpus passeert 10M chunks.
- Hybrid search wordt centraal en de FTS-fusion in Postgres te brokkelig wordt.
- Je rerank/ColBERT/miniCOIL nodig hebt — Qdrant biedt dit native, pgvector niet.

**Schuif naar Weaviate** alleen als native hybrid-search-as-a-service de #1 driver wordt en multi-modal (text + image) nodig is.

**Schuif naar Milvus Distributed** alleen bij 100M+ vectors én een ops-team dat K8s/etcd/Kafka comfortabel runt.

**Chroma en LanceDB**: niet als default — Chroma voor prototypes, LanceDB voor toekomstige multi-modal use-cases.

**Architecturele richtlijn**: bouw de retrieval-laag in een MCP-server abstractie (`module-rag`) zodat de implementatie achter een stabiele interface zit. Default = pgvector; een tweede implementatie tegen Qdrant kan later. Stable chunk-IDs in Postgres als source-of-truth, zodat eventuele migratie naar Qdrant geen re-embedding-kost forceert behalve ANN-index opnieuw bouwen.

---

## Geavanceerde patronen

> Scope: alleen patronen die *bovenop* een werkende baseline-pipeline (chunking + hybrid retrieval + citaties) komen.
> Leidraad: platform-default is baseline + reranker. Alle andere geavanceerde patronen erbij alleen wanneer een aantoonbaar symptoom of use-case-eis dat rechtvaardigt.

### Re-ranking

Cross-encoder reranking is in 2026 zo dicht bij "standaard" als een geavanceerd patroon kan worden: lift van 10-25% op nDCG@10 voor een paar honderd ms latency en marginale kosten. De praktische vraag is niet *of* je een reranker neemt, maar *welke* en *hoe groot* je kandidatenset is.

#### Vergelijking

| Model | Type | Self-host | Lat. (100 docs, GPU) | Multilingual / NL | Praktische sterktes | Aandachtspunten |
|---|---|---|---|---|---|---|
| **BGE-reranker-v2-m3** (BAAI, 0.6B) | Cross-encoder | Ja, Apache 2.0 | 50-150 ms | 100+ talen, getraind op MIRACL. Geen NL-specifieke benchmark beschikbaar; impliciet "redelijk" via mMARCO/MIRACL. | Gratis, lage drempel, brede coverage. *De facto* open-source baseline. | Voor cross-lingual queries 5-10 nDCG-punten onder Cohere. |
| **Cohere Rerank 3.5 / v4.0 Pro** | API (cross-encoder) | Nee (alleen via Bedrock/Azure/OCI privé) | 80-150 ms p50, 200+ p99 | 100+ talen; *industry-leading* op niet-Engels. | Beste multilingual kwaliteit-per-call. ~$2/1k searches of $2/1M tokens. | Vendor lock-in, data-egress. Voor strikt data-soevereine deployments een blocker. |
| **Jina-reranker-v3** (0.6B listwise) | Cross-encoder + listwise | Ja, maar CC-BY-NC 4.0 (commercieel = Jina API/AWS/Azure marketplace) | <200 ms p95 | 18 talen MIRACL 66.5 nDCG; sterk multilingual. 131K context. | Beste open-gewichten multilingual (61.94 BEIR). | Non-commercial license — voor on-prem productie moet je betalen of v2 nemen. |
| **mxbai-rerank-large-v2** (Mixedbread, 1.5B) | Cross-encoder (Qwen-2.5-based) | Ja, Apache 2.0 | 150-400 ms (1.5B groter) | 100+ talen, 8k context (compatible tot 32k) | Open + commercieel + lange context + 57.49 BEIR. Sterk voor JSON/code/tool-routing. | Groter model = meer GPU. Voor pure NL-tekst is BGE-v2-m3 efficiënter. |
| **Sentence-transformers cross-encoders** (bv. `ms-marco-MiniLM-L-12-v2`) | Cross-encoder | Ja, Apache 2.0 | 20-60 ms (CPU haalbaar) | Vooral EN. Multilingual varianten zwakker dan BGE. | Klein, snel, CPU-vriendelijk. | Te zwak voor multilingual NL-corpora. |

Bronnen: [Local AI Master 2026 reranker guide](https://localaimaster.com/blog/reranking-cross-encoders-guide), [Cohere docs](https://docs.cohere.com/docs/rerank), [Agentset leaderboard](https://agentset.ai/rerankers), [Jina v2 model card](https://jina.ai/models/jina-reranker-v2-base-multilingual/), [BSWEN 2026 comparison](https://docs.bswen.com/blog/2026-02-25-best-reranker-models/).

#### Trade-off-tabel

| Dimensie | Geen rerank | BGE-v2-m3 | Cohere 3.5 | Jina v3 (gehost / paid) | mxbai-large-v2 |
|---|---|---|---|---|---|
| Kwaliteits-lift t.o.v. hybride retrieval alleen | baseline | +10-15% nDCG@10 | +15-25% nDCG@10 | +15-25% nDCG@10 | +12-20% nDCG@10 |
| Extra latency p95 | 0 | 50-150 ms | 100-200 ms (network) | 100-200 ms | 150-400 ms |
| Kosten per 1k queries (100 docs) | 0 | GPU-uur ($) | ~$2 | ~$2 | GPU-uur ($) |
| Data-soevereiniteit | n.v.t. | volledig on-prem | nee (API) | nee (commercieel) | volledig on-prem |
| NL-kwaliteit | baseline | redelijk | best | best | redelijk-goed |

#### Decision-guide

**Voeg een reranker toe wanneer:**
- Top-k (k=5..10) bevat zichtbaar irrelevante chunks die de generator afleiden.
- Faithfulness/citatie-precisie laag is terwijl recall@20 hoog is.
- Hybride scoring (BM25 + dense) niet eenduidig is en je een merge-strategie nodig hebt.

**Doe het niet wanneer:**
- p95-latency-budget <500 ms is en je geen GPU hebt.
- Recall@10 al >85% is op je gold-set.
- Corpus is zo klein (<1000 chunks) dat top-20 in de prompt past.

**Kandidaten N vóór rerank (vuistregel):**
- Standaard: N=50, rerank naar top-5..8.
- Lange documenten met fijnkorrelige zoekvragen: N=80-100 om zeldzame paragrafen te dekken.
- Latency-kritisch (chatbot <2s): N=30, rerank naar top-3.

**Platform-default:**
- **BGE-reranker-v2-m3 self-hosted** als startpunt: gratis, soeverein, brede taaldekking (Apache 2.0).
- Upgrade-pad: switch naar Cohere of Jina-v3 zodra een use-case-specifieke gold-set ≥5 nDCG-punten verschil laat zien én data-egress acceptabel is (Cohere via Bedrock EU is hier de practische escape-hatch).
- Vermijd mxbai-large-v2 als default — 3× GPU-kosten zelden gerechtvaardigd voor de mediane use-case.

### Query-rewriting / -uitbreiding

Query-transformaties verbergen één centrale assumptie: de gebruiker formuleert zijn vraag nooit zoals het document is geschreven. Vooral acuut bij domeinen waar gebruikers in alledaagse taal vragen stellen aan formeel of technisch materiaal (beleid, juridisch, regelgeving, productdocumentatie).

#### Vergelijking

| Patroon | Wat het doet | Extra calls / latency | Kwaliteit-uplift | Wanneer |
|---|---|---|---|---|
| **HyDE** (Hypothetical Document Embeddings) | LLM genereert een fictief "antwoord-document"; dat embed je en gebruik je voor retrieval i.p.v. de query. | +1 LLM-call (~500-1500 ms) + 1 embedding-call | Verbetert *semantische alignment* tussen korte query en lange documenten, vooral op korte/vage queries. | Korte, vage vraag, groot stijlverschil tussen vraag en doc. |
| **Multi-query** | LLM genereert N (typ. 3-5) varianten van de vraag, elke wordt apart geretrieved; resultaten samengevoegd (RRF/dedup). | +1 LLM-call + N parallelle retrievals | +5-15% recall@k bij ambigue queries. | Ambigue intent, meerdere geldige interpretaties. |
| **Query expansion** (synoniemen, vertaling) | Voeg termen toe (synoniemen in corpus-taal, cross-language termen bij multilingual corpora, domein-jargon). | +1 LLM-call (kan gecached) | +3-10% recall op BM25-leg; vooral bij domein-jargon. | Domein-specifiek vocabulair, of multilingual corpus waarbij gebruiker en doc een andere taal hebben. |
| **Query decomposition** | LLM splitst complexe meervragige vraag in sub-vragen; elke sub-vraag retrievet apart; antwoorden gesynthetiseerd. | +1 LLM-call + N retrievals + N (klein) generatiecalls | Grote uplift op multi-hop. ACL 2026: +35% document-precision, +15% α-nDCG. | Conjuncties of meerdere aspecten. |
| **Step-back prompting** | LLM genereert abstractere vraag; retrieve daarop voor *achtergrond*; combineer met originele retrieval. | +1 LLM-call + 1 extra retrieval | Subtiele uplift, sterk bij beleids-Q&A. | Heel specifieke vraag zonder breder kader. |

Bronnen: [LangChain Query Transformations](https://blog.langchain.com/query-transformations/), [Medium - Retrieval is the bottleneck](https://medium.com/@mudassar.hakim/retrieval-is-the-bottleneck-hyde-query-expansion-and-multi-query-rag-explained-for-production-c1842bed7f8a), [ACL Anthology - Query Decomposition for RAG](https://aclanthology.org/2026.eacl-long.322/).

#### Trade-off-tabel

| Patroon | Extra latency p95 | Extra LLM-tokens | Recall-impact | Faithfulness-impact | Risico |
|---|---|---|---|---|---|
| HyDE | +0.5-1.5 s | +200-500 (gen) | neutraal/+ | + (betere context) | LLM hallucineert "verkeerd" doc → retrievet langs onderwerp heen |
| Multi-query | +1-2 s | +150-300 (gen) | + 5-15% | + | duplicate context, prompt-bloat |
| Query expansion | +0.3-0.8 s | +50-150 | + 3-10% | neutraal | irrelevante synoniemen → drift |
| Decomposition | +2-5 s | +300-800 | + 10-25% bij multi-hop | + significant | foute decompositie versterkt fout in alle hops |
| Step-back | +0.5-1 s | +100-200 | + bij specifieke vragen | + (betere context) | step-back te abstract → ruis |

#### Decision-guide

**Platform-default:** start met **query expansion** (cheap, generieke domein-glossary per project, weinig risico) + **decomposition** alleen wanneer een classifier meervragigheid ziet. **HyDE** alleen als baseline-retrieval faalt op korte stijlverschil-queries. **Step-back** als optionele toevoeging in een agentic loop, niet als default.

**Selectie-heuristiek (kan in een lichte classifier-node):**
- Query < 5 woorden, geen meervragigheid → HyDE
- Query bevat conjuncties of vergelijkingsmarkers ("en", "ook", "verschil tussen", "hoe verhoudt zich") → Decomposition
- Domein-jargon gedetecteerd (NER-hit op project-glossary) → Query expansion
- Query gebruikt specifieke artikel-/clausule-verwijzing → Step-back
- Anders → geen transformatie

**Anti-patronen:**
- Multi-query + decomposition tegelijk = N×M retrievals, latency explodeert.
- HyDE op queries die *al* document-stijl gebruiken: verspilling.
- Decomposition met >4 sub-vragen: cap op N=3.

### GraphRAG

Knowledge-graph RAG was in 2024-25 een hype; in 2026 is de pragmatische consensus dat het een gespecialiseerd patroon is, niet een vervanger van vector-RAG.

#### Vergelijking

| Aanpak | Wat het is | Indexing-kosten (500 pagina's) | Query-kosten | Maturity | Sterkte |
|---|---|---|---|---|---|
| **Microsoft GraphRAG** | LLM extraheert entities + relations → bouwt graaf → Leiden community-detectie → community-summaries. Local search (entity-buurt) + Global search (community map-reduce). | $50-200, 45+ min, GPT-4-tier | Global search: duur (map-reduce over communities); Local: vergelijkbaar met vector-RAG. | Mature open-source (31.6k GitHub stars), Azure-ecosysteem. | Holistische "wat zijn de hoofdthema's over de hele corpus" vragen. |
| **LazyGraphRAG** (Microsoft) | Skipt vooraf-extractie; bouwt graaf lazily op query-tijd. | ≈ vector-RAG (0.1% van GraphRAG) | 700× lager dan global GraphRAG bij vergelijkbare global-query-kwaliteit. | Nieuwer, minder battle-tested. | Globale vragen zonder de upfront cost. |
| **LightRAG** | Lichtgewicht GraphRAG: simpelere entity-extractie, platte graaf, dual-mode (graph + vector). | ~$0.50, 3 min. Incrementeel updatebaar. | Snel, vergelijkbaar met vector-RAG. | Actief (14k stars). | 70-90% van GraphRAG-kwaliteit op multi-entity-vragen tegen 1/100e kost; werkt bij continu wijzigende corpora. |
| **Generieke KG retrieval-augmented patterns** (Neo4j, NebulaGraph + custom entity-extraction) | DIY: eigen ontologie, vul de graaf, doe Cypher/Gremlin-queries vanuit natural language (LLM → query). | Hoog (engineering-tijd) | Laag per query. | Mature stack, maar custom ontologie = veel werk. | Wanneer je *al* een gedefinieerde domein-ontologie hebt (productcatalogus, bestuurlijk register, organigram, klantmodel). |

Bronnen: [Microsoft Research: LazyGraphRAG](https://www.microsoft.com/en-us/research/blog/lazygraphrag-setting-a-new-standard-for-quality-and-cost/), [Paperclipped 2026 GraphRAG Production Guide](https://www.paperclipped.de/en/blog/graph-rag-production/), [Tongbing Medium - GraphRAG buyer's guide](https://medium.com/@tongbing00/graphrag-in-2026-a-practical-buyers-guide-to-knowledge-graph-augmented-rag-43e5e72d522d), [arXiv: When to use Graphs in RAG](https://arxiv.org/html/2506.05690v3).

#### Trade-off-tabel

| Dimensie | Vector-RAG (baseline) | LightRAG | LazyGraphRAG | Microsoft GraphRAG |
|---|---|---|---|---|
| Indexing-kosten relatief | 1× | 1× | 1× | 50-200× |
| Indexing-tijd (500 pp) | minuten | ~3 min | ~minuten | 45+ min |
| Incremental update | ja | ja, fijn | ja | moeilijk (re-clustering communities) |
| Local entity-vraag | matig | goed | goed | goed |
| Global synthesis-vraag | slecht | matig | goed | best |
| Multi-hop tussen entiteiten | matig | goed | goed | best |
| Engineering-overhead | laag | midden | midden | hoog |

#### Decision-guide

**Voeg GraphRAG toe wanneer:**
- Use-case heeft duidelijk **multi-entity, multi-hop vragen** ("welke partij heeft beslissingen goedgekeurd die raken aan onderwerp X over alle documenten?").
- Je wilt **globale synthese** ("wat zijn de terugkerende thema's in de hele corpus?") — daar is vector-RAG slecht in.
- Het corpus heeft een **duidelijke ontologie** (personen, organisaties, besluiten, domeinen) met expliciete relaties.

**Doe het niet wanneer:**
- 80% van de queries is "single-fact lookup".
- Het corpus verandert dagelijks (volledige GraphRAG is dan dure herindexering).
- Het team heeft nog geen werkende vector-RAG-baseline.

**Platform-default:**
- Begin met vector-RAG + reranker. GraphRAG is **niet default**.
- Als een use-case-vraagprofiel ≥30% "synthesis/multi-hop" queries laat zien, **introduceer LightRAG** als parallelle retriever in een Adaptive RAG-router. Niet als vervanger.
- Volledig Microsoft GraphRAG alleen bij expliciete corpus-brede synthese-projecten met budget voor herindex-cycli.

### Agentic RAG

Agentic RAG = LLM beslist *zelf* welk retrieval-pad te kiezen, valideert het resultaat, en kan loops draaien. Voor 80% van de queries is dit verspilling; voor de moeilijke 20% is het het verschil tussen "hallucineert" en "antwoordt".

#### Vergelijking

| Patroon | Wat het is | Latency | Wanneer | Wanneer niet |
|---|---|---|---|---|
| **Adaptive RAG** (router) | Classifier (klein LLM of fine-tuned model) classificeert de query: skip retrieval / vector / graph / web. Per pad een andere pipeline. | +50-200 ms voor classifier. | Heterogene query-load: simpele lookups gaan snel, synthesis-vragen krijgen het zwaardere pad. | Homogene workload. |
| **Self-RAG / Corrective RAG (CRAG)** | LLM-as-judge beoordeelt of retrieval relevant is; zo niet → query-rewrite + retry, of fall-back naar web/andere bron. | +1 LLM-call per iteratie (typ. 1-2 iters). +1-3 s p95. | Domein waar irrelevante retrieval frequent voorkomt (vage queries, domein-jargon-gap). | Latency-kritisch UI. |
| **Plan-and-execute** (PlanRAG, ReSP, PAR-RAG) | LLM maakt retrieval-plan (sub-doelen + volgorde), executeert stap-voor-stap, kan herplannen. | +2-8 s. | Echt complexe research-vragen. | Dagelijkse Q&A — overkill. |
| **Multi-hop retrieval** (ReAct, IRCoT, RT-RAG) | LLM interleaved thought ↔ retrieve ↔ thought. Hop N gebruikt antwoord-context van hop N-1 als query-bron. | +2-6 s (per hop ~1-2 s). | Vragen waar antwoord pas zichtbaar wordt na een keten. | Single-hop factual queries. Foutpropagatie risico. |

Bronnen: [LangChain agentic RAG docs](https://docs.langchain.com/oss/python/langgraph/agentic-rag), [arXiv: ReSP (2407.13101)](https://arxiv.org/abs/2407.13101), [arXiv: PAR-RAG (2504.16787)](https://arxiv.org/pdf/2504.16787), [arXiv: RT-RAG (2601.11255)](https://arxiv.org/html/2601.11255v1).

#### Trade-off-tabel

| Patroon | Extra p95-latency | Extra LLM-calls (typisch) | Kwaliteit-impact | Foutmodus |
|---|---|---|---|---|
| Adaptive RAG (router only) | +100-300 ms | +1 (classifier) | +5-10% gemiddeld; voorkomt verspilling op simpele queries | Mis-classificatie → verkeerd pad |
| Corrective / Self-RAG (1 retry) | +1.5-3 s | +2-3 | +10-20% op vage queries | Oneindige retry-loop zonder cap |
| Plan-and-execute | +3-8 s | +5-10 | +15-30% op complex; -% op simpel (overkill) | Slechte plan = slechte antwoord; hoge kost |
| Multi-hop (3 hops) | +3-6 s | +3-6 retrievals + judge-calls | Significant op multi-hop; nul op single-hop | Foutpropagatie tussen hops |

#### Decision-guide

**Stappenplan voor de platform-stack:**
1. **Begin niet met agentic.** Eerst baseline + reranker werkend krijgen.
2. **Eerste agentic-stap = Adaptive Router.** Een 3-4-klasses classifier (factual lookup / synthesis / multi-hop / conversational) bovenop bestaande pipelines.
3. **Tweede stap = Self-RAG / Corrective grading** in het "synthesis" en "multi-hop" pad. *Niet* op factual lookup.
4. **Derde stap (alleen bij bewezen behoefte) = Plan-and-execute** voor echte research-vragen.
5. **Multi-hop apart**: alleen als de router de query als multi-hop tagt, cap op N=3 met circuit-breaker.

**Verplichte controls bij agentic:**
- Hard cap op iteraties (max 3 retries Self-RAG, max 3 hops multi-hop, max 4 sub-doelen plan-and-execute).
- Token-budget per query (bv. 50k input-tokens hard limit).
- Latency-circuit-breaker (kill na 10 s, fall-back naar baseline-antwoord).
- LangSmith-tracing met `iteration_count`, `retrieval_round`, `token_budget_used` per node.

**Wanneer agentic geen ROI heeft:**
- Latency-eis <2 s p95.
- Corpus is klein en queries homogeen.
- Budget hard constraint — agentic vermenigvuldigt LLM-kosten 3-10×.

---

## RAG-specifieke NFRs

NFRs voor RAG zitten niet bij "uptime" alleen; de meeste kwaliteitsfaalmodi zijn *invisible to end-to-end metrics*. Een TD voor een RAG-systeem moet NFRs op drie lagen specificeren: **retrieval**, **generation**, en **operationele pipeline**.

### Behandelde NFRs

#### 1. Retrieval-latency
Tijd van query-binnenkomst tot top-k chunks beschikbaar (excl. generatie). Tracing op de retriever-call; P50/P95/P99 op een gold-set, minimaal weekly. Reranker is vaak de p99-veroorzaker — apart meten ([Future AGI](https://futureagi.com/blog/evaluating-cohere-rerank-rag-2026/)).

#### 2. Relevantie (Recall@k, MRR, nDCG, Hit-rate)
- **Recall@k**: hoe vaak verschijnt een relevant chunk in top-k.
- **MRR**: hoe snel komt het eerste relevante chunk (single-answer).
- **nDCG@k**: ranking-kwaliteit met graded relevance (multi-relevant).
- **Hit-rate**: minstens één relevant in top-k — debug-metric.

Gold-set van 100-300 queries in de doel-taal met human-labeled relevante chunk-IDs, per use-case. RAGAS of DeepEval; faal bij regressie. Synthetic eval-set kan starter zijn, SME-validation vereist ([CallSphere](https://callsphere.ai/blog/rag-evaluation-frameworks-2026-ragas-trulens-deepeval)).

Defaults: Recall@5 ≥ 80% voor FAQ-stijl; Recall@10 ≥ 75% voor lange documenten. MRR ≥ 0.7 voor single-fact. nDCG@5 ≥ 0.75 met reranker actief.

#### 3. Citatie-nauwkeurigheid (claim-to-source matching, hallucination rate)
Per atomaire claim: wordt deze ondersteund door de geciteerde bron? RAGAS `faithfulness`, RAGChecker, Google's grounding-check API; LLM-as-judge plus sample-based human audits (≥30 antwoorden/week). **Onmisbaar voor regulated/high-stakes domeinen** (bestuurlijk, juridisch, compliance, medisch, financieel): "fake citations" zijn daar het grootste reputatie- en juridische risico. Defaults: Faithfulness ≥ 0.85 algemeen; ≥ 0.90 voor regulated ([Future AGI](https://futureagi.com/blogs/rag-evaluation-metrics-2025), [Medium - Fake Citations](https://medium.com/@Nexumo_/rag-grounding-11-tests-that-expose-fake-citations-30d84140831a)).

#### 4. Freshness
Tijd tussen mutatie aan bron en zichtbaarheid in index. Lifecycle-tag per document; monitor op `now() - source_updated_at > SLA`. Tier content per decay-rate. **Named owner per content-domein** is een organisatorische NFR; zonder eigenaar zijn freshness-alerts wensdenkers ([TianPan](https://tianpan.co/blog/2026-04-17-enterprise-rag-knowledge-base-governance), [RAGAboutIt](https://ragaboutit.com/the-rag-freshness-paradox-why-your-enterprise-agents-are-making-decisions-on-yesterdays-data/)). Defaults: high-decay <1h, medium <24h, low <7 dagen.

#### 5. Index-grootte / -kosten
Cost-attribution per node in LangSmith; aggregate cost-per-query als KPI; alert bij regressie >20% week-over-week. Voor mid-size workloads (10k queries/maand): <$50/maand totaal LLM+rerank haalbaar met self-hosted BGE + paid rerank alleen voor moeilijke queries.

#### 6. End-to-end latency (retrieval + generation)
Time-to-first-token (TTFT) en time-to-complete (TTC) afzonderlijk; P50/P95/P99. Defaults: Simple RAG P95 <2s; Agentic RAG P95 <8s; research-stijl synthesis P95 <5s acceptabel mits TTFT <1.5s zodat user feedback krijgt.

#### 7. Beschikbaarheid van de retrieval-pipeline
Vector-store health-checks + actief synthetisch-query monitoring; ingest-SLA; reranker-fallback bij API-failure. Defaults: 99.5% interactief / 99.9% high-stakes productie. **Degraded-mode-eis**: bij reranker-failure draaien zonder rerank; bij vector-store-partial-failure duidelijk error, niet stil-incomplete antwoord.

### Default-NFR-tabel

> Plak deze direct als TR-xx in een TD. Pas targets aan per archetype:
> - **Interactief / low-stakes (LS)**: chatbot, FAQ, snelle Q&A.
> - **Interactief / high-stakes (HS)**: bestuurlijk advies, juridisch, compliance, klantcontact in regulated domeinen.
> - **Batch / asynchroon (B)**: research-summaries, nightly digest.

| TR | NFR | Meet-methode | Target LS-interactief | Target HS-interactief | Target Batch |
|---|---|---|---|---|---|
| TR-RAG-01 | Retrieval-latency P95 | Tracing op retriever-call | <500 ms | <800 ms | <5 s |
| TR-RAG-02 | Retrieval-latency P99 | Tracing | <1 s | <1.5 s | <10 s |
| TR-RAG-03 | Recall@10 op gold-set | RAGAS / handmatig | ≥75% | ≥85% | ≥90% |
| TR-RAG-04 | nDCG@5 op gold-set | RAGAS / handmatig | ≥0.70 | ≥0.80 | ≥0.85 |
| TR-RAG-05 | MRR (single-answer queries) | RAGAS | ≥0.65 | ≥0.75 | ≥0.80 |
| TR-RAG-06 | Faithfulness (claim support) | RAGAS / DeepEval | ≥0.80 | ≥0.90 | ≥0.92 |
| TR-RAG-07 | Citation precision (geciteerde bron ondersteunt claim) | Human audit + LLM-judge | ≥0.85 | ≥0.95 | ≥0.95 |
| TR-RAG-08 | Hallucination-rate (claims niet in bron) | RAGAS faithfulness inverse | ≤10% | ≤3% | ≤3% |
| TR-RAG-09 | Freshness SLA - high-decay docs | `now() - source_updated_at` monitor | <1 uur | <15 min | <1 uur |
| TR-RAG-10 | Freshness SLA - medium-decay (vastgestelde documenten, beleid) | idem | <24 uur | <4 uur | <24 uur |
| TR-RAG-11 | Freshness SLA - low-decay (historisch) | idem | <7 dagen | <7 dagen | <30 dagen |
| TR-RAG-12 | Named content owner per domein | Governance audit | verplicht | verplicht | verplicht |
| TR-RAG-13 | End-to-end latency P95 (TTC) | Distributed tracing | <2 s | <5 s | <30 s |
| TR-RAG-14 | Time-to-first-token P95 | Streaming-tracing | <800 ms | <1.5 s | n.v.t. |
| TR-RAG-15 | Retrieval-pipeline uptime | Synthetic monitoring | 99.5% | 99.9% | 99.5% |
| TR-RAG-16 | Degraded-mode bij reranker-failure | Failover-test (chaos) | functioneel zonder rerank | functioneel zonder rerank, met user-warning | n.v.t. |
| TR-RAG-17 | Cost per 1k queries | Cost-attribution per node | <$5 | <$15 | <$2 |
| TR-RAG-18 | Index-update SLA (ingest → searchable) | Event-tracing | <30 min | <5 min | <1 uur |
| TR-RAG-19 | CI-gate op faithfulness en latency regressies | DeepEval in PR-pipeline | verplicht | verplicht | verplicht |
| TR-RAG-20 | Gold-set onderhoud (weekly refresh, ≥100 queries) | Process | verplicht | verplicht (≥300 queries) | aanbevolen |
| TR-RAG-21 | PII / classificatie-tagging vóór indexing | Pipeline-gate | verplicht | verplicht | verplicht |
| TR-RAG-22 | Lineage per chunk (`source_id`, `version`, `ingested_at`) | Schema-validatie | verplicht | verplicht | verplicht |

---

## Eindaanbeveling

RAG wordt in Druppie aangeboden als **generiek platform-bouwblok** achter de `module-rag` MCP-interface. De keuzes hieronder zijn de platform-defaults — geldig voor elke doc-heavy use-case ongeacht taal of domein. Per project kan een architect daarvan afwijken, maar alleen met een expliciete trigger uit de decision-guides (corpus-grootte, query-type, latency-budget, taal-mix, stakes). Doel: één goed gefundamenteerd bouwblok dat in 80% van de use-cases out-of-the-box past, en in de overige 20% met een gerichte upgrade ook.

### Platform-default-stack

| Laag | Default | Trigger om af te wijken |
|---|---|---|
| Chunking | Recursive 512-token (tiktoken-encoder), 10–20% overlap | Upgrade naar parent-document/hierarchical zodra citaten te smal/breed worden; voeg late chunking toe bij anafoor-zware tekst |
| Retrieval | Hybrid (BM25 + dense) met RRF k=60 | Pure-vector alleen tijdelijk; ColBERT bij gemeten gat op out-of-domain queries |
| BM25-analyzer | Postgres `to_tsvector('<corpus-taal>', ...)` per veld | Multilingual analyzer voor mixed-language corpora; verplicht per taal, niet één globale instelling |
| Metadata-filter | SQL-joins op `doc_type`, `datum`, `status`, `tenant`, `acl` | Naar Qdrant in-graph filtering zodra p95 op filtered ANN hard requirement wordt |
| Embedding | `multilingual-e5-large-instruct` (MIT, ~2 GB, CPU haalbaar, brede multilingual coverage) | Qwen3-Embedding-4B bij ≥8 GB GPU-budget en kwaliteits-eis; BGE-M3 bij hybrid-met-één-model voorkeur |
| Vector-store | **pgvector** (al onderdeel van de Postgres-stack — geen extra service) | Qdrant bij >10M chunks, hard p95-eis op filtered ANN, of hybrid wordt centraal genoeg dat manual RRF te brokkelig wordt |
| Re-ranking | BGE-reranker-v2-m3 self-hosted (Apache 2.0) | Cohere Rerank (Bedrock EU) zodra use-case-gold-set ≥5 nDCG-punten verschil laat zien |
| Query-transformatie | Query expansion (cheap, project-glossary) + classifier-gated decomposition | HyDE bij korte/vage queries met stijlverschil; step-back in agentic-loop |
| GraphRAG | **Niet default** | LightRAG als parallelle retriever in Adaptive Router zodra ≥30% van use-case-queries multi-entity/synthesis blijkt |
| Agentic loop | **Niet default** — Adaptive Router als enige eerste agentic-stap | Self-RAG/CRAG in synthesis-pad bij bewezen vage-query-probleem; plan-and-execute alleen voor research-vragen |
| Citaties | Content-hash chunk-IDs + page/paragraph metadata + parent-section-titel; footnote-style in formele output + anchor-tags voor UI | Sentence-level span-tracking voor juridische/compliance-precisie (Claude Citations API of post-hoc matching) |
| NFRs | TR-RAG-01 t/m TR-RAG-22, targets per archetype (LS / HS / Batch) | Targets per use-case afstemmen; archetype-keuze (LS vs HS vs B) bepaalt de drempel |

### Pragmatische bouwvolgorde

1. **Foundation**: `module-rag` MCP-interface, pgvector-schema, `multilingual-e5-large-instruct`-embedding (via een eigen MCP-server of `module-llm`-uitbreiding), basis-tools (`index_documents`, `search`, `get_chunk`, `delete_index`, `list_indices`).
2. **Productie-kwaliteit**: taal-specifieke BM25-kolom(men), hybrid search met RRF, metadata-filtering, content-hash chunk-IDs, parent-section-titel.
3. **Kwaliteits-vangnet**: BGE-reranker-v2-m3, faithfulness-CI-gate (RAGAS in PR-pipeline), per-use-case gold-set, footnote-citaties in output.
4. **Slim wanneer nodig**: parent-document-chunking voor lange gestructureerde documenten, late chunking als anaforen haperen, query expansion + decomposition gated door classifier.
5. **Alleen bij bewezen behoefte**: Adaptive Router, LightRAG-parallel, Self-RAG in synthesis-pad, escape-hatch naar Qdrant.

### Validatie-scenario's

De keuzes hierboven worden in Story A's e2e-test en Story B gevalideerd op minimaal:
- **HDSR-notas** (Nederlandstalig, lange gestructureerde documenten, bestuurlijke stakes, harde citatie-eis) — als smoke-test die meerdere lastige assen tegelijk raakt.
- Aanvullende scenario's per use-case wanneer een project `module-rag` gaat consumeren.

### Open vraagstukken voor MODULE_SPEC

1. **Embedding-server-plaatsing**: wordt de embedding-call een eigen MCP-server (`module-embedding`), een tool in `module-llm`, of een directe library-call binnen `module-rag`? Heeft directe impact op het MODULE_SPEC. Voorstel: aparte tool-groep in `module-llm` zodat embedding én generation onder hetzelfde model-/resource-beheer vallen; `module-rag` consumeert via MCP.
2. **Tenant- en index-isolatie**: support voor logische isolatie via `tenant_id`-filter binnen één pgvector-tabel, of mogelijkheid voor fysiek gescheiden indexen per klant/project? Beïnvloedt MODULE_SPEC schema en TR-RAG-21 (PII/classificatie).
3. **Document-pre-processing**: PDF/Word/HTML → tekst + page/section-metadata behoort dit tot `module-rag` (één tool indexeert "ruw document") of valt het buiten de module (caller extract zelf en stuurt structured text)? Eerste = makkelijker voor app-bouwers; tweede = simpelere module met cleaner contract.
4. **Re-ranker-plaatsing**: in `module-rag` ingebakken (default-aan) of als losse `module-reranker` zodat verschillende rerankers per use-case gekozen kunnen worden? Voorstel: in `module-rag` met config-toggle voor v1, losse module als v2 wanneer meerdere rerankers nodig blijken.
5. **Module-naam-bevestiging**: `module-rag` is gekozen i.p.v. `module-vectorstore` omdat de architect in "RAG"-termen denkt. Tool-lijst (index_documents / search / get_chunk / delete_index / list_indices) maakt de scope duidelijk — als de naam bezwaar oproept (te belovend qua "Generation"), is dat nu het moment om te corrigeren.

---

## Bronnen

### Chunking, Retrieval & Citaties
- [Evaluating RAG Chunking Strategies in 2026 - FutureAGI](https://futureagi.com/blog/evaluating-rag-chunking-strategies-2026/)
- [Best Chunking Strategies for RAG (and LLMs) in 2026 - Firecrawl](https://www.firecrawl.dev/blog/best-chunking-strategies-rag)
- [RAG Chunking Strategies: A 2026 Retrieval Playbook - Digital Applied](https://www.digitalapplied.com/blog/rag-chunking-strategies-2026-retrieval-quality-playbook)
- [Hybrid Search: BM25, Vector & Reranking Reference 2026 - Digital Applied](https://www.digitalapplied.com/blog/hybrid-search-bm25-vector-reranking-reference-2026)
- [Hybrid Search Scoring (RRF) - Microsoft Azure AI Search](https://learn.microsoft.com/en-us/azure/search/hybrid-search-ranking)
- [Late Chunking in Long-Context Embedding Models - Jina](https://jina.ai/news/late-chunking-in-long-context-embedding-models/)
- [Late Chunking - Weaviate](https://weaviate.io/blog/late-chunking)
- [Parent Document Retrieval with MongoDB and LangChain](https://www.mongodb.com/docs/atlas/ai-integrations/langchain/parent-document-retrieval/)
- [Hierarchical Re-ranker Retriever (HRR) - arXiv](https://arxiv.org/pdf/2503.02401)
- [ColBERTv2: Effective and Efficient Retrieval via Lightweight Late Interaction - arXiv](https://arxiv.org/pdf/2112.01488)
- [A Complete Guide to Filtering in Vector Search - Qdrant](https://qdrant.tech/articles/vector-search-filtering/)
- [Citation-Aware RAG - Tensorlake](https://www.tensorlake.ai/blog/rag-citations)
- [Citations - Claude API Docs](https://platform.claude.com/docs/en/build-with-claude/citations)
- [How to Make My RAG Agent Cite Sources Correctly - Particula](https://particula.tech/blog/fix-rag-citations)
- [How LLMs and RAG Systems Retrieve, Rank, and Cite Content - Visively](https://visively.com/kb/ai/llm-rag-retrieval-ranking)
- [spaCy Dutch Models](https://spacy.io/models/nl/)
- [Frog - Dutch NLP Toolkit](http://languagemachines.github.io/frog/)

### Embedding-modellen & Vector-stores
- [MTEB-NL and E5-NL: Embedding Benchmark and Models for Dutch (arXiv 2509.12340)](https://arxiv.org/abs/2509.12340)
- [Awesome Agents MTEB March 2026 Leaderboard](https://awesomeagents.ai/leaderboards/embedding-model-leaderboard-mteb-march-2026/)
- [PE Collective: Best Embedding Models 2026](https://pecollective.com/tools/best-embedding-models/)
- [BAAI/bge-m3 HuggingFace](https://huggingface.co/BAAI/bge-m3)
- [Qwen3 Embedding blog (Alibaba)](https://qwenlm.github.io/blog/qwen3-embedding/)
- [Simon Willison on Qwen3 Embedding](https://simonwillison.net/2025/Jun/8/qwen3-embedding/)
- [Jina-embeddings-v3 announcement](https://jina.ai/news/jina-embeddings-v3-a-frontier-multilingual-embedding-model/)
- [Cohere Embed v4 (Oracle docs)](https://docs.oracle.com/en-us/iaas/Content/generative-ai/cohere-embed-4.htm)
- [Tiger Data: Finding the best open-source embedding](https://www.tigerdata.com/blog/finding-the-best-open-source-embedding-model-for-rag)
- [Layerbase: Vector databases compared 2026](https://layerbase.com/blog/vector-databases-compared-2026)
- [CallSphere: Vector Database Benchmarks 2026](https://callsphere.ai/blog/vector-database-benchmarks-2026-pgvector-qdrant-weaviate-milvus-lancedb)
- [MarkTechPost: Best Vector Databases 2026](https://www.marktechpost.com/2026/05/10/best-vector-databases-in-2026-pricing-scale-limits-and-architecture-tradeoffs-across-nine-leading-systems/)
- [Markaicode: pgvector vs Qdrant 2026](https://markaicode.com/vs/pgvector-vs-qdrant/)
- [Qdrant: Start with pgvector tradeoffs](https://qdrant.tech/blog/pgvector-tradeoffs/)
- [Qdrant Hybrid Queries documentation](https://qdrant.tech/documentation/search/hybrid-queries/)
- [Zilliz: Choose Milvus deployment mode](https://zilliz.com/blog/choose-the-right-milvus-deployment-mode-ai-applications)
- [ParadeDB: Hybrid Search in PostgreSQL](https://www.paradedb.com/blog/hybrid-search-in-postgresql-the-missing-manual)

### Geavanceerde patronen & NFRs
- [Local AI Master - Reranking 2026](https://localaimaster.com/blog/reranking-cross-encoders-guide)
- [Cohere Rerank docs](https://docs.cohere.com/docs/rerank)
- [Agentset Reranker Leaderboard](https://agentset.ai/rerankers)
- [BSWEN - Best Reranker Models 2026](https://docs.bswen.com/blog/2026-02-25-best-reranker-models/)
- [Future AGI - Cohere Rerank in RAG 2026](https://futureagi.com/blog/evaluating-cohere-rerank-rag-2026/)
- [LangChain Query Transformations](https://blog.langchain.com/query-transformations/)
- [ACL Anthology - Query Decomposition for RAG](https://aclanthology.org/2026.eacl-long.322/)
- [Microsoft Research - LazyGraphRAG](https://www.microsoft.com/en-us/research/blog/lazygraphrag-setting-a-new-standard-for-quality-and-cost/)
- [Paperclipped - Graph RAG in 2026](https://www.paperclipped.de/en/blog/graph-rag-production/)
- [Tongbing Medium - GraphRAG Buyer's Guide](https://medium.com/@tongbing00/graphrag-in-2026-a-practical-buyers-guide-to-knowledge-graph-augmented-rag-43e5e72d522d)
- [arXiv - When to use Graphs in RAG](https://arxiv.org/html/2506.05690v3)
- [LangChain Docs - Agentic RAG](https://docs.langchain.com/oss/python/langgraph/agentic-rag)
- [arXiv - ReSP Multi-hop QA](https://arxiv.org/abs/2407.13101)
- [arXiv - PAR-RAG](https://arxiv.org/pdf/2504.16787)
- [CallSphere - RAG Eval Frameworks 2026](https://callsphere.ai/blog/rag-evaluation-frameworks-2026-ragas-trulens-deepeval)
- [Future AGI - RAG Evaluation Metrics 2026](https://futureagi.com/blogs/rag-evaluation-metrics-2025)
- [Medium - Top 10 Retrieval Metrics](https://medium.com/@ThinkingLoop/top-10-retrieval-metrics-for-tuning-your-rag-14c61d5957f4)
- [Medium - RAG Grounding Fake Citations](https://medium.com/@Nexumo_/rag-grounding-11-tests-that-expose-fake-citations-30d84140831a)
- [TianPan - Enterprise RAG Governance](https://tianpan.co/blog/2026-04-17-enterprise-rag-knowledge-base-governance)
- [RAGAboutIt - Freshness Paradox](https://ragaboutit.com/the-rag-freshness-paradox-why-your-enterprise-agents-are-making-decisions-on-yesterdays-data/)
- [Atlan - LLM Knowledge Base Data Quality](https://atlan.com/know/llm-knowledge-base-data-quality/)
