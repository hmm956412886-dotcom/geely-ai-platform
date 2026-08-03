import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from ai_gateway.model_client import load_model_config, update_model_config


class ModelConfigTests(unittest.TestCase):
    def test_load_model_config_for_opencode_provider(self) -> None:
        config = load_model_config(
            {
                "AI_MODEL_BASE_URL": "https://api.example.com/v1",
                "AI_MODEL_API_KEY": "secret",
                "AI_MODEL_NAME": "demo-model",
                "AI_MODEL_TIMEOUT_SECONDS": "45",
            }
        )

        self.assertTrue(config.is_configured)
        self.assertEqual(config.base_url, "https://api.example.com/v1")
        self.assertEqual(config.model, "demo-model")
        self.assertEqual(config.timeout_seconds, 45)
        self.assertTrue(config.public_dict()["api_key_configured"])
        self.assertNotIn("secret", json.dumps(config.public_dict()))

    def test_update_model_config_persists_and_keeps_existing_key(self) -> None:
        with TemporaryDirectory() as directory:
            config_path = Path(directory) / "ai-model.env"
            config_path.write_text("# customer config\nUNRELATED=value\n", encoding="utf-8")
            env = {"AI_MODEL_CONFIG_FILE": str(config_path)}

            saved = update_model_config(
                {
                    "base_url": "https://api.example.com/v1",
                    "api_key": "secret",
                    "model": "model-a",
                },
                env,
            )
            switched = update_model_config({"model": "model-b"}, env)
            contents = config_path.read_text(encoding="utf-8")

        self.assertTrue(saved.is_configured)
        self.assertEqual(switched.model, "model-b")
        self.assertEqual(switched.api_key, "secret")
        self.assertIn("UNRELATED=value", contents)
        self.assertIn("AI_MODEL_BASE_URL=https://api.example.com/v1", contents)
        self.assertIn("AI_MODEL_API_KEY=secret", contents)
        self.assertIn("AI_MODEL_NAME=model-b", contents)
        self.assertEqual(switched.public_dict()["available_models"], ["model-a", "model-b"])
        self.assertNotIn("secret", json.dumps(switched.public_dict()))

    def test_update_model_config_rejects_invalid_values(self) -> None:
        with TemporaryDirectory() as directory:
            env = {"AI_MODEL_CONFIG_FILE": str(Path(directory) / "ai-model.env")}

            with self.assertRaisesRegex(ValueError, "http"):
                update_model_config(
                    {"base_url": "file:///private", "api_key": "secret", "model": "m"},
                    env,
                )
            with self.assertRaisesRegex(ValueError, "unsupported"):
                update_model_config({"unsupported": "value"}, env)
            with self.assertRaisesRegex(ValueError, "API key"):
                update_model_config(
                    {"base_url": "https://api.example.com/v1", "model": "m"},
                    env,
                )


if __name__ == "__main__":
    unittest.main()
