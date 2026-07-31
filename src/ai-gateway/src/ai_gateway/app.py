"""Small dependency-free request handlers for the AI Gateway MVP."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import sys
from typing import Any, Mapping
from urllib.parse import parse_qs, unquote, urlsplit
from uuid import uuid4

from .audit_log import append_audit_event, list_audit_events
from .access_control import access_control_enabled, is_authorized, is_host_authorized
from .copilot_service import run_copilot
from .host_assets import register_host_asset, release_host_assets, resolve_host_asset
from .host_context import (
    get_host_context,
    normalize_host_session_id,
    peek_host_context,
    release_host_context,
    update_host_context,
)
from .host_snapshot import (
    get_host_snapshot,
    release_host_snapshot,
    update_host_snapshot,
)
from .model_client import load_model_config
from .opencode_runtime import get_opencode_runtime
from .test_data_adapter import compare_test_runs, load_test_data_insights, load_test_run_summary
from .workspace import (
    get_workspace_path,
    get_workspace_status,
    register_workspace,
    release_workspace,
    workspace_count,
)


@dataclass(frozen=True)
class Response:
    status: int
    body: str | bytes
    content_type: str = "application/json; charset=utf-8"
    headers: Mapping[str, str] | None = None


def handle_request(
    method: str,
    path: str,
    body: str = "",
    headers: Mapping[str, str] | None = None,
) -> Response:
    parsed_url = urlsplit(path)
    route_path = parsed_url.path
    host_session_id = None
    try:
        host_session_id = _query_value(parsed_url.query, "host_session_id")
        if route_path.startswith("/api/v1/") and not is_authorized(headers):
            response = Response(
                401,
                json.dumps(
                    {
                        "request_id": _request_id(),
                        "error": {
                            "code": "unauthorized",
                            "message": "A valid AI Gateway bearer token is required",
                        },
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                headers={"WWW-Authenticate": "Bearer"},
            )
        elif (
            (method, route_path)
            in {
                ("POST", "/api/v1/host/assets"),
                ("POST", "/api/v1/host/snapshot"),
                ("POST", "/api/v1/host/workspace"),
                ("DELETE", "/api/v1/host/session"),
            }
            and not is_host_authorized(headers)
        ):
            response = error_response(
                "host_forbidden",
                "A valid AI Gateway host token is required for trusted host operations",
                status=403,
            )
        else:
            response = _handle_request(method, route_path, body, host_session_id)
    except json.JSONDecodeError as exc:
        response = error_response("invalid_json", f"Invalid JSON request body: {exc.msg}", status=400)
    except ValueError as exc:
        response = error_response("bad_request", str(exc), status=400)
    _append_request_audit(method, route_path, response, host_session_id)
    return response


def _handle_request(
    method: str, path: str, body: str = "", host_session_id: str | None = None
) -> Response:
    if method == "GET" and path == "/health":
        return json_response({"status": "ok", "service": "geely-ai-gateway"})
    if method == "GET" and path == "/showcase":
        return Response(200, _showcase_html(), "text/html; charset=utf-8")
    if method == "GET" and path == "/copilot":
        return _copilot_shell_file("index.html")
    if method == "GET" and (path == "/copilot-shell" or path == "/copilot-shell/"):
        return _copilot_shell_file("index.html")
    if method == "GET" and path.startswith("/copilot-shell/"):
        return _copilot_shell_file(unquote(path.removeprefix("/copilot-shell/")))
    if method == "GET" and path == "/openapi.json":
        return json_response(_contract_json("ai-gateway.openapi.json"))
    if method == "GET" and path == "/plugin-manifest.json":
        return json_response(_contract_json("host-plugin.manifest.json"))
    if method == "GET" and path == "/api/v1/model/config":
        return json_response({"request_id": _request_id(), "result": load_model_config().public_dict()})
    if method == "GET" and path == "/api/v1/agent/status":
        return json_response(
            {
                "request_id": _request_id(),
                "result": {
                    "workspace": get_workspace_status(host_session_id),
                    "runtime": get_opencode_runtime().status(check_health=True),
                },
            }
        )
    if method == "POST" and path == "/api/v1/agent/permissions":
        payload = _read_json(body)
        _require_fields(payload, {"conversation_id"})
        try:
            permissions = get_opencode_runtime().pending_permissions(
                _agent_session_key(payload, host_session_id)
            )
            return json_response(
                {"request_id": _request_id(), "result": {"permissions": permissions}}
            )
        except RuntimeError as exc:
            return error_response("agent_unavailable", str(exc), status=502)
    if method == "POST" and path == "/api/v1/agent/permissions/reply":
        payload = _read_json(body)
        _require_fields(payload, {"conversation_id", "request_id", "reply"})
        request_id = str(payload["request_id"])
        if re.fullmatch(r"[A-Za-z0-9_-]{1,100}", request_id) is None:
            raise ValueError("request_id must be a short identifier")
        try:
            get_opencode_runtime().reply_permission(
                _agent_session_key(payload, host_session_id),
                request_id,
                str(payload["reply"]),
            )
            return json_response({"request_id": _request_id(), "result": {"replied": True}})
        except RuntimeError as exc:
            return error_response("agent_unavailable", str(exc), status=502)
    if method == "POST" and path == "/api/v1/agent/abort":
        payload = _read_json(body)
        _require_fields(payload, {"conversation_id"})
        try:
            aborted = get_opencode_runtime().abort(
                _agent_session_key(payload, host_session_id)
            )
            return json_response(
                {"request_id": _request_id(), "result": {"aborted": aborted}}
            )
        except RuntimeError as exc:
            return error_response("agent_unavailable", str(exc), status=502)
    if method == "GET" and path == "/api/v1/host/context":
        return json_response(
            {"request_id": _request_id(), "result": get_host_context(host_session_id)}
        )
    if method == "POST" and path == "/api/v1/host/context":
        return json_response(
            {
                "request_id": _request_id(),
                "result": update_host_context(_read_json(body), host_session_id),
            }
        )
    if method == "POST" and path == "/api/v1/host/assets":
        return json_response(
            {
                "request_id": _request_id(),
                "result": register_host_asset(_read_json(body), host_session_id),
            }
        )
    if method == "POST" and path == "/api/v1/host/workspace":
        previous_workspace = get_workspace_path(host_session_id)
        workspace = register_workspace(_read_json(body), host_session_id)
        workspace_path = get_workspace_path(host_session_id)
        if workspace_path is None:
            raise ValueError("workspace registration is unavailable")
        runtime = get_opencode_runtime()
        try:
            if previous_workspace is not None and previous_workspace != workspace_path:
                runtime.release_sessions(normalize_host_session_id(host_session_id))
                runtime.stop()
            runtime_status = runtime.start(workspace_path)
        except (OSError, RuntimeError, ValueError) as exc:
            runtime_status = runtime.status()
            runtime_status["error"] = str(exc)
        return json_response(
            {
                "request_id": _request_id(),
                "result": {"workspace": workspace, "runtime": runtime_status},
            }
        )
    if method == "GET" and path == "/api/v1/host/snapshot":
        return json_response(
            {"request_id": _request_id(), "result": get_host_snapshot(host_session_id)}
        )
    if method == "POST" and path == "/api/v1/host/snapshot":
        return json_response(
            {
                "request_id": _request_id(),
                "result": update_host_snapshot(_read_json(body), host_session_id),
            }
        )
    if method == "DELETE" and path == "/api/v1/host/session":
        session_id = normalize_host_session_id(host_session_id)
        get_opencode_runtime().release_sessions(session_id)
        released_assets = release_host_assets(session_id)
        released_context = release_host_context(session_id)
        released_snapshot = release_host_snapshot(session_id)
        released_workspace = release_workspace(session_id)
        if released_workspace and workspace_count() == 0:
            get_opencode_runtime().stop()
        return json_response(
            {
                "request_id": _request_id(),
                "result": {
                    "host_session_id": session_id,
                    "released_context": released_context,
                    "released_assets": released_assets,
                    "released_snapshot": released_snapshot,
                    "released_workspace": released_workspace,
                },
            }
        )
    if method == "GET" and path == "/api/v1/audit/events":
        return json_response({"request_id": _request_id(), "result": {"events": list_audit_events()}})
    if method == "POST" and path == "/api/v1/test-data/summary":
        return json_response(_test_data_summary(_read_json(body), host_session_id))
    if method == "POST" and path == "/api/v1/test-data/compare":
        return json_response(_test_data_compare(_read_json(body), host_session_id))
    if method == "POST" and path == "/api/v1/test-data/insights":
        return json_response(_test_data_insights(_read_json(body), host_session_id))
    if method == "POST" and path == "/api/v1/copilot/query":
        try:
            payload = _read_json(body)
            result = _workspace_copilot(payload, host_session_id)
            return json_response({"request_id": _request_id(), **result})
        except RuntimeError as exc:
            return error_response("model_unavailable", str(exc), status=502)
    if method == "POST" and path == "/api/v1/host/snapshot/analyze":
        try:
            payload = _read_json(body)
            result = _workspace_copilot(
                {
                    "question": str(payload.get("question") or "分析当前界面"),
                    "conversation_id": str(
                        payload.get("conversation_id") or "current-object"
                    ),
                },
                host_session_id,
            )
            return json_response({"request_id": _request_id(), **result})
        except RuntimeError as exc:
            return error_response("model_unavailable", str(exc), status=502)
    if method == "POST" and path == "/api/v1/analyze":
        try:
            return json_response(_analyze(_read_json(body), host_session_id))
        except RuntimeError as exc:
            return error_response("model_unavailable", str(exc), status=502)
    return error_response("not_found", f"No route for {method} {path}", status=404)


def json_response(payload: dict[str, Any], *, status: int = 200) -> Response:
    return Response(status, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def error_response(code: str, message: str, *, status: int) -> Response:
    return json_response(
        {"request_id": _request_id(), "error": {"code": code, "message": message}},
        status=status,
    )


def _copilot_shell_file(relative_path: str) -> Response:
    requested = Path(relative_path)
    if not relative_path or requested.is_absolute() or ".." in requested.parts:
        return error_response("not_found", "Copilot shell asset not found", status=404)
    root = _repo_root() / "frontend" / "copilot-shell" / "dist"
    target = root / requested
    if not target.is_file():
        return error_response("not_found", "Copilot shell asset not found", status=404)
    content_type = _content_type(target.suffix)
    if target.suffix.lower() in {".html", ".css", ".js", ".json", ".map", ".svg"}:
        return Response(200, target.read_text(encoding="utf-8"), content_type)
    return Response(200, target.read_bytes(), content_type)


def _contract_json(name: str) -> dict[str, Any]:
    try:
        value = json.loads((_repo_root() / "contracts" / name).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Gateway contract is unavailable: {name}") from exc
    if not isinstance(value, dict):
        raise RuntimeError(f"Gateway contract is invalid: {name}")
    return value


def _repo_root() -> Path:
    configured = os.getenv("AI_GATEWAY_ASSET_ROOT", "").strip()
    if configured:
        return Path(configured).resolve()
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / "frontend" / "copilot-shell").exists():
            return parent
    return current.parents[4]


def _content_type(suffix: str) -> str:
    return {
        ".html": "text/html; charset=utf-8",
        ".css": "text/css; charset=utf-8",
        ".js": "application/javascript; charset=utf-8",
        ".json": "application/json; charset=utf-8",
        ".map": "application/json; charset=utf-8",
        ".svg": "image/svg+xml; charset=utf-8",
        ".png": "image/png",
        ".woff": "font/woff",
        ".woff2": "font/woff2",
        ".ttf": "font/ttf",
        ".wasm": "application/wasm",
    }.get(suffix.lower(), "application/octet-stream")


def _append_request_audit(
    method: str, path: str, response: Response, host_session_id: str | None = None
) -> None:
    if not path.startswith("/api/v1/") or path == "/api/v1/audit/events":
        return
    assert isinstance(response.body, str)
    payload = json.loads(response.body)
    append_audit_event(
        method=method,
        path=path,
        status=response.status,
        request_id=payload.get("request_id"),
        context=peek_host_context(host_session_id),
        error_code=(payload.get("error") or {}).get("code"),
    )


def _read_json(body: str) -> dict[str, Any]:
    if not body.strip():
        return {}
    payload = json.loads(body)
    if not isinstance(payload, dict):
        raise ValueError("request body must be a JSON object")
    return payload


def _query_value(query: str, name: str) -> str | None:
    values = parse_qs(query).get(name)
    if not values:
        return None
    return normalize_host_session_id(values[0])


def _test_data_summary(
    payload: dict[str, Any], host_session_id: str | None = None
) -> dict[str, Any]:
    source_file, source_asset_id = _resolve_source(
        payload, "source_file", "source_asset_id", host_session_id
    )
    if source_file:
        result = load_test_run_summary(source_file)
        _mask_asset_source(result, source_asset_id)
        return {"request_id": _request_id(), "result": result}
    raise ValueError("source_file or source_asset_id is required")


def _test_data_compare(
    payload: dict[str, Any], host_session_id: str | None = None
) -> dict[str, Any]:
    baseline_file, baseline_asset_id = _resolve_source(
        payload, "baseline_file", "baseline_asset_id", host_session_id
    )
    target_file, target_asset_id = _resolve_source(
        payload, "target_file", "target_asset_id", host_session_id
    )
    result = compare_test_runs(baseline_file, target_file)
    _mask_asset_source(result["baseline"], baseline_asset_id)
    _mask_asset_source(result["target"], target_asset_id)
    return {"request_id": _request_id(), "result": result}


def _test_data_insights(
    payload: dict[str, Any], host_session_id: str | None = None
) -> dict[str, Any]:
    source_file, source_asset_id = _resolve_source(
        payload, "source_file", "source_asset_id", host_session_id
    )
    result = load_test_data_insights(source_file)
    _mask_asset_source(result, source_asset_id)
    return {"request_id": _request_id(), "result": result}


def _analyze(payload: dict[str, Any], host_session_id: str | None = None) -> dict[str, Any]:
    question = str(payload.get("question") or "分析本次测试失败原因")
    summary_payload = payload.get("test_data", {})
    if payload.get("source_file") or payload.get("source_asset_id"):
        summary_payload = {
            key: payload[key]
            for key in ("source_file", "source_asset_id")
            if payload.get(key)
        }
    summary = _test_data_summary(summary_payload, host_session_id)
    result = summary["result"]
    agent = _workspace_copilot(
        {
            "question": question,
            "conversation_id": "test-data-analysis",
            "attachments": [
                {
                    "name": "test-data.json",
                    "content": json.dumps(result, ensure_ascii=False),
                }
            ],
        },
        host_session_id,
    )
    return {
        "request_id": _request_id(),
        "answer": agent["answer"],
        "data": result,
        "citations": [],
        "warnings": [],
        "question": question,
    }


def _resolve_source(
    payload: dict[str, Any],
    file_field: str,
    asset_field: str,
    host_session_id: str | None,
) -> tuple[str, str | None]:
    asset_id = str(payload.get(asset_field) or "").strip()
    if asset_id:
        return resolve_host_asset(asset_id, host_session_id), asset_id
    if access_control_enabled() and payload.get(file_field):
        raise ValueError(
            f"{file_field} is disabled when Gateway access control is enabled; register a host asset"
        )
    return str(payload.get(file_field) or ""), None


def _mask_asset_source(result: dict[str, Any], asset_id: str | None) -> None:
    if asset_id and isinstance(result.get("source"), dict):
        result["source"] = {"type": "host_asset", "ref": asset_id}


def _workspace_copilot(
    payload: dict[str, Any], host_session_id: str | None
) -> dict[str, Any]:
    if get_workspace_path(host_session_id) is None:
        raise RuntimeError("OpenCode workspace is not registered")
    runtime = get_opencode_runtime()
    session_id = normalize_host_session_id(host_session_id)
    conversation_id = payload.get("conversation_id") or "default"
    return run_copilot(
        payload,
        host_context=get_host_context(session_id),
        host_snapshot=get_host_snapshot(session_id),
        workspace_agent=lambda question, system, history, new_session: runtime.prompt(
            f"{session_id}:{conversation_id}",
            question,
            system=system,
            history=history,
            new_session=new_session,
        ),
    )


def _agent_session_key(
    payload: dict[str, Any], host_session_id: str | None
) -> str:
    conversation_id = payload.get("conversation_id")
    if not isinstance(conversation_id, str) or re.fullmatch(
        r"[A-Za-z0-9_-]{1,100}", conversation_id
    ) is None:
        raise ValueError("conversation_id must be a short identifier")
    return f"{normalize_host_session_id(host_session_id)}:{conversation_id}"


def _require_fields(payload: dict[str, Any], fields: set[str]) -> None:
    if set(payload) != fields:
        raise ValueError(f"request fields must be: {', '.join(sorted(fields))}")


def _request_id() -> str:
    return f"req_{uuid4().hex}"


def _showcase_html() -> str:
    return """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Geely Test AI Workbench</title>
  <style>
    * { box-sizing: border-box; }
    body { margin: 0; font-family: "Segoe UI", Arial, sans-serif; color: #172033; background: #eef2f6; }
    button, input, textarea { font: inherit; }
    .shell { min-height: 100vh; display: grid; grid-template-columns: 230px 1fr 420px; }
    nav { background: #182235; color: #f8fafc; padding: 18px 14px; }
    .brand { font-size: 18px; font-weight: 700; margin-bottom: 22px; }
    .navitem { height: 34px; display: flex; align-items: center; padding: 0 10px; border-radius: 6px; color: #cbd5e1; margin-bottom: 4px; }
    .navitem.active { background: #27364f; color: #ffffff; }
    .content { padding: 18px; min-width: 0; }
    .topbar { height: 58px; display: flex; align-items: center; justify-content: space-between; gap: 12px; border-bottom: 1px solid #d8dee8; background: #ffffff; padding: 0 18px; }
    .title { font-size: 20px; font-weight: 700; }
    .sub { font-size: 12px; color: #64748b; margin-top: 3px; }
    .toolbar { display: flex; gap: 8px; flex-wrap: wrap; }
    button { min-height: 34px; border: 1px solid #2f6fed; background: #2f6fed; color: #fff; border-radius: 6px; padding: 0 12px; cursor: pointer; font-weight: 650; }
    button.secondary { background: #ffffff; color: #24324a; border-color: #b8c2d2; }
    .metrics { display: grid; grid-template-columns: repeat(4, minmax(120px, 1fr)); gap: 10px; margin: 16px 0; }
    .metric { background: #ffffff; border: 1px solid #d8dee8; border-radius: 8px; padding: 12px; min-height: 76px; }
    .metric strong { display: block; font-size: 22px; margin-bottom: 4px; }
    .metric span { color: #64748b; font-size: 12px; }
    .workspace { display: grid; grid-template-columns: minmax(0, 1.35fr) minmax(280px, .65fr); gap: 12px; }
    section { background: #ffffff; border: 1px solid #d8dee8; border-radius: 8px; min-width: 0; }
    section h2 { font-size: 15px; margin: 0; padding: 12px 14px; border-bottom: 1px solid #e5eaf1; }
    table { width: 100%; border-collapse: collapse; table-layout: fixed; font-size: 13px; }
    th, td { text-align: left; border-bottom: 1px solid #edf1f6; padding: 10px 12px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    th { color: #64748b; font-weight: 650; background: #f8fafc; }
    .failed { color: #b42318; font-weight: 700; }
    .passed { color: #047857; font-weight: 700; }
    .chart { padding: 14px; display: grid; gap: 12px; }
    .barrow { display: grid; grid-template-columns: 86px 1fr 32px; gap: 8px; align-items: center; font-size: 12px; }
    .bar { height: 10px; border-radius: 999px; background: #e5eaf1; overflow: hidden; }
    .fill { height: 100%; background: #2f6fed; }
    aside { background: #ffffff; border-left: 1px solid #d8dee8; min-width: 0; }
    .copilot-frame { width: 100%; height: 100vh; border: 0; display: block; background: #ffffff; }
    .context { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; padding: 12px 16px; border-bottom: 1px solid #e5eaf1; }
    label { display: block; font-size: 12px; color: #5b667a; margin-bottom: 5px; }
    input, textarea { width: 100%; border: 1px solid #cbd3df; border-radius: 6px; padding: 8px; color: #172033; background: #fff; }
    .full { grid-column: 1 / -1; }
    textarea { min-height: 82px; resize: vertical; }
    .copilot-actions { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; padding: 0 16px 14px; }
    .answer { flex: 1; min-height: 220px; background: #f8fafc; border-top: 1px solid #e5eaf1; padding: 14px 16px; overflow: auto; }
    .status { font-size: 12px; color: #64748b; margin-bottom: 10px; }
    pre { margin: 0; white-space: pre-wrap; overflow-wrap: anywhere; font-size: 12px; line-height: 1.45; }
    @media (max-width: 1080px) {
      .shell { grid-template-columns: 1fr; }
      nav { display: none; }
      aside { border-left: 0; border-top: 1px solid #d8dee8; }
      .copilot-frame { height: 720px; }
      .workspace { grid-template-columns: 1fr; }
    }
    @media (max-width: 680px) {
      .topbar { height: auto; align-items: flex-start; flex-direction: column; padding: 14px; }
      .metrics { grid-template-columns: 1fr 1fr; }
      .context { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
  <div class="shell">
    <nav>
      <div class="brand">Geely Test Platform</div>
      <div class="navitem active">测试结果</div>
      <div class="navitem">测试计划</div>
      <div class="navitem">数据文件</div>
      <div class="navitem">知识规范</div>
      <div class="navitem">系统设置</div>
    </nav>
    <main>
      <div class="topbar">
        <div>
          <div class="title">动力系统回归测试</div>
          <div class="sub">RUN_CSV_001 · 当前视图 test_result_detail · 只读分析模式</div>
        </div>
        <div class="toolbar">
          <button class="secondary" id="sync">同步上下文</button>
          <button id="quickAnalyze">刷新 Copilot</button>
        </div>
      </div>
      <div class="content">
        <div class="metrics">
          <div class="metric"><strong>3</strong><span>测试用例</span></div>
          <div class="metric"><strong>1</strong><span>通过</span></div>
          <div class="metric"><strong>1</strong><span>失败</span></div>
          <div class="metric"><strong>33.33%</strong><span>通过率</span></div>
        </div>
        <div class="workspace">
          <section>
            <h2>当前测试用例</h2>
            <table>
              <thead><tr><th>Case ID</th><th>名称</th><th>状态</th><th>原因</th></tr></thead>
              <tbody>
                <tr><td>TC_001</td><td>动力响应测试</td><td class="failed">failed</td><td>扭矩误差超过阈值</td></tr>
                <tr><td>TC_002</td><td>电压稳定性测试</td><td class="passed">passed</td><td></td></tr>
                <tr><td>TC_003</td><td>通信稳定性测试</td><td>warning</td><td>偶发抖动</td></tr>
              </tbody>
            </table>
          </section>
          <section>
            <h2>失败分布</h2>
            <div class="chart">
              <div class="barrow"><span>动力响应</span><div class="bar"><div class="fill" style="width: 100%"></div></div><span>1</span></div>
              <div class="barrow"><span>通信稳定</span><div class="bar"><div class="fill" style="width: 0%"></div></div><span>0</span></div>
              <div class="barrow"><span>电压稳定</span><div class="bar"><div class="fill" style="width: 0%"></div></div><span>0</span></div>
            </div>
          </section>
        </div>
      </div>
    </main>
    <aside>
      <iframe class="copilot-frame" id="copilotFrame" title="Reusable Geely AI Copilot"></iframe>
    </aside>
  </div>
  <script>
    const copilotFrame = document.getElementById("copilotFrame");
    const hostSessionId = "showcase-demo";
    function loadCopilot() {
      const accessToken = new URLSearchParams(window.location.hash.slice(1)).get("access_token");
      const shellUrl = new URL("/copilot-shell/", window.location.origin);
      shellUrl.searchParams.set("host_session_id", hostSessionId);
      if (accessToken) shellUrl.hash = `access_token=${encodeURIComponent(accessToken)}`;
      if (copilotFrame.src !== shellUrl.href) copilotFrame.src = shellUrl.href;
    }
    const context = {
      project_id: "GEELY_TEST",
      run_id: "RUN_CSV_001",
      source_asset_id: "demo-current",
      target_asset_id: "demo-target",
      current_view: "test_result_detail",
      user_id: "demo_user"
    };

    function syncContext() {
      copilotFrame.contentWindow.postMessage({
        type: "geely-ai.host-context",
        host_session_id: hostSessionId,
        context
      }, window.location.origin);
    }

    document.getElementById("sync").addEventListener("click", syncContext);
    document.getElementById("quickAnalyze").addEventListener("click", syncContext);
    copilotFrame.addEventListener("load", syncContext);
    window.addEventListener("load", loadCopilot, { once: true });
    window.addEventListener("hashchange", loadCopilot);
  </script>
</body>
</html>
"""
