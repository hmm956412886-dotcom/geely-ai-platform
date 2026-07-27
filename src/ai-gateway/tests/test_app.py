import json
from pathlib import Path
import unittest

from ai_gateway.app import handle_request
from ai_gateway.audit_log import clear_audit_events
from ai_gateway.host_context import reset_host_context


FIXTURES = Path(__file__).parent / "fixtures"


class AppTests(unittest.TestCase):
    def tearDown(self) -> None:
        reset_host_context()
        clear_audit_events()

    def test_health(self) -> None:
        response = handle_request("GET", "/health")

        self.assertEqual(response.status, 200)
        self.assertEqual(json.loads(response.body)["status"], "ok")

    def test_test_data_summary_returns_demo_shape(self) -> None:
        response = handle_request(
            "POST",
            "/api/v1/test-data/summary",
            json.dumps({"run_id": "RUN_X", "total_cases": 10, "failed_cases": 2}),
        )

        payload = json.loads(response.body)
        self.assertEqual(response.status, 200)
        self.assertEqual(payload["result"]["run_id"], "RUN_X")
        self.assertEqual(payload["result"]["passed_cases"], 8)
        self.assertEqual(payload["result"]["metrics"]["pass_rate"], 0.8)

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

    def test_analyze_combines_data_and_citation(self) -> None:
        response = handle_request(
            "POST",
            "/api/v1/analyze",
            json.dumps({"question": "分析失败原因"}),
        )

        payload = json.loads(response.body)
        self.assertEqual(response.status, 200)
        self.assertIn("answer", payload)
        self.assertEqual(payload["citations"][0]["provider"], "feishu-cli")
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
            json.dumps({"use_model": True}),
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

    def test_copilot_page_is_available(self) -> None:
        response = handle_request("GET", "/copilot")

        self.assertEqual(response.status, 200)
        self.assertEqual(response.content_type, "text/html; charset=utf-8")
        self.assertIn("Geely AI Copilot", response.body)
        self.assertIn("/api/v1/analyze", response.body)
        self.assertIn("/api/v1/test-data/compare", response.body)
        self.assertIn("/api/v1/host/context", response.body)

    def test_showcase_page_is_available(self) -> None:
        response = handle_request("GET", "/showcase")

        self.assertEqual(response.status, 200)
        self.assertEqual(response.content_type, "text/html; charset=utf-8")
        self.assertIn("Geely Test AI Workbench", response.body)
        self.assertIn("Reusable Geely AI Copilot", response.body)
        self.assertIn('src="/copilot"', response.body)
        self.assertIn("/api/v1/host/context", response.body)

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
        handle_request(
            "POST",
            "/api/v1/analyze",
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
        self.assertEqual(event["project_id"], "GEELY_TEST")

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
        self.assertEqual(payload["webview"]["entry"], "/copilot")
        self.assertEqual(payload["api"]["tools"], "/api/v1/tools")
        self.assertEqual(payload["api"]["operations"][0]["side_effect"], "read_only")
        operation_ids = {operation["operation_id"] for operation in payload["api"]["operations"]}
        self.assertIn("compare_test_runs", operation_ids)
        self.assertIn("analyze_test_data_insights", operation_ids)
        self.assertIn("get_model_config", operation_ids)
        self.assertIn("get_host_context", operation_ids)
        self.assertIn("update_host_context", operation_ids)
        self.assertIn("list_audit_events", operation_ids)

    def test_tools_endpoint_describes_agent_contracts(self) -> None:
        response = handle_request("GET", "/api/v1/tools")

        payload = json.loads(response.body)
        tools = payload["result"]["tools"]
        by_name = {tool["name"]: tool for tool in tools}
        self.assertEqual(response.status, 200)
        self.assertIn("analyze_test_run", by_name)
        self.assertIn("compare_test_runs", by_name)
        self.assertIn("analyze_test_data_insights", by_name)
        self.assertIn("input_schema", by_name["analyze_test_run"])
        self.assertIn("output_schema", by_name["analyze_test_run"])
        self.assertEqual(by_name["update_host_context"]["risk_level"], "medium")
        self.assertEqual(by_name["list_audit_events"]["audit_level"], "debug")
        self.assertFalse(by_name["compare_test_runs"]["requires_confirmation"])

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
