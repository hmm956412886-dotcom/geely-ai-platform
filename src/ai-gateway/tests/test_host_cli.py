from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import unittest
from unittest.mock import patch

from ai_gateway import host_cli


class HostCliTests(unittest.TestCase):
    def test_simple_arguments_are_forwarded_without_json_shell_quoting(self) -> None:
        output = StringIO()
        with patch(
            "ai_gateway.host_cli._request", return_value={"result": {"kind": "dbc"}}
        ) as request, redirect_stdout(output):
            status = host_cli.main(
                [
                    "call",
                    "dbc.inspect",
                    "--arg",
                    "dbc_name=vehicle.dbc",
                    "--arg",
                    "frame_id=0x100",
                ]
            )

        self.assertEqual(status, 0)
        request.assert_called_once_with(
            "POST",
            "/v1/invoke",
            {
                "capability": "dbc.inspect",
                "arguments": {"dbc_name": "vehicle.dbc", "frame_id": "0x100"},
            },
        )
        self.assertIn('"kind": "dbc"', output.getvalue())

    def test_invalid_simple_argument_returns_nonzero(self) -> None:
        error = StringIO()
        with redirect_stderr(error):
            status = host_cli.main(["call", "dbc.inspect", "--arg", "invalid"])

        self.assertEqual(status, 1)
        self.assertIn("NAME=VALUE", error.getvalue())


if __name__ == "__main__":
    unittest.main()
