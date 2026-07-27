"""Tiny stdlib Host SDK for embedding the AI Gateway from host software."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from typing import Any
from urllib.parse import quote
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from uuid import uuid4


@dataclass(frozen=True)
class HostContext:
    project_id: str
    run_id: str
    source_asset_id: str | None = None
    target_asset_id: str | None = None
    source_file: str | None = None
    target_file: str | None = None
    current_view: str = "test_result_detail"
    user_id: str | None = None

    def to_payload(self) -> dict[str, Any]:
        return {key: value for key, value in asdict(self).items() if value is not None}


class GatewayError(RuntimeError):
    def __init__(self, status: int, payload: dict[str, Any]) -> None:
        error = payload.get("error") or {}
        self.status = status
        self.request_id = payload.get("request_id")
        self.error_code = error.get("code")
        message = error.get("message") or f"AI Gateway returned HTTP {status}"
        super().__init__(message)


class GeelyAIGatewayClient:
    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8765",
        *,
        host_session_id: str | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.host_session_id = host_session_id or f"host-{uuid4().hex}"

    @property
    def copilot_url(self) -> str:
        return f"{self.base_url}/copilot-shell/?host_session_id={quote(self.host_session_id)}"

    def health(self) -> dict[str, Any]:
        return self._request("GET", "/health")

    def plugin_manifest(self) -> dict[str, Any]:
        return self._request("GET", "/plugin-manifest.json")

    def tools(self) -> dict[str, Any]:
        return self._request("GET", "/api/v1/tools")

    def get_host_context(self) -> dict[str, Any]:
        return self._request("GET", self._session_path("/api/v1/host/context"))

    def update_host_context(self, context: HostContext | dict[str, Any]) -> dict[str, Any]:
        payload = context.to_payload() if isinstance(context, HostContext) else context
        return self._request("POST", self._session_path("/api/v1/host/context"), payload)

    def register_asset(self, file_path: str, *, asset_id: str | None = None) -> dict[str, Any]:
        payload = {"file_path": file_path}
        if asset_id:
            payload["asset_id"] = asset_id
        return self._request("POST", self._session_path("/api/v1/host/assets"), payload)

    def analyze(
        self,
        *,
        question: str,
        source_asset_id: str | None = None,
        source_file: str | None = None,
        use_model: bool = False,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            self._session_path("/api/v1/analyze"),
            {**_source_payload(source_asset_id, source_file), "question": question, "use_model": use_model},
        )

    def insights(
        self, *, source_asset_id: str | None = None, source_file: str | None = None
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            self._session_path("/api/v1/test-data/insights"),
            _source_payload(source_asset_id, source_file),
        )

    def compare(
        self,
        *,
        baseline_asset_id: str | None = None,
        target_asset_id: str | None = None,
        baseline_file: str | None = None,
        target_file: str | None = None,
    ) -> dict[str, Any]:
        if baseline_asset_id and target_asset_id:
            payload = {
                "baseline_asset_id": baseline_asset_id,
                "target_asset_id": target_asset_id,
            }
        elif baseline_file and target_file:
            payload = {"baseline_file": baseline_file, "target_file": target_file}
        else:
            raise ValueError("both comparison assets or both comparison files are required")
        return self._request(
            "POST",
            self._session_path("/api/v1/test-data/compare"),
            payload,
        )

    def query_knowledge(self, *, query: str) -> dict[str, Any]:
        return self._request(
            "POST", self._session_path("/api/v1/knowledge/query"), {"query": query}
        )

    def _session_path(self, path: str) -> str:
        return f"{path}?host_session_id={quote(self.host_session_id)}"

    def _request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        body = None
        headers = {"Accept": "application/json"}
        if payload is not None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = Request(f"{self.base_url}{path}", data=body, headers=headers, method=method)
        try:
            with urlopen(request, timeout=30) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            try:
                error_payload = json.loads(exc.read().decode("utf-8"))
            except json.JSONDecodeError:
                error_payload = {"error": {"message": str(exc)}}
            raise GatewayError(exc.code, error_payload) from exc


def _source_payload(source_asset_id: str | None, source_file: str | None) -> dict[str, str]:
    if source_asset_id:
        return {"source_asset_id": source_asset_id}
    if source_file:
        return {"source_file": source_file}
    raise ValueError("source_asset_id or source_file is required")
