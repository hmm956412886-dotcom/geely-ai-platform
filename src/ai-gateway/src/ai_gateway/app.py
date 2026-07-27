"""Small dependency-free request handlers for the AI Gateway MVP."""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any
from uuid import uuid4

from .audit_log import append_audit_event, list_audit_events
from .host_context import get_host_context, update_host_context
from .model_client import chat_completion, load_model_config
from .test_data_adapter import compare_test_runs, load_test_run_summary
from .tool_registry import list_tools, manifest_operations


@dataclass(frozen=True)
class Response:
    status: int
    body: str
    content_type: str = "application/json; charset=utf-8"


def handle_request(method: str, path: str, body: str = "") -> Response:
    try:
        response = _handle_request(method, path, body)
    except json.JSONDecodeError as exc:
        response = error_response("invalid_json", f"Invalid JSON request body: {exc.msg}", status=400)
    except ValueError as exc:
        response = error_response("bad_request", str(exc), status=400)
    _append_request_audit(method, path, response)
    return response


def _handle_request(method: str, path: str, body: str = "") -> Response:
    if method == "GET" and path == "/health":
        return json_response({"status": "ok", "service": "geely-ai-gateway"})
    if method == "GET" and path == "/demo":
        return Response(200, _demo_html(), "text/html; charset=utf-8")
    if method == "GET" and path == "/copilot":
        return Response(200, _copilot_html(), "text/html; charset=utf-8")
    if method == "GET" and path == "/openapi.json":
        return json_response(_openapi())
    if method == "GET" and path == "/plugin-manifest.json":
        return json_response(_plugin_manifest())
    if method == "GET" and path == "/api/v1/tools":
        return json_response({"request_id": _request_id(), "result": {"tools": list_tools()}})
    if method == "GET" and path == "/api/v1/model/config":
        return json_response({"request_id": _request_id(), "result": load_model_config().public_dict()})
    if method == "GET" and path == "/api/v1/host/context":
        return json_response({"request_id": _request_id(), "result": get_host_context()})
    if method == "POST" and path == "/api/v1/host/context":
        return json_response({"request_id": _request_id(), "result": update_host_context(_read_json(body))})
    if method == "GET" and path == "/api/v1/audit/events":
        return json_response({"request_id": _request_id(), "result": {"events": list_audit_events()}})
    if method == "POST" and path == "/api/v1/test-data/summary":
        return json_response(_test_data_summary(_read_json(body)))
    if method == "POST" and path == "/api/v1/test-data/compare":
        return json_response(_test_data_compare(_read_json(body)))
    if method == "POST" and path == "/api/v1/knowledge/query":
        return json_response(_knowledge_query(_read_json(body)))
    if method == "POST" and path == "/api/v1/analyze":
        return json_response(_analyze(_read_json(body)))
    return error_response("not_found", f"No route for {method} {path}", status=404)


