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
    if method == "GET" and path == "/showcase":
        return Response(200, _showcase_html(), "text/html; charset=utf-8")
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
    aside { background: #ffffff; border-left: 1px solid #d8dee8; display: flex; flex-direction: column; min-width: 0; }
    .copilot-head { padding: 16px; border-bottom: 1px solid #d8dee8; }
    .copilot-title { font-size: 18px; font-weight: 750; }
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
          <button id="quickAnalyze">AI 分析</button>
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
      <div class="copilot-head">
        <div class="copilot-title">AI Copilot</div>
        <div class="sub">读取当前测试上下文，返回可追踪结论</div>
      </div>
      <div class="context">
        <div>
          <label for="project">项目</label>
          <input id="project" value="GEELY_TEST" />
        </div>
        <div>
          <label for="run">Run</label>
          <input id="run" value="RUN_CSV_001" />
        </div>
        <div class="full">
          <label for="source">当前测试文件</label>
          <input id="source" value="D:\\geely-ai-platform\\src\\ai-gateway\\tests\\fixtures\\test-run-cases.csv" />
        </div>
        <div class="full">
          <label for="target">对比测试文件</label>
          <input id="target" value="D:\\geely-ai-platform\\src\\ai-gateway\\tests\\fixtures\\test-run-cases-target.csv" />
        </div>
        <div class="full">
          <label for="question">问题</label>
          <textarea id="question">分析当前动力系统测试失败原因，并给出下一步排查建议。</textarea>
        </div>
      </div>
      <div class="copilot-actions">
        <button id="analyze">分析当前测试</button>
        <button class="secondary" id="compare">对比两次结果</button>
      </div>
      <div class="answer">
        <div id="status" class="status">等待操作</div>
        <pre id="output">点击“AI 分析”开始。</pre>
      </div>
    </aside>
  </div>
  <script>
    const output = document.getElementById("output");
    const status = document.getElementById("status");
    const project = document.getElementById("project");
    const run = document.getElementById("run");
    const source = document.getElementById("source");
    const target = document.getElementById("target");
    const question = document.getElementById("question");

    async function postJson(path, body) {
      status.textContent = "请求中...";
      const response = await fetch(path, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body)
      });
      const payload = await response.json();
      status.textContent = response.ok ? "完成" : "请求失败";
      output.textContent = JSON.stringify(payload, null, 2);
      return payload;
    }

    async function syncContext() {
      await postJson("/api/v1/host/context", {
        project_id: project.value,
        run_id: run.value,
        source_file: source.value,
        target_file: target.value,
        current_view: "test_result_detail",
        user_id: "demo_user"
      });
    }

    async function analyze() {
      await syncContext();
      await postJson("/api/v1/analyze", { source_file: source.value, question: question.value });
    }

    document.getElementById("sync").addEventListener("click", syncContext);
    document.getElementById("quickAnalyze").addEventListener("click", analyze);
    document.getElementById("analyze").addEventListener("click", analyze);
    document.getElementById("compare").addEventListener("click", () => {
      postJson("/api/v1/test-data/compare", { baseline_file: source.value, target_file: target.value });
    });
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
            "/showcase": {"get": {"summary": "Host software showcase with Copilot side panel"}},
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
