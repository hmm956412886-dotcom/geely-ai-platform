"""Persistence boundary for normalized knowledge documents."""

from __future__ import annotations

from hashlib import sha256
import json
from typing import Any, Protocol
from uuid import uuid4


class Cursor(Protocol):
    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> Any:
        ...


class Connection(Protocol):
    def cursor(self) -> Any:
        ...

    def commit(self) -> None:
        ...

    def rollback(self) -> None:
        ...


def save_normalized_document(
    connection: Connection,
    document: dict[str, Any],
    *,
    sync_status: str = "normalized",
) -> str:
    """Persist a normalized document and enqueue an index job.

    Sections and ACL entries are replaced as a document-level snapshot. That is
    simpler and safer than trying to diff partial Feishu block changes before
    the real API connector exists.
    """

    job_id = str(uuid4())
    cursor_context = connection.cursor()
    try:
        with cursor_context as cursor:
            _upsert_document(cursor, document, sync_status)
            _replace_sections(cursor, document)
            _replace_acl(cursor, document)
            _create_index_job(cursor, document["document_id"], job_id)
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    return job_id


def _upsert_document(
    cursor: Cursor,
    document: dict[str, Any],
    sync_status: str,
) -> None:
    cursor.execute(
        """
        INSERT INTO source_documents (
            document_id,
            source_type,
            space_id,
            node_token,
            object_token,
            title,
            source_url,
            updated_at,
            content_hash,
            sync_status,
            last_synced_at,
            changed_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now(), now())
        ON CONFLICT (document_id) DO UPDATE SET
            source_type = EXCLUDED.source_type,
            space_id = EXCLUDED.space_id,
            node_token = EXCLUDED.node_token,
            object_token = EXCLUDED.object_token,
            title = EXCLUDED.title,
            source_url = EXCLUDED.source_url,
            updated_at = EXCLUDED.updated_at,
            content_hash = EXCLUDED.content_hash,
            sync_status = EXCLUDED.sync_status,
            last_synced_at = now(),
            changed_at = now()
        """,
        (
            document["document_id"],
            document["source_type"],
            document.get("space_id"),
            document.get("node_token"),
            document.get("object_token"),
            document["title"],
            document["source_url"],
            document["updated_at"],
            document.get("content_hash"),
            sync_status,
        ),
    )


def _replace_sections(cursor: Cursor, document: dict[str, Any]) -> None:
    document_id = document["document_id"]
    cursor.execute(
        "DELETE FROM knowledge_sections WHERE document_id = %s",
        (document_id,),
    )
    for ordinal, section in enumerate(document.get("sections", []), start=1):
        cursor.execute(
            """
            INSERT INTO knowledge_sections (
                section_id,
                document_id,
                section_ordinal,
                heading_path,
                content,
                content_hash,
                page_no,
                block_id,
                changed_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, now())
            """,
            (
                f"{document_id}:{section['section_id']}",
                document_id,
                ordinal,
                section.get("heading_path", []),
                section["content"],
                _section_hash(section),
                section.get("page_no"),
                section.get("block_id"),
            ),
        )


def _replace_acl(cursor: Cursor, document: dict[str, Any]) -> None:
    document_id = document["document_id"]
    cursor.execute(
        "DELETE FROM source_acl_entries WHERE document_id = %s",
        (document_id,),
    )
    for entry in document.get("acl", []):
        cursor.execute(
            """
            INSERT INTO source_acl_entries (
                document_id,
                principal_type,
                principal_id,
                permission,
                source,
                changed_at
            )
            VALUES (%s, %s, %s, %s, %s, now())
            """,
            (
                document_id,
                entry["principal_type"],
                entry["principal_id"],
                entry["permission"],
                "feishu",
            ),
        )


def _create_index_job(cursor: Cursor, document_id: str, job_id: str) -> None:
    cursor.execute(
        """
        INSERT INTO sync_jobs (
            job_id,
            document_id,
            job_type,
            status,
            payload
        )
        VALUES (%s, %s, %s, %s, %s::jsonb)
        """,
        (
            job_id,
            document_id,
            "index",
            "pending",
            json.dumps({"document_id": document_id}, separators=(",", ":")),
        ),
    )


def _section_hash(section: dict[str, Any]) -> str:
    payload = {
        "heading_path": section.get("heading_path", []),
        "content": section["content"],
        "page_no": section.get("page_no"),
        "block_id": section.get("block_id"),
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(encoded).hexdigest()

