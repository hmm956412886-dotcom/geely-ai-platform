"""Tiny stdlib Host SDK for embedding the AI Gateway from host software."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen


@dataclass(frozen=True)
class HostContext:
    project_id: str
    run_id: str
    source_file: str
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
    def __init__(self, base_url: str = "http://127.0.0.1:8765") -> None:
        self.base_url = base_url.rstrip("/")

    @property
    def copilot_url(self) -> str:
        return f"{self.base_url}/copilot"

    def health(self) -> dict[str, Any]:
        return self._request("GET", "/health")

    def plugin_manifest(self) -> dict[str, Any]:
        return self._request("GET", "/plugin-manifest.json")

    def tools(self) -> dict[str, Any]:
        return self._request("GET", "/api/v1/tools")

    def get_host_context(self) -> dict[str, Any]:
        return self._request("GET", "/api/v1/host/context")

    def update_host_context(self, context: HostContext | dict[str, Any]) -> dict[str, Any]:
        payload = context.to_payload() if isinstance(context, HostContext) else context
        return self._request("POST", "/api/v1/host/context", payload)

    def analyze(self, *, source_file: str, question: str, use_model: bool = False) -> dict[str, Any]:
        return self._request(
            "POST",
            "/api/v1/analyze",
            {"source_file": source_file, "question": question, "use_model": use_model},
        )

    def insights(self, *, source_file: str) -> dict[str, Any]:
        return self._request("POST", "/api/v1/test-data/insights", {"source_file": source_file})

    def compare(self, *, baseline_file: str, target_file: str) -> dict[str, Any]:
        return self._request(
            "POST",
            "/api/v1/test-data/compare",
            {"baseline_file": baseline_file, "target_file": target_file},
        )

    def query_knowledge(self, *, query: str) -> dict[str, Any]:
        return self._request("POST", "/api/v1/knowledge/query", {"query": query})

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
