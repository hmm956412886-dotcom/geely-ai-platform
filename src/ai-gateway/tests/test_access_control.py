from __future__ import annotations

import unittest
from unittest.mock import patch

from ai_gateway.access_control import validate_bind_access


class AccessControlTests(unittest.TestCase):
    def test_loopback_bind_does_not_require_token(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            validate_bind_access("127.0.0.1")
            validate_bind_access("::1")
            validate_bind_access("localhost")

    def test_non_loopback_bind_requires_token(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaisesRegex(ValueError, "AI_GATEWAY_ACCESS_TOKEN"):
                validate_bind_access("0.0.0.0")

        with patch.dict("os.environ", {"AI_GATEWAY_ACCESS_TOKEN": "host-secret"}, clear=True):
            with self.assertRaisesRegex(ValueError, "AI_GATEWAY_HOST_TOKEN"):
                validate_bind_access("0.0.0.0")

        with patch.dict(
            "os.environ",
            {
                "AI_GATEWAY_ACCESS_TOKEN": "copilot-secret",
                "AI_GATEWAY_HOST_TOKEN": "host-secret",
            },
            clear=True,
        ):
            validate_bind_access("0.0.0.0")


if __name__ == "__main__":
    unittest.main()
