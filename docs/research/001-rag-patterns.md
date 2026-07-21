---
id: "001"
title: "Technical Research — RAG Patterns as a Platform Building Block"
status: complete
author: mk2023-land
date: 2026-06-01
outcome: null
---

# Technical Research — RAG Patterns as a Platform Building Block

> Status: Research foundation for the `rag-patterns` skill and the
> app-local pgvector approach (`app/rag.py` + `module-llm` embed).
> **Note:** this document historically refers to `module-vectorstore`;
> that has been replaced by distributed storage in each app's own database.
> Part of Story A — RAG as a design building block for the Architect.
> Date: 2026-06-01.

## Introduction

### Topic

Retrieval-Augmented Generation (RAG) as a generic platform building block in Druppie. Intended to be deployed by the Architect agent in every doc-heavy application we build — knowledge bases, legal search, compliance search, customer-contact Q&A, internal docs, policy texts, product documentation, and so on. Use cases differ per project in language, scale, query type, and stakes; the building block must be able to handle that variation.

The **HDSR notes use case** is used later in this track (Story A's e2e test and Story B) as one validation scenario that touches a difficult combination: long documents, Dutch-language, administrative stakes, hard citation requirement. It is a good smoke test, **not a design driver**.

### Research question

Which choices — chunking strategy, retrieval pattern, citation tracking, embedding model, vector store, advanced patterns (re-ranking, query rewriting, GraphRAG, agentic), and RAG-specific NFRs — must the Architect agent be able to justify in a TD for any doc-heavy application in Druppie, and which defaults do we justify as the platform standard?

### Starting points

- **Multilingual is a hard requirement.** Use cases differ per project in language (NL, EN, mix, sometimes broader). The platform must handle that out of the box; no language-specific pipelines per project.
- **Greenfield** — no existing RAG choices in Druppie to be tied to.
- **Postgres is already running** in the Druppie stack as the primary datastore (no JSON/JSONB convention). A new stateful service has to justify itself.
- **Modules are containerized MCP servers** according to the `module-convention` skill. RAG should be plugged in as `module-rag`, not as an application library.
- **Self-hosted is preferred** for data residency. API-only solutions are a blocker unless hosted in the EU region and legally covered — given that many Druppie clients are public bodies.
- **Pragmatic over academic** — the Architect chooses; he does not have to understand everything.
- **Format**: this document follows the hybrid `technical-research-format`. Because RAG has multiple independent choice axes, each axis gets its own comparison + trade-off table + decision guide. The **Final recommendation** consolidates into platform defaults plus explicit deviation triggers per use case.

---

## Chunking strategies

Chunking determines how a source document is split into pieces that are embedded, indexed, and cited separately. For long, structured documents (reports, contracts, policy texts, annual reports, legal files) this is the lever with the greatest impact on both retrieval quality and citation precision — more than any embedding model. It takes little to get it wrong: a naive split loses 9% recall on identical corpora, and in domains with strong structural boundaries the gap grows to tens of percent ([Vecta benchmark Feb 2026](https://futureagi.com/blog/evaluating-rag-chunking-strategies-2026/), [Digital Applied 2026 playbook](https://www.digitalapplied.com/blog/rag-chunking-strategies-2026-retrieval-quality-playbook)).

### Comparison

#### Fixed-size
The document is cut into pieces of a fixed number of tokens (e.g. 512), optionally with a fixed overlap. No awareness of sentences, paragraphs, or sections.
- **When:** only for prototypes and very homogeneous text (logs, transcripts). Not for structured documents.
- **Trade-offs:** fastest indexing and simplest code, but breaks sentences and headings in the middle of a definition. A peer-reviewed study (MDPI Bioengineering, Nov 2025) showed that fixed-size achieved 13% accuracy versus 87% for topic-aware on structured text — significant with p=0.001 ([Firecrawl 2026](https://www.firecrawl.dev/blog/best-chunking-strategies-rag)).
- **NL:** sentence and paragraph boundaries are lost; referring words ("this measure", "the board") become detached from their antecedent.

#### Sliding-window
Variant on fixed-size: cut at a fixed length, but with a large overlap (e.g. 50%). Each sentence thus appears in multiple chunks.
- **When:** if you want to rescue a fixed-size baseline for queries where context falls just outside the chunk; also useful with sentence-window retrieval (LlamaIndex).
- **Trade-offs:** improves recall, but doubles index size and produces duplicated citations (the same passage in two chunks → ambiguous citation).
- **NL:** no specific effects.

#### Recursive
Splits hierarchically: first on double newlines (paragraphs), then single newlines, then sentences, then words, until it fits within the chunk budget. LangChain's `RecursiveCharacterTextSplitter` is the de-facto default.
- **When:** safe starting option for almost anything, including long structured documents in any language. Vecta's February 2026 benchmark ranked recursive 512 as no. 1 across 7 strategies (69% accuracy) ([Vecta via FutureAGI](https://futureagi.com/blog/evaluating-rag-chunking-strategies-2026/)).
- **Trade-offs:** 80% of semantic quality for 5% of the cost. Watch out for the well-known pitfall: LangChain's splitter counts **characters**, not tokens. Use `from_tiktoken_encoder()` for token-accurate splitting ([Digital Applied](https://www.digitalapplied.com/blog/rag-chunking-strategies-2026-retrieval-quality-playbook)).
- **NL:** works the same as in English — paragraph and sentence separators are the same characters.

#### Semantic (sentence-/paragraph-/topic-aware)
Splits on meaning: consecutive sentences that are semantically close together are merged; at a threshold value (cosine distance) a cut is made. Variants: `SemanticChunker` (embedding-drift-based), `LLMSemanticChunker` (LLM determines boundaries).
- **When:** if recursive demonstrably scores below the norm and the document type benefits from meaning clusters (long essays, scientific texts).
- **Trade-offs:** LLM-semantic achieves 0.919 recall (vs. 0.881–0.895 for recursive 400-token), but is ~14× slower than token-based ([Chonkie benchmarks via Firecrawl](https://www.firecrawl.dev/blog/best-chunking-strategies-rag)). Recent benchmarks are mixed: Vecta saw semantic underperform because the chunks became too short (avg 43 tokens).
- **NL:** depends on good sentence detection. spaCy's `nl_core_news_lg` and NLTK's Punkt Dutch are solid for modern text; for formal policy language, **Frog** (KU Leuven/Tilburg) is more robust with abbreviations ("art.", "lid", "jo.") ([spaCy NL](https://spacy.io/models/nl/), [Frog](http://languagemachines.github.io/frog/)).

#### Parent-document / hierarchical (small-to-big)
Two levels: small child chunks (sentences, 128–256 tokens) are embedded for retrieval; on a hit, the **parent** chunk (section or paragraph, 1024–2048 tokens) is passed to the LLM. LlamaIndex's `HierarchicalNodeParser` has a default of [2048, 512, 128].
- **When:** strong fit for long documents with numbered sections (reports, policy texts, contracts, annual reports). Answers must find precisely the relevant sentence ("which date was decided?") but be cited in a context-rich way ("§3.2 of [source document]").
- **Trade-offs:** double storage (child + parent), slightly more complex ingestion. Delivers clearly better answers for long documents; arXiv 2503.02401 (HRR) showed +25% MRR compared to flat recursive.
- **NL:** no specific risks, provided sentence detection for the child layer is good.

#### Late chunking
The order is reversed: first the entire (long) document is run through a long-context embedding model to obtain contextually rich **token** embeddings; only then are chunks formed through mean-pooling within boundaries. Conceived by Jina (2024); now in jina-embeddings-v3 and integrated into Weaviate, Elastic, Milvus.
- **When:** long documents with many anaphora and cross-references ("this decision", "the aforementioned committee", "the party mentioned above"). The longer the document, the greater the gain. Typically strong in legal, policy, and contract corpora.
- **Trade-offs:** requires a long-context embedding model (8k+ tokens). Implementation is minimal (~30 lines at the pooling step), but you consume more tokens per ingest. Combines well with parent-document. Jina reports higher similarity scores on anaphora-heavy passages; Anthropic's Contextual Retrieval (a related technique) cut top-20 retrieval failures by 67% ([Jina](https://jina.ai/news/late-chunking-in-long-context-embedding-models/), [Weaviate](https://weaviate.io/blog/late-chunking)).
- **Language:** depends on the language support of the long-context model (jina-v3 and bge-m3 cover a broad set of languages incl. NL well).

### Trade-off table

| Strategy | Complexity | Retrieval quality | Citation precision | Operational cost | Fit long docs (50+p) |
|---|---|---|---|---|---|
| Fixed-size | Low | Low | Low (breaks sentences) | Very low | Poor |
| Sliding-window | Low | Medium | Medium (duplicates) | Low-medium | Medium |
| Recursive | Low | Good | Good | Low | Good |
| Semantic | Medium | High | High | Medium (~14× recursive) | Good |
| Parent-document | Medium | High | Very high (section anchor) | Medium (2× storage) | Very good |
| Late chunking | Medium-high | Very high | High | Medium (long-ctx model) | Very good |

### Decision guide

1. **Start with recursive 512-token** with the tiktoken encoder and 10–20% overlap. This is the safe default from all 2026 benchmarks, regardless of use case or language.
2. **Move to parent-document/hierarchical** as soon as answers are correct but citations are too narrow or too broad — typically with long structured documents with numbered sections.
3. **Add late chunking** for documents with many referring words ("this measure", "aforementioned party") where baseline retrieval points to the wrong paragraph. Requires a long-context embedding model.
4. **Consider semantic** only if you see a measured quality gap that parent+late do not close; the 14× compute overhead is real.
5. **Avoid fixed-size** in production unless your corpus is genuinely homogeneous.

---

## Retrieval & search patterns

Retrieval determines which chunks are fed to the LLM. In doc-heavy applications this is harder than it seems: users ask both natural questions ("what is the policy on X?") and jargon questions (article/clause references, file numbers, product codes) — two retrieval regimes that are each other's weakness.

### Comparison

#### Pure vector search (dense)
Query and chunks are embedded; cosine/dot-product similarity determines the top-k. ANN indexes (HNSW, IVF) keep it scalable.
- **When:** natural language, paraphrasing, synonyms. Good default for unexpected query formulations.
- **Trade-offs:** stumbles over rare terms (jargon, proper names, file numbers, article references). For "Water permit 2024-WV-0451" dense search is virtually useless; vector finds something "nearby" that is wrong.
- **NL:** strongly dependent on the model's NL coverage. Multilingual models (BGE-M3, jina-v3, multilingual-e5) perform solidly on NL; ada-002 loses ~5–10% nDCG on NL vs. EN.

#### Lexical / BM25
Classic sparse keyword retrieval based on term frequency × inverse document frequency. No embeddings needed.
- **When:** exact terms, codes, names, jargon. Indispensable for article/clause references, IBANs, file/product numbers, quoted text.
- **Trade-offs:** misses synonymy and morphological variations. Solid, predictable, cheap.
- **Language:** requires a **language-specific analyzer** (stemmer + stopword list) per corpus language. Postgres `to_tsvector('<language>', ...)` and Elasticsearch provide this out of the box for all common European languages incl. NL and EN. For multilingual corpora: one analyzer per language field or a multilingual analyzer.

#### Hybrid (vector + BM25 with RRF or weighted fusion)
Both retrievers run in parallel; their rankings are merged. **Reciprocal Rank Fusion (RRF)** is dominant in 2026: score = Σ 1/(k + rank), with k=60 as a safe default (k=20–30 if you want to weight top results more heavily). RRF works on **ranks**, not scores, so no normalization is needed ([Microsoft Learn](https://learn.microsoft.com/en-us/azure/search/hybrid-search-ranking)).
- **When:** almost always, in production. BEIR benchmarks and Anthropic reports consistently show +5–15% nDCG compared to the best of the two alone ([Digital Applied 2026](https://www.digitalapplied.com/blog/hybrid-search-bm25-vector-reranking-reference-2026)).
- **Trade-offs:** maintaining two indexes (vector + inverted index), two query paths. Operationally slightly more complex; ParadeDB, Weaviate, Qdrant, Elasticsearch 8.13+, and Azure AI Search offer this natively.
- **Language:** works language-independently provided the BM25 analyzer is set correctly per language. Combines the best of both worlds — BM25 catches exact terms, vector catches paraphrasing and synonyms.

#### Metadata-filtered search
Filter on structured fields (doc_type=note, date>2023-01-01, status=adopted) before, during, or after the vector step.
- **When:** always, as soon as you have more than one doctype, year, or category — virtually every production RAG.
- **Trade-offs:** three strategies: **pre-filter** (filter first, then ANN) guarantees k results but breaks HNSW graph connectivity at low cardinality; **post-filter** is simple but sometimes yields <k results; **in-graph filtering** (Qdrant filterable HNSW, Milvus, Weaviate) is the modern standard and solves both problems ([Qdrant](https://qdrant.tech/articles/vector-search-filtering/)).
- **Language:** not language-dependent; crucial for citation precision ("only passages with status=adopted, date=2024").

#### Multi-vector / ColBERT-style (late interaction)
Instead of one vector per chunk, the model stores a vector per token. During scoring, for each query token the maximum is compared against all document tokens (MaxSim).
- **When:** out-of-domain corpora where single-vector dense falls short; long documents with fine-grained matches; multilingual scenarios. ColBERTv2/PLAID is production-ready.
- **Trade-offs:** ~10× storage (ColBERTv2 brings this down to ~2× with residual quantization), higher index complexity. For Druppie scale (10⁴–10⁶ chunks) the costs are manageable. ColPali (visual ColBERT) extends this to PDF pages directly.
- **Language:** language-specific late-interaction models are scarce; the multilingual variant (`jina-colbert-v2-multilingual`) covers a broad language set incl. NL reasonably. For most use cases, hybrid+rerank is sufficient and cheaper.

### Trade-off table

| Pattern | Relevance short queries | Relevance long queries | Jargon/proper names | Operational complexity | NL fit |
|---|---|---|---|---|---|
| Pure vector | Medium | High | Low | Low | Good (with multilingual model) |
| BM25 | High (exact) | Medium | Very high | Low | Good (with language analyzer) |
| Hybrid (RRF) | High | High | High | Medium | Very good |
| Metadata-filtered | n/a (modifier) | n/a (modifier) | n/a | Low-medium | n/a |
| Multi-vector / ColBERT | High | Very high | High | High | Medium (language models scarce) |

### Decision guide

1. **Start with hybrid (BM25 + dense, RRF k=60).** In 2026 it is the defensive default; pure dense structurally misses jargon in formal/technical texts.
2. **Configure a language-specific analyzer for the BM25 side** per corpus language (Postgres `to_tsvector('<language>', ...)`, Elasticsearch language analyzers). For multilingual corpora: analyzer-per-field or a multilingual analyzer. Without this, lexical delivers only half its value.
3. **Always add metadata filtering** on doctype, date, status, tenant. Virtually every question is inefficient without a context filter.
4. **Pick ColBERT/late-interaction** only if you see a measured gap on out-of-domain queries and you can afford the storage/index budget.
5. **Pure vector** is a reasonable baseline if you are under time pressure, but it visibly leaves money on the table — not the final state.

---

## Citation tracking

For doc-heavy applications where users must be able to verify the source (legal, policy, compliance, customer contact, medical, financial), citation tracking is not a feature but a requirement: a statement without a verifiable source is unusable for those domains. The chain runs from chunk metadata in the index → context injection in the prompt → output formatting → UI rendering. Each link can leak information.

### Comparison

#### Chunk ID + source document ID
Each chunk gets a stable ID (`doc_id + version + hash(span_text)`) and a reference to the original document.
- **When:** absolute baseline. Without this you can trace nothing.
- **Trade-offs:** content hashing makes IDs stable across reindexing — otherwise citations break on every ingest ([Visively](https://visively.com/kb/ai/llm-rag-retrieval-ranking)). Trivial to implement; only disciplinary cost.

#### Page / paragraph / offset
In addition to IDs you store position metadata: page number (PDF), section title, paragraph index, character offsets in the original.
- **When:** as soon as users must be able to jump to the source ("show that sentence on page 23"). Essential for formal documents with pagination.
- **Trade-offs:** PDF extraction must preserve position (Tensorlake, Unstructured, AWS Textract with `geometry`); bounding boxes add ~10–15% storage but make inline preview possible ([Tensorlake](https://www.tensorlake.ai/blog/rag-citations)). Page + paragraph is more robust than character offset; offsets change with small document edits, page numbers rarely.

#### Span tracking within chunks
Not just "this chunk", but "characters 412–587 in this chunk" — the actual cited sentence.
- **When:** for sentence-level highlights in the UI, or as input for Anthropic's Citations API (which returns character-level provenance, 0-indexed with exclusive end).
- **Trade-offs:** highest precision, best UX. Implementation slightly more complex: either the LLM produces spans (vulnerable to hallucination), or you match the generated sentence post-hoc back to the source (costs some compute). The Citations API does this for you for free if you use Claude ([Claude Citations docs](https://platform.claude.com/docs/en/build-with-claude/citations)).

#### Parent-document IDs (with hierarchical chunking)
The child chunk is cited for the match, but the citation shows the **parent** section (and gives the user a view of the context in which the sentence sits).
- **When:** mandatory as soon as you use parent-document chunking. A bare child citation is misleading — half a sentence out of context.
- **Trade-offs:** UX wish (show section title + surrounding sentences) versus prompt budget (you add more tokens). Good compromise: show parent as context in the UI, not in the prompt.

#### Citation styles in output
- **Inline numeric markers** (`[1]`, `[2]`): familiar, reads like academic text. Good for formal written output.
- **Anchor-based** (`<cite chunk_id="..." span="...">text</cite>`): machine-parsable, ideal for interactive UI with hover/click.
- **Footnotes** (`text¹` with footnote at the bottom): highest readability for formal documents.
- **Appended source list**: simplest form — answer first, then "Sources: [list]". It works, but lacks the binding between sentence and source, which is exactly the problem citations are supposed to solve.

Two generation patterns:
1. **Single-pass:** the LLM produces answer and citations at the same time in one call (Anthropic's approach; resembles internal use in Claude Citations).
2. **Two-step verify:** the LLM writes a draft → a second LLM pass verifies claims against passages → final output with verified citations. Slower, more robust against hallucination ([Particula](https://particula.tech/blog/fix-rag-citations)).

### Trade-off table

| Pattern | Traceability precision | UX | Implementation complexity | Fit long documents |
|---|---|---|---|---|
| Chunk ID + doc ID | Document level | Basic | Trivial | Insufficient alone |
| Page / paragraph / offset | Paragraph level | Good (jump-to-source) | Low-medium | Very good |
| Span tracking | Sentence/character level | Excellent (highlight) | Medium | Very good |
| Parent-document IDs | Section + sentence | Excellent (context) | Medium (with hierarchical) | Mandatory with hierarchical |
| Inline [1] style | Depends on anchor | Familiar | Low | Good |
| Anchor-based tags | High | Interactive | Medium | Good |
| Footnotes | Depends on anchor | Formal, readable | Low-medium | Very good |
| Appended list | Low (no binding) | Poor for audit | Trivial | Insufficient |

### Decision guide

1. **Start with chunk ID + doc ID + page/paragraph as mandatory metadata** in the index. Use content-hash-based IDs (`doc_id + version + hash(span)`), not positional indexes, otherwise every reindex breaks your citations.
2. **Add the parent section title** as metadata as soon as you deploy hierarchical chunking — show this in the UI ("[Source document], §3.2 [Section title], p.18").
3. **For formal written output: choose footnote style** in the generated Markdown. Readable when exported to Word/PDF, fits academic and administrative styles.
4. **For interactive UI**: add anchor tags in parallel (`<cite>...</cite>`) that link the footnote numbers to a clickable source preview with page jump.
5. **Sentence-level span tracking** is the upgrade if legal or compliance precision is needed. If you use Claude: let the Citations API do the work ([Claude docs](https://platform.claude.com/docs/en/build-with-claude/citations)). Otherwise: instruct the LLM to deliver sentence tags and parse them post-hoc.
6. **Two-step verify** only if hallucination risks score high in evaluation. For most use cases, single-pass + sentence-level anchors is sufficient. Remember: citations verify that the source *exists*, not that the claim *is correct* — that distinction must be clear in UX and evaluation.

---

## Embedding models

### Comparison

#### BGE-M3 (BAAI)
- **What**: Open multilingual embedding model from the Beijing Academy of AI (Jan 2024, still a production standard in early 2026). Built on XLM-RoBERTa-large.
- **Hosting**: Self-hosted (HuggingFace) or via providers (DeepInfra, IONOS, Zilliz). 568M parameters.
- **Dimensions**: 1024 dense, plus native sparse and multi-vector (ColBERT) output from a single forward pass — unique.
- **Max input**: 8192 tokens — fits well with long documents (in combination with chunking).
- **NL performance**: On MTEB-NL (Banar et al., Sept 2025) **AvgT 63.1, retrieval 60.0** — solid but not top. Beaten by multilingual-e5-large-instruct (66.9) and Qwen3-Embedding-4B (69.2). ([arXiv 2509.12340](https://arxiv.org/abs/2509.12340))
- **License**: MIT — fully commercially usable.
- **Ops**: ~2.3 GB FP32, runs on CPU (slow) or a single consumer GPU. Fits in an MCP container with 4-6 GB RAM.
- **Strength for Druppie**: Native dense+sparse+ColBERT in a single pass makes hybrid search with one model feasible ([BAAI/bge-m3 HuggingFace](https://huggingface.co/BAAI/bge-m3)).

#### multilingual-e5-large-instruct (Microsoft)
- **What**: Instruct version of the E5 family (Microsoft Research, 2024). 560M parameters.
- **Hosting**: Self-hosted, MIT license.
- **Dimensions**: 1024 (no Matryoshka).
- **Max input**: 512 tokens — this is a real limitation for long documents; requires stricter chunking.
- **NL performance**: **Highest overall score on MTEB-NL among non-NL-specific models: AvgT 66.9, retrieval 61.4, clustering 46.0** ([MTEB-NL paper](https://arxiv.org/html/2509.12340v1)).
- **License**: MIT.
- **Ops**: 2.2 GB FP32, comparable to BGE-M3.
- **Caveat**: Requires instruction prefixes ("query: ..." / "passage: ...") — the pipeline must enforce that or accuracy drops noticeably.

#### E5-NL (University of Antwerp, Sept 2025)
- **What**: NL-specific E5 variant with a trimmed tokenizer, trained by Banar et al. Small/base/large.
- **Hosting**: Self-hosted (HuggingFace).
- **Dimensions**: 1024 (large), 768 (base), 384 (small).
- **NL performance**: **State-of-the-art among non-instruct models on MTEB-NL**; e5-large-trm-nl is the top non-instruct. For pure NL RAG stronger than BGE-M3, comparable to multilingual-e5-large-instruct but more parameter-efficient.
- **License**: MIT.
- **Caveat**: NL-only — multilingual capability has been sacrificed for NL precision. Poor for mixed NL/EN corpora.

#### Qwen3-Embedding (Alibaba, June 2025)
- **What**: 0.6B / 4B / 8B variants on the Qwen3 foundation. Apache 2.0.
- **Hosting**: Self-hosted, also available via Ollama (0.6B is 639 MB GGUF).
- **Dimensions**: Custom dimensions (MRL support).
- **Max input**: 32K (0.6B/4B), 128K (8B).
- **NL performance**: **Qwen3-Embedding-4B: MTEB-NL AvgT 69.2 — highest of all tested open models on Dutch**. 0.6B reaches 62.6. 8B ranked #1 on multilingual MTEB v1 (70.58) ([Qwen3 Embedding blog](https://qwenlm.github.io/blog/qwen3-embedding/)).
- **License**: Apache 2.0.
- **Ops**: 0.6B CPU-only; 4B requires ~8 GB GPU VRAM; 8B requires 16+ GB GPU.

#### jina-embeddings-v3 (Jina AI)
- **What**: 570M parameters, XLM-RoBERTa base with task-specific LoRA adapters.
- **Hosting**: Self-hosted and Jina API.
- **Dimensions**: 1024 default, MRL down to 32 (retains 92% retrieval at 64 dims).
- **Max input**: 8192 tokens (RoPE).
- **NL performance**: MTEB-NL **AvgT 62.7** — comparable to BGE-M3.
- **License**: **CC BY-NC 4.0 — non-commercial**. For production via API or a commercial license. **Important disqualifier for self-hosted commercial Druppie deployment** ([jina-v3 announcement](https://jina.ai/news/jina-embeddings-v3-a-frontier-multilingual-embedding-model/)).

#### Cohere embed-v4
- **What**: Commercial multilingual+multimodal (text + image), 2025.
- **Hosting**: **API-only** (also via AWS Bedrock, Azure, Oracle).
- **Dimensions**: Matryoshka 256/512/1024/1536, native int8/binary quantization.
- **Max input**: **128K tokens** — largest of all commercial embedding models.
- **NL performance**: Cohere is historically a leader in multilingual retrieval; v4 is consistently reported as top for 100+ languages. No MTEB-NL score published.
- **License/cost**: API ~$0.10–$0.12 per 1M tokens.
- **Problem for Druppie**: API-only conflicts with data residency. Bedrock deployment in an EU region is a way out.

#### OpenAI text-embedding-3-large / -small
- **Hosting**: API-only.
- **Max input**: 8191 tokens.
- **NL performance**: text-embedding-3-large is strong on MTEB EN, but **multiple 2026 sources report consistent underperformance on European languages incl. NL** ([PE Collective](https://pecollective.com/tools/best-embedding-models/)).
- **Disqualifier**: data residency + weaker NL.

#### mxbai-embed-large, nomic-embed-text-v2
Both effectively English-language in benchmarks — **not suitable for NL** ([Tiger Data](https://www.tigerdata.com/blog/finding-the-best-open-source-embedding-model-for-rag), [PE Collective](https://pecollective.com/tools/best-embedding-models/)).

### Trade-off table

| Model | NL perf (MTEB-NL AvgT) | Multilingual breadth | Dims | Max input | Self-host | GPU req | License | Cost |
|---|---|---|---|---|---|---|---|---|
| **Qwen3-Embedding-4B** | **69.2** | 100+ languages | MRL flex | 32K | Yes | ~8 GB VRAM | Apache 2.0 | Compute-only |
| multilingual-e5-large-instruct | 66.9 | ~94 languages | 1024 fixed | 512 | Yes | CPU possible / 2 GB VRAM | MIT | Compute-only |
| **E5-NL-large** | SOTA non-instruct (>67 est.) | NL-only | 1024 | 512 | Yes | CPU/low VRAM | MIT | Compute-only |
| BGE-M3 | 63.1 | 100+ languages | 1024 + sparse + ColBERT | 8192 | Yes | CPU/4 GB VRAM | MIT | Compute-only |
| jina-embeddings-v3 | 62.7 | 32 languages (NL included) | 1024 MRL | 8192 | Yes, **non-commercial** | 4 GB VRAM | CC BY-NC 4.0 | API or commercial license |
| Qwen3-Embedding-0.6B | 62.6 | 100+ languages | MRL flex | 32K | Yes | CPU OK | Apache 2.0 | Compute-only |
| Cohere embed-v4 | unknown, strong multilingual | 100+ languages | MRL 256–1536 | **128K** | No | n/a | proprietary | $0.10–0.12/1M |
| OpenAI 3-large | weak EU/NL | limited | MRL 256–3072 | 8191 | No | n/a | proprietary | $0.13/1M |
| mxbai-embed-large | almost zero cross-lingual | EN-only | 1024 | 512 | Yes | 2 GB VRAM | Apache 2.0 | Compute-only |
| nomic-embed-v2 | R@1<0.16 multilingual | EN-only in practice | 768 MRL | 8192 | Yes | CPU | Apache 2.0 | Compute-only |

### Decision guide

**Selection criteria (in order of weight for the platform default):**
1. **Broad multilingual coverage** — must work out of the box for at least NL and EN, preferably broader. Druppie use cases differ per project.
2. **Self-host feasibility** — must be able to run in an MCP container without an expensive GPU requirement. Data residency: API-only is a blocker unless EU-hosted and legally covered.
3. **Permissive license** — MIT or Apache 2.0. Non-commercial licenses are a blocker.
4. **Proven quality** — solid scores on multilingual MTEB and language-specific benchmarks such as MTEB-NL (to confirm that NL does not drop off).
5. **Ops footprint** — memory and latency must be predictable.

**Platform default: `multilingual-e5-large-instruct`** — strong multilingual baseline (94 languages), MIT license, CPU-feasible (~2 GB), and proven quality on both multilingual MTEB and MTEB-NL (66.9 AvgT). The 512-token limit is not a blocker for RAG because chunking falls below that limit anyway.

**Upgrade paths, only with an explicit trigger:**
- **Qwen3-Embedding-4B** if quality is the heaviest criterion and you have an ≥8 GB GPU budget in an MCP container. Apache 2.0, MTEB multilingual #1 rank, MRL, 32K context. Trigger: a measurable lower bound on a use-case-specific gold set that the default does not meet.
- **Qwen3-Embedding-0.6B** if you still want CPU-only but want to leverage the extra coverage of the Qwen foundation. Apache 2.0, 32K context.
- **BGE-M3** if you make hybrid retrieval central and want dense + sparse + ColBERT in one model for pipeline simplicity. MIT, 8K context. Slightly lower multilingual scores than e5-instruct, but the architectural gain may compensate.
- **E5-NL** only for projects that explicitly state that the corpus is NL-only and will remain so. Losing multilingual = lock-in on a single language; unsuitable as a platform default.

**When in doubt**: `multilingual-e5-large-instruct`. Build the pipeline **model-agnostically** (stable content-hash chunk IDs, embedding generation behind an MCP interface) so that switching to Qwen3-4B or another model is possible later without breaking changes.

**Disqualifiers for the platform default:**
- OpenAI text-embedding-3-*: API-only + weaker on non-English European languages.
- mxbai-embed-large, nomic-embed-text-v2: effectively English-language in benchmarks — no multilingual default.
- jina-embeddings-v3: CC BY-NC 4.0 blocks commercial self-host. Only deployable via Jina API/marketplace, and therefore a data-residency blocker.
- Cohere embed-v4: API-only; usable via Bedrock EU region if data residency is covered, otherwise a disqualifier.

---

## Vector stores

### Comparison

#### pgvector (Postgres extension)
- **What**: Postgres extension (since 2021, v0.9 in early 2026). Vectors as the `vector` column type, with HNSW/IVFFlat/DiskANN indices.
- **Architecture**: No extra service — part of the existing Postgres instance.
- **Hybrid search**: **Not native end-to-end** — combine `tsvector` (Postgres FTS) with vector search via RRF/manual fusion (~100 lines of Python). v0.9 adds sparse vector support but there is still no high-quality BM25 in core Postgres. ParadeDB's `pg_search` extension is a serious attempt ([ParadeDB Hybrid Search](https://www.paradedb.com/blog/hybrid-search-in-postgresql-the-missing-manual)).
- **Metadata filter**: Fully SQL — joins with other tables, ACL via row-level security, transactional consistency. Strong point.
- **Scaling**: Vertical (HNSW must fit in RAM). **Performance degrades noticeably beyond 10M vectors** — at 50M vectors: 41 QPS vs Qdrant's 471 QPS @ 99% recall ([Layerbase](https://layerbase.com/blog/vector-databases-compared-2026), [CallSphere](https://callsphere.ai/blog/vector-database-benchmarks-2026-pgvector-qdrant-weaviate-milvus-lancedb)).
- **Ops**: Zero new service. Backups, replication, monitoring work immediately.
- **License**: PostgreSQL License.

#### Qdrant
- **What**: Rust-native standalone vector engine. Single binary.
- **Architecture**: Separate service (REST + gRPC). Fits well into the MCP-container pattern.
- **Hybrid search**: **Native server-side via the Query API** (since v1.10). Dense + sparse (BM25 via FastEmbed or native sparse vectors) + miniCOIL + ColBERT-style late interaction, fused with RRF or DBSF. Multi-stage reranking is first-class ([Qdrant Hybrid Queries](https://qdrant.tech/documentation/search/hybrid-queries/)).
- **Metadata filter**: **Filterable HNSW** — filters during graph traversal, not afterward. Filtered queries @ 500K vectors p50 ~6ms vs pgvector ~25ms ([Markaicode pgvector vs qdrant](https://markaicode.com/vs/pgvector-vs-qdrant/)).
- **Scaling**: Vertically strong; horizontally via sharding + replicas. Sub-10ms p95 on 10M+ vectors.
- **Ops**: A single Rust binary. **Sync tax**: if Postgres is your source of truth, you have to build outbox/CDC to keep vectors synchronized.
- **License**: Apache 2.0.

#### Weaviate
- **What**: Open-source vector DB, Go-based runtime.
- **Hybrid search**: **Best native hybrid search on the market** — BM25 + dense + metadata filters in one query, modular vectorizer modules embed text inline.
- **Metadata filter**: Strong, with multi-tenancy (namespaces).
- **Ops**: Heavier than Qdrant; ~16 GB RAM recommended; GraphQL learning curve.
- **License**: BSD-3 (core).

#### Milvus
- **Architecture**: Three deployment modes: Lite (embedded), Standalone (3 containers: Milvus + etcd + MinIO), Distributed (7–10 microservices on K8s).
- **Hybrid search**: Native dense + sparse hybrid since 2.4; integrates nicely with BGE-M3's sparse output.
- **Scaling**: **Designed for billions of vectors**. Storage Format V2 makes 10B+ feasible on object storage.
- **Ops**: Standalone feasible for one engineer; **Distributed requires a platform-engineering investment**. Break-even for Distributed: ~50–100M vectors or >1M req/day ([Zilliz deployment guide](https://zilliz.com/blog/choose-the-right-milvus-deployment-mode-ai-applications)).
- **License**: Apache 2.0.

#### Chroma
- **Architecture**: Embedded or standalone server. **2025 Rust rewrite** gave 4× faster writes/queries.
- **Hybrid search**: Limited — no native BM25.
- **Scaling**: Good up to ~1M vectors on a single VPS; limits above that. No multi-tenancy.
- **Best fit**: prototyping. Production deployments usually migrate to Qdrant or pgvector.

#### LanceDB
- **Architecture**: Embedded vector DB on the Lance columnar storage format. Mindshare growth 6.7% → 9.6% YoY in 2026.
- **Hybrid search**: Native full-text + vector + multi-modal.
- **Scaling**: Strong on a large corpus with frequent updates.
- **Best fit**: image+text pipelines, agent memory stores. Mid-tier for doc-heavy NL RAG.

### Trade-off table

| Store | Hybrid search native | Ops complexity for Druppie | Scaling | Metadata filter | Maturity | License |
|---|---|---|---|---|---|---|
| **pgvector** | Manual (FTS + RRF) | **Zero** — already part of Druppie's Postgres | Solid up to ~10M vectors | Excellent (SQL joins, RLS) | Very high | PostgreSQL License |
| **Qdrant** | **Excellent** (BM25 + dense + miniCOIL + ColBERT in Query API) | Low (1 binary, 1 container) + sync tax with Postgres | Sub-10ms p95 @ 10M+; horizontal | Excellent (filterable HNSW) | High | Apache 2.0 |
| Weaviate | **Best in class** (BM25+dense+filters in 1 query) | Medium (16 GB RAM, GraphQL) | Horizontal via sharding | Strong + namespaces | High | BSD-3 |
| Milvus | Native dense+sparse | Standalone low / Distributed high (K8s + etcd + MinIO + Kafka) | Billions of vectors | Strong + partitions | High | Apache 2.0 |
| Chroma | Limited | Very low | Up to ~1M vectors | Basic | Medium | Apache 2.0 |
| LanceDB | Native FTS + vector + multimodal | Very low (embedded) | Strong on large corpus with updates | Strong | Growing, younger | Apache 2.0 |

### Decision guide

**Default for Druppie: pgvector**, for the following evidence-based reasons:

1. **Postgres is already running** — adding pgvector is a `CREATE EXTENSION`, no new container, no extra failure mode. Fits into Druppie's normalization convention as an ordinary column.
2. **Scale reality of Druppie RAG**: most doc-heavy use cases (knowledge bases, legal search, compliance search, customer-contact Q&A, policy documents) sit between 10⁴ and 10⁶ chunks. **Well within pgvector's effective range (<10M vectors)**. Qdrant advantages only materialize beyond that point.
3. **Transactional consistency**: on doc upload, Druppie writes metadata, ACL, and chunks at the same time; pgvector lets this happen in a single transaction. With a dedicated store we have a sync problem that requires outbox/CDC.
4. **SQL for permissions**: Druppie's domain model is rich (sessions, agents, approvals). Search-time filtering on user roles, tenant, doc status expresses itself naturally in SQL joins.
5. **Ops budget**: Druppie is a platform, not a vector-search SaaS. Every extra service must justify itself.

**When to deviate from pgvector — move to Qdrant** as soon as:
- Filtered ANN p95 becomes a hard requirement (>25ms unacceptable), e.g. multi-tenant SaaS mode.
- The corpus passes 10M chunks.
- Hybrid search becomes central and the FTS fusion in Postgres becomes too brittle.
- You need rerank/ColBERT/miniCOIL — Qdrant offers this natively, pgvector does not.

**Move to Weaviate** only if native hybrid-search-as-a-service becomes the #1 driver and multi-modal (text + image) is needed.

**Move to Milvus Distributed** only with 100M+ vectors and an ops team that comfortably runs K8s/etcd/Kafka.

**Chroma and LanceDB**: not as default — Chroma for prototypes, LanceDB for future multi-modal use cases.

**Architectural guideline**: build the retrieval layer in an MCP-server abstraction (`module-rag`) so that the implementation sits behind a stable interface. Default = pgvector; a second implementation against Qdrant can come later. Stable chunk IDs in Postgres as the source of truth, so that any migration to Qdrant does not force a re-embedding cost except rebuilding the ANN index.

---

## Advanced patterns

> Scope: only patterns that come *on top of* a working baseline pipeline (chunking + hybrid retrieval + citations).
> Guiding principle: the platform default is baseline + reranker. Add all other advanced patterns only when a demonstrable symptom or use-case requirement justifies it.

### Re-ranking

Cross-encoder reranking in 2026 is as close to "standard" as an advanced pattern can get: a lift of 10-25% on nDCG@10 for a few hundred ms of latency and marginal cost. The practical question is not *whether* you take a reranker, but *which one* and *how large* your candidate set is.

#### Comparison

| Model | Type | Self-host | Lat. (100 docs, GPU) | Multilingual / NL | Practical strengths | Points of attention |
|---|---|---|---|---|---|---|
| **BGE-reranker-v2-m3** (BAAI, 0.6B) | Cross-encoder | Yes, Apache 2.0 | 50-150 ms | 100+ languages, trained on MIRACL. No NL-specific benchmark available; implicitly "reasonable" via mMARCO/MIRACL. | Free, low threshold, broad coverage. *The de facto* open-source baseline. | For cross-lingual queries 5-10 nDCG points below Cohere. |
| **Cohere Rerank 3.5 / v4.0 Pro** | API (cross-encoder) | No (only via Bedrock/Azure/OCI private) | 80-150 ms p50, 200+ p99 | 100+ languages; *industry-leading* on non-English. | Best multilingual quality-per-call. ~$2/1k searches or $2/1M tokens. | Vendor lock-in, data egress. For strictly data-sovereign deployments a blocker. |
| **Jina-reranker-v3** (0.6B listwise) | Cross-encoder + listwise | Yes, but CC-BY-NC 4.0 (commercial = Jina API/AWS/Azure marketplace) | <200 ms p95 | 18 languages MIRACL 66.5 nDCG; strong multilingual. 131K context. | Best open-weights multilingual (61.94 BEIR). | Non-commercial license — for on-prem production you must pay or take v2. |
| **mxbai-rerank-large-v2** (Mixedbread, 1.5B) | Cross-encoder (Qwen-2.5-based) | Yes, Apache 2.0 | 150-400 ms (1.5B larger) | 100+ languages, 8k context (compatible up to 32k) | Open + commercial + long context + 57.49 BEIR. Strong for JSON/code/tool routing. | Larger model = more GPU. For pure NL text BGE-v2-m3 is more efficient. |
| **Sentence-transformers cross-encoders** (e.g. `ms-marco-MiniLM-L-12-v2`) | Cross-encoder | Yes, Apache 2.0 | 20-60 ms (CPU feasible) | Mainly EN. Multilingual variants weaker than BGE. | Small, fast, CPU-friendly. | Too weak for multilingual NL corpora. |

Sources: [Local AI Master 2026 reranker guide](https://localaimaster.com/blog/reranking-cross-encoders-guide), [Cohere docs](https://docs.cohere.com/docs/rerank), [Agentset leaderboard](https://agentset.ai/rerankers), [Jina v2 model card](https://jina.ai/models/jina-reranker-v2-base-multilingual/), [BSWEN 2026 comparison](https://docs.bswen.com/blog/2026-02-25-best-reranker-models/).

#### Trade-off table

| Dimension | No rerank | BGE-v2-m3 | Cohere 3.5 | Jina v3 (hosted / paid) | mxbai-large-v2 |
|---|---|---|---|---|---|
| Quality lift vs. hybrid retrieval alone | baseline | +10-15% nDCG@10 | +15-25% nDCG@10 | +15-25% nDCG@10 | +12-20% nDCG@10 |
| Extra latency p95 | 0 | 50-150 ms | 100-200 ms (network) | 100-200 ms | 150-400 ms |
| Cost per 1k queries (100 docs) | 0 | GPU-hour ($) | ~$2 | ~$2 | GPU-hour ($) |
| Data sovereignty | n/a | fully on-prem | no (API) | no (commercial) | fully on-prem |
| NL quality | baseline | reasonable | best | best | reasonable-good |

#### Decision guide

**Add a reranker when:**
- Top-k (k=5..10) contains visibly irrelevant chunks that distract the generator.
- Faithfulness/citation precision is low while recall@20 is high.
- Hybrid scoring (BM25 + dense) is not unambiguous and you need a merge strategy.

**Do not do it when:**
- The p95 latency budget is <500 ms and you have no GPU.
- Recall@10 is already >85% on your gold set.
- The corpus is so small (<1000 chunks) that top-20 fits in the prompt.

**Candidates N before rerank (rule of thumb):**
- Standard: N=50, rerank to top-5..8.
- Long documents with fine-grained search queries: N=80-100 to cover rare paragraphs.
- Latency-critical (chatbot <2s): N=30, rerank to top-3.

**Platform default:**
- **BGE-reranker-v2-m3 self-hosted** as a starting point: free, sovereign, broad language coverage (Apache 2.0).
- Upgrade path: switch to Cohere or Jina-v3 as soon as a use-case-specific gold set shows a ≥5 nDCG-point difference and data egress is acceptable (Cohere via Bedrock EU is the practical escape hatch here).
- Avoid mxbai-large-v2 as default — 3× GPU cost rarely justified for the median use case.

### Query rewriting / expansion

Query transformations conceal one central assumption: the user never formulates their question the way the document is written. Especially acute in domains where users ask questions in everyday language of formal or technical material (policy, legal, regulation, product documentation).

#### Comparison

| Pattern | What it does | Extra calls / latency | Quality uplift | When |
|---|---|---|---|---|
| **HyDE** (Hypothetical Document Embeddings) | The LLM generates a fictional "answer document"; you embed that and use it for retrieval instead of the query. | +1 LLM call (~500-1500 ms) + 1 embedding call | Improves *semantic alignment* between a short query and long documents, especially on short/vague queries. | Short, vague question, large stylistic gap between question and doc. |
| **Multi-query** | The LLM generates N (typ. 3-5) variants of the question, each retrieved separately; results merged (RRF/dedup). | +1 LLM call + N parallel retrievals | +5-15% recall@k on ambiguous queries. | Ambiguous intent, multiple valid interpretations. |
| **Query expansion** (synonyms, translation) | Add terms (synonyms in the corpus language, cross-language terms for multilingual corpora, domain jargon). | +1 LLM call (can be cached) | +3-10% recall on the BM25 leg; especially with domain jargon. | Domain-specific vocabulary, or a multilingual corpus where user and doc use a different language. |
| **Query decomposition** | The LLM splits a complex multi-part question into sub-questions; each sub-question is retrieved separately; answers synthesized. | +1 LLM call + N retrievals + N (small) generation calls | Large uplift on multi-hop. ACL 2026: +35% document precision, +15% α-nDCG. | Conjunctions or multiple aspects. |
| **Step-back prompting** | The LLM generates a more abstract question; retrieve on it for *background*; combine with the original retrieval. | +1 LLM call + 1 extra retrieval | Subtle uplift, strong for policy Q&A. | Very specific question without a broader frame. |

Sources: [LangChain Query Transformations](https://blog.langchain.com/query-transformations/), [Medium - Retrieval is the bottleneck](https://medium.com/@mudassar.hakim/retrieval-is-the-bottleneck-hyde-query-expansion-and-multi-query-rag-explained-for-production-c1842bed7f8a), [ACL Anthology - Query Decomposition for RAG](https://aclanthology.org/2026.eacl-long.322/).

#### Trade-off table

| Pattern | Extra latency p95 | Extra LLM tokens | Recall impact | Faithfulness impact | Risk |
|---|---|---|---|---|---|
| HyDE | +0.5-1.5 s | +200-500 (gen) | neutral/+ | + (better context) | LLM hallucinates the "wrong" doc → retrieves off-topic |
| Multi-query | +1-2 s | +150-300 (gen) | + 5-15% | + | duplicate context, prompt bloat |
| Query expansion | +0.3-0.8 s | +50-150 | + 3-10% | neutral | irrelevant synonyms → drift |
| Decomposition | +2-5 s | +300-800 | + 10-25% on multi-hop | + significant | a wrong decomposition amplifies the error across all hops |
| Step-back | +0.5-1 s | +100-200 | + on specific questions | + (better context) | step-back too abstract → noise |

#### Decision guide

**Platform default:** start with **query expansion** (cheap, a generic domain glossary per project, low risk) + **decomposition** only when a classifier detects multi-part questions. **HyDE** only if baseline retrieval fails on short stylistic-gap queries. **Step-back** as an optional addition in an agentic loop, not as default.

**Selection heuristic (can live in a lightweight classifier node):**
- Query < 5 words, no multi-part → HyDE
- Query contains conjunctions or comparison markers ("and", "also", "difference between", "how does X compare") → Decomposition
- Domain jargon detected (NER hit on the project glossary) → Query expansion
- Query uses a specific article/clause reference → Step-back
- Otherwise → no transformation

**Anti-patterns:**
- Multi-query + decomposition at the same time = N×M retrievals, latency explodes.
- HyDE on queries that *already* use document style: waste.
- Decomposition with >4 sub-questions: cap at N=3.

### GraphRAG

Knowledge-graph RAG was a hype in 2024-25; in 2026 the pragmatic consensus is that it is a specialized pattern, not a replacement for vector RAG.

#### Comparison

| Approach | What it is | Indexing cost (500 pages) | Query cost | Maturity | Strength |
|---|---|---|---|---|---|
| **Microsoft GraphRAG** | The LLM extracts entities + relations → builds a graph → Leiden community detection → community summaries. Local search (entity neighborhood) + Global search (community map-reduce). | $50-200, 45+ min, GPT-4-tier | Global search: expensive (map-reduce over communities); Local: comparable to vector RAG. | Mature open-source (31.6k GitHub stars), Azure ecosystem. | Holistic "what are the main themes across the whole corpus" questions. |
| **LazyGraphRAG** (Microsoft) | Skips up-front extraction; builds the graph lazily at query time. | ≈ vector RAG (0.1% of GraphRAG) | 700× lower than global GraphRAG at comparable global-query quality. | Newer, less battle-tested. | Global questions without the up-front cost. |
| **LightRAG** | Lightweight GraphRAG: simpler entity extraction, flat graph, dual-mode (graph + vector). | ~$0.50, 3 min. Incrementally updatable. | Fast, comparable to vector RAG. | Active (14k stars). | 70-90% of GraphRAG quality on multi-entity questions at 1/100th the cost; works with continuously changing corpora. |
| **Generic KG retrieval-augmented patterns** (Neo4j, NebulaGraph + custom entity extraction) | DIY: your own ontology, populate the graph, run Cypher/Gremlin queries from natural language (LLM → query). | High (engineering time) | Low per query. | Mature stack, but a custom ontology = a lot of work. | When you *already* have a defined domain ontology (product catalog, administrative register, org chart, customer model). |

Sources: [Microsoft Research: LazyGraphRAG](https://www.microsoft.com/en-us/research/blog/lazygraphrag-setting-a-new-standard-for-quality-and-cost/), [Paperclipped 2026 GraphRAG Production Guide](https://www.paperclipped.de/en/blog/graph-rag-production/), [Tongbing Medium - GraphRAG buyer's guide](https://medium.com/@tongbing00/graphrag-in-2026-a-practical-buyers-guide-to-knowledge-graph-augmented-rag-43e5e72d522d), [arXiv: When to use Graphs in RAG](https://arxiv.org/html/2506.05690v3).

#### Trade-off table

| Dimension | Vector RAG (baseline) | LightRAG | LazyGraphRAG | Microsoft GraphRAG |
|---|---|---|---|---|
| Indexing cost relative | 1× | 1× | 1× | 50-200× |
| Indexing time (500 pp) | minutes | ~3 min | ~minutes | 45+ min |
| Incremental update | yes | yes, fine-grained | yes | difficult (re-clustering communities) |
| Local entity question | moderate | good | good | good |
| Global synthesis question | poor | moderate | good | best |
| Multi-hop between entities | moderate | good | good | best |
| Engineering overhead | low | medium | medium | high |

#### Decision guide

**Add GraphRAG when:**
- The use case clearly has **multi-entity, multi-hop questions** ("which party approved decisions that touch on topic X across all documents?").
- You want **global synthesis** ("what are the recurring themes across the whole corpus?") — something vector RAG is poor at.
- The corpus has a **clear ontology** (people, organizations, decisions, domains) with explicit relations.

**Do not do it when:**
- 80% of queries are "single-fact lookup".
- The corpus changes daily (full GraphRAG is then expensive re-indexing).
- The team does not yet have a working vector-RAG baseline.

**Platform default:**
- Start with vector RAG + reranker. GraphRAG is **not the default**.
- If a use-case query profile shows ≥30% "synthesis/multi-hop" queries, **introduce LightRAG** as a parallel retriever in an Adaptive RAG router. Not as a replacement.
- Full Microsoft GraphRAG only for explicit corpus-wide synthesis projects with budget for re-index cycles.

### Agentic RAG

Agentic RAG = the LLM decides *itself* which retrieval path to choose, validates the result, and can run loops. For 80% of queries this is waste; for the difficult 20% it is the difference between "hallucinates" and "answers".

#### Comparison

| Pattern | What it is | Latency | When | When not |
|---|---|---|---|---|
| **Adaptive RAG** (router) | A classifier (small LLM or fine-tuned model) classifies the query: skip retrieval / vector / graph / web. A different pipeline per path. | +50-200 ms for the classifier. | Heterogeneous query load: simple lookups go fast, synthesis questions get the heavier path. | Homogeneous workload. |
| **Self-RAG / Corrective RAG (CRAG)** | LLM-as-judge assesses whether retrieval is relevant; if not → query rewrite + retry, or fall back to web/another source. | +1 LLM call per iteration (typ. 1-2 iters). +1-3 s p95. | A domain where irrelevant retrieval occurs frequently (vague queries, domain-jargon gap). | Latency-critical UI. |
| **Plan-and-execute** (PlanRAG, ReSP, PAR-RAG) | The LLM makes a retrieval plan (sub-goals + order), executes step by step, can re-plan. | +2-8 s. | Genuinely complex research questions. | Daily Q&A — overkill. |
| **Multi-hop retrieval** (ReAct, IRCoT, RT-RAG) | The LLM interleaves thought ↔ retrieve ↔ thought. Hop N uses the answer context of hop N-1 as the query source. | +2-6 s (per hop ~1-2 s). | Questions where the answer only becomes visible after a chain. | Single-hop factual queries. Error-propagation risk. |

Sources: [LangChain agentic RAG docs](https://docs.langchain.com/oss/python/langgraph/agentic-rag), [arXiv: ReSP (2407.13101)](https://arxiv.org/abs/2407.13101), [arXiv: PAR-RAG (2504.16787)](https://arxiv.org/pdf/2504.16787), [arXiv: RT-RAG (2601.11255)](https://arxiv.org/html/2601.11255v1).

#### Trade-off table

| Pattern | Extra p95 latency | Extra LLM calls (typical) | Quality impact | Failure mode |
|---|---|---|---|---|
| Adaptive RAG (router only) | +100-300 ms | +1 (classifier) | +5-10% on average; prevents waste on simple queries | Misclassification → wrong path |
| Corrective / Self-RAG (1 retry) | +1.5-3 s | +2-3 | +10-20% on vague queries | Infinite retry loop without a cap |
| Plan-and-execute | +3-8 s | +5-10 | +15-30% on complex; -% on simple (overkill) | A bad plan = a bad answer; high cost |
| Multi-hop (3 hops) | +3-6 s | +3-6 retrievals + judge calls | Significant on multi-hop; zero on single-hop | Error propagation between hops |

#### Decision guide

**Step-by-step plan for the platform stack:**
1. **Do not start with agentic.** First get the baseline + reranker working.
2. **First agentic step = Adaptive Router.** A 3-4-class classifier (factual lookup / synthesis / multi-hop / conversational) on top of existing pipelines.
3. **Second step = Self-RAG / Corrective grading** in the "synthesis" and "multi-hop" paths. *Not* on factual lookup.
4. **Third step (only with proven need) = Plan-and-execute** for genuine research questions.
5. **Multi-hop separately**: only if the router tags the query as multi-hop, cap at N=3 with a circuit breaker.

**Mandatory controls with agentic:**
- Hard cap on iterations (max 3 retries Self-RAG, max 3 hops multi-hop, max 4 sub-goals plan-and-execute).
- Token budget per query (e.g. 50k input-token hard limit).
- Latency circuit breaker (kill after 10 s, fall back to the baseline answer).
- LangSmith tracing with `iteration_count`, `retrieval_round`, `token_budget_used` per node.

**When agentic has no ROI:**
- Latency requirement <2 s p95.
- The corpus is small and queries homogeneous.
- Budget is a hard constraint — agentic multiplies LLM costs 3-10×.

---

## RAG-specific NFRs

NFRs for RAG are not just about "uptime"; most quality failure modes are *invisible to end-to-end metrics*. A TD for a RAG system must specify NFRs on three layers: **retrieval**, **generation**, and **operational pipeline**.

### NFRs covered

#### 1. Retrieval latency
Time from query arrival to top-k chunks available (excl. generation). Tracing on the retriever call; P50/P95/P99 on a gold set, at least weekly. The reranker is often the p99 culprit — measure it separately ([Future AGI](https://futureagi.com/blog/evaluating-cohere-rerank-rag-2026/)).

#### 2. Relevance (Recall@k, MRR, nDCG, hit rate)
- **Recall@k**: how often a relevant chunk appears in the top-k.
- **MRR**: how quickly the first relevant chunk comes up (single-answer).
- **nDCG@k**: ranking quality with graded relevance (multi-relevant).
- **Hit rate**: at least one relevant in the top-k — a debug metric.

A gold set of 100-300 queries in the target language with human-labeled relevant chunk IDs, per use case. RAGAS or DeepEval; fail on regression. A synthetic eval set can be a starter, SME validation is required ([CallSphere](https://callsphere.ai/blog/rag-evaluation-frameworks-2026-ragas-trulens-deepeval)).

Defaults: Recall@5 ≥ 80% for FAQ-style; Recall@10 ≥ 75% for long documents. MRR ≥ 0.7 for single-fact. nDCG@5 ≥ 0.75 with the reranker active.

#### 3. Citation accuracy (claim-to-source matching, hallucination rate)
Per atomic claim: is it supported by the cited source? RAGAS `faithfulness`, RAGChecker, Google's grounding-check API; LLM-as-judge plus sample-based human audits (≥30 answers/week). **Indispensable for regulated/high-stakes domains** (administrative, legal, compliance, medical, financial): "fake citations" are the biggest reputational and legal risk there. Defaults: Faithfulness ≥ 0.85 general; ≥ 0.90 for regulated ([Future AGI](https://futureagi.com/blogs/rag-evaluation-metrics-2025), [Medium - Fake Citations](https://medium.com/@Nexumo_/rag-grounding-11-tests-that-expose-fake-citations-30d84140831a)).

#### 4. Freshness
Time between a change to the source and its visibility in the index. A lifecycle tag per document; monitor on `now() - source_updated_at > SLA`. Tier content by decay rate. A **named owner per content domain** is an organizational NFR; without an owner, freshness alerts are wishful thinking ([TianPan](https://tianpan.co/blog/2026-04-17-enterprise-rag-knowledge-base-governance), [RAGAboutIt](https://ragaboutit.com/the-rag-freshness-paradox-why-your-enterprise-agents-are-making-decisions-on-yesterdays-data/)). Defaults: high-decay <1h, medium <24h, low <7 days.

#### 5. Index size / cost
Cost attribution per node in LangSmith; aggregate cost-per-query as a KPI; alert on regression >20% week-over-week. For mid-size workloads (10k queries/month): <$50/month total LLM+rerank feasible with self-hosted BGE + paid rerank only for difficult queries.

#### 6. End-to-end latency (retrieval + generation)
Time-to-first-token (TTFT) and time-to-complete (TTC) separately; P50/P95/P99. Defaults: Simple RAG P95 <2s; Agentic RAG P95 <8s; research-style synthesis P95 <5s acceptable provided TTFT <1.5s so that the user gets feedback.

#### 7. Availability of the retrieval pipeline
Vector-store health checks + active synthetic-query monitoring; ingest SLA; reranker fallback on API failure. Defaults: 99.5% interactive / 99.9% high-stakes production. **Degraded-mode requirement**: on reranker failure run without rerank; on vector-store partial failure a clear error, not a silently incomplete answer.

### Default NFR table

> Paste this directly as TR-xx in a TD. Adjust targets per archetype:
> - **Interactive / low-stakes (LS)**: chatbot, FAQ, fast Q&A.
> - **Interactive / high-stakes (HS)**: administrative advice, legal, compliance, customer contact in regulated domains.
> - **Batch / asynchronous (B)**: research summaries, nightly digest.

| TR | NFR | Measurement method | Target LS-interactive | Target HS-interactive | Target Batch |
|---|---|---|---|---|---|
| TR-RAG-01 | Retrieval latency P95 | Tracing on retriever call | <500 ms | <800 ms | <5 s |
| TR-RAG-02 | Retrieval latency P99 | Tracing | <1 s | <1.5 s | <10 s |
| TR-RAG-03 | Recall@10 on gold set | RAGAS / manual | ≥75% | ≥85% | ≥90% |
| TR-RAG-04 | nDCG@5 on gold set | RAGAS / manual | ≥0.70 | ≥0.80 | ≥0.85 |
| TR-RAG-05 | MRR (single-answer queries) | RAGAS | ≥0.65 | ≥0.75 | ≥0.80 |
| TR-RAG-06 | Faithfulness (claim support) | RAGAS / DeepEval | ≥0.80 | ≥0.90 | ≥0.92 |
| TR-RAG-07 | Citation precision (cited source supports claim) | Human audit + LLM judge | ≥0.85 | ≥0.95 | ≥0.95 |
| TR-RAG-08 | Hallucination rate (claims not in source) | RAGAS faithfulness inverse | ≤10% | ≤3% | ≤3% |
| TR-RAG-09 | Freshness SLA - high-decay docs | `now() - source_updated_at` monitor | <1 hour | <15 min | <1 hour |
| TR-RAG-10 | Freshness SLA - medium-decay (adopted documents, policy) | same | <24 hours | <4 hours | <24 hours |
| TR-RAG-11 | Freshness SLA - low-decay (historical) | same | <7 days | <7 days | <30 days |
| TR-RAG-12 | Named content owner per domain | Governance audit | mandatory | mandatory | mandatory |
| TR-RAG-13 | End-to-end latency P95 (TTC) | Distributed tracing | <2 s | <5 s | <30 s |
| TR-RAG-14 | Time-to-first-token P95 | Streaming tracing | <800 ms | <1.5 s | n/a |
| TR-RAG-15 | Retrieval pipeline uptime | Synthetic monitoring | 99.5% | 99.9% | 99.5% |
| TR-RAG-16 | Degraded mode on reranker failure | Failover test (chaos) | functional without rerank | functional without rerank, with user warning | n/a |
| TR-RAG-17 | Cost per 1k queries | Cost attribution per node | <$5 | <$15 | <$2 |
| TR-RAG-18 | Index update SLA (ingest → searchable) | Event tracing | <30 min | <5 min | <1 hour |
| TR-RAG-19 | CI gate on faithfulness and latency regressions | DeepEval in PR pipeline | mandatory | mandatory | mandatory |
| TR-RAG-20 | Gold-set maintenance (weekly refresh, ≥100 queries) | Process | mandatory | mandatory (≥300 queries) | recommended |
| TR-RAG-21 | PII / classification tagging before indexing | Pipeline gate | mandatory | mandatory | mandatory |
| TR-RAG-22 | Lineage per chunk (`source_id`, `version`, `ingested_at`) | Schema validation | mandatory | mandatory | mandatory |

---

## Final recommendation

RAG is offered in Druppie as a **generic platform building block** behind the `module-rag` MCP interface. The choices below are the platform defaults — valid for any doc-heavy use case regardless of language or domain. Per project, an architect may deviate from them, but only with an explicit trigger from the decision guides (corpus size, query type, latency budget, language mix, stakes). Goal: one well-founded building block that fits out of the box in 80% of use cases, and in the remaining 20% with a targeted upgrade as well.

### Platform default stack

| Layer | Default | Trigger to deviate |
|---|---|---|
| Chunking | Recursive 512-token (tiktoken encoder), 10–20% overlap | Upgrade to parent-document/hierarchical as soon as citations become too narrow/broad; add late chunking for anaphora-heavy text |
| Retrieval | Hybrid (BM25 + dense) with RRF k=60 | Pure-vector only temporarily; ColBERT for a measured gap on out-of-domain queries |
| BM25 analyzer | Postgres `to_tsvector('<corpus-language>', ...)` per field | Multilingual analyzer for mixed-language corpora; mandatory per language, not one global setting |
| Metadata filter | SQL joins on `doc_type`, `datum`, `status`, `tenant`, `acl` | To Qdrant in-graph filtering as soon as p95 on filtered ANN becomes a hard requirement |
| Embedding | `multilingual-e5-large-instruct` (MIT, ~2 GB, CPU-feasible, broad multilingual coverage) | Qwen3-Embedding-4B with an ≥8 GB GPU budget and a quality requirement; BGE-M3 with a preference for hybrid-with-one-model |
| Vector store | **pgvector** (already part of the Postgres stack — no extra service) | Qdrant with >10M chunks, a hard p95 requirement on filtered ANN, or hybrid becoming central enough that manual RRF becomes too brittle |
| Re-ranking | BGE-reranker-v2-m3 self-hosted (Apache 2.0) | Cohere Rerank (Bedrock EU) as soon as the use-case gold set shows a ≥5 nDCG-point difference |
| Query transformation | Query expansion (cheap, project glossary) + classifier-gated decomposition | HyDE for short/vague queries with a stylistic gap; step-back in an agentic loop |
| GraphRAG | **Not default** | LightRAG as a parallel retriever in an Adaptive Router as soon as ≥30% of use-case queries prove to be multi-entity/synthesis |
| Agentic loop | **Not default** — Adaptive Router as the only first agentic step | Self-RAG/CRAG in the synthesis path with a proven vague-query problem; plan-and-execute only for research questions |
| Citations | Content-hash chunk IDs + page/paragraph metadata + parent-section title; footnote style in formal output + anchor tags for the UI | Sentence-level span tracking for legal/compliance precision (Claude Citations API or post-hoc matching) |
| NFRs | TR-RAG-01 through TR-RAG-22, targets per archetype (LS / HS / Batch) | Tune targets per use case; the archetype choice (LS vs HS vs B) determines the threshold |

### Pragmatic build order

1. **Foundation**: `module-rag` MCP interface, pgvector schema, `multilingual-e5-large-instruct` embedding (via a dedicated MCP server or a `module-llm` extension), basic tools (`index_documents`, `search`, `get_chunk`, `delete_index`, `list_indices`).
2. **Production quality**: language-specific BM25 column(s), hybrid search with RRF, metadata filtering, content-hash chunk IDs, parent-section title.
3. **Quality safety net**: BGE-reranker-v2-m3, faithfulness CI gate (RAGAS in the PR pipeline), a per-use-case gold set, footnote citations in the output.
4. **Smart when needed**: parent-document chunking for long structured documents, late chunking when anaphora falter, query expansion + decomposition gated by a classifier.
5. **Only with proven need**: Adaptive Router, LightRAG-parallel, Self-RAG in the synthesis path, an escape hatch to Qdrant.

### Validation scenarios

The choices above are validated in Story A's e2e test and Story B on at least:
- **HDSR notes** (Dutch-language, long structured documents, administrative stakes, hard citation requirement) — as a smoke test that touches several difficult axes at once.
- Additional scenarios per use case when a project starts to consume `module-rag`.

### Open questions for MODULE_SPEC

1. **Embedding-server placement**: does the embedding call become a dedicated MCP server (`module-embedding`), a tool in `module-llm`, or a direct library call within `module-rag`? Has a direct impact on the MODULE_SPEC. Proposal: a separate tool group in `module-llm` so that embedding and generation fall under the same model/resource management; `module-rag` consumes via MCP.
2. **Tenant and index isolation**: support for logical isolation via a `tenant_id` filter within one pgvector table, or the option for physically separated indexes per client/project? Affects the MODULE_SPEC schema and TR-RAG-21 (PII/classification).
3. **Document pre-processing**: PDF/Word/HTML → text + page/section metadata — does this belong to `module-rag` (one tool indexes a "raw document") or does it fall outside the module (the caller extracts itself and sends structured text)? The former = easier for app builders; the latter = a simpler module with a cleaner contract.
4. **Re-ranker placement**: baked into `module-rag` (default on) or as a separate `module-reranker` so that different rerankers can be chosen per use case? Proposal: in `module-rag` with a config toggle for v1, a separate module as v2 when multiple rerankers prove necessary.
5. **Module-name confirmation**: `module-rag` was chosen instead of `module-vectorstore` because the architect thinks in "RAG" terms. The tool list (index_documents / search / get_chunk / delete_index / list_indices) makes the scope clear — if the name raises objections (too promising in terms of "Generation"), now is the moment to correct it.

---

## Sources

### Chunking, Retrieval & Citations
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

### Embedding models & Vector stores
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

### Advanced patterns & NFRs
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
</content>
</invoke>
