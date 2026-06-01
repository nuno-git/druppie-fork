CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS indices (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id      TEXT NOT NULL,
    name            TEXT NOT NULL,
    description     TEXT NOT NULL DEFAULT '',
    embedding_model TEXT NOT NULL DEFAULT 'default',
    dimensions      INTEGER NOT NULL DEFAULT 0,
    chunk_size      INTEGER NOT NULL DEFAULT 1000,
    chunk_overlap   INTEGER NOT NULL DEFAULT 200,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (project_id, name)
);

CREATE TABLE IF NOT EXISTS documents (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    index_id        UUID NOT NULL REFERENCES indices(id) ON DELETE CASCADE,
    source_name     TEXT NOT NULL,
    source_type     TEXT NOT NULL DEFAULT 'text',
    chunk_count     INTEGER NOT NULL DEFAULT 0,
    metadata        JSONB NOT NULL DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_documents_index_id ON documents(index_id);

CREATE TABLE IF NOT EXISTS chunks (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    index_id        UUID NOT NULL REFERENCES indices(id) ON DELETE CASCADE,
    document_id     UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    chunk_index     INTEGER NOT NULL,
    content         TEXT NOT NULL,
    embedding       vector,
    source_name     TEXT NOT NULL DEFAULT '',
    source_page     INTEGER,
    source_section  TEXT,
    metadata        JSONB NOT NULL DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_chunks_index_id ON chunks(index_id);
CREATE INDEX IF NOT EXISTS idx_chunks_document_id ON chunks(document_id);
