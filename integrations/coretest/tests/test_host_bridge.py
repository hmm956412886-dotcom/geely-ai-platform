from __future__ import annotations

import json
from urllib.error import HTTPError
from urllib.request import Request, urlopen
import unittest

from coretest_copilot.host_bridge import ReadOnlyHostBridge


class ReadOnlyHostBridgeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.bridge = ReadOnlyHostBridge(
            capabilities=[
                {
                    "name": "project.summary",
                    "description": "Return the active project summary",
                    "input_schema": {"type": "object", "additionalProperties": False},
                }
            ],
            invoke=self._invoke,
            token="test-token",
        )
        self.bridge.start()

    def tearDown(self) -> None:
        self.bridge.stop()

    def _invoke(self, name: str, arguments: dict) -> dict:
        self.calls.append((name, arguments))
        return {"kind": "project", "data": {"name": "demo"}}

    def test_lists_capabilities_and_invokes_read_only_operation(self) -> None:
        capabilities = self._request("GET", "/v1/capabilities")
        result = self._request(
            "POST",
            "/v1/invoke",
            {"capability": "project.summary", "arguments": {}},
        )

        self.assertEqual(capabilities["capabilities"][0]["name"], "project.summary")
        self.assertEqual(result["result"]["data"]["name"], "demo")
        self.assertEqual(self.calls, [("project.summary", {})])

    def test_rejects_missing_token_and_unknown_capability(self) -> None:
        with self.assertRaises(HTTPError) as unauthorized:
            self._request("GET", "/v1/capabilities", authenticated=False)
        self.assertEqual(unauthorized.exception.code, 401)

        with self.assertRaises(HTTPError) as missing:
            self._request(
                "POST",
                "/v1/invoke",
                {"capability": "hardware.send", "arguments": {}},
            )
        self.assertEqual(missing.exception.code, 400)
        self.assertEqual(self.calls, [])

    def test_registration_contains_private_endpoint_and_token(self) -> None:
        registration = self.bridge.registration

        self.assertTrue(registration["url"].startswith("http://127.0.0.1:"))
        self.assertEqual(registration["token"], "test-token")

    def _request(
        self,
        method: str,
        path: str,
        payload: dict | None = None,
        *,
        authenticated: bool = True,
    ) -> dict:
        headers = {"Content-Type": "application/json"}
        if authenticated:
            headers["Authorization"] = "Bearer test-token"
        request = Request(
            f"{self.bridge.registration['url']}{path}",
            data=json.dumps(payload).encode("utf-8") if payload is not None else None,
            headers=headers,
            method=method,
        )
        with urlopen(request, timeout=2) as response:
            return json.load(response)


if __name__ == "__main__":
    unittest.main()