def json_response(payload: dict[str, Any], *, status: int = 200) -> Response:
    return Response(status, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def error_response(code: str, message: str, *, status: int) -> Response:
    return json_response(
        {"request_id": _request_id(), "error": {"code": code, "message": message}},
        status=status,
    )


def _append_request_audit(method: str, path: str, response: Response) -> None:
    if not path.startswith("/api/v1/") or path in {"/api/v1/audit/events", "/api/v1/tools"}:
        return
    payload = json.loads(response.body)
    append_audit_event(
        method=method,
        path=path,
        status=response.status,
        request_id=payload.get("request_id"),
        context=get_host_context(),
        error_code=(payload.get("error") or {}).get("code"),
    )


def _read_json(body: str) -> dict[str, Any]:
    if not body.strip():
        return {}
    payload = json.loads(body)
    if not isinstance(payload, dict):
        raise ValueError("request body must be a JSON object")
    return payload


def _test_data_summary(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("source_file"):
        return {"request_id": _request_id(), "result": load_test_run_summary(str(payload["source_file"]))}

    run_id = str(payload.get("run_id") or "RUN_DEMO_001")
    source_ref = str(payload.get("source_ref") or "demo-fixture.json")
    total_cases = int(payload.get("total_cases") or 120)
    failed_cases = int(payload.get("failed_cases") or 12)
    passed_cases = max(total_cases - failed_cases, 0)
    pass_rate = round(passed_cases / total_cases, 4) if total_cases else 0
    return {
        "request_id": _request_id(),
        "result": {
            "run_id": run_id,
            "source": {"type": "json", "ref": source_ref},
            "project_id": payload.get("project_id", "GEELY_TEST"),
            "status": "failed" if failed_cases else "passed",
            "started_at": payload.get("started_at"),
            "finished_at": payload.get("finished_at"),
            "total_cases": total_cases,
            "passed_cases": passed_cases,
            "failed_cases": failed_cases,
            "metrics": {"pass_rate": pass_rate},
            "failures": [
                {
                    "case_id": "TC_001",
                    "name": "动力响应测试",
                    "reason": "扭矩误差超过阈值",
                }
            ]
            if failed_cases
            else [],
        },
    }


def _test_data_compare(payload: dict[str, Any]) -> dict[str, Any]:
    baseline_file = str(payload.get("baseline_file") or "")
    target_file = str(payload.get("target_file") or "")
    return {"request_id": _request_id(), "result": compare_test_runs(baseline_file, target_file)}


def _knowledge_query(payload: dict[str, Any]) -> dict[str, Any]:
    query = str(payload.get("query") or "动力系统测试规范")
    return {
        "request_id": _request_id(),
        "answer": f"已在飞书知识源中准备检索：{query}",
        "citations": [
            {
                "title": "动力系统测试规范",
                "source_url": "https://example.feishu.cn/wiki/demo",
                "section_path": ["第三章", "通过标准"],
                "provider": "feishu-cli",
            }
        ],
        "warnings": ["当前 MVP 使用演示数据；接入 lark-cli 后返回真实飞书引用。"],
    }


def _analyze(payload: dict[str, Any]) -> dict[str, Any]:
    question = str(payload.get("question") or "分析本次测试失败原因")
    summary_payload = payload.get("test_data", {})
    if payload.get("source_file"):
        summary_payload = {"source_file": payload["source_file"]}
    summary = _test_data_summary(summary_payload)
    knowledge = _knowledge_query({"query": payload.get("knowledge_query", question)})
    result = summary["result"]
    answer = _fallback_analysis_answer(result)
    model_warning = None
    if payload.get("use_model"):
        try:
            answer = chat_completion(_analysis_messages(question, result, knowledge["citations"]))
        except ValueError as exc:
            model_warning = str(exc)
    return {
        "request_id": _request_id(),
        "answer": answer,
        "data": result,
        "citations": knowledge["citations"],
        "warnings": [model_warning] if model_warning else [],
        "next_actions": [
            "用客户真实导出文件替换当前 fixture",
            "接入真实 lark-cli 检索结果",
            "把该接口嵌入客户软件 WebView 或插件按钮",
        ],
        "question": question,
    }


def _fallback_analysis_answer(result: dict[str, Any]) -> str:
    first_failure = result["failures"][0]["name"] if result["failures"] else "当前测试结果"
    return (
        f"本次测试共 {result['total_cases']} 个用例，失败 {result['failed_cases']} 个，"
        f"通过率 {result['metrics']['pass_rate']:.2%}。主要风险集中在{first_failure}，"
        "建议先核对扭矩误差阈值、测试环境和相关标定版本。"
    )


def _analysis_messages(
    question: str,
    result: dict[str, Any],
    citations: list[dict[str, Any]],
) -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": "你是汽车测试数据分析助手。只能基于给定测试数据和引用来源回答，不要编造。",
        },
        {
            "role": "user",
            "content": json.dumps(
                {"question": question, "test_data": result, "citations": citations},
                ensure_ascii=False,
            ),
        },
    ]


def _request_id() -> str:
    return f"req_{uuid4().hex}"


