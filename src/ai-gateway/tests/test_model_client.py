import json
import unittest

from ai_gateway.model_client import load_model_config


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


if __name__ == "__main__":
    unittest.main()
