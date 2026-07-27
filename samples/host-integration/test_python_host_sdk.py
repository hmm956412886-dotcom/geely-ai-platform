from __future__ import annotations

import unittest

from python_host_sdk import GeelyAIGatewayClient, HostContext


class FakeClient(GeelyAIGatewayClient):
    def __init__(self) -> None:
        super().__init__("http://example.test/", host_session_id="test-session")
        self.calls: list[tuple[str, str, dict | None]] = []

    def _request(self, method: str, path: str, payload: dict | None = None) -> dict:
        self.calls.append((method, path, payload))
        return {"ok": True}


class PythonHostSdkTests(unittest.TestCase):
    def test_host_context_omits_none_values(self) -> None:
        context = HostContext(project_id="P", run_id="R", source_asset_id="current-run")

        self.assertEqual(
            context.to_payload(),
            {
                "project_id": "P",
                "run_id": "R",
                "source_asset_id": "current-run",
                "current_view": "test_result_detail",
            },
        )

    def test_client_uses_stable_gateway_paths(self) -> None:
        client = FakeClient()

        client.register_asset("run.csv", asset_id="current-run")
        client.update_host_context(
            HostContext(project_id="P", run_id="R", source_asset_id="current-run")
        )
        client.analyze(source_asset_id="current-run", question="why")
        client.insights(source_asset_id="current-run")
        client.compare(baseline_asset_id="baseline", target_asset_id="target")

        self.assertEqual(
            client.copilot_url,
            "http://example.test/copilot-shell/?host_session_id=test-session",
        )
        self.assertEqual(client.calls[0][1], "/api/v1/host/assets?host_session_id=test-session")
        self.assertEqual(client.calls[1][1], "/api/v1/host/context?host_session_id=test-session")
        self.assertEqual(client.calls[2][1], "/api/v1/analyze?host_session_id=test-session")
        self.assertEqual(client.calls[3][1], "/api/v1/test-data/insights?host_session_id=test-session")
        self.assertEqual(client.calls[4][1], "/api/v1/test-data/compare?host_session_id=test-session")


if __name__ == "__main__":
    unittest.main()
