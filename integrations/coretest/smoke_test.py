"""Headless product smoke test for the installed CoreTest Agent Dock."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import sys
from tempfile import TemporaryDirectory
from urllib.request import Request, urlopen

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QDockWidget


def main() -> int:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu")
    os.environ.setdefault("QTWEBENGINE_DISABLE_SANDBOX", "1")
    root = Path(__file__).resolve().parents[2]
    smoke_state = None
    if not os.environ.get("CORETEST_OPENCODE_HOME") and not os.environ.get(
        "CORETEST_SMOKE_PROMPT", ""
    ).strip():
        smoke_state = TemporaryDirectory(prefix="coretest-agent-smoke-")
        os.environ["CORETEST_OPENCODE_HOME"] = str(Path(smoke_state.name) / "opencode")
    customer_root = Path(
        os.environ.get("CORETEST_ROOT", root / "customer-data" / "hk-coretest-ai")
    ).resolve()
    os.environ.setdefault("CORETEST_AI_PLATFORM_ROOT", str(root))
    sys.path.insert(0, str(customer_root))

    from app.view.window import MainWindow

    app = QApplication(sys.argv)
    if project_root := os.environ.get("CORETEST_PROJECT_ROOT"):
        from app.service import project_runtime_service

        project_runtime_service.activate_project(str(Path(project_root).resolve()))
    window = MainWindow()
    window.resize(1280, 800)
    window.show()
    failures: list[str] = []
    prompt = os.environ.get("CORETEST_SMOKE_PROMPT", "").strip()

    def finish(message: str) -> None:
        if message:
            print(message)
        window.copilot.bridge.release()
        window.close()
        app.quit()

    def fail(exc: object) -> None:
        failures.append(str(exc) or type(exc).__name__)
        finish("")

    def read_json(path: str) -> dict[str, object]:
        bridge = window.copilot.bridge
        request = Request(f"{bridge.base_url}{path}")
        if bridge._access_token:
            request.add_header("Authorization", f"Bearer {bridge._access_token}")
        with urlopen(request, timeout=3) as response:
            return json.load(response)

    def verify_activity(payload: dict[str, object]) -> None:
        try:
            result = payload.get("result")
            assert isinstance(result, dict)
            activity = result.get("activity")
            if os.environ.get("CORETEST_SMOKE_REQUIRE_TOOL") == "1":
                assert isinstance(activity, list) and any(
                    isinstance(item, dict) and item.get("status") == "completed"
                    for item in activity
                ), f"Agent did not complete a tool call: {activity!r}"
            finish("PASS CoreTest Agent real-model smoke")
        except Exception as exc:
            fail(exc)

    def verify_prompt(payload: dict[str, object]) -> None:
        try:
            answer = payload.get("answer")
            assert isinstance(answer, str) and answer.strip(), "Agent returned an empty answer"
            window.copilot.bridge.request(
                "POST",
                "/api/v1/agent/activity",
                {"conversation_id": "coretest-smoke"},
                success=verify_activity,
            )
        except Exception as exc:
            fail(exc)

    def verify_dom(text: object) -> None:
        try:
            assert window.copilot.dock.objectName() == "coretest-copilot-dock"
            assert window.copilot.dock.windowTitle() == "CoreTest Agent"
            assert window.copilot.title_label.text() == "CoreTest Agent"
            assert window.copilot.open_action.text() == "CoreTest Agent"
            assert not (
                window.copilot.dock.features()
                & QDockWidget.DockWidgetFeature.DockWidgetFloatable
            )
            assert not hasattr(window.copilot, "collapse_button")
            assert not hasattr(window.copilot, "float_button")
            assert window.copilot.bridge.ready
            page_path = window.copilot.web.url().path()
            assert page_path in {
                "/agent-native/",
                "/Q29yZVRlc3QgV29ya3NwYWNl",
                "/new-session",
            } or re.fullmatch(r"/server/[^/]+/session/[^/]+", page_path)
            assert window.copilot.open_action.isChecked()
            window.copilot.close_button.click()
            QApplication.processEvents()
            assert not window.copilot.dock.isVisible()
            window.copilot.open_action.trigger()
            QApplication.processEvents()
            assert window.copilot.dock.isVisible()
            page_text = str(text)
            assert any(
                label in page_text
                for label in (
                    "分析文件、DBC/Trace，或描述测试任务...",
                    "输入要在当前工程中执行的命令...",
                    "新建会话",
                )
            ), (
                f"missing native Agent content: {page_text[:500]!r}"
            )
            session = window.copilot.bridge.session_id
            context = read_json(f"/api/v1/host/context?host_session_id={session}")["result"]
            snapshot = read_json(f"/api/v1/host/snapshot?host_session_id={session}")["result"]
            status = read_json(f"/api/v1/agent/status?host_session_id={session}")["result"]
            assert context["host_application"] == "HK CoreTest"
            assert context["current_view"] == "文件管理 / 首页"
            assert snapshot["kind"] == "project"
            assert status["workspace"]["registered"]
            assert status["runtime"]["running"]
            if screenshot_path := os.environ.get("CORETEST_SMOKE_SCREENSHOT"):
                assert window.grab().save(str(Path(screenshot_path).resolve()))
            if prompt:
                window.copilot.bridge.request(
                    "POST",
                    "/api/v1/copilot/query",
                    {
                        "question": prompt,
                        "task": "chat",
                        "conversation_id": "coretest-smoke",
                    },
                    success=verify_prompt,
                )
                return
            finish("PASS CoreTest Agent headless smoke")
        except Exception as exc:
            fail(exc)

    def verify_loaded(_ok: bool) -> None:
        QTimer.singleShot(
            1200,
            lambda: window.copilot.web.page().runJavaScript("document.body.innerText", verify_dom),
        )

    window.copilot.web.loadFinished.connect(verify_loaded)

    def timeout() -> None:
        stderr = bytes(window.copilot.bridge.process.readAllStandardError()).decode(
            "utf-8", errors="replace"
        ).strip()
        detail = window.copilot.status_text.text().replace("\n", " ").strip()
        failures.append(
            "Gateway or WebEngine startup timeout"
            + (f": {detail}" if detail else "")
            + (f"; {stderr}" if stderr else "")
        )
        window.copilot.bridge.release()
        app.quit()

    default_timeout = "180000" if prompt else "30000"
    QTimer.singleShot(int(os.environ.get("CORETEST_SMOKE_TIMEOUT_MS", default_timeout)), timeout)
    app.exec()
    if smoke_state is not None:
        smoke_state.cleanup()
    if failures:
        print(f"FAIL CoreTest Agent headless smoke: {failures[0]}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
