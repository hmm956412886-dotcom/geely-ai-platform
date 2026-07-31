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
