---
name: rag-patterns
description: >
  Decision guide for RAG (Retrieval-Augmented Generation) patterns.
  Covers chunking strategy, retrieval patterns, citation tracking,
  embedding choices, and module-vectorstore configuration. Use when
  a functional design involves document search, knowledge bases,
  source references, or large-document processing.
---

# RAG Pattern Decision Guide

## 1. When to Use RAG

Use this decision tree to determine if a project needs RAG:

```
Does the project need to answer questions from a document corpus?
  NO  -> RAG is not needed. Stop here.
  YES -> Is the corpus small enough to fit in a single LLM context window (<50 pages)?
           YES -> Consider prompt-stuffing (include full text in prompt). RAG optional.
           NO  -> RAG is needed. Continue below.
                  Does the corpus change over time?
                    YES -> Use incremental indexing (re-index on change).
                    NO  -> Index once at setup.
                  Are source citations required in the output?
                    YES -> Citation tracking is mandatory (see Section 5).
                    NO  -> Citation tracking is recommended but optional.
```

**RAG indicators in a functional design:**
- "Doorzoeken van beleidsdocumenten" / searching policy documents
- "Bronverwijzingen" / source references or citations
- "Kennisbank" / knowledge base
- "Documenten als input voor antwoorden" / documents as input for answers
- "Grote documenten verwerken" / processing large documents
- References to specific document collections (notas, rapporten, beleidsstukken)

## 2. RAG Pattern Catalog

### Pattern A — Simple RAG (Index-then-Search)

**How it works:** Documents are chunked and indexed once (or on change).
At query time, the query is embedded, similar chunks are retrieved, and
passed as context to the LLM for answer generation.

**Best for:** Static document collections, FAQ-style retrieval, reference
lookup where the user asks a single question.

**Trade-offs:**
| Aspect | Assessment |
|--------|------------|
| Complexity | Low — straightforward pipeline |
| Latency | Low — single search + single LLM call |
| Accuracy | Good for factual lookup, weaker for multi-hop reasoning |
| Citation | Directly available from search results |

**module-vectorstore usage:**
1. `index_documents` at setup or document upload
2. `search` per user query
3. Pass results as context to `module-llm` chat

### Pattern B — Conversational RAG

**How it works:** Extends Simple RAG with conversation history. The user's
question is rewritten using chat history before searching, so follow-up
questions resolve pronouns and context.

**Best for:** Interactive Q&A sessions where users ask follow-up questions
about documents. Chat-based interfaces.

**Trade-offs:**
| Aspect | Assessment |
|--------|------------|
| Complexity | Medium — needs query rewriting step |
| Latency | Medium — extra LLM call for query rewriting |
| Accuracy | Better for multi-turn conversations |
| Citation | Same as Simple RAG |

**Implementation:** Use `module-llm` to rewrite the query incorporating
chat history, then proceed as Simple RAG.

### Pattern C — Agentic RAG

**How it works:** An agent decides when and what to search. It may perform
multiple searches with different queries, combine results across indices,
and reason about whether it has enough information before answering.

**Best for:** Complex multi-step reasoning, cross-document analysis,
tasks where the agent must synthesise information from multiple sources.

**Trade-offs:**
| Aspect | Assessment |
|--------|------------|
| Complexity | High — agent loop with search tool |
| Latency | Higher — multiple search iterations possible |
| Accuracy | Highest for complex questions |
| Citation | Requires aggregation across multiple searches |

**Implementation:** Give the agent `vectorstore_search` as an MCP tool.
The agent's system prompt instructs it to search before answering and to
cite sources from results.

## 3. Chunking Strategy Decision Tree

```
What type of document?
  Unstructured text (prose, policy docs, reports)
    -> chunk_size: 1000, chunk_overlap: 200 (default)

  Structured with clear sections (markdown, HTML with headings)
    -> chunk_size: 1500, chunk_overlap: 200
       Set source_section per chunk for better citation

  Tables / structured data
    -> chunk_size: 500, chunk_overlap: 50
       Keep rows together, don't split mid-row

  Legal / regulatory text
    -> chunk_size: 800, chunk_overlap: 300
       Higher overlap preserves cross-reference context

  Mixed content (text + tables + diagrams)
    -> Pre-process: split by content type first, then chunk each type
       with its own settings
```

**Rules of thumb:**
- Smaller chunks (500-800) → higher precision, less context per result
- Larger chunks (1000-2000) → more context, but may dilute relevance
- Overlap (10-30% of chunk_size) → prevents losing information at boundaries
- Always split at sentence boundaries, never mid-word

## 4. Retrieval & Search Patterns

### Vector-only search (default)
Use `module-vectorstore` `search` tool with just a query. Best for
semantic/meaning-based questions.

### Metadata-filtered search
Use `filter_metadata` parameter to narrow results. Best when documents
have known categories, dates, or types.

Example: search within a specific document type:
```
search(index_name="beleidsdocumenten", query="waterkwaliteitsnorm",
       filter_metadata={"document_type": "nota"})
```

