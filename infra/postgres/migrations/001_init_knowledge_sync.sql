-- P0-002: Knowledge sync metadata.
-- This migration keeps only the tables required for the first Feishu sync and
-- indexing loop. Business users, projects, vector collections, and search
-- indexes are intentionally left out until the retrieval service needs them.

CREATE TABLE IF NOT EXISTS source_documents (
    document_id TEXT PRIMARY KEY,
    source_type TEXT NOT NULL CHECK (
        source_type IN (
            'feishu_docx',
            'feishu_sheet',
            'feishu_base',
            'feishu_file'
        )
    ),
    space_id TEXT,
    node_token TEXT,
    object_token TEXT,
    title TEXT NOT NULL,
    source_url TEXT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    content_hash TEXT,
    sync_status TEXT NOT NULL DEFAULT 'discovered' CHECK (
        sync_status IN (
            'discovered',
            'fetching',
            'normalized',
            'indexing',
            'active',
            'permission_denied',
            'fetch_failed',
            'parse_failed',
            'index_failed',
            'deleted'
        )
    ),
    last_synced_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    changed_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_source_documents_feishu_node
    ON source_documents (source_type, node_token)
    WHERE node_token IS NOT NULL;

CREATE INDEX IF NOT EXISTS ix_source_documents_status
    ON source_documents (sync_status, changed_at);

CREATE TABLE IF NOT EXISTS knowledge_sections (
    section_id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES source_documents (document_id) ON DELETE CASCADE,
    section_ordinal INTEGER NOT NULL CHECK (section_ordinal > 0),
    heading_path TEXT[] NOT NULL DEFAULT '{}',
    content TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    page_no INTEGER,
    block_id TEXT,
    embedding_id TEXT,
    indexed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    changed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (document_id, section_ordinal)
);

CREATE INDEX IF NOT EXISTS ix_knowledge_sections_document
    ON knowledge_sections (document_id, section_ordinal);

CREATE INDEX IF NOT EXISTS ix_knowledge_sections_embedding
    ON knowledge_sections (embedding_id)
    WHERE embedding_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS source_acl_entries (
    acl_entry_id BIGSERIAL PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES source_documents (document_id) ON DELETE CASCADE,
    principal_type TEXT NOT NULL CHECK (
        principal_type IN (
            'user',
            'department',
            'group',
            'app',
            'role'
        )
    ),
    principal_id TEXT NOT NULL,
    permission TEXT NOT NULL CHECK (
        permission IN (
            'read',
            'write',
            'admin'
        )
    ),
    source TEXT NOT NULL DEFAULT 'feishu',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    changed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (document_id, principal_type, principal_id, permission)
);

CREATE INDEX IF NOT EXISTS ix_source_acl_principal
    ON source_acl_entries (principal_type, principal_id, permission);

CREATE TABLE IF NOT EXISTS sync_jobs (
    job_id UUID PRIMARY KEY,
    document_id TEXT REFERENCES source_documents (document_id) ON DELETE SET NULL,
    job_type TEXT NOT NULL CHECK (
        job_type IN (
            'discover',
            'full',
            'incremental',
            'delete',
            'index'
        )
    ),
    status TEXT NOT NULL DEFAULT 'pending' CHECK (
        status IN (
            'pending',
            'running',
            'success',
            'failed'
        )
    ),
    attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    error_code TEXT,
    error_message TEXT,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS ix_sync_jobs_status
    ON sync_jobs (status, created_at);

CREATE INDEX IF NOT EXISTS ix_sync_jobs_document
    ON sync_jobs (document_id, created_at);

