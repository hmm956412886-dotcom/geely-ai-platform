"""Machine-readable tool contracts exposed by the AI Gateway."""

from __future__ import annotations

from copy import deepcopy
from typing import Any


_STRING = {"type": "string"}
_BOOLEAN = {"type": "boolean"}


_TOOLS: list[dict[str, Any]] = [
    {
        "name": "analyze_test_run",
        "description": "Analyze a test run and return deterministic data plus optional knowledge citations.",
        "method": "POST",
        "path": "/api/v1/analyze",
        "input_schema": {
            "type": "object",
            "properties": {
                "question": _STRING,
                "source_file": _STRING,
                "knowledge_query": _STRING,
                "use_model": _BOOLEAN,
                "test_data": {"type": "object"},
            },
            "additionalProperties": True,
        },
        "output_schema": {
            "type": "object",
            "required": ["request_id", "answer", "data", "citations"],
            "properties": {
                "request_id": _STRING,
                "answer": _STRING,
                "data": {"type": "object"},
                "citations": {"type": "array", "items": {"type": "object"}},
                "warnings": {"type": "array", "items": _STRING},
            },
        },
        "side_effect": "read_only",
        "requires_confirmation": False,
        "risk_level": "low",
        "audit_level": "standard",
    },
    {
        "name": "summarize_test_data",
        "description": "Return a normalized summary for demo, JSON, or CSV test-run data.",
        "method": "POST",
        "path": "/api/v1/test-data/summary",
        "input_schema": {
            "type": "object",
            "properties": {
                "source_file": _STRING,
                "run_id": _STRING,
                "source_ref": _STRING,
                "total_cases": {"type": "integer"},
                "failed_cases": {"type": "integer"},
            },
            "additionalProperties": True,
        },
        "output_schema": {
            "type": "object",
            "required": ["request_id", "result"],
            "properties": {"request_id": _STRING, "result": {"type": "object"}},
        },
        "side_effect": "read_only",
        "requires_confirmation": False,
        "risk_level": "low",
        "audit_level": "standard",
    },
    {
        "name": "compare_test_runs",
        "description": "Compare two test run files and return changed metrics.",
        "method": "POST",
        "path": "/api/v1/test-data/compare",
        "input_schema": {
            "type": "object",
            "required": ["baseline_file", "target_file"],
            "properties": {"baseline_file": _STRING, "target_file": _STRING},
            "additionalProperties": False,
        },
        "output_schema": {
            "type": "object",
            "required": ["request_id", "result"],
            "properties": {"request_id": _STRING, "result": {"type": "object"}},
        },
        "side_effect": "read_only",
        "requires_confirmation": False,
        "risk_level": "low",
        "audit_level": "standard",
    },
    {
        "name": "analyze_test_data_insights",
        "description": "Return deterministic status distribution and top failure reasons for a test data file.",
        "method": "POST",
        "path": "/api/v1/test-data/insights",
        "input_schema": {
            "type": "object",
            "required": ["source_file"],
            "properties": {"source_file": _STRING},
            "additionalProperties": False,
        },
        "output_schema": {
            "type": "object",
            "required": ["request_id", "result"],
            "properties": {"request_id": _STRING, "result": {"type": "object"}},
        },
        "side_effect": "read_only",
        "requires_confirmation": False,
        "risk_level": "low",
        "audit_level": "standard",
    },
    {
        "name": "query_knowledge",
        "description": "Query the configured knowledge provider and return answer citations.",
        "method": "POST",
        "path": "/api/v1/knowledge/query",
        "input_schema": {
            "type": "object",
            "properties": {"query": _STRING},
            "additionalProperties": False,
        },
        "output_schema": {
            "type": "object",
            "required": ["request_id", "answer", "citations"],
            "properties": {
                "request_id": _STRING,
                "answer": _STRING,
                "citations": {"type": "array", "items": {"type": "object"}},
                "warnings": {"type": "array", "items": _STRING},
            },
        },
        "side_effect": "read_only",
        "requires_confirmation": False,
        "risk_level": "low",
        "audit_level": "standard",
    },
    {
        "name": "get_model_config",
        "description": "Return public model configuration without exposing the API key.",
        "method": "GET",
        "path": "/api/v1/model/config",
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
        "output_schema": {
            "type": "object",
            "required": ["request_id", "result"],
            "properties": {"request_id": _STRING, "result": {"type": "object"}},
        },
        "side_effect": "read_only",
        "requires_confirmation": False,
        "risk_level": "low",
        "audit_level": "standard",
    },
    {
        "name": "get_host_context",
        "description": "Return the latest host software context used by the Copilot panel.",
        "method": "GET",
        "path": "/api/v1/host/context",
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
        "output_schema": {
            "type": "object",
            "required": ["request_id", "result"],
            "properties": {"request_id": _STRING, "result": {"type": "object"}},
        },
        "side_effect": "read_only",
        "requires_confirmation": False,
        "risk_level": "low",
        "audit_level": "standard",
    },
    {
        "name": "update_host_context",
        "description": "Update local host context for the current gateway process.",
        "method": "POST",
        "path": "/api/v1/host/context",
        "input_schema": {
            "type": "object",
            "properties": {
                "project_id": _STRING,
                "run_id": _STRING,
                "source_file": _STRING,
                "target_file": _STRING,
                "baseline_file": _STRING,
                "current_view": _STRING,
                "user_id": _STRING,
            },
            "additionalProperties": False,
        },
        "output_schema": {
            "type": "object",
            "required": ["request_id", "result"],
            "properties": {"request_id": _STRING, "result": {"type": "object"}},
        },
        "side_effect": "local_state",
        "requires_confirmation": False,
        "risk_level": "medium",
        "audit_level": "standard",
    },
    {
        "name": "list_audit_events",
        "description": "Return recent in-process audit events for debugging and demo verification.",
        "method": "GET",
        "path": "/api/v1/audit/events",
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
        "output_schema": {
            "type": "object",
            "required": ["request_id", "result"],
            "properties": {"request_id": _STRING, "result": {"type": "object"}},
        },
        "side_effect": "read_only",
        "requires_confirmation": False,
        "risk_level": "low",
        "audit_level": "debug",
    },
]


def list_tools() -> list[dict[str, Any]]:
    return deepcopy(_TOOLS)


def manifest_operations() -> list[dict[str, Any]]:
    return [
        {
            "operation_id": tool["name"],
            "method": tool["method"],
            "path": tool["path"],
            "side_effect": tool["side_effect"],
            "requires_confirmation": tool["requires_confirmation"],
        }
        for tool in _TOOLS
    ]