### Multi-index search
Search multiple indices and merge results. Best for cross-domain
questions that span different document collections.

### Hybrid search (vector + metadata)
Combine semantic search with metadata filters for the best balance of
relevance and precision. This is the **recommended default** for most
water authority use cases.

## 5. Citation Tracking Pipeline

Every search result from `module-vectorstore` includes:
- `source_name` — original document filename or URI
- `source_page` — page number (when available)
- `source_section` — section heading (when available)
- `chunk_index` — position within the document

**Citation format for generated answers:**

```
[source_name, p. source_page, §source_section]
```

Example: [Nota Waterkwaliteit 2025.pdf, p. 12, §3.2 Normen]

**Pipeline:**
1. Search returns ranked chunks with source metadata
2. LLM generates answer using chunks as context
3. LLM instruction: "Cite every claim using [source, page, section] format"
4. Verify citations map back to actual search results

**TR requirements for citation-driven projects:**
- TR-xx: Every generated claim MUST include a source citation traceable
  to an indexed document (Principle 13: Traceability, Principle 15:
  Reliability)
- TR-xx: Citation accuracy: ≥95% of citations must correctly reference
  the source chunk content
- TR-xx: Source provenance: the system must store and expose the full
  chain from generated answer → cited chunk → source document

## 6. Embedding & Vector Store Choices

### Platform defaults (use unless there's a reason to deviate)

| Setting | Default | Rationale |
|---------|---------|-----------|
| Vector store | `module-vectorstore` (pgvector) | Platform standard, managed |
| Embedding model | Platform default via `module-llm` | Centrally configured, multilingual |
| Dimensions | Determined by model (auto-detected) | No manual config needed |
| Distance metric | Cosine similarity | Best for text embeddings |
| Index type | HNSW | Best recall/speed trade-off |

### When to deviate

- **Self-hosted embedding model:** Only if data sovereignty requires it
  (data cannot leave the network). Requires extending `module-llm` with
  a local model backend.
- **Different vector store:** Only if pgvector performance is insufficient
  for the scale (>10M chunks). For most water authority use cases,
  pgvector handles the volume.

## 7. RAG-Specific NFR Defaults

Use these as starting points for TR-xx requirements in the TD:

| Requirement | Default target | Verification |
|-------------|---------------|--------------|
| Retrieval latency | < 2 seconds for top-5 results | Performance test |
| Relevance score | > 0.7 similarity threshold for included results | Relevance evaluation |
| Citation accuracy | ≥ 95% of citations traceable to source | Manual + automated audit |
| Index freshness | Re-indexed within 1 hour of document change | Integration test |
| Chunk completeness | No information loss at chunk boundaries | Manual review of chunk samples |

## 8. module-vectorstore Integration Pattern

### Indexing documents (at setup or document upload)

```python
result = druppie.call("vectorstore", "index_documents", {
    "index_name": "beleidsdocumenten",
    "documents": [
        {
            "content": "Full text of document...",
            "source_name": "Nota Waterkwaliteit 2025.pdf",
            "source_type": "pdf",
            "source_page": 1,
            "source_section": "Inleiding",
            "metadata": {"year": "2025", "type": "nota"}
        }
    ],
    "chunk_size": 1000,
    "chunk_overlap": 200,
    "description": "Beleidsdocumenten waterschap"
})
```

### Searching (at query time)

```python
results = druppie.call("vectorstore", "search", {
    "index_name": "beleidsdocumenten",
    "query": "Wat zijn de waterkwaliteitsnormen voor 2025?",
    "top_k": 5
})
```

### Generating answer with citations

Pass search results as context to module-llm with citation instructions:

```python
context = "\n\n".join([
    f"[{r['source_name']}, p.{r['source_page']}, §{r['source_section']}]:\n{r['content']}"
    for r in results["results"]
])

answer = druppie.call("llm", "chat", {
    "prompt": f"Beantwoord de vraag op basis van de bronnen. Citeer elke claim.\n\nBronnen:\n{context}\n\nVraag: {query}",
    "system": "Je bent een beleidsmedewerker. Gebruik alleen de gegeven bronnen. Citeer met [bron, pagina, sectie] formaat."
})
```

## 9. Anti-Patterns

| Anti-pattern | Problem | Correct approach |
|-------------|---------|------------------|
| Indexing all documents in one batch | Memory pressure, timeout risk | Batch in groups of 10-50 documents |
| No project_id scoping | Data leaks between projects | Always use project-scoped indices |
| Ignoring chunk boundaries | Sentences split mid-word | Use module-vectorstore defaults (sentence-aware splitting) |
| Skipping metadata | No way to filter or cite | Always set source_name, source_page, source_section |
| Very large chunks (>3000 chars) | Diluted relevance scores | Keep chunks 500-1500 chars |
| Very small chunks (<200 chars) | Lost context | Minimum 500 chars recommended |
| Building custom vector store | Duplicates platform capability | Use module-vectorstore |
| Direct embedding API calls | Bypasses centralized model config | Use module-llm embed tool |
