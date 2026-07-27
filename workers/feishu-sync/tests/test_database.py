import os
import unittest
from unittest.mock import patch

from feishu_sync.database import (
    DatabaseConfigurationError,
    DatabaseSettings,
    load_database_settings,
)


class DatabaseSettingsTests(unittest.TestCase):
    def test_cli_database_url_wins_over_environment(self) -> None:
        with patch.dict(
            os.environ,
            {"DATABASE_URL": "postgresql://env"},
            clear=False,
        ):
            settings = load_database_settings("postgresql://cli")

        self.assertEqual(settings, DatabaseSettings(url="postgresql://cli"))

    def test_environment_database_url_is_used(self) -> None:
        with patch.dict(
            os.environ,
            {"DATABASE_URL": "postgresql://env"},
            clear=False,
        ):
            settings = load_database_settings()

        self.assertEqual(settings, DatabaseSettings(url="postgresql://env"))

    def test_missing_database_url_is_clear_error(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(
                DatabaseConfigurationError,
                "DATABASE_URL is required",
            ):
                load_database_settings()


if __name__ == "__main__":
    unittest.main()
