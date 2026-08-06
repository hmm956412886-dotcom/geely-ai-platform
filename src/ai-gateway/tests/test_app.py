import json
from base64 import b64encode
from pathlib import Path
import re
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from ai_gateway.app import handle_request
from ai_gateway.audit_log import clear_audit_events
from ai_gateway.host_assets import reset_host_assets
from ai_gateway.host_bridge import reset_host_bridges
from ai_gateway.host_context import reset_host_context
from ai_gateway.host_snapshot import reset_host_snapshots
from ai_gateway.opencode_runtime import OpenCodeNativeResponse, reset_opencode_runtime
from ai_gateway.workspace import get_workspace_path, reset_workspaces


FIXTURES = Path(__file__).parent / "fixtures"


class AppTests(unittest.TestCase):
    def tearDown(self) -> None:
        reset_host_context()
        reset_host_assets()
        reset_host_bridges()
        reset_host_snapshots()
        reset_workspaces()
        reset_opencode_runtime()
        clear_audit_events()

    def test_health(self) -> None:
        response = handle_request("GET", "/health")

        self.assertEqual(response.status, 200)
        self.assertEqual(json.loads(response.body)["status"], "ok")

    def test_test_data_summary_requires_real_source(self) -> None:
        response = handle_request(
            "POST",
            "/api/v1/test-data/summary",
            json.dumps({"run_id": "RUN_X", "total_cases": 10, "failed_cases": 2}),
        )

        payload = json.loads(response.body)
        self.assertEqual(response.status, 400)
        self.assertEqual(payload["error"]["code"], "bad_request")
        self.assertIn("source_file or source_asset_id is required", payload["error"]["message"])

    def test_test_data_summary_reads_source_file(self) -> None:
        response = handle_request(
            "POST",
            "/api/v1/test-data/summary",
            json.dumps({"source_file": str(FIXTURES / "test-run-cases.csv")}),
        )

        payload = json.loads(response.body)
        self.assertEqual(response.status, 200)
        self.assertEqual(payload["result"]["run_id"], "RUN_CSV_001")
        self.assertEqual(payload["result"]["failed_cases"], 1)

    def test_analyze_sends_deterministic_data_to_opencode(self) -> None:
        runtime = _FakeOpenCodeRuntime()
        with TemporaryDirectory() as directory, patch(
            "ai_gateway.app.get_opencode_runtime", return_value=runtime
        ):
            handle_request(
                "POST",
                "/api/v1/host/workspace?host_session_id=analyze-data",
                json.dumps({"project_root": directory}),
            )
            response = handle_request(
                "POST",
                "/api/v1/analyze?host_session_id=analyze-data",
                json.dumps(
                    {
                        "question": "分析失败原因",
                        "source_file": str(FIXTURES / "test-run-cases.json"),
                    }
                ),
            )

        payload = json.loads(response.body)
        self.assertEqual(response.status, 200)
        self.assertEqual(payload["answer"], "来自工作区 Agent 的回答")
        self.assertEqual(payload["data"]["source"]["type"], "json")
        self.assertIn("RUN_JSON_001", runtime.prompts[0][1])

    def test_test_data_summary_reads_json_source_file(self) -> None:
        response = handle_request(
            "POST",
            "/api/v1/test-data/summary",
            json.dumps({"source_file": str(FIXTURES / "test-run-cases.json")}),
        )

        payload = json.loads(response.body)
        self.assertEqual(response.status, 200)
        self.assertEqual(payload["result"]["run_id"], "RUN_JSON_001")

    def test_analyze_requires_registered_workspace(self) -> None:
        response = handle_request(
            "POST",
            "/api/v1/analyze",
            json.dumps({"source_file": str(FIXTURES / "test-run-cases.json")}),
        )

        payload = json.loads(response.body)
        self.assertEqual(response.status, 502)
        self.assertEqual(payload["error"]["code"], "model_unavailable")
        self.assertIn("workspace is not registered", payload["error"]["message"])

    def test_model_config_does_not_expose_secret(self) -> None:
        response = handle_request("GET", "/api/v1/model/config")

        payload = json.loads(response.body)
        self.assertEqual(response.status, 200)
        self.assertIn("configured", payload["result"])
        self.assertNotIn("api_key", payload["result"])

    def test_model_config_can_be_saved_and_reloads_runtime(self) -> None:
        with TemporaryDirectory() as directory, patch.dict(
            "os.environ",
            {"AI_MODEL_CONFIG_FILE": str(Path(directory) / "ai-model.env")},
            clear=True,
        ), patch("ai_gateway.app.reset_opencode_runtime") as reset_runtime:
            response = handle_request(
                "POST",
                "/api/v1/model/config",
                json.dumps(
                    {
                        "base_url": "https://api.example.com/v1",
                        "api_key": "secret",
                        "model": "tool-model",
                    }
                ),
            )

        payload = json.loads(response.body)
        self.assertEqual(response.status, 200)
        self.assertEqual(payload["result"]["model"], "tool-model")
        self.assertTrue(payload["result"]["api_key_configured"])
        self.assertNotIn("secret", response.body)
        reset_runtime.assert_called_once_with()

    def test_model_provider_routes_proxy_only_safe_opencode_operations(self) -> None:
        runtime = _FakeOpenCodeRuntime()
        with TemporaryDirectory() as directory, patch(
            "ai_gateway.app.get_opencode_runtime", return_value=runtime
        ):
            handle_request(
                "POST",
                "/api/v1/host/workspace?host_session_id=providers",
                json.dumps({"project_root": directory}),
            )
            saved = handle_request(
                "POST",
                "/api/v1/model/providers?host_session_id=providers",
                json.dumps(
                    {
                        "id": "company-api",
                        "name": "Company API",
                        "base_url": "https://api.example.com/v1",
                        "api_key": "never-return-this-key",
                        "models": [{"id": "tool-model", "name": "Tool Model"}],
                        "activate": True,
                    }
                ),
            )
            listed = handle_request(
                "GET", "/api/v1/model/providers?host_session_id=providers"
            )
            activated = handle_request(
                "POST",
                "/api/v1/model/providers/company-api/activate?host_session_id=providers",
                json.dumps({"model": "tool-model"}),
            )
            tested = handle_request(
                "POST",
                "/api/v1/model/providers/company-api/test?host_session_id=providers",
                json.dumps({"model": "tool-model"}),
            )
            deleted = handle_request(
                "DELETE",
                "/api/v1/model/providers/company-api?host_session_id=providers",
            )

        for response in (saved, listed, activated, tested, deleted):
            self.assertEqual(response.status, 200)
            self.assertNotIn("never-return-this-key", response.body)
        self.assertEqual(runtime.saved_providers[0]["id"], "company-api")
        self.assertEqual(runtime.activated_providers, [("company-api", "tool-model")])
        self.assertEqual(runtime.tested_providers, [("company-api", "tool-model")])
        self.assertEqual(runtime.deleted_providers, ["company-api"])

    def test_api_access_token_is_optional_and_protects_api_routes(self) -> None:
        with patch.dict("os.environ", {"AI_GATEWAY_ACCESS_TOKEN": "host-secret"}):
            missing = handle_request("GET", "/api/v1/model/config")
            wrong = handle_request(
                "GET",
                "/api/v1/model/config",
                headers={"Authorization": "Bearer wrong-secret"},
            )
            authorized = handle_request(
                "GET",
                "/api/v1/model/config",
                headers={"authorization": "Bearer host-secret"},
            )
            health = handle_request("GET", "/health")
            shell = handle_request("GET", "/showcase")

        self.assertEqual(missing.status, 401)
        self.assertEqual(wrong.status, 401)
        self.assertEqual(json.loads(missing.body)["error"]["code"], "unauthorized")
        self.assertEqual(missing.headers, {"WWW-Authenticate": "Bearer"})
        self.assertEqual(authorized.status, 200)
        self.assertEqual(health.status, 200)
        self.assertEqual(shell.status, 200)

    def test_api_access_token_is_not_exposed_in_error_response_or_audit(self) -> None:
        token = "never-return-this-token"
        with patch.dict("os.environ", {"AI_GATEWAY_ACCESS_TOKEN": token}):
            response = handle_request("GET", "/api/v1/model/config")

        audit = handle_request("GET", "/api/v1/audit/events")
        self.assertNotIn(token, response.body)
        self.assertNotIn(token, audit.body)

    def test_copilot_page_is_available(self) -> None:
        response = handle_request("GET", "/copilot")

        self.assertEqual(response.status, 200)
        self.assertEqual(response.content_type, "text/html; charset=utf-8")
        self.assertIn("CoreTest Agent", response.body)
        self.assertNotIn("GEELY_TEST", response.body)
        self.assertNotIn("D:\\geely-ai-platform", response.body)

    def test_copilot_shell_assets_are_available(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            assets = root / "frontend" / "copilot-shell" / "dist" / "assets"
            assets.mkdir(parents=True)
            (assets.parent / "index.html").write_text(
                '<title>CoreTest Agent</title>'
                '<script src="/copilot-shell/assets/index-test.js"></script>'
                '<link href="/copilot-shell/assets/index-test.css" rel="stylesheet">',
                encoding="utf-8",
            )
            (assets / "index-test.js").write_text("/api/v1/copilot/query", encoding="utf-8")
            (assets / "index-test.css").write_text("body {}", encoding="utf-8")
            (assets / "font-test.woff2").write_bytes(b"font")

            with patch("ai_gateway.app._repo_root", return_value=root):
                page = handle_request("GET", "/copilot-shell/")
                self.assertEqual(page.status, 200)
                self.assertEqual(page.content_type, "text/html; charset=utf-8")
                self.assertIsInstance(page.body, str)
                self.assertIn("CoreTest Agent", page.body)
                script_path = re.search(r'src="(/copilot-shell/assets/[^"]+\.js)"', page.body)
                style_path = re.search(r'href="(/copilot-shell/assets/[^"]+\.css)"', page.body)
                self.assertIsNotNone(script_path)
                self.assertIsNotNone(style_path)

                script = handle_request("GET", script_path.group(1))
                styles = handle_request("GET", style_path.group(1))
                self.assertEqual(script.status, 200)
                self.assertEqual(script.content_type, "application/javascript; charset=utf-8")
                self.assertIn("/api/v1/copilot/query", script.body)
                self.assertEqual(styles.status, 200)
                self.assertEqual(styles.content_type, "text/css; charset=utf-8")

                font_response = handle_request("GET", "/copilot-shell/assets/font-test.woff2")
                self.assertEqual(font_response.status, 200)
                self.assertEqual(font_response.content_type, "font/woff2")
                self.assertIsInstance(font_response.body, bytes)

    def test_native_agent_page_uses_opencode_ui_without_exposing_runtime_auth(self) -> None:
        runtime = _FakeOpenCodeRuntime()
        with TemporaryDirectory() as directory, patch(
            "ai_gateway.app.get_opencode_runtime", return_value=runtime
        ):
            handle_request(
                "POST",
                "/api/v1/host/workspace?host_session_id=native-page",
                json.dumps({"project_root": directory}),
            )
            response = handle_request(
                "GET", "/agent-native/?host_session_id=native-page"
            )

        self.assertEqual(response.status, 200)
        self.assertIn("<title>CoreTest Agent</title>", response.body)
        self.assertIn("coretest-agent-bootstrap", response.body)
        self.assertIn("/coretest-file/", response.body)
        self.assertNotIn("native-runtime-secret", response.body)
        self.assertIn("coretest_host_session=native-page", response.headers["Set-Cookie"])
        self.assertEqual(runtime.native_requests, [])

    def test_native_agent_server_session_route_uses_spa_page(self) -> None:
        runtime = _FakeOpenCodeRuntime()
        with TemporaryDirectory() as directory, patch(
            "ai_gateway.app.get_opencode_runtime", return_value=runtime
        ):
            handle_request(
                "POST",
                "/api/v1/host/workspace?host_session_id=native-session-page",
                json.dumps({"project_root": directory}),
            )
            response = handle_request(
                "GET",
                "/server/bG9jYWw/session/session-1?host_session_id=native-session-page",
            )

        self.assertEqual(response.status, 200)
        self.assertEqual(response.content_type, "text/html; charset=utf-8")
        self.assertIn("coretest-agent-bootstrap", response.body)
        self.assertEqual(runtime.native_requests, [])

    def test_native_agent_product_assets_are_served_without_runtime_proxy(self) -> None:
        repo_root = Path(__file__).resolve().parents[3]
        page = (repo_root / "frontend" / "opencode-coretest" / "dist" / "index.html").read_text(encoding="utf-8")
        script_path = re.search(r'src="(/assets/[^"]+\.js)"', page)
        self.assertIsNotNone(script_path)
        runtime = _FakeOpenCodeRuntime()
        with TemporaryDirectory() as directory, patch(
            "ai_gateway.app.get_opencode_runtime", return_value=runtime
        ):
            handle_request(
                "POST",
                "/api/v1/host/workspace?host_session_id=native-assets",
                json.dumps({"project_root": directory}),
            )
            response = handle_request(
                "GET",
                script_path.group(1) + "?host_session_id=native-assets",
            )

        self.assertEqual(response.status, 200)
        self.assertEqual(response.content_type, "application/javascript; charset=utf-8")
        self.assertIsInstance(response.body, bytes)
        self.assertEqual(runtime.native_requests, [])

    def test_native_agent_product_assets_hide_customer_visible_upstream_branding(self) -> None:
        dist = Path(__file__).resolve().parents[3] / "frontend" / "opencode-coretest" / "dist"
        self.assertTrue(dist.is_dir(), "CoreTest Agent native UI dist is missing")

        candidates = [dist / "index.html"]
        candidates.extend((dist / "assets").glob("index-*.js"))
        candidates.extend((dist / "assets").glob("dialog-*.js"))
        candidates.extend((dist / "assets").glob("new-session-*.js"))
        candidates.extend((dist / "assets").glob("zh-*.js"))
        candidates.extend((dist / "assets").glob("zht-*.js"))

        visible_upstream_phrases = [
            "OpenCode Go",
            "OpenCode Zen",
            "Subscribe to OpenCode",
            "opencode.ai/zen",
            "No recent projects",
            "Get started by opening a local project",
            "Switch which OpenCode server",
            "Configure model API",
            "Install OpenCode",
            "Update OpenCode",
        ]
        combined = "\n".join(
            path.read_text(encoding="utf-8", errors="ignore") for path in candidates
        )
        for phrase in visible_upstream_phrases:
            self.assertNotIn(phrase, combined)

    def test_native_agent_page_reports_missing_workspace_without_dropping_connection(self) -> None:
        response = handle_request(
            "GET", "/agent-native/?host_session_id=native-missing"
        )

        self.assertEqual(response.status, 502)
        self.assertEqual(
            json.loads(response.body)["error"]["code"], "service_unavailable"
        )

    def test_native_agent_profile_hides_unsupported_provider_fields(self) -> None:
        response = handle_request("GET", "/agent-native-profile.css")

        self.assertEqual(response.status, 200)
        self.assertIn('input[placeholder="Header-Name"]', response.body)
        self.assertIn('input[placeholder="API 密钥"]', response.body)
        self.assertIn('href^="https://opencode.ai/docs/providers/"', response.body)

    def test_native_agent_profile_hides_project_management_but_keeps_new_session(self) -> None:
        response = handle_request("GET", "/agent-native-profile.css")

        self.assertEqual(response.status, 200)
        self.assertIn('data-action="home-add-project"', response.body)
        self.assertIn('data-action="home-add-project-row"', response.body)
        self.assertIn('data-action="home-project-menu"', response.body)
        self.assertNotIn('aside[aria-label="项目"]', response.body)
        self.assertNotIn('aside[aria-label="Projects"]', response.body)
        self.assertNotIn('aria-label="新建会话"', response.body)
        self.assertNotIn('aria-label="New session"', response.body)

    def test_native_agent_protocol_uses_basic_gateway_auth_and_session_cookie(self) -> None:
        runtime = _FakeOpenCodeRuntime()
        basic = b64encode(b"opencode:copilot-secret").decode("ascii")
        with TemporaryDirectory() as directory, patch.dict(
            "os.environ",
            {
                "AI_GATEWAY_ACCESS_TOKEN": "copilot-secret",
                "AI_GATEWAY_HOST_TOKEN": "host-secret",
            },
        ), patch("ai_gateway.app.get_opencode_runtime", return_value=runtime):
            handle_request(
                "POST",
                "/api/v1/host/workspace?host_session_id=native-api",
                json.dumps({"project_root": directory}),
                headers={"Authorization": "Bearer host-secret"},
            )
            missing = handle_request(
                "GET", "/session", headers={"Cookie": "coretest_host_session=native-api"}
            )
            response = handle_request(
                "GET",
                "/session?directory=C%3A%5Cwrong",
                headers={
                    "Authorization": f"Basic {basic}",
                    "Cookie": "coretest_host_session=native-api",
                },
            )
            signed_cookie = response.headers["Set-Cookie"].split(";", 1)[0]
            resumed = handle_request(
                "GET",
                "/session",
                headers={
                    "Cookie": (
                        "coretest_host_session=native-api; " + signed_cookie
                    )
                },
            )

        self.assertEqual(missing.status, 401)
        self.assertEqual(response.status, 200)
        self.assertEqual(resumed.status, 200)
        self.assertNotIn("copilot-secret", response.headers["Set-Cookie"])
        self.assertEqual(
            runtime.native_requests,
            [
                ("GET", "/session?directory=C%3A%5Cwrong", None),
                ("GET", "/session", None),
            ],
        )

    def test_showcase_page_is_available(self) -> None:
        response = handle_request("GET", "/showcase")

        self.assertEqual(response.status, 200)
        self.assertEqual(response.content_type, "text/html; charset=utf-8")
        self.assertIn("Geely Test AI Workbench", response.body)
        self.assertIn("CoreTest Agent", response.body)
        self.assertNotIn('src="/copilot-shell/', response.body)
        self.assertIn("function loadCopilot()", response.body)
        self.assertIn('window.addEventListener("hashchange", loadCopilot)', response.body)
        self.assertIn("geely-ai.host-context", response.body)
        self.assertIn('source_asset_id: "demo-current"', response.body)
        self.assertIn('window.location.hash.slice(1)', response.body)
        self.assertNotIn("AI_GATEWAY_ACCESS_TOKEN", response.body)
        self.assertNotIn("D:/geely-ai-platform", response.body)

    def test_host_context_roundtrip(self) -> None:
        update = handle_request(
            "POST",
            "/api/v1/host/context",
            json.dumps(
                {
                    "project_id": "GEELY_TEST",
                    "run_id": "RUN_HOST_001",
                    "source_file": str(FIXTURES / "test-run-cases.csv"),
                    "target_file": str(FIXTURES / "test-run-cases-target.csv"),
                    "current_view": "test_result_detail",
                    "user_id": "tester",
                }
            ),
        )
        read = handle_request("GET", "/api/v1/host/context")

        update_payload = json.loads(update.body)
        read_payload = json.loads(read.body)
        self.assertEqual(update.status, 200)
        self.assertEqual(read.status, 200)
        self.assertEqual(update_payload["result"]["run_id"], "RUN_HOST_001")
        self.assertEqual(read_payload["result"]["source_file"], str(FIXTURES / "test-run-cases.csv"))

    def test_new_host_session_has_no_demo_context(self) -> None:
        response = handle_request(
            "GET", "/api/v1/host/context?host_session_id=unconnected-copilot"
        )

        context = json.loads(response.body)["result"]
        self.assertEqual(response.status, 200)
        self.assertIsNone(context["host_application"])
        self.assertIsNone(context["project_id"])
        self.assertIsNone(context["current_view"])
        self.assertNotIn("GEELY_TEST", response.body)
        self.assertNotIn("test_result_detail", response.body)

    def test_host_snapshot_roundtrip_and_trace_analysis(self) -> None:
        session = "coretest-trace"
        runtime = _FakeOpenCodeRuntime()
        snapshot = {
            "kind": "trace",
            "revision": "7",
            "selection": {"frame_id": "0x123"},
            "data": {
                "total_frames": 120,
                "duration_seconds": 2.5,
                "error_frames": 3,
                "top_frame_ids": [{"frame_id": "0x123", "count": 40}],
            },
        }
        with TemporaryDirectory() as directory, patch(
            "ai_gateway.app.get_opencode_runtime", return_value=runtime
        ):
            handle_request(
                "POST",
                f"/api/v1/host/workspace?host_session_id={session}",
                json.dumps({"project_root": directory}),
            )
            published = handle_request(
                "POST",
                f"/api/v1/host/snapshot?host_session_id={session}",
                json.dumps(snapshot),
            )
            read = handle_request("GET", f"/api/v1/host/snapshot?host_session_id={session}")
            analysis = handle_request(
                "POST",
                f"/api/v1/host/snapshot/analyze?host_session_id={session}",
                json.dumps({"question": "分析当前 Trace"}, ensure_ascii=False),
            )

        self.assertEqual(published.status, 200)
        self.assertEqual(json.loads(read.body)["result"]["revision"], "7")
        payload = json.loads(analysis.body)
        self.assertEqual(analysis.status, 200)
        self.assertEqual(payload["answer"], "来自工作区 Agent 的回答")
        self.assertIn("120", runtime.prompts[0][1])
        self.assertIn("0x123", runtime.prompts[0][1])

    def test_host_snapshot_is_session_isolated_and_size_limited(self) -> None:
        handle_request(
            "POST",
            "/api/v1/host/snapshot?host_session_id=snapshot-a",
            json.dumps({"kind": "project", "revision": "1", "data": {"name": "A"}}),
        )
        other = handle_request("GET", "/api/v1/host/snapshot?host_session_id=snapshot-b")
        with patch.dict("os.environ", {"AI_GATEWAY_MAX_HOST_SNAPSHOT_BYTES": "80"}):
            oversized = handle_request(
                "POST",
                "/api/v1/host/snapshot?host_session_id=snapshot-a",
                json.dumps(
                    {"kind": "project", "revision": "2", "data": {"text": "x" * 200}}
                ),
            )

        self.assertIsNone(json.loads(other.body)["result"]["kind"])
        self.assertEqual(oversized.status, 400)
        self.assertIn("size limit", oversized.body)

    def test_pdx_snapshot_is_analyzed_by_opencode(self) -> None:
        session = "coretest-pdx"
        runtime = _FakeOpenCodeRuntime()
        with TemporaryDirectory() as directory, patch(
            "ai_gateway.app.get_opencode_runtime", return_value=runtime
        ):
            handle_request(
                "POST",
                f"/api/v1/host/workspace?host_session_id={session}",
                json.dumps({"project_root": directory}),
            )
            published = handle_request(
                "POST",
                f"/api/v1/host/snapshot?host_session_id={session}",
                json.dumps(
                    {
                        "kind": "pdx",
                        "revision": "8",
                        "selection": {"pdx_name": "somersault.pdx"},
                        "data": {
                            "ecu_count": 2,
                            "diagnostic_layer_count": 4,
                            "ecus": [
                                {"name": "somersault_lazy", "service_count": 6},
                                {"name": "somersault_assiduous", "service_count": 6},
                            ],
                        },
                    }
                ),
            )
            analysis = handle_request(
                "POST",
                f"/api/v1/host/snapshot/analyze?host_session_id={session}",
                json.dumps({"question": "Analyze this PDX"}),
            )

        self.assertEqual(published.status, 200)
        self.assertEqual(analysis.status, 200)
        self.assertIn("somersault.pdx", runtime.prompts[0][1])
        self.assertIn("somersault_lazy", runtime.prompts[0][1])

    def test_copilot_token_cannot_publish_host_snapshot(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "AI_GATEWAY_ACCESS_TOKEN": "copilot-secret",
                "AI_GATEWAY_HOST_TOKEN": "host-secret",
            },
        ):
            forbidden = handle_request(
                "POST",
                "/api/v1/host/snapshot?host_session_id=secure-snapshot",
                json.dumps({"kind": "project", "revision": "1", "data": {}}),
                headers={"Authorization": "Bearer copilot-secret"},
            )
            allowed = handle_request(
                "POST",
                "/api/v1/host/snapshot?host_session_id=secure-snapshot",
                json.dumps({"kind": "project", "revision": "1", "data": {}}),
                headers={"Authorization": "Bearer host-secret"},
            )

        self.assertEqual(forbidden.status, 403)
        self.assertEqual(allowed.status, 200)

    def test_host_context_is_isolated_by_session(self) -> None:
        handle_request(
            "POST",
            "/api/v1/host/context?host_session_id=session-a",
            json.dumps({"project_id": "PROJECT_A", "run_id": "RUN_A"}),
        )
        handle_request(
            "POST",
            "/api/v1/host/context?host_session_id=session-b",
            json.dumps({"project_id": "PROJECT_B", "run_id": "RUN_B"}),
        )

        session_a = handle_request("GET", "/api/v1/host/context?host_session_id=session-a")
        session_b = handle_request("GET", "/api/v1/host/context?host_session_id=session-b")
        payload_a = json.loads(session_a.body)["result"]
        payload_b = json.loads(session_b.body)["result"]

        self.assertEqual(payload_a["host_session_id"], "session-a")
        self.assertEqual(payload_a["project_id"], "PROJECT_A")
        self.assertEqual(payload_b["host_session_id"], "session-b")
        self.assertEqual(payload_b["project_id"], "PROJECT_B")

    def test_host_asset_analysis_uses_asset_id_without_exposing_file_path(self) -> None:
        source_file = str(FIXTURES / "test-run-cases.csv")
        registration = handle_request(
            "POST",
            "/api/v1/host/assets?host_session_id=session-assets",
            json.dumps({"asset_id": "current-run", "file_path": source_file}),
        )
        analysis = handle_request(
            "POST",
            "/api/v1/test-data/summary?host_session_id=session-assets",
            json.dumps({"source_asset_id": "current-run"}),
        )

        registration_payload = json.loads(registration.body)
        analysis_payload = json.loads(analysis.body)
        self.assertEqual(registration.status, 200)
        self.assertEqual(registration_payload["result"]["asset_id"], "current-run")
        self.assertNotIn("file_path", registration_payload["result"])
        self.assertEqual(analysis.status, 200)
        self.assertEqual(analysis_payload["result"]["source"], {"type": "host_asset", "ref": "current-run"})
        self.assertNotIn(source_file, analysis.body)

    def test_access_control_requires_registered_assets_instead_of_file_paths(self) -> None:
        access_token = "copilot-secret"
        host_token = "host-secret"
        headers = {"Authorization": f"Bearer {access_token}"}
        host_headers = {"Authorization": f"Bearer {host_token}"}
        with patch.dict(
            "os.environ",
            {
                "AI_GATEWAY_ACCESS_TOKEN": access_token,
                "AI_GATEWAY_HOST_TOKEN": host_token,
            },
        ):
            direct = handle_request(
                "POST",
                "/api/v1/test-data/summary?host_session_id=secure-session",
                json.dumps({"source_file": str(FIXTURES / "test-run-cases.csv")}),
                headers=headers,
            )
            registered = handle_request(
                "POST",
                "/api/v1/host/assets?host_session_id=secure-session",
                json.dumps(
                    {
                        "asset_id": "secure-run",
                        "file_path": str(FIXTURES / "test-run-cases.csv"),
                    }
                ),
                headers=host_headers,
            )
            analysis = handle_request(
                "POST",
                "/api/v1/test-data/summary?host_session_id=secure-session",
                json.dumps({"source_asset_id": "secure-run"}),
                headers=headers,
            )

        self.assertEqual(direct.status, 400)
        self.assertIn("register a host asset", direct.body)
        self.assertEqual(registered.status, 200)
        self.assertEqual(analysis.status, 200)

    def test_copilot_token_cannot_register_local_file(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "AI_GATEWAY_ACCESS_TOKEN": "copilot-secret",
                "AI_GATEWAY_HOST_TOKEN": "host-secret",
            },
        ):
            response = handle_request(
                "POST",
                "/api/v1/host/assets?host_session_id=secure-session",
                json.dumps({"file_path": str(FIXTURES / "test-run-cases.csv")}),
                headers={"Authorization": "Bearer copilot-secret"},
            )

        self.assertEqual(response.status, 403)
        self.assertEqual(json.loads(response.body)["error"]["code"], "host_forbidden")

    def test_host_registers_private_workspace_without_starting_agent_runtime(self) -> None:
        runtime = _FakeOpenCodeRuntime()
        with TemporaryDirectory() as directory, patch.dict(
            "os.environ",
            {
                "AI_GATEWAY_ACCESS_TOKEN": "copilot-secret",
                "AI_GATEWAY_HOST_TOKEN": "host-secret",
            },
        ), patch("ai_gateway.app.get_opencode_runtime", return_value=runtime):
            forbidden = handle_request(
                "POST",
                "/api/v1/host/workspace?host_session_id=workspace-session",
                json.dumps({"project_root": directory}),
                headers={"Authorization": "Bearer copilot-secret"},
            )
            registered = handle_request(
                "POST",
                "/api/v1/host/workspace?host_session_id=workspace-session",
                json.dumps(
                    {
                        "project_root": directory,
                        "host_bridge": {
                            "url": "http://127.0.0.1:43123",
                            "token": "private-bridge-token",
                        },
                    }
                ),
                headers={"Authorization": "Bearer host-secret"},
            )
            status = handle_request(
                "GET",
                "/api/v1/agent/status?host_session_id=workspace-session",
                headers={"Authorization": "Bearer copilot-secret"},
            )

        self.assertEqual(forbidden.status, 403)
        self.assertEqual(registered.status, 200)
        self.assertEqual(status.status, 200)
        self.assertIsNone(runtime.started_with)
        self.assertNotIn(directory, registered.body)
        self.assertNotIn(directory, status.body)
        self.assertNotIn("runtime-secret", status.body)
        self.assertNotIn("private-bridge-token", registered.body)
        self.assertNotIn("127.0.0.1:43123", registered.body)
        self.assertTrue(json.loads(status.body)["result"]["workspace"]["registered"])
        self.assertTrue(json.loads(registered.body)["result"]["host_bridge"]["available"])

    def test_releasing_last_workspace_stops_agent_runtime(self) -> None:
        runtime = _FakeOpenCodeRuntime()
        with TemporaryDirectory() as directory, patch(
            "ai_gateway.app.get_opencode_runtime", return_value=runtime
        ):
            handle_request(
                "POST",
                "/api/v1/host/workspace?host_session_id=release-workspace",
                json.dumps(
                    {
                        "project_root": directory,
                        "host_bridge": {
                            "url": "http://127.0.0.1:43123",
                            "token": "private-bridge-token",
                        },
                    }
                ),
            )
            released = handle_request(
                "DELETE", "/api/v1/host/session?host_session_id=release-workspace"
            )

        payload = json.loads(released.body)["result"]
        self.assertTrue(payload["released_workspace"])
        self.assertTrue(payload["released_host_bridge"])
        self.assertEqual(runtime.released_session_groups, ["release-workspace"])
        self.assertTrue(runtime.stopped)

    def test_copilot_uses_workspace_agent_after_workspace_registration(self) -> None:
        runtime = _FakeOpenCodeRuntime()
        with TemporaryDirectory() as directory, patch(
            "ai_gateway.app.get_opencode_runtime", return_value=runtime
        ):
            handle_request(
                "POST",
                "/api/v1/host/workspace?host_session_id=agent-chat",
                json.dumps({"project_root": directory}),
            )
            response = handle_request(
                "POST",
                "/api/v1/copilot/query?host_session_id=agent-chat",
                json.dumps(
                    {
                        "question": "先查看项目结构再回答",
                        "conversation_id": "conversation-1",
                        "task": "chat",
                        "attachments": [],
                        "history": [],
                    }
                ),
            )

        payload = json.loads(response.body)
        self.assertEqual(response.status, 200)
        self.assertEqual(runtime.started_with, get_workspace_path("agent-chat"))
        self.assertEqual(payload["answer"], "来自工作区 Agent 的回答")
        self.assertEqual(len(runtime.prompts), 1)
        session_id, question, system, history, new_session = runtime.prompts[0]
        self.assertEqual(session_id, "agent-chat:conversation-1")
        self.assertEqual(question, "用户任务：先查看项目结构再回答")
        self.assertIn("工作区智能体", system)
        self.assertEqual(history, [])
        self.assertTrue(new_session)

    def test_copilot_stream_returns_sse_events(self) -> None:
        runtime = _FakeOpenCodeRuntime()
        with TemporaryDirectory() as directory, patch(
            "ai_gateway.app.get_opencode_runtime", return_value=runtime
        ):
            handle_request(
                "POST",
                "/api/v1/host/workspace?host_session_id=agent-stream",
                json.dumps({"project_root": directory}),
            )
            response = handle_request(
                "POST",
                "/api/v1/copilot/stream?host_session_id=agent-stream",
                json.dumps(
                    {
                        "question": "inspect the project",
                        "conversation_id": "conversation-1",
                        "task": "chat",
                        "attachments": [],
                        "history": [],
                    }
                ),
            )
            chunks = b"".join(response.stream or ()).decode("utf-8")
            invalid = handle_request(
                "POST",
                "/api/v1/copilot/stream?host_session_id=agent-stream",
                json.dumps({"question": "inspect", "unsupported": True}),
            )

        self.assertEqual(response.status, 200)
        self.assertEqual(response.content_type, "text/event-stream; charset=utf-8")
        self.assertEqual(invalid.status, 400)
        self.assertIn('"type": "text_delta"', chunks)
        self.assertIn('"type": "completed"', chunks)
        self.assertEqual(runtime.started_with, get_workspace_path("agent-stream"))
        self.assertEqual(runtime.streamed_sessions, ["agent-stream:conversation-1"])

    def test_copilot_stream_maps_stalled_runtime_error(self) -> None:
        runtime = _FakeOpenCodeRuntime()

        def stalled_stream(*_args, **_kwargs):
            yield {"type": "started"}
            raise RuntimeError("OpenCode event stream made no progress for too long")

        runtime.stream_prompt = stalled_stream
        with TemporaryDirectory() as directory, patch(
            "ai_gateway.app.get_opencode_runtime", return_value=runtime
        ):
            handle_request(
                "POST",
                "/api/v1/host/workspace?host_session_id=agent-stalled",
                json.dumps({"project_root": directory}),
            )
            response = handle_request(
                "POST",
                "/api/v1/copilot/stream?host_session_id=agent-stalled",
                json.dumps(
                    {
                        "question": "inspect the project",
                        "conversation_id": "conversation-1",
                        "task": "chat",
                        "attachments": [],
                        "history": [],
                    }
                ),
            )
            chunks = b"".join(response.stream or ()).decode("utf-8")

        self.assertIn('"type": "error"', chunks)
        self.assertIn('"code": "agent_stalled"', chunks)

    def test_copilot_permission_and_abort_routes_are_conversation_scoped(self) -> None:
        runtime = _FakeOpenCodeRuntime()
        runtime.permissions = [
            {
                "id": "per-1",
                "permission": "bash",
                "resources": ["python -m pytest"],
            }
        ]
        runtime.activities = [
            {
                "id": "part-1",
                "tool": "bash",
                "status": "completed",
                "title": "python -m pytest",
                "output": "1 passed",
            }
        ]
        runtime.diffs = {
            "files": [
                {
                    "path": "src/sample.py",
                    "status": "modified",
                    "additions": 1,
                    "deletions": 0,
                    "patch": "+print('ok')",
                    "truncated": False,
                }
            ],
            "revert_available": True,
            "revert_reason": None,
        }
        with patch("ai_gateway.app.get_opencode_runtime", return_value=runtime):
            pending = handle_request(
                "POST",
                "/api/v1/agent/permissions?host_session_id=agent-chat",
                json.dumps({"conversation_id": "conversation-1"}),
            )
            activity = handle_request(
                "POST",
                "/api/v1/agent/activity?host_session_id=agent-chat",
                json.dumps({"conversation_id": "conversation-1"}),
            )
            diff = handle_request(
                "POST",
                "/api/v1/agent/diff?host_session_id=agent-chat",
                json.dumps({"conversation_id": "conversation-1"}),
            )
            reverted = handle_request(
                "POST",
                "/api/v1/agent/revert?host_session_id=agent-chat",
                json.dumps({"conversation_id": "conversation-1"}),
            )
            replied = handle_request(
                "POST",
                "/api/v1/agent/permissions/reply?host_session_id=agent-chat",
                json.dumps(
                    {
                        "conversation_id": "conversation-1",
                        "request_id": "per-1",
                        "reply": "once",
                    }
                ),
            )
            aborted = handle_request(
                "POST",
                "/api/v1/agent/abort?host_session_id=agent-chat",
                json.dumps({"conversation_id": "conversation-1"}),
            )

        self.assertEqual(
            json.loads(pending.body)["result"]["permissions"], runtime.permissions
        )
        self.assertEqual(
            json.loads(activity.body)["result"]["activity"], runtime.activities
        )
        self.assertEqual(json.loads(diff.body)["result"], runtime.diffs)
        self.assertEqual(runtime.reverted_sessions, ["agent-chat:conversation-1"])
        self.assertEqual(
            runtime.permission_replies,
            [("agent-chat:conversation-1", "per-1", "once")],
        )
        self.assertEqual(runtime.aborted_sessions, ["agent-chat:conversation-1"])
        self.assertTrue(json.loads(replied.body)["result"]["replied"])
        self.assertTrue(json.loads(aborted.body)["result"]["aborted"])
        self.assertTrue(json.loads(reverted.body)["result"]["reverted"])

    def test_host_can_release_one_session_without_affecting_another(self) -> None:
        source_file = str(FIXTURES / "test-run-cases.csv")
        for session in ("release-a", "release-b"):
            handle_request(
                "POST",
                f"/api/v1/host/context?host_session_id={session}",
                json.dumps({"project_id": session, "run_id": f"run-{session}"}),
            )
            handle_request(
                "POST",
                f"/api/v1/host/assets?host_session_id={session}",
                json.dumps({"asset_id": "current", "file_path": source_file}),
            )
            handle_request(
                "POST",
                f"/api/v1/host/snapshot?host_session_id={session}",
                json.dumps({"kind": "project", "revision": "1", "data": {}}),
            )

        released = handle_request(
            "DELETE", "/api/v1/host/session?host_session_id=release-a"
        )
        old_asset = handle_request(
            "POST",
            "/api/v1/test-data/summary?host_session_id=release-a",
            json.dumps({"source_asset_id": "current"}),
        )
        other_asset = handle_request(
            "POST",
            "/api/v1/test-data/summary?host_session_id=release-b",
            json.dumps({"source_asset_id": "current"}),
        )

        payload = json.loads(released.body)["result"]
        self.assertEqual(released.status, 200)
        self.assertTrue(payload["released_context"])
        self.assertEqual(payload["released_assets"], 1)
        self.assertTrue(payload["released_snapshot"])
        self.assertEqual(old_asset.status, 400)
        self.assertEqual(other_asset.status, 200)

    def test_host_session_and_asset_limits_are_enforced(self) -> None:
        source_file = str(FIXTURES / "test-run-cases.csv")
        with patch.dict(
            "os.environ",
            {
                "AI_GATEWAY_MAX_HOST_SESSIONS": "1",
                "AI_GATEWAY_MAX_ASSETS_PER_SESSION": "1",
            },
        ):
            reset_host_context()
            session_limit = handle_request(
                "GET", "/api/v1/host/context?host_session_id=second"
            )
            first_asset = handle_request(
                "POST",
                "/api/v1/host/assets",
                json.dumps({"asset_id": "first", "file_path": source_file}),
            )
            asset_limit = handle_request(
                "POST",
                "/api/v1/host/assets",
                json.dumps({"asset_id": "second", "file_path": source_file}),
            )

        self.assertEqual(session_limit.status, 400)
        self.assertIn("host session limit", session_limit.body)
        self.assertEqual(first_asset.status, 200)
        self.assertEqual(asset_limit.status, 400)
        self.assertIn("host asset limit", asset_limit.body)

    def test_host_context_rejects_unknown_fields(self) -> None:
        response = handle_request(
            "POST",
            "/api/v1/host/context",
            json.dumps({"unsafe": "value"}),
        )

        payload = json.loads(response.body)
        self.assertEqual(response.status, 400)
        self.assertEqual(payload["error"]["code"], "bad_request")
        self.assertIn("unsupported host context fields", payload["error"]["message"])

    def test_audit_events_record_successful_api_request(self) -> None:
        session = "audit-coretest"
        handle_request(
            "POST",
            f"/api/v1/host/context?host_session_id={session}",
            json.dumps({"host_application": "HK CoreTest", "project_id": "vehicle-a"}),
        )
        handle_request(
            "POST",
            f"/api/v1/test-data/summary?host_session_id={session}",
            json.dumps({"source_file": str(FIXTURES / "test-run-cases.csv")}),
        )
        response = handle_request("GET", "/api/v1/audit/events")

        payload = json.loads(response.body)
        event = payload["result"]["events"][-1]
        self.assertEqual(response.status, 200)
        self.assertEqual(event["method"], "POST")
        self.assertEqual(event["path"], "/api/v1/test-data/summary")
        self.assertEqual(event["status"], 200)
        self.assertTrue(event["request_id"].startswith("req_"))
        self.assertEqual(event["project_id"], "vehicle-a")

    def test_audit_events_record_error_code(self) -> None:
        handle_request("POST", "/api/v1/analyze", "{bad")
        response = handle_request("GET", "/api/v1/audit/events")

        payload = json.loads(response.body)
        event = payload["result"]["events"][-1]
        self.assertEqual(event["status"], 400)
        self.assertEqual(event["error_code"], "invalid_json")

    def test_plugin_manifest_describes_host_integration(self) -> None:
        response = handle_request("GET", "/plugin-manifest.json")

        payload = json.loads(response.body)
        self.assertEqual(response.status, 200)
        self.assertIn("webview", payload["integration_modes"])
        self.assertEqual(payload["webview"]["entry"], "/agent-native/")
        self.assertEqual(payload["webview"]["legacy_entry"], "/copilot-shell/")
        self.assertEqual(payload["webview"]["fallback_entry"], "/copilot")
        self.assertEqual(payload["webview"]["host_session_query_parameter"], "host_session_id")
        self.assertEqual(payload["webview"]["host_origin_query_parameter"], "host_origin")
        self.assertEqual(payload["webview"]["access_token_fragment_parameter"], "access_token")
        self.assertEqual(
            payload["webview"]["post_message"]["host_to_copilot"],
            "geely-ai.host-context",
        )
        self.assertEqual(payload["api"]["host_assets"], "/api/v1/host/assets")
        self.assertEqual(payload["api"]["host_snapshot"], "/api/v1/host/snapshot")
        self.assertEqual(payload["api"]["authentication"]["type"], "http-bearer")
        self.assertEqual(
            payload["api"]["authentication"]["privileged_host_env"],
            "AI_GATEWAY_HOST_TOKEN",
        )
        operation_ids = {operation["operation_id"] for operation in payload["api"]["operations"]}
        self.assertIn("compare_test_runs", operation_ids)
        self.assertIn("analyze_test_data_insights", operation_ids)
        self.assertIn("get_host_context", operation_ids)
        self.assertIn("update_host_context", operation_ids)
        self.assertIn("query_copilot", operation_ids)
        self.assertIn("release_host_session", operation_ids)
        self.assertIn("analyze_host_snapshot", operation_ids)
        self.assertIn("get_host_snapshot", operation_ids)

    def test_openapi_describes_bearer_auth_and_public_pages(self) -> None:
        payload = json.loads(handle_request("GET", "/openapi.json").body)

        self.assertEqual(
            payload["components"]["securitySchemes"]["bearerAuth"]["scheme"],
            "bearer",
        )
        self.assertEqual(payload["security"], [{"bearerAuth": []}, {}])
        self.assertEqual(payload["paths"]["/health"]["get"]["security"], [])
        self.assertEqual(payload["paths"]["/copilot-shell/"]["get"]["security"], [])
        self.assertEqual(payload["paths"]["/agent-native/"]["get"]["security"], [])
        self.assertEqual(
            payload["paths"]["/api/v1/host/assets"]["post"]["x-required-token"],
            "host",
        )
        self.assertEqual(
            payload["paths"]["/api/v1/host/session"]["delete"]["x-required-token"],
            "host",
        )
        self.assertEqual(
            payload["paths"]["/api/v1/host/snapshot"]["post"]["x-required-token"],
            "host",
        )
        self.assertIn("/api/v1/copilot/query", payload["paths"])
        self.assertIn("/api/v1/copilot/stream", payload["paths"])
        self.assertIn("/api/v1/agent/permissions", payload["paths"])
        self.assertIn("/api/v1/agent/activity", payload["paths"])
        self.assertIn("/api/v1/agent/diff", payload["paths"])
        self.assertIn("/api/v1/agent/revert", payload["paths"])
        self.assertIn("/api/v1/agent/permissions/reply", payload["paths"])
        self.assertIn("/api/v1/agent/abort", payload["paths"])
        copilot = payload["paths"]["/api/v1/copilot/query"]["post"]
        self.assertEqual(
            copilot["requestBody"]["content"]["application/json"]["schema"]["$ref"],
            "#/components/schemas/CopilotQueryRequest",
        )
        self.assertIn(
            "text/event-stream",
            payload["paths"]["/api/v1/copilot/stream"]["post"]["responses"]["200"]["content"],
        )
        self.assertEqual(
            payload["components"]["schemas"]["CopilotQueryRequest"]["properties"]
            ["attachments"]["maxItems"],
            5,
        )
        self.assertEqual(
            payload["paths"]["/api/v1/host/snapshot"]["post"]["security"],
            [{"hostBearerAuth": []}],
        )

    def test_static_contracts_are_served_at_runtime(self) -> None:
        repo_root = Path(__file__).resolve().parents[3]
        runtime_manifest = json.loads(handle_request("GET", "/plugin-manifest.json").body)
        static_manifest = json.loads(
            (repo_root / "contracts" / "host-plugin.manifest.json").read_text(encoding="utf-8")
        )
        runtime_openapi = json.loads(handle_request("GET", "/openapi.json").body)
        static_openapi = json.loads(
            (repo_root / "contracts" / "ai-gateway.openapi.json").read_text(encoding="utf-8")
        )
        self.assertEqual(static_manifest, runtime_manifest)
        self.assertEqual(static_openapi, runtime_openapi)

    def test_test_data_insights_reads_source_file(self) -> None:
        response = handle_request(
            "POST",
            "/api/v1/test-data/insights",
            json.dumps({"source_file": str(FIXTURES / "test-run-cases.csv")}),
        )

        payload = json.loads(response.body)
        self.assertEqual(response.status, 200)
        self.assertIn(payload["result"]["engine"], {"duckdb", "stdlib"})
        self.assertEqual(payload["result"]["run_id"], "RUN_CSV_001")
        self.assertEqual(payload["result"]["status_counts"][0]["count"], 1)
        self.assertEqual(payload["result"]["failure_reasons"][0]["reason"], "扭矩误差超过阈值")

    def test_test_data_compare_reads_two_source_files(self) -> None:
        response = handle_request(
            "POST",
            "/api/v1/test-data/compare",
            json.dumps(
                {
                    "baseline_file": str(FIXTURES / "test-run-cases.csv"),
                    "target_file": str(FIXTURES / "test-run-cases-target.csv"),
                }
            ),
        )

        payload = json.loads(response.body)
        self.assertEqual(response.status, 200)
        self.assertEqual(payload["result"]["baseline_run_id"], "RUN_CSV_001")
        self.assertEqual(payload["result"]["target_run_id"], "RUN_CSV_002")
        self.assertIn("失败用例增加 1 个", payload["result"]["summary"])

    def test_not_found(self) -> None:
        response = handle_request("GET", "/missing")

        self.assertEqual(response.status, 404)
        payload = json.loads(response.body)
        self.assertTrue(payload["request_id"].startswith("req_"))
        self.assertEqual(payload["error"]["code"], "not_found")

    def test_bad_json_returns_request_id(self) -> None:
        response = handle_request("POST", "/api/v1/analyze", "{bad")

        payload = json.loads(response.body)
        self.assertEqual(response.status, 400)
        self.assertTrue(payload["request_id"].startswith("req_"))
        self.assertEqual(payload["error"]["code"], "invalid_json")

    def test_missing_source_file_returns_bad_request(self) -> None:
        response = handle_request(
            "POST",
            "/api/v1/test-data/summary",
            json.dumps({"source_file": str(FIXTURES / "missing.csv")}),
        )

        payload = json.loads(response.body)
        self.assertEqual(response.status, 400)
        self.assertEqual(payload["error"]["code"], "bad_request")
        self.assertIn("does not exist", payload["error"]["message"])

    def test_unsupported_source_file_returns_bad_request(self) -> None:
        response = handle_request(
            "POST",
            "/api/v1/test-data/summary",
            json.dumps({"source_file": str(FIXTURES / "test-run-cases.txt")}),
        )

        payload = json.loads(response.body)
        self.assertEqual(response.status, 400)
        self.assertEqual(payload["error"]["code"], "bad_request")
        self.assertIn("unsupported", payload["error"]["message"])


