from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import json
import os
from pathlib import Path
from threading import Thread
import unittest

from ai_gateway.agent_orchestrator import build_openapi_spec
from ai_gateway.app import handle_request
from ai_gateway.server import GatewayHandler
from ai_gateway.tool_registry import list_tools


FIXTURES = Path(__file__).parent / "fixtures"
HAS_SEMANTIC_KERNEL = importlib.util.find_spec("semantic_kernel") is not None


class AgentOrchestratorTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.gateway = ThreadingHTTPServer(("127.0.0.1", 0), GatewayHandler)
        cls.gateway_thread = Thread(target=cls.gateway.serve_forever, daemon=True)
        cls.gateway_thread.start()
        cls.gateway_url = f"http://127.0.0.1:{cls.gateway.server_port}"

    @classmethod
    def tearDownClass(cls) -> None:
        cls.gateway.shutdown()
        cls.gateway.server_close()
        cls.gateway_thread.join(timeout=5)

    def setUp(self) -> None:
        self.original_env = os.environ.copy()
        os.environ["AI_GATEWAY_INTERNAL_BASE_URL"] = self.gateway_url
        os.environ["AI_AGENT_MODE"] = "deterministic"
        for name in ("AI_MODEL_BASE_URL", "AI_MODEL_API_KEY", "AI_MODEL_NAME"):
            os.environ.pop(name, None)

    def tearDown(self) -> None:
        os.environ.clear()
        os.environ.update(self.original_env)

    def test_deterministic_agent_selects_insights_rest_tool(self) -> None:
        session = "agent-insights"
        handle_request(
            "POST",
            f"/api/v1/host/context?host_session_id={session}",
            json.dumps({"source_file": str(FIXTURES / "test-run-cases.csv")}),
        )

        response = handle_request(
            "POST",
            f"/api/v1/agent/query?host_session_id={session}",
            json.dumps({"question": "生成当前测试状态分布洞察"}, ensure_ascii=False),
        )

        payload = json.loads(response.body)
        self.assertEqual(response.status, 200)
        self.assertEqual(payload["tool_calls"][0]["name"], "analyze_test_data_insights")
        self.assertEqual(payload["orchestrator"]["mode"], "deterministic")
        self.assertIn("failed 1 个", payload["answer"])

    def test_deterministic_agent_forwards_gateway_access_token(self) -> None:
        session = "agent-auth"
        os.environ["AI_GATEWAY_ACCESS_TOKEN"] = "agent-secret"
        response = handle_request(
            "POST",
            f"/api/v1/agent/query?host_session_id={session}",
            json.dumps({"question": "分析当前测试"}, ensure_ascii=False),
            headers={"Authorization": "Bearer agent-secret"},
        )

        payload = json.loads(response.body)
        self.assertEqual(response.status, 200)
        self.assertEqual(payload["tool_calls"][0]["name"], "analyze_test_run")

    def test_deterministic_agent_selects_compare_rest_tool(self) -> None:
        session = "agent-compare"
        handle_request(
            "POST",
            f"/api/v1/host/context?host_session_id={session}",
            json.dumps(
                {
                    "source_file": str(FIXTURES / "test-run-cases.csv"),
                    "target_file": str(FIXTURES / "test-run-cases-target.csv"),
                }
            ),
        )

        response = handle_request(
            "POST",
            f"/api/v1/agent/query?host_session_id={session}",
            json.dumps({"question": "比较当前测试与目标测试"}, ensure_ascii=False),
        )

        payload = json.loads(response.body)
        self.assertEqual(response.status, 200)
        self.assertEqual(payload["tool_calls"][0]["name"], "compare_test_runs")
        self.assertIn("失败用例增加 1 个", payload["answer"])

    def test_deterministic_agent_prefers_current_host_snapshot(self) -> None:
        session = "agent-coretest"
        handle_request(
            "POST",
            f"/api/v1/host/context?host_session_id={session}",
            json.dumps(
                {
                    "host_application": "HK CoreTest",
                    "project_id": "vehicle-a",
                    "run_id": "live",
                    "current_view": "TRACE / 实时CAN TRACE",
                    "snapshot_revision": "12",
                },
                ensure_ascii=False,
            ),
        )
        handle_request(
            "POST",
            f"/api/v1/host/snapshot?host_session_id={session}",
            json.dumps(
                {
                    "kind": "trace",
                    "revision": "12",
                    "data": {"total_frames": 10, "duration_seconds": 1, "error_frames": 0},
                }
            ),
        )

        response = handle_request(
            "POST",
            f"/api/v1/agent/query?host_session_id={session}",
            json.dumps({"question": "分析当前界面"}, ensure_ascii=False),
        )

        payload = json.loads(response.body)
        self.assertEqual(response.status, 200)
        self.assertEqual(payload["tool_calls"][0]["name"], "analyze_host_snapshot")
        self.assertIn("10 帧", payload["answer"])

    def test_openapi_adapter_only_exposes_read_only_tools(self) -> None:
        spec = build_openapi_spec(list_tools(), self.gateway_url)

        self.assertIn("/api/v1/analyze", spec["paths"])
        self.assertIn("/api/v1/host/snapshot/analyze", spec["paths"])
        self.assertIn("get", spec["paths"]["/api/v1/host/context"])
        self.assertNotIn("post", spec["paths"]["/api/v1/host/context"])

    @unittest.skipUnless(HAS_SEMANTIC_KERNEL, "semantic-kernel optional dependency is not installed")
    def test_semantic_kernel_invokes_gateway_rest_tool(self) -> None:
        model = _FakeModelServer()
        model.start()
        try:
            os.environ["AI_AGENT_MODE"] = "semantic-kernel"
            os.environ["AI_MODEL_BASE_URL"] = model.base_url
            os.environ["AI_MODEL_API_KEY"] = "test-key"
            os.environ["AI_MODEL_NAME"] = "fake-model"

            response = handle_request(
                "POST",
                "/api/v1/agent/query?host_session_id=agent-sk",
                json.dumps({"question": "查询测试规范文档"}, ensure_ascii=False),
            )

            payload = json.loads(response.body)
            self.assertEqual(response.status, 200)
            self.assertEqual(payload["orchestrator"]["framework"], "semantic-kernel")
            self.assertEqual(payload["orchestrator"]["mode"], "model")
            self.assertEqual(payload["tool_calls"][0]["name"], "query_knowledge")
            self.assertEqual(payload["citations"][0]["provider"], "feishu-cli")
            self.assertGreaterEqual(model.request_count, 2)
        finally:
            model.stop()


