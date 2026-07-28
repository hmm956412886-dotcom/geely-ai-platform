from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from ai_gateway.app import handle_request


class CopilotServiceTests(unittest.TestCase):
    @patch("ai_gateway.copilot_service.chat_completion", return_value="可以先检查帧周期。")
    def test_chat_uses_model_with_attachment(self, completion) -> None:
        response = handle_request(
            "POST",
            "/api/v1/copilot/query",
            json.dumps(
                {
                    "question": "这个配置有什么风险？",
                    "attachments": [{"name": "config.json", "content": '{"cycle": 10}'}],
                },
                ensure_ascii=False,
            ),
        )

        payload = json.loads(response.body)
        self.assertEqual(response.status, 200)
        self.assertEqual(payload["answer"], "可以先检查帧周期。")
        self.assertEqual(payload["artifacts"], [])
        self.assertIn("config.json", completion.call_args.args[0][1]["content"])

    @patch(
        "ai_gateway.copilot_service.chat_completion",
        return_value="```python\ndef test_value():\n    assert 1 == 1\n```",
    )
    def test_generate_test_returns_downloadable_python_artifact(self, _completion) -> None:
        response = handle_request(
            "POST",
            "/api/v1/copilot/query",
            json.dumps(
                {
                    "question": "为这个模块生成测试",
                    "task": "generate_test",
                    "attachments": [{"name": "calculator.py", "content": "def add(a,b): return a+b"}],
                },
                ensure_ascii=False,
            ),
        )

        payload = json.loads(response.body)
        self.assertEqual(response.status, 200)
        self.assertEqual(payload["artifacts"][0]["name"], "test_calculator.py")
        self.assertTrue(payload["artifacts"][0]["content"].startswith("def test_value"))
        self.assertNotIn("```", payload["artifacts"][0]["content"])
        compile(payload["artifacts"][0]["content"], payload["artifacts"][0]["name"], "exec")

    def test_generate_test_requires_supported_bounded_text_attachment(self) -> None:
        missing = handle_request(
            "POST",
            "/api/v1/copilot/query",
            json.dumps({"question": "生成测试", "task": "generate_test"}, ensure_ascii=False),
        )
        binary = handle_request(
            "POST",
            "/api/v1/copilot/query",
            json.dumps(
                {
                    "question": "生成测试",
                    "task": "generate_test",
                    "attachments": [{"name": "firmware.bin", "content": "abc"}],
                },
                ensure_ascii=False,
            ),
        )

        self.assertEqual(missing.status, 400)
        self.assertEqual(binary.status, 400)

    def test_unconfigured_model_is_reported_as_service_error(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            response = handle_request(
                "POST", "/api/v1/copilot/query", json.dumps({"question": "你好"}, ensure_ascii=False)
            )

        self.assertEqual(response.status, 502)
        self.assertEqual(json.loads(response.body)["error"]["code"], "model_unavailable")


if __name__ == "__main__":
    unittest.main()
