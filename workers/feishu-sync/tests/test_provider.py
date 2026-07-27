import json
import unittest

from feishu_sync.provider import (
    CliResponse,
    FeishuCliError,
    FeishuCliProvider,
)


class FakeCli:
    def __init__(self, responses: list[CliResponse]) -> None:
        self.responses = iter(responses)
        self.calls: list[list[str]] = []

    def __call__(self, args: list[str]) -> CliResponse:
        self.calls.append(args)
        return next(self.responses)


class FeishuCliProviderTests(unittest.TestCase):
    def test_search_builds_cli_command_and_normalizes_hits(self) -> None:
        runner = FakeCli(
            [
                CliResponse(
                    0,
                    json.dumps(
                        {
                            "data": {
                                "items": [
                                    {
                                        "obj_token": "doxcn-001",
                                        "title": "动力系统测试规范",
                                        "url": "https://example.feishu.cn/wiki/wikcn-001",
                                        "snippet": "通过标准",
                                        "obj_type": "docx",
                                    }
                                ]
                            }
                        },
                        ensure_ascii=False,
                    ),
                    "",
                )
            ]
        )
        provider = FeishuCliProvider(runner=runner)

        hits = provider.search("动力系统", limit=3)

        self.assertEqual(
            hits[0].document_ref,
            "doxcn-001",
        )
        self.assertEqual(hits[0].title, "动力系统测试规范")
        self.assertEqual(
            runner.calls[0],
            [
                "lark-cli",
                "drive",
                "+search",
                "--query",
                "动力系统",
                "--format",
                "json",
                "--as",
                "user",
            ],
        )

    def test_fetch_returns_normalized_document(self) -> None:
        runner = FakeCli(
            [
                CliResponse(
                    0,
                    json.dumps(
                        {
                            "data": {
                                "document_id": "doxcn-001",
                                "obj_type": "docx",
                                "title": "测试规范",
                                "url": "https://example.feishu.cn/docx/doxcn-001",
                                "updated_at": "2026-07-24T08:00:00Z",
                                "blocks": [
                                    {
                                        "block_type": "heading1",
                                        "text": "通过标准",
                                    },
                                    {
                                        "block_type": "text",
                                        "text": "误差小于 5%。",
                                    },
                                ],
                            }
                        },
                        ensure_ascii=False,
                    ),
                    "",
                )
            ]
        )
        provider = FeishuCliProvider(runner=runner)

        document = provider.fetch("doxcn-001")

        self.assertEqual(document["document_id"], "doxcn-001")
        self.assertEqual(document["source_type"], "feishu_docx")
        self.assertEqual(document["sections"][0]["heading_path"], ["通过标准"])
        self.assertEqual(runner.calls[0][0:4], ["lark-cli", "docs", "+fetch", "--doc"])

    def test_search_supports_current_lark_cli_envelope(self) -> None:
        runner = FakeCli(
            [
                CliResponse(
                    0,
                    json.dumps(
                        {
                            "ok": True,
                            "data": {
                                "results": [
                                    {
                                        "entity_type": "WIKI",
                                        "title_highlighted": "动力<h>测试</h>规范",
                                        "summary_highlighted": "通过<hb>标准</hb>",
                                        "result_meta": {
                                            "token": "wikcn-001",
                                            "url": "https://example.feishu.cn/wiki/wikcn-001",
                                            "doc_types": "DOCX",
                                        },
                                    }
                                ]
                            },
                        },
                        ensure_ascii=False,
                    ),
                    "",
                )
            ]
        )

        hit = FeishuCliProvider(runner=runner).search("动力测试", limit=1)[0]

        self.assertEqual(hit.document_ref, "wikcn-001")
        self.assertEqual(hit.title, "动力测试规范")
        self.assertEqual(hit.snippet, "通过标准")
        self.assertEqual(hit.source_type, "WIKI")

    def test_fetch_excerpt_returns_plain_text(self) -> None:
        runner = FakeCli(
            [
                CliResponse(
                    0,
                    json.dumps(
                        {
                            "ok": True,
                            "data": {
                                "document": {
                                    "document_id": "doxcn-001",
                                    "revision_id": 7,
                                    "content": "<fragment><title>测试规范</title><p>误差小于 5%。</p></fragment>",
                                }
                            },
                        },
                        ensure_ascii=False,
                    ),
                    "",
                )
            ]
        )

        excerpt = FeishuCliProvider(runner=runner).fetch_excerpt(
            "doxcn-001", keyword="误差"
        )

        self.assertEqual(excerpt.document_id, "doxcn-001")
        self.assertEqual(excerpt.revision_id, 7)
        self.assertEqual(excerpt.text, "测试规范 误差小于 5%。")
        self.assertIn("--scope", runner.calls[0])

    def test_nonzero_cli_exit_becomes_domain_error(self) -> None:
        runner = FakeCli([CliResponse(1, "", "permission denied")])
        provider = FeishuCliProvider(runner=runner)

        with self.assertRaisesRegex(FeishuCliError, "permission denied"):
            provider.search("secret")

    def test_invalid_json_becomes_domain_error(self) -> None:
        runner = FakeCli([CliResponse(0, "not-json", "")])
        provider = FeishuCliProvider(runner=runner)

        with self.assertRaisesRegex(FeishuCliError, "invalid JSON"):
            provider.search("test")


if __name__ == "__main__":
    unittest.main()
