from types import SimpleNamespace
import json
import unittest

from ai_gateway.model_client import ModelConfig, chat_completion, load_model_config


class FakeResponses:
    def __init__(self) -> None:
        self.payload = None

    def create(self, **kwargs):
        self.payload = kwargs
        return SimpleNamespace(output_text="测试代码建议")


class FakeChatCompletions:
    def __init__(self) -> None:
        self.payload = None

    def create(self, **kwargs):
        self.payload = kwargs
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="模型分析结果"))]
        )


class FakeClient:
    def __init__(self) -> None:
        self.responses = FakeResponses()
        self.chat = SimpleNamespace(completions=FakeChatCompletions())


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

    def test_chat_completion_uses_official_chat_client(self) -> None:
        client = FakeClient()

        answer = chat_completion(
            [{"role": "user", "content": "分析"}],
            config=ModelConfig("https://api.example.com/v1", "secret", "demo-model"),
            client=client,
        )

        self.assertEqual(answer, "模型分析结果")
        self.assertEqual(client.chat.completions.payload["model"], "demo-model")
        self.assertEqual(client.chat.completions.payload["messages"][0]["content"], "分析")

    def test_chat_completion_rejects_missing_config(self) -> None:
        with self.assertRaisesRegex(ValueError, "not configured"):
            chat_completion([], config=ModelConfig(None, None, None))

    def test_responses_api_disables_storage_and_sets_reasoning(self) -> None:
        client = FakeClient()

        answer = chat_completion(
            [
                {"role": "system", "content": "只读助手"},
                {"role": "user", "content": "分析文件"},
            ],
            config=ModelConfig(
                "https://api.example.com/responses",
                "secret",
                "gpt-5.5",
                wire_api="responses",
                reasoning_effort="high",
            ),
            client=client,
        )

        self.assertEqual(answer, "测试代码建议")
        self.assertEqual(client.responses.payload["input"][0]["role"], "developer")
        self.assertEqual(client.responses.payload["reasoning"], {"effort": "high"})
        self.assertFalse(client.responses.payload["store"])

    def test_load_model_config_rejects_unknown_wire_api(self) -> None:
        with self.assertRaisesRegex(ValueError, "AI_MODEL_WIRE_API"):
            load_model_config({"AI_MODEL_WIRE_API": "unknown"})


if __name__ == "__main__":
    unittest.main()