class _FakeModelHandler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(length).decode("utf-8"))
        self.server.request_count += 1  # type: ignore[attr-defined]
        if any(message.get("role") == "tool" for message in body.get("messages", [])):
            message = {"role": "assistant", "content": "已根据 Gateway 知识工具完成查询。"}
            finish_reason = "stop"
        else:
            tool_name = next(
                item["function"]["name"]
                for item in body["tools"]
                if item["function"]["name"].endswith("query_knowledge")
            )
            message = {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_query_knowledge",
                        "type": "function",
                        "function": {
                            "name": tool_name,
                            "arguments": json.dumps({"query": "测试规范"}, ensure_ascii=False),
                        },
                    }
                ],
            }
            finish_reason = "tool_calls"
        payload = {
            "id": "chatcmpl-test",
            "object": "chat.completion",
            "created": 1,
            "model": "fake-model",
            "choices": [
                {"index": 0, "message": message, "finish_reason": finish_reason}
            ],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }
        encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, format: str, *args: object) -> None:
        return


class _FakeModelServer:
    def __init__(self) -> None:
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _FakeModelHandler)
        self.server.request_count = 0  # type: ignore[attr-defined]
        self.thread = Thread(target=self.server.serve_forever, daemon=True)

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.server.server_port}/v1"

    @property
    def request_count(self) -> int:
        return self.server.request_count  # type: ignore[attr-defined,no-any-return]

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
