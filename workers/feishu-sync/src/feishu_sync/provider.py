"""Knowledge provider abstractions and the Feishu CLI adapter."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
import subprocess
from typing import Any, Callable, Sequence

from .normalize import normalize_snapshot


class FeishuCliError(RuntimeError):
    """Raised when the Feishu CLI cannot return usable data."""


@dataclass(frozen=True)
class KnowledgeHit:
    document_ref: str
    title: str
    source_url: str | None
    snippet: str | None
    source_type: str | None


@dataclass(frozen=True)
class CliResponse:
    returncode: int
    stdout: str
    stderr: str


Runner = Callable[[Sequence[str]], CliResponse]


class FeishuCliProvider:
    """Read Feishu knowledge through the installed lark-cli executable."""

    def __init__(
        self,
        *,
        executable: str | None = None,
        identity: str = "user",
        timeout_seconds: int = 30,
        runner: Runner | None = None,
    ) -> None:
        self.executable = executable or os.getenv("LARK_CLI_COMMAND", "lark-cli")
        self.identity = identity
        self.timeout_seconds = timeout_seconds
        self._runner = runner or self._run_process

    def search(self, query: str, *, limit: int = 10) -> list[KnowledgeHit]:
        if not query.strip():
            raise ValueError("query must not be empty")
        if limit < 1:
            raise ValueError("limit must be greater than zero")

        response = self._run(
            [
                self.executable,
                "drive",
                "+search",
                "--query",
                query,
                "--format",
                "json",
                "--as",
                self.identity,
            ]
        )
        items = _extract_items(_decode_json(response.stdout))
        hits: list[KnowledgeHit] = []
        for item in items:
            document_ref = _first_string(
                item,
                "document_ref",
                "obj_token",
                "object_token",
                "file_token",
                "url",
                "source_url",
            )
            title = _first_string(item, "title", "name") or document_ref
            if not document_ref or not title:
                continue
            hits.append(
                KnowledgeHit(
                    document_ref=document_ref,
                    title=title,
                    source_url=_first_string(item, "source_url", "url"),
                    snippet=_first_string(item, "snippet", "content", "text"),
                    source_type=_first_string(item, "obj_type", "source_type"),
                )
            )
            if len(hits) >= limit:
                break
        return hits

    def fetch(self, document_ref: str) -> dict[str, Any]:
        if not document_ref.strip():
            raise ValueError("document_ref must not be empty")

        response = self._run(
            [
                self.executable,
                "docs",
                "+fetch",
                "--doc",
                document_ref,
                "--format",
                "json",
                "--as",
                self.identity,
            ]
        )
        payload = _decode_json(response.stdout)
        return normalize_snapshot(_to_snapshot(payload, document_ref))

    def _run(self, args: Sequence[str]) -> CliResponse:
        response = self._runner(args)
        if response.returncode != 0:
            detail = response.stderr.strip() or "no error detail"
            raise FeishuCliError(
                f"Feishu CLI failed with exit code {response.returncode}: {detail}"
            )
        return response

    def _run_process(self, args: Sequence[str]) -> CliResponse:
        try:
            completed = subprocess.run(
                list(args),
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
                check=False,
            )
        except FileNotFoundError as exc:
            raise FeishuCliError(
                f"Feishu CLI executable not found: {self.executable}"
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise FeishuCliError(
                f"Feishu CLI timed out after {self.timeout_seconds}s"
            ) from exc
        return CliResponse(
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )


def _decode_json(output: str) -> Any:
    try:
        return json.loads(output)
    except json.JSONDecodeError as exc:
        raise FeishuCliError("Feishu CLI returned invalid JSON") from exc


def _extract_items(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        raise FeishuCliError("Feishu CLI search output is not an object or list")

    data = payload.get("data", payload)
    if isinstance(data, dict):
        items = data.get("items", data.get("results", []))
    else:
        items = data
    if not isinstance(items, list):
        raise FeishuCliError("Feishu CLI search output has no items")
    return [item for item in items if isinstance(item, dict)]


def _to_snapshot(payload: Any, document_ref: str) -> dict[str, Any]:
    root = payload.get("data", payload) if isinstance(payload, dict) else payload
    if isinstance(root, dict) and isinstance(root.get("document"), dict):
        root = root["document"]
    if not isinstance(root, dict):
        raise FeishuCliError("Feishu CLI document output is not an object")

    blocks = root.get("blocks")
    if not isinstance(blocks, list):
        content = root.get("content")
        blocks = [{"block_type": "text", "text": content}] if isinstance(content, str) else []

    document_id = _first_string(
        root,
        "document_id",
        "obj_token",
        "object_token",
        "token",
    ) or document_ref
    updated_at = _first_string(root, "updated_at", "update_time", "modified_time")
    if not updated_at:
        raise FeishuCliError("Feishu CLI document output is missing updated_at")

    return {
        "document_id": document_id,
        "obj_type": _first_string(root, "obj_type", "object_type", "type") or "docx",
        "obj_token": _first_string(root, "obj_token", "object_token", "token")
        or document_id,
        "space_id": _first_string(root, "space_id"),
        "node_token": _first_string(root, "node_token"),
        "title": _first_string(root, "title", "name") or document_id,
        "source_url": _first_string(root, "source_url", "url") or document_ref,
        "updated_at": updated_at,
        "blocks": blocks,
        "acl": root.get("acl", root.get("permissions", [])),
    }


def _first_string(value: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        candidate = value.get(key)
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    return None

