from __future__ import annotations

import unittest

from python_host_sdk import GeelyAIGatewayClient, HostContext


class FakeClient(GeelyAIGatewayClient):
    def __init__(self) -> None:
        super().__init__("http://example.test/")
        self.calls: list[tuple[str, str, dict | None]] = []

    def _request(self, method: str, path: str, payload: dict | None = None) -> dict:
        self.calls.append((method, path, payload))
        return {"ok": True}


class PythonHostSdkTests(unittest.TestCase):
    def test_host_context_omits_none_values(self) -> None:
        context = HostContext(project_id="P", run_id="R", source_file="run.csv")

        self.assertEqual(
            context.to_payload(),
            {
                "project_id": "P",
                "run_id": "R",
                "source_file": "run.csv",
                "current_view": "test_result_detail",
            },
        )

    def test_client_uses_stable_gateway_paths(self) -> None:
        client = FakeClient()

        client.update_host_context(HostContext(project_id="P", run_id="R", source_file="run.csv"))
        client.analyze(source_file="run.csv", question="why")
        client.insights(source_file="run.csv")
        client.compare(baseline_file="a.csv", target_file="b.csv")

        self.assertEqual(client.copilot_url, "http://example.test/copilot")
        self.assertEqual(client.calls[0][1], "/api/v1/host/context")
        self.assertEqual(client.calls[1][1], "/api/v1/analyze")
        self.assertEqual(client.calls[2][1], "/api/v1/test-data/insights")
        self.assertEqual(client.calls[3][1], "/api/v1/test-data/compare")


if __name__ == "__main__":
    unittest.main()