class _FakeOpenCodeRuntime:
    def __init__(self) -> None:
        self.started_with = None
        self.stopped = False
        self.prompts = []
        self.released_sessions = []
        self.released_session_groups = []
        self.permissions = []
        self.activities = []
        self.diffs = []
        self.permission_replies = []
        self.aborted_sessions = []
        self.reverted_sessions = []
        self.streamed_sessions = []
        self.saved_providers = []
        self.deleted_providers = []
        self.activated_providers = []
        self.tested_providers = []
        self.native_requests = []

    def start(self, workspace):
        self.started_with = workspace
        return self.status()

    def status(self, *, check_health=False):
        return {
            "installed": True,
            "running": self.started_with is not None and not self.stopped,
            "healthy": bool(check_health and self.started_with is not None),
            "version": "test" if check_health else None,
            "model_configured": True,
            "error": None,
        }

    def stop(self) -> None:
        self.stopped = True

    def prompt(
        self, host_session_id, question, *, system, history, new_session=False
    ):
        self.prompts.append(
            (host_session_id, question, system, history, new_session)
        )
        return "来自工作区 Agent 的回答"

    def release_session(self, host_session_id):
        self.released_sessions.append(host_session_id)

    def stream_prompt(
        self, host_session_id, question, *, system, history, new_session=False
    ):
        self.streamed_sessions.append(host_session_id)
        yield {"type": "started"}
        yield {"type": "text_delta", "delta": "streamed answer"}
        yield {"type": "completed", "answer": "streamed answer"}

    def release_sessions(self, host_session_id):
        self.released_session_groups.append(host_session_id)

    def pending_permissions(self, host_session_id):
        return self.permissions

    def activity(self, host_session_id):
        return self.activities

    def diff(self, host_session_id):
        return self.diffs

    def revert(self, host_session_id):
        self.reverted_sessions.append(host_session_id)
        return True

    def reply_permission(self, host_session_id, request_id, reply):
        self.permission_replies.append((host_session_id, request_id, reply))

    def abort(self, host_session_id):
        self.aborted_sessions.append(host_session_id)
        return True

    def providers(self):
        return {
            "providers": [
                {
                    "id": "company-api",
                    "name": "Company API",
                    "base_url": "https://api.example.com/v1",
                    "models": [{"id": "tool-model", "name": "Tool Model"}],
                    "api_key_configured": True,
                    "active": True,
                }
            ],
            "active_provider_id": "company-api",
            "active_model_id": "tool-model",
        }

    def save_provider(self, payload):
        self.saved_providers.append(payload)
        return self.providers()

    def delete_provider(self, provider_id):
        self.deleted_providers.append(provider_id)
        return {"providers": [], "active_provider_id": None, "active_model_id": None}

    def activate_provider(self, provider_id, model_id):
        self.activated_providers.append((provider_id, model_id))
        return self.providers()

    def test_provider(self, provider_id, model_id):
        self.tested_providers.append((provider_id, model_id))
        return {"ok": True, "provider_id": provider_id, "model_id": model_id}

    def native_request(self, method, path, body=None, *, content_type="application/json"):
        self.native_requests.append((method, path, body))
        if path == "/":
            return OpenCodeNativeResponse(
                200,
                b"<!doctype html><html><head><title>OpenCode</title></head><body>native-runtime-secret</body></html>".replace(
                    b"native-runtime-secret", b"OpenCode UI"
                ),
                "text/html; charset=utf-8",
            )
        return OpenCodeNativeResponse(200, b"[]", "application/json")


if __name__ == "__main__":
    unittest.main()
