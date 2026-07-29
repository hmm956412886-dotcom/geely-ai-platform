from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from coretest_copilot.gateway import GatewayBridge, _load_env_values


class GatewayConfigTests(unittest.TestCase):
    def test_publish_updates_context_only_after_snapshot_succeeds(self) -> None:
        bridge = GatewayBridge.__new__(GatewayBridge)
        calls = []

        def request(method, path, payload=None, *, privileged=False, success=None):
            calls.append((method, path, payload, privileged))
            if success:
                success({"result": payload})

        bridge.request = request
        bridge.publish({"selection_kind": "dbc"}, {"kind": "dbc", "revision": "2"})

        self.assertEqual([call[1] for call in calls], ["/api/v1/host/snapshot", "/api/v1/host/context"])
        self.assertTrue(calls[0][3])
        self.assertFalse(calls[1][3])

    def test_load_env_values_reads_only_assignments(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            path.write_text(
                "# CoreTest model settings\nAI_MODEL_BASE_URL=https://api.example.com\ninvalid\nAI_MODEL_WIRE_API=responses\n",
                encoding="utf-8",
            )

            values = _load_env_values(path)

        self.assertEqual(values["AI_MODEL_BASE_URL"], "https://api.example.com")
        self.assertEqual(values["AI_MODEL_WIRE_API"], "responses")
        self.assertNotIn("invalid", values)

    def test_load_env_values_ignores_missing_file(self) -> None:
        self.assertEqual(_load_env_values(Path("missing.env")), {})


if __name__ == "__main__":
    unittest.main()
