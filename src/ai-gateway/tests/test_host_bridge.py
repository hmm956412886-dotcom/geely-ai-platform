from __future__ import annotations

import json
import unittest

from ai_gateway.host_bridge import (
    get_host_bridge,
    register_host_bridge,
    release_host_bridge,
    reset_host_bridges,
)


class HostBridgeRegistryTests(unittest.TestCase):
    def tearDown(self) -> None:
        reset_host_bridges()

    def test_registers_loopback_read_only_bridge_without_exposing_token(self) -> None:
        result = register_host_bridge(
            {"url": "http://127.0.0.1:43123", "token": "secret-token-1234"},
            "coretest-session",
        )

        self.assertEqual(result, {"host_session_id": "coretest-session", "available": True})
        bridge = get_host_bridge("coretest-session")
        self.assertEqual(bridge.url, "http://127.0.0.1:43123")
        self.assertEqual(bridge.token, "secret-token-1234")

    def test_rejects_non_loopback_or_unknown_fields(self) -> None:
        with self.assertRaisesRegex(ValueError, "loopback"):
            register_host_bridge(
                {"url": "https://example.com", "token": "secret-token-1234"},
                "coretest-session",
            )
        with self.assertRaisesRegex(ValueError, "unsupported"):
            register_host_bridge(
                {
                    "url": "http://127.0.0.1:43123",
                    "token": "secret-token-1234",
                    "mode": "write",
                },
                "coretest-session",
            )

    def test_release_removes_private_bridge(self) -> None:
        register_host_bridge(
            {"url": "http://127.0.0.1:43123", "token": "secret-token-1234"},
            "coretest-session",
        )

        self.assertTrue(release_host_bridge("coretest-session"))
        self.assertIsNone(get_host_bridge("coretest-session"))


if __name__ == "__main__":
    unittest.main()
