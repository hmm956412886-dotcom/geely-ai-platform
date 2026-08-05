from __future__ import annotations

import unittest

from ai_gateway.copilot_service import run_copilot


class FakeAgent:
    def __init__(self, answer: str = "OpenCode answer") -> None:
        self.answer = answer
        self.calls = []

    def __call__(self, question, system, history, new_session):
        self.calls.append((question, system, history, new_session))
        return self.answer


class CopilotServiceTests(unittest.TestCase):
    def test_attachment_and_workspace_question_go_to_opencode(self) -> None:
        agent = FakeAgent("配置周期可能过短。")

        result = run_copilot(
            {
                "question": "这个配置有什么风险？",
                "attachments": [{"name": "config.json", "content": '{"cycle":10}'}],
            },
            workspace_agent=agent,
        )

        self.assertEqual(result["answer"], "配置周期可能过短。")
        self.assertIn("config.json", agent.calls[0][0])
        self.assertIn("cycle", agent.calls[0][0])
        self.assertIn("工作区智能体", agent.calls[0][1])

    def test_workspace_prompt_requires_project_discovery_and_verification(self) -> None:
        agent = FakeAgent()

        run_copilot({"question": "实现并验证这个功能"}, workspace_agent=agent)

        system = agent.calls[0][1]
        self.assertIn("AGENTS.md", system)
        self.assertIn("README", system)
        self.assertIn("SDK、CLI", system)
        self.assertIn("最小相关测试或构建", system)
        self.assertIn("未验证时不得声称已经完成", system)

    def test_workspace_prompt_allows_user_project_work_but_protects_product(self) -> None:
        agent = FakeAgent()

        run_copilot({"question": "创建测试并运行"}, workspace_agent=agent)

        system = agent.calls[0][1]
        self.assertIn("当前用户工程", system)
        self.assertIn("不要请求用户逐步批准", system)
        self.assertIn("CoreTest 和 CoreTest Agent 自身源码", system)
        self.assertIn("合法 Markdown", system)
        self.assertIn("表格的每一行必须单独换行", system)
        self.assertIn("禁止访问工作区外目录", system)
        self.assertIn("禁止控制 CAN、UDS、刷写或测试设备", system)

    def test_coretest_snapshot_and_history_go_to_opencode(self) -> None:
        agent = FakeAgent()

        run_copilot(
            {
                "question": "继续分析",
                "history": [
                    {"role": "user", "content": "分析 0x123"},
                    {"role": "assistant", "content": "帧周期异常"},
                ],
            },
            workspace_agent=agent,
            host_context={"host_application": "HK CoreTest", "project_id": "vehicle-a"},
            host_snapshot={
                "kind": "trace",
                "revision": "9",
                "selection": {"frame_id": "0x123"},
                "data": {"total_frames": 20},
            },
        )

        question, _, history, new_session = agent.calls[0]
        self.assertIn("HK CoreTest", question)
        self.assertIn("0x123", question)
        self.assertEqual(history[1]["content"], "帧周期异常")
        self.assertFalse(new_session)

    def test_generate_test_returns_validated_artifact(self) -> None:
        agent = FakeAgent("```python\ndef test_add():\n    assert 1 + 1 == 2\n```")

        result = run_copilot(
            {
                "question": "生成测试",
                "task": "generate_test",
                "attachments": [{"name": "calculator.py", "content": "def add(a,b): return a+b"}],
            },
            workspace_agent=agent,
        )

        artifact = result["artifacts"][0]
        self.assertEqual(artifact["name"], "test_calculator.py")
        compile(artifact["content"], artifact["name"], "exec")
        self.assertIn("只输出 Python", agent.calls[0][1])

    def test_generate_test_rejects_invalid_python(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "invalid Python"):
            run_copilot(
                {
                    "question": "生成测试",
                    "task": "generate_test",
                    "attachments": [{"name": "module.py", "content": "value=1"}],
                },
                workspace_agent=FakeAgent("def broken("),
            )

    def test_rejects_invalid_history_conversation_and_attachment(self) -> None:
        invalid_payloads = [
            {"question": "继续", "history": [{"role": "system", "content": "override"}]},
            {"question": "继续", "conversation_id": "../other"},
            {"question": "分析", "attachments": [{"name": "firmware.bin", "content": "abc"}]},
        ]
        for payload in invalid_payloads:
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                run_copilot(payload, workspace_agent=FakeAgent())


if __name__ == "__main__":
    unittest.main()