def _demo_html() -> str:
    return """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Geely AI Gateway MVP</title>
  <style>
    body { font-family: "Segoe UI", Arial, sans-serif; margin: 0; color: #1f2937; background: #f6f7f9; }
    main { max-width: 980px; margin: 0 auto; padding: 28px; }
    h1 { font-size: 28px; margin: 0 0 8px; }
    .layout { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-top: 20px; }
    section { background: white; border: 1px solid #d8dee8; border-radius: 8px; padding: 16px; }
    textarea { width: 100%; min-height: 120px; resize: vertical; box-sizing: border-box; }
    button { height: 36px; padding: 0 14px; margin-top: 10px; cursor: pointer; }
    pre { white-space: pre-wrap; overflow-wrap: anywhere; background: #101827; color: #e5edf7; padding: 12px; border-radius: 6px; min-height: 260px; }
    @media (max-width: 760px) { .layout { grid-template-columns: 1fr; } }
  </style>
</head>
<body>
  <main>
    <h1>Geely AI Gateway MVP</h1>
    <p>外置 AI Runtime 演示页，可嵌入客户软件 WebView。当前返回演示数据，接口形态保持稳定。</p>
    <div class="layout">
      <section>
        <label for="question">分析问题</label>
        <textarea id="question">分析本次动力系统测试失败原因，并结合飞书规范给出建议。</textarea>
        <button id="run">运行分析</button>
      </section>
      <section>
        <strong>结果</strong>
        <pre id="result">等待请求...</pre>
      </section>
    </div>
  </main>
  <script>
    document.getElementById("run").addEventListener("click", async () => {
      const result = document.getElementById("result");
      result.textContent = "请求中...";
      const response = await fetch("/api/v1/analyze", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: document.getElementById("question").value })
      });
      result.textContent = JSON.stringify(await response.json(), null, 2);
    });
  </script>
</body>
</html>
"""


