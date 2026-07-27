"""Convert a Feishu document snapshot into the platform document contract."""

from __future__ import annotations

from hashlib import sha256
import json
from typing import Any


_HEADING_TYPES = {
    "heading1": 1,
    "heading2": 2,
    "heading3": 3,
    "heading4": 4,
    "heading5": 5,
    "heading6": 6,
}

_SOURCE_TYPE_BY_OBJECT = {
    "doc": "feishu_docx",
    "docx": "feishu_docx",
    "sheet": "feishu_sheet",
    "bitable": "feishu_base",
    "base": "feishu_base",
    "file": "feishu_file",
}


def normalize_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Normalize one already-fetched Feishu document snapshot.

    The function intentionally knows nothing about Feishu authentication or API
    pagination. Those concerns belong to the connector layer. Keeping this
    boundary pure makes it testable with fixtures and reusable for other
    document sources later.
    """

    document_id = _required_string(snapshot, "document_id")
    title = _required_string(snapshot, "title")
    source_url = _required_string(snapshot, "source_url")
    updated_at = _required_string(snapshot, "updated_at")
    object_type = _required_string(snapshot, "obj_type").lower()
    source_type = _SOURCE_TYPE_BY_OBJECT.get(object_type)
    if source_type is None:
        raise ValueError(f"Unsupported Feishu object type: {object_type}")

    sections = _build_sections(snapshot.get("blocks", []))
    normalized: dict[str, Any] = {
        "document_id": document_id,
        "source_type": source_type,
        "space_id": snapshot.get("space_id"),
        "node_token": snapshot.get("node_token"),
        "object_token": snapshot.get("obj_token"),
        "title": title,
        "source_url": source_url,
        "updated_at": updated_at,
        "content_hash": None,
        "acl": _normalize_acl(snapshot.get("acl", [])),
        "sections": sections,
    }
    normalized["content_hash"] = _content_hash(normalized)
    return normalized


def _build_sections(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    sections: list[dict[str, Any]] = []
    heading_path: list[str] = []
    section_number = 0

    for block in blocks:
        block_type = str(block.get("block_type", "text")).lower()
        text = _clean_text(block.get("text"))
        if not text:
            continue

        level = _HEADING_TYPES.get(block_type)
        if level is not None:
            heading_path = heading_path[: level - 1]
            heading_path.append(text)
            continue

        section_number += 1
        sections.append(
            {
                "section_id": f"section-{section_number}",
                "heading_path": list(heading_path),
                "content": text,
                "page_no": block.get("page_no"),
                "block_id": block.get("block_id"),
            }
        )

    return sections


def _normalize_acl(acl: list[dict[str, Any]]) -> list[dict[str, str]]:
    normalized: list[dict[str, str]] = []
    for entry in acl:
        principal_type = _required_string(entry, "principal_type")
        principal_id = _required_string(entry, "principal_id")
        permission = _required_string(entry, "permission")
        normalized.append(
            {
                "principal_type": principal_type,
                "principal_id": principal_id,
                "permission": permission,
            }
        )
    return sorted(
        normalized,
        key=lambda item: (
            item["principal_type"],
            item["principal_id"],
            item["permission"],
        ),
    )


def _content_hash(document: dict[str, Any]) -> str:
    payload = {
        "document_id": document["document_id"],
        "source_type": document["source_type"],
        "title": document["title"],
        "source_url": document["source_url"],
        "sections": document["sections"],
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def _required_string(value: dict[str, Any], key: str) -> str:
    result = value.get(key)
    if not isinstance(result, str) or not result.strip():
        raise ValueError(f"Missing required string: {key}")
    return result.strip()


def _clean_text(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.split())

