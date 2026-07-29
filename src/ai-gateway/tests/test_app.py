import json
from pathlib import Path
import re
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from ai_gateway.app import handle_request
from ai_gateway.audit_log import clear_audit_events
from ai_gateway.host_assets import reset_host_assets
from ai_gateway.host_context import reset_host_context
from ai_gateway.host_snapshot import reset_host_snapshots


FIXTURES = Path(__file__).parent / "fixtures"


class AppTests(unittest.TestCase):
    def tearDown(self) -> None:
        reset_host_context()
        reset_host_assets()
        reset_host_snapshots()
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

    def test_analyze_combines_deterministic_data(self) -> None:
        response = handle_request(
            "POST",
            "/api/v1/analyze",
            json.dumps(
                {
                    "question": "分析失败原因",
                    "source_file": str(FIXTURES / "test-run-cases.json"),
                }
            ),
        )

        payload = json.loads(response.body)
        self.assertEqual(response.status, 200)
        self.assertIn("answer", payload)
        self.assertEqual(payload["citations"], [])
        self.assertEqual(payload["data"]["source"]["type"], "json")

    def test_analyze_reads_source_file(self) -> None:
        response = handle_request(
            "POST",
            "/api/v1/analyze",
            json.dumps({"source_file": str(FIXTURES / "test-run-cases.json")}),
        )

        payload = json.loads(response.body)
        self.assertEqual(response.status, 200)
        self.assertEqual(payload["data"]["run_id"], "RUN_JSON_001")
        self.assertIn("本次测试共 3 个用例", payload["answer"])

    def test_analyze_use_model_falls_back_when_unconfigured(self) -> None:
        response = handle_request(
            "POST",
            "/api/v1/analyze",
            json.dumps(
                {
                    "source_file": str(FIXTURES / "test-run-cases.json"),
                    "use_model": True,
                }
            ),
        )

        payload = json.loads(response.body)
        self.assertEqual(response.status, 200)
        self.assertIn("本次测试共", payload["answer"])
        self.assertIn("model api is not configured", payload["warnings"][0])

    def test_model_config_does_not_expose_secret(self) -> None:
        response = handle_request("GET", "/api/v1/model/config")

        payload = json.loads(response.body)
        self.assertEqual(response.status, 200)
        self.assertIn("configured", payload["result"])
        self.assertNotIn("api_key", payload["result"])

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
        self.assertIn("Geely AI Copilot Shell", response.body)
        self.assertNotIn("GEELY_TEST", response.body)
        self.assertNotIn("D:\\geely-ai-platform", response.body)

    def test_copilot_shell_assets_are_available(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            assets = root / "frontend" / "copilot-shell" / "dist" / "assets"
            assets.mkdir(parents=True)
            (assets.parent / "index.html").write_text(
                '<title>Geely AI Copilot Shell</title>'
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
                self.assertIn("Geely AI Copilot Shell", page.body)
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

    def test_showcase_page_is_available(self) -> None:
        response = handle_request("GET", "/showcase")

        self.assertEqual(response.status, 200)
        self.assertEqual(response.content_type, "text/html; charset=utf-8")
        self.assertIn("Geely Test AI Workbench", response.body)
        self.assertIn("Reusable Geely AI Copilot", response.body)
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
        self.assertIn("120 帧", payload["answer"])
        self.assertIn("0x123", payload["answer"])
        self.assertEqual(payload["data"]["kind"], "trace")

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
            "/api/v1/analyze?host_session_id=session-assets",
            json.dumps({"source_asset_id": "current-run", "question": "分析失败原因"}),
        )

        registration_payload = json.loads(registration.body)
        analysis_payload = json.loads(analysis.body)
        self.assertEqual(registration.status, 200)
        self.assertEqual(registration_payload["result"]["asset_id"], "current-run")
        self.assertNotIn("file_path", registration_payload["result"])
        self.assertEqual(analysis.status, 200)
        self.assertEqual(analysis_payload["data"]["source"], {"type": "host_asset", "ref": "current-run"})
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
                "/api/v1/analyze?host_session_id=secure-session",
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
                "/api/v1/analyze?host_session_id=secure-session",
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
            "/api/v1/analyze?host_session_id=release-a",
            json.dumps({"source_asset_id": "current"}),
        )
        other_asset = handle_request(
            "POST",
            "/api/v1/analyze?host_session_id=release-b",
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
            f"/api/v1/analyze?host_session_id={session}",
            json.dumps({"source_file": str(FIXTURES / "test-run-cases.csv")}),
        )
        response = handle_request("GET", "/api/v1/audit/events")

        payload = json.loads(response.body)
        event = payload["result"]["events"][-1]
        self.assertEqual(response.status, 200)
        self.assertEqual(event["method"], "POST")
        self.assertEqual(event["path"], "/api/v1/analyze")
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
        self.assertEqual(payload["webview"]["entry"], "/copilot-shell/")
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
        copilot = payload["paths"]["/api/v1/copilot/query"]["post"]
        self.assertEqual(
            copilot["requestBody"]["content"]["application/json"]["schema"]["$ref"],
            "#/components/schemas/CopilotQueryRequest",
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


if __name__ == "__main__":
    unittest.main()