def _copilot_html() -> str:
    return """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Geely AI Copilot</title>
  <style>
    * { box-sizing: border-box; }
    body { margin: 0; font-family: "Segoe UI", Arial, sans-serif; color: #172033; background: #f4f6f8; }
    main { width: min(100vw, 460px); min-height: 100vh; margin: 0 auto; background: #ffffff; border-left: 1px solid #d7dde7; border-right: 1px solid #d7dde7; display: flex; flex-direction: column; }
    header { padding: 14px 16px; border-bottom: 1px solid #d7dde7; background: #ffffff; }
    h1 { margin: 0; font-size: 18px; font-weight: 650; letter-spacing: 0; }
    .sub { margin-top: 4px; font-size: 12px; color: #657186; }
    .panel { padding: 14px 16px; border-bottom: 1px solid #e3e7ee; }
    label { display: block; margin: 10px 0 6px; font-size: 12px; color: #4b5568; }
    input, textarea { width: 100%; border: 1px solid #cbd3df; border-radius: 6px; padding: 8px 9px; font: inherit; color: #172033; background: #ffffff; }
    textarea { min-height: 76px; resize: vertical; }
    .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
    .actions { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-top: 12px; }
    button { min-height: 36px; border: 1px solid #2f6fed; border-radius: 6px; background: #2f6fed; color: white; cursor: pointer; font-weight: 600; }
    button.secondary { background: #ffffff; color: #2f405f; border-color: #b8c2d2; }
    button:disabled { opacity: .62; cursor: not-allowed; }
    .result { flex: 1; min-height: 240px; padding: 14px 16px; background: #f8fafc; }
    pre { margin: 0; white-space: pre-wrap; overflow-wrap: anywhere; font-size: 12px; line-height: 1.45; color: #132033; }
    .status { margin-bottom: 10px; font-size: 12px; color: #657186; }
    @media (min-width: 760px) { main { margin-left: auto; margin-right: 0; } }
  </style>
</head>
<body>
  <main>
    <header>
      <h1>Geely AI Copilot</h1>
      <div class="sub">当前测试上下文 · 只读分析</div>
    </header>
    <section class="panel">
      <div class="grid">
        <div>
          <label for="project">项目</label>
          <input id="project" value="GEELY_TEST" />
        </div>
        <div>
          <label for="run">测试 Run</label>
          <input id="run" value="RUN_CSV_001" />
        </div>
      </div>
      <label for="source">当前测试文件</label>
      <input id="source" value="D:\\geely-ai-platform\\src\\ai-gateway\\tests\\fixtures\\test-run-cases.csv" />
      <label for="target">对比测试文件</label>
      <input id="target" value="D:\\geely-ai-platform\\src\\ai-gateway\\tests\\fixtures\\test-run-cases-target.csv" />
      <label for="question">问题</label>
      <textarea id="question">分析当前测试失败原因，并给出下一步排查建议。</textarea>
      <div class="actions">
        <button id="analyze">分析当前测试</button>
        <button id="compare" class="secondary">对比测试结果</button>
      </div>
    </section>
    <section class="result">
      <div id="status" class="status">等待操作</div>
      <pre id="output">选择一个动作开始。</pre>
    </section>
  </main>
  <script>
    const output = document.getElementById("output");
    const status = document.getElementById("status");
    const project = document.getElementById("project");
    const run = document.getElementById("run");
    const source = document.getElementById("source");
    const target = document.getElementById("target");
    const question = document.getElementById("question");

    async function loadContext() {
      const response = await fetch("/api/v1/host/context");
      const payload = await response.json();
      if (!response.ok) return;
      const context = payload.result || {};
      project.value = context.project_id || project.value;
      run.value = context.run_id || run.value;
      source.value = context.source_file || source.value;
      target.value = context.target_file || context.baseline_file || target.value;
      status.textContent = "已加载宿主上下文";
    }

    async function postJson(path, body) {
      status.textContent = "请求中...";
      output.textContent = "";
      const response = await fetch(path, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body)
      });
      const payload = await response.json();
      status.textContent = response.ok ? "完成" : "请求失败";
      output.textContent = JSON.stringify(payload, null, 2);
    }

    document.getElementById("analyze").addEventListener("click", () => {
      postJson("/api/v1/analyze", { source_file: source.value, question: question.value });
    });
    document.getElementById("compare").addEventListener("click", () => {
      postJson("/api/v1/test-data/compare", { baseline_file: source.value, target_file: target.value });
    });
    loadContext();
  </script>
</body>
</html>
"""


def _openapi() -> dict[str, Any]:
    return {
        "openapi": "3.0.3",
        "info": {"title": "Geely AI Gateway MVP", "version": "0.1.0"},
        "paths": {
            "/health": {"get": {"summary": "Health check"}},
            "/demo": {"get": {"summary": "Embeddable demo panel"}},
            "/copilot": {"get": {"summary": "Embeddable Copilot side panel"}},
            "/plugin-manifest.json": {"get": {"summary": "Host integration manifest"}},
            "/api/v1/tools": {"get": {"summary": "Return machine-readable AI tool contracts"}},
            "/api/v1/model/config": {"get": {"summary": "Return public model runtime config"}},
            "/api/v1/host/context": {"get": {"summary": "Return host software context"}, "post": {"summary": "Update host software context"}},
            "/api/v1/audit/events": {"get": {"summary": "Return recent audit events"}},
            "/api/v1/analyze": {"post": {"summary": "Analyze test data with knowledge citations"}},
            "/api/v1/test-data/summary": {"post": {"summary": "Return a test run summary"}},
            "/api/v1/test-data/compare": {"post": {"summary": "Compare two test run files"}},
            "/api/v1/knowledge/query": {"post": {"summary": "Query knowledge provider"}},
        },
    }


def _plugin_manifest() -> dict[str, Any]:
    return {
        "id": "geely-ai-gateway",
        "version": "0.1.0",
        "display_name": "Geely AI Assistant",
        "integration_modes": ["webview", "http-api", "cli-launch"],
        "webview": {"entry": "/copilot", "preferred_width": 460, "preferred_height": 720},
        "api": {
            "base_path": "/api/v1",
            "tools": "/api/v1/tools",
            "operations": manifest_operations(),
        },
    }
