import json
import unittest

from ai_gateway.model_client import ModelConfig, chat_completion, load_model_config


class ModelClientTests(unittest.TestCase):
    def test_load_model_config_from_env(self) -> None:
        config = load_model_config(
            {
                "AI_MODEL_BASE_URL": "https://api.example.com/v1",
                "AI_MODEL_API_KEY": "secret",
                "AI_MODEL_NAME": "demo-model",
            }
        )

        self.assertTrue(config.is_configured)
        self.assertEqual(config.base_url, "https://api.example.com/v1")
        self.assertEqual(config.model, "demo-model")
        self.assertEqual(config.wire_api, "chat_completions")
        self.assertTrue(config.public_dict()["api_key_configured"])
        self.assertNotIn("secret", json.dumps(config.public_dict()))

    def test_chat_completion_uses_openai_compatible_shape(self) -> None:
        captured = {}

        def fake_transport(request, timeout):
            captured["url"] = request.full_url
            captured["body"] = json.loads(request.data.decode("utf-8"))
            captured["auth"] = request.headers["Authorization"]
            return json.dumps({"choices": [{"message": {"content": "模型分析结果"}}]}).encode("utf-8")

        answer = chat_completion(
            [{"role": "user", "content": "分析"}],
            config=ModelConfig("https://api.example.com/v1", "secret", "demo-model"),
            transport=fake_transport,
        )

        self.assertEqual(answer, "模型分析结果")
        self.assertEqual(captured["url"], "https://api.example.com/v1/chat/completions")
        self.assertEqual(captured["body"]["model"], "demo-model")
        self.assertEqual(captured["auth"], "Bearer secret")

    def test_chat_completion_rejects_missing_config(self) -> None:
        with self.assertRaisesRegex(ValueError, "not configured"):
            chat_completion([], config=ModelConfig(None, None, None))

    def test_responses_api_uses_input_and_reasoning_effort(self) -> None:
        captured = {}

        def fake_transport(request, timeout):
            captured["url"] = request.full_url
            captured["body"] = json.loads(request.data.decode("utf-8"))
            captured["auth"] = request.headers["Authorization"]
            return json.dumps(
                {
                    "output": [
                        {
                            "type": "message",
                            "content": [{"type": "output_text", "text": "测试代码建议"}],
                        }
                    ]
                }
            ).encode("utf-8")

        answer = chat_completion(
            [
                {"role": "system", "content": "只读助手"},
                {"role": "user", "content": "分析文件"},
            ],
            config=ModelConfig(
                "https://api.example.com",
                "secret",
                "gpt-5.5",
                wire_api="responses",
                reasoning_effort="high",
            ),
            transport=fake_transport,
        )

        self.assertEqual(answer, "测试代码建议")
        self.assertEqual(captured["url"], "https://api.example.com/responses")
        self.assertEqual(captured["body"]["input"][0]["role"], "developer")
        self.assertEqual(captured["body"]["reasoning"], {"effort": "high"})
        self.assertFalse(captured["body"]["store"])
        self.assertEqual(captured["auth"], "Bearer secret")

    def test_load_model_config_rejects_unknown_wire_api(self) -> None:
        with self.assertRaisesRegex(ValueError, "AI_MODEL_WIRE_API"):
            load_model_config({"AI_MODEL_WIRE_API": "unknown"})


if __name__ == "__main__":
    unittest.main()
