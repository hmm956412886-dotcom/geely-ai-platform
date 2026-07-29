from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from coretest_copilot.gateway import _load_env_values


class GatewayConfigTests(unittest.TestCase):
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
