"""Knowledge query boundary with an optional real Feishu CLI provider."""

from __future__ import annotations

import os
from typing import Any


def query_knowledge(query: str, provider: Any | None = None) -> dict[str, Any]:
    cleaned_query = query.strip() or "动力系统测试规范"
    if provider is None and os.getenv("AI_KNOWLEDGE_PROVIDER", "demo") != "feishu-cli":
        return _demo_result(cleaned_query)

    try:
        knowledge_provider = provider or _feishu_provider()
        hits = knowledge_provider.search(cleaned_query, limit=3)
        if not hits:
            return {
                "answer": "当前飞书知识库未检索到可靠依据。",
                "citations": [],
                "warnings": [],
            }
        top_hit = hits[0]
        excerpt = knowledge_provider.fetch_excerpt(
            top_hit.source_url or top_hit.document_ref,
            keyword=cleaned_query,
        )
    except (ImportError, RuntimeError, ValueError):
        return {
            "answer": "飞书知识查询暂不可用。",
            "citations": [],
            "warnings": ["请检查 lark-cli 登录状态、文档权限和查询词长度。"],
        }

    citations = [
        {
            "document_id": hit.document_ref,
            "title": hit.title,
            "source_url": hit.source_url or hit.document_ref,
            "section_path": [],
            "provider": "feishu-cli",
            "snippet": hit.snippet,
        }
        for hit in hits
    ]
    citations[0]["excerpt"] = _truncate(excerpt.text, 1200)
    return {
        "answer": f"根据《{top_hit.title}》检索到：{citations[0]['excerpt']}",
        "citations": citations,
        "warnings": [],
    }


def _feishu_provider() -> Any:
    from feishu_sync.provider import FeishuCliProvider

    return FeishuCliProvider(executable=os.getenv("LARK_CLI_COMMAND"))


def _demo_result(query: str) -> dict[str, Any]:
    return {
        "answer": f"已在飞书知识源中准备检索：{query}",
        "citations": [
            {
                "document_id": "feishu-demo-001",
                "title": "动力系统测试规范",
                "source_url": "https://example.feishu.cn/wiki/demo",
                "section_path": ["第三章", "通过标准"],
                "provider": "feishu-cli",
            }
        ],
        "warnings": ["当前使用演示知识；配置 lark-cli 后返回真实飞书引用。"],
    }


def _truncate(value: str, limit: int) -> str:
    return value if len(value) <= limit else value[:limit].rstrip() + "..."
