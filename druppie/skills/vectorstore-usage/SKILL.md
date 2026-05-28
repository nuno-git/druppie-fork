---
name: vectorstore-usage
description: >
  How to use module-vectorstore tools for semantic search over indexed
  document collections. Covers search, citation, and result interpretation.
  Invoke when you have vectorstore tools available and need to search
  or explore indexed documents.
allowed-tools:
  vectorstore:
    - search
    - get_chunk
    - list_indices
    - index_documents
    - delete_index
---

# Vectorstore Usage Guide

## Available Tools

### vectorstore_list_indices()
List all indexed document collections for the current project. Use this
first to discover what's available before searching.

Returns: index name, description, document count, chunk count, embedding
model, and chunk size settings per index.

### vectorstore_search(index_name, query, top_k=5, similarity_threshold=0.0, filter_metadata=None)
Semantic search over an indexed document collection. Returns the most
relevant text chunks ranked by similarity score.

**Parameters:**
- `index_name` — which index to search (from list_indices)
- `query` — natural language question or search phrase
- `top_k` — number of results to return (default 5, increase for broader context)
- `similarity_threshold` — minimum similarity score (0.0-1.0, default 0.0 = no filter)
- `filter_metadata` — optional dict to narrow results by metadata fields
  (e.g., `{"document_type": "nota", "year": "2025"}`)

**Result fields per chunk:**
- `content` — the chunk text
- `score` — similarity score (0.0-1.0, higher = more relevant)
- `source_name` — original document name or URI
- `source_page` — page number (if available)
- `source_section` — section heading (if available)
- `chunk_id` — unique ID for use with get_chunk
- `metadata` — caller-defined metadata attached at indexing time

### vectorstore_get_chunk(chunk_id)
Retrieve a specific chunk by ID. Use after search when you need the full
context of a result, including all source metadata for citation.

### vectorstore_index_documents(index_name, documents, chunk_size=1000, chunk_overlap=200)
Index documents for semantic search. Each document in the list needs:
- `content` (required) — full text to index
- `source_name` (required) — original filename or URI
- `source_type` — text, pdf, markdown, html (default: text)
- `source_page` — page number
- `source_section` — section heading
- `metadata` — arbitrary dict for filtering (e.g., `{"year": "2025"}`)

### vectorstore_delete_index(index_name)
Delete an entire index and all its documents and chunks. Irreversible.

## When to Search

- **Context gathering:** Search indexed documents to understand the domain
  before making decisions.
- **Research phase:** Find relevant precedents, policies, or reference
  material to ground your analysis.
- **Answering questions:** Retrieve specific passages from documents to
  answer user questions with citations.
- **Similarity check:** Search for related existing content before
  creating new documents.

## How to Cite

Every search result includes source metadata for traceability. Use this
format when referencing content from search results:

```
[source_name, p. source_page, §source_section]
```

Example: [Nota Waterkwaliteit 2025.pdf, p. 12, §3.2 Normen]

When source_page or source_section is null, omit that part:
- `[Beleidsdocument.pdf, §Inleiding]`
- `[Rapport 2024.pdf, p. 5]`
- `[Handleiding.md]`

## Search Tips

1. **Be specific in queries** — "waterkwaliteitsnormen voor stikstof"
   returns better results than "normen"
2. **Use metadata filters** to narrow scope — filter by document type,
   year, or category when the index contains diverse documents
3. **Increase top_k** (e.g., 10-15) when you need broader context or
   aren't sure which documents are relevant
4. **Use similarity_threshold** (e.g., 0.5) to filter out low-quality
   matches when you need only high-confidence results
5. **Multiple queries** — rephrase and search again if the first query
   doesn't return relevant results; different phrasings surface
   different chunks
