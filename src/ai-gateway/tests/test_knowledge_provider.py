import os
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from ai_gateway.knowledge_provider import query_knowledge


class FakeProvider:
    def search(self, query: str, *, limit: int) -> list[SimpleNamespace]:
        return [
            SimpleNamespace(
                document_ref="wikcn-001",
                title="动力测试规范",
                source_url="https://example.feishu.cn/wiki/wikcn-001",
                snippet="通过标准",
                source_type="WIKI",
            )
        ]

    def fetch_excerpt(self, document_ref: str, *, keyword: str) -> SimpleNamespace:
        return SimpleNamespace(text="测试误差必须小于 5%。")


class FailingProvider:
    def search(self, query: str, *, limit: int) -> list[SimpleNamespace]:
        raise RuntimeError("lark-cli unavailable")


class KnowledgeProviderTests(unittest.TestCase):
    def test_demo_provider_remains_available_offline(self) -> None:
        with patch.dict(os.environ, {"AI_KNOWLEDGE_PROVIDER": "demo"}):
            result = query_knowledge("测试规范")

        self.assertEqual(result["citations"][0]["document_id"], "feishu-demo-001")
        self.assertTrue(result["warnings"])

    def test_feishu_provider_returns_excerpt_and_citation(self) -> None:
        result = query_knowledge("误差", provider=FakeProvider())

        self.assertIn("测试误差必须小于 5%", result["answer"])
        self.assertEqual(result["citations"][0]["provider"], "feishu-cli")
        self.assertEqual(result["citations"][0]["excerpt"], "测试误差必须小于 5%。")
        self.assertEqual(result["warnings"], [])

    def test_feishu_failure_returns_actionable_fallback(self) -> None:
        result = query_knowledge("误差", provider=FailingProvider())

        self.assertEqual(result["citations"], [])
        self.assertIn("lark-cli", result["warnings"][0])


if __name__ == "__main__":
    unittest.main()
