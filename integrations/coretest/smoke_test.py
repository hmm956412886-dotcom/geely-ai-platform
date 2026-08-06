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
    ).strip() and not os.environ.get("CORETEST_SMOKE_TEST_PROVIDER", "").strip():
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
    if project_root:
        from app.service import project_file_service

        project_file_service.scan_files()
    failures: list[str] = []
    prompt = os.environ.get("CORETEST_SMOKE_PROMPT", "").strip()
    prompt_answer = ""
    provider_id = os.environ.get("CORETEST_SMOKE_TEST_PROVIDER", "").strip()
    provider_model = os.environ.get("CORETEST_SMOKE_TEST_MODEL", "").strip()

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
            activity_items = activity if isinstance(activity, list) else []
            completed_tools = {
                str(item.get("tool"))
                for item in activity_items
                if isinstance(item, dict) and item.get("status") == "completed"
            }
            if os.environ.get("CORETEST_SMOKE_REQUIRE_TOOL") == "1":
                assert completed_tools, f"Agent did not complete a tool call: {activity!r}"
            expected_tools = {
                item.strip()
                for item in os.environ.get("CORETEST_SMOKE_EXPECT_TOOLS", "").split(",")
                if item.strip()
            }
            assert expected_tools <= completed_tools, (
                f"Agent did not complete expected tools {sorted(expected_tools)}: "
                f"{sorted(completed_tools)}"
            )

            artifact = ""
            if expected_file := os.environ.get("CORETEST_SMOKE_EXPECT_FILE", "").strip():
                workspace = Path(os.environ["CORETEST_PROJECT_ROOT"]).resolve()
                relative = Path(expected_file)
                assert not relative.is_absolute(), "Expected smoke artifact must be relative"
                target = (workspace / relative).resolve()
                target.relative_to(workspace)
                assert target.is_file(), f"Agent did not create expected artifact: {expected_file}"
                expected_text = os.environ.get("CORETEST_SMOKE_EXPECT_TEXT", "")
                if expected_text:
                    assert expected_text in target.read_text(encoding="utf-8"), (
                        f"Expected artifact does not contain {expected_text!r}: {expected_file}"
                    )
                artifact = relative.as_posix()

            if report_path := os.environ.get("CORETEST_SMOKE_REPORT", "").strip():
                report = {
                    "answer": prompt_answer,
                    "completed_tools": sorted(completed_tools),
                    "activity": activity,
                    "artifact": artifact or None,
                }
                Path(report_path).resolve().write_text(
                    json.dumps(report, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
            summary = f" tools={','.join(sorted(completed_tools))}"
            if artifact:
                summary += f" artifact={artifact}"
            finish(f"PASS CoreTest Agent real-model smoke{summary}")
        except Exception as exc:
            fail(exc)

    def verify_prompt(payload: dict[str, object]) -> None:
        nonlocal prompt_answer
        try:
            answer = payload.get("answer")
            assert isinstance(answer, str) and answer.strip(), "Agent returned an empty answer"
            forbidden_text = os.environ.get("CORETEST_SMOKE_FORBID_ANSWER_TEXT", "")
            assert not forbidden_text or forbidden_text not in answer, (
                "Agent answer exposed forbidden acceptance text"
            )
            prompt_answer = answer
            window.copilot.bridge.request(
                "POST",
                "/api/v1/agent/activity",
                {"conversation_id": "coretest-smoke"},
                success=verify_activity,
            )
        except Exception as exc:
            fail(exc)

    def run_prompt_or_finish() -> None:
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
        finish(
            "PASS CoreTest Agent provider compatibility smoke"
            if provider_id
            else "PASS CoreTest Agent headless smoke"
        )

    def verify_provider(payload: dict[str, object]) -> None:
        try:
            result = payload.get("result")
            assert isinstance(result, dict) and result.get("ok") is True, (
                f"Provider compatibility test failed: {result!r}"
            )
            run_prompt_or_finish()
        except Exception as exc:
            fail(exc)

    def verify_prompt_menu(text: object) -> None:
        try:
            page_text = str(text)
            labels = ("图片和文件", "快捷命令", "工程上下文", "终端命令")
            missing = [label for label in labels if label not in page_text]
            assert not missing, (
                f"missing native prompt menu labels: {missing}; "
                f"page tail: {page_text[-800:]!r}"
            )
            if screenshot_path := os.environ.get("CORETEST_SMOKE_SCREENSHOT"):
                assert window.grab().save(str(Path(screenshot_path).resolve()))
            if provider_id:
                assert re.fullmatch(r"[A-Za-z0-9_-]+", provider_id), (
                    "Invalid smoke provider id"
                )
                assert provider_model, "CORETEST_SMOKE_TEST_MODEL is required"
                window.copilot.bridge.request(
                    "POST",
                    f"/api/v1/model/providers/{provider_id}/test",
                    {"model": provider_model},
                    success=verify_provider,
                )
                return
            run_prompt_or_finish()
        except Exception as exc:
            fail(exc)

    def verify_new_session_path(path: object) -> None:
        try:
            assert str(path) == "/new-session", f"new session did not open: {path!r}"
            window.copilot.web.page().runJavaScript(
                """(() => {
                  const buttons = [...document.querySelectorAll('[data-action="prompt-attach"]')];
                  const button = buttons.find((item) => {
                    const rect = item.getBoundingClientRect();
                    return item instanceof HTMLElement && rect.width > 0 && rect.height > 0;
                  });
                  if (!(button instanceof HTMLElement)) return false;
                  button.dispatchEvent(new PointerEvent('pointerdown', {
                    bubbles: true, button: 0, pointerType: 'mouse'
                  }));
                  button.dispatchEvent(new PointerEvent('pointerup', {
                    bubbles: true, button: 0, pointerType: 'mouse'
                  }));
                  button.dispatchEvent(new MouseEvent('click', { bubbles: true, button: 0 }));
                  return true;
                })()""",
                lambda clicked: QTimer.singleShot(
                    300,
                    lambda: window.copilot.web.page().runJavaScript(
                        "document.body.innerText",
                        verify_prompt_menu,
                    ),
                )
                if clicked
                else fail("missing visible native prompt add-menu button"),
            )
        except Exception as exc:
            fail(exc)

    def verify_workspace_controls(result: object) -> None:
        try:
            controls = json.loads(str(result))
            assert not controls.get("error"), controls["error"]
            assert controls.get("newSessionVisible") is True, (
                "missing visible native new-session control"
            )
            assert controls.get("projectManagementVisible") is False, (
                "unsupported project management control is visible"
            )
            assert controls.get("newSessionActivated") is True, (
                "native new-session control could not be activated"
            )
            QTimer.singleShot(
                300,
                lambda: window.copilot.web.page().runJavaScript(
                    "location.pathname",
                    verify_new_session_path,
                ),
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
                )
            ), f"missing native Agent prompt: {page_text[:500]!r}"
            session = window.copilot.bridge.session_id
            context = read_json(f"/api/v1/host/context?host_session_id={session}")["result"]
            snapshot = read_json(f"/api/v1/host/snapshot?host_session_id={session}")["result"]
            status = read_json(f"/api/v1/agent/status?host_session_id={session}")["result"]
            assert context["host_application"] == "HK CoreTest"
            assert context["current_view"] == "文件管理 / 首页"
            assert snapshot["kind"] == "project"
            assert status["workspace"]["registered"]
            assert status["runtime"]["running"]
            if expected_dbc := os.environ.get("CORETEST_SMOKE_EXPECT_DBC", "").strip():
                from app.service import project_dbc_service

                assert expected_dbc in project_dbc_service.list_filenames(), (
                    f"DBC is not registered in CoreTest: {expected_dbc}"
                )
                assert project_dbc_service.is_file_loaded(expected_dbc), (
                    f"DBC is not loaded in CoreTest: {expected_dbc}"
                )
                assert project_dbc_service.get_dbc_frames_by_file(expected_dbc), (
                    f"DBC parsed cache is empty: {expected_dbc}"
                )
            window.copilot.web.page().runJavaScript(
                """(() => {
                  try {
                    const visible = (item) => {
                      const rect = item.getBoundingClientRect();
                      const style = getComputedStyle(item);
                      return rect.width > 0 && rect.height > 0 && style.display !== 'none' && style.visibility !== 'hidden';
                    };
                    const newSession = [...document.querySelectorAll(
                      '[data-action="home-new-session"], [data-action="home-project-new-session"], button[aria-label="新建会话"], button[aria-label="New session"]'
                    )];
                    const projectManagement = [...document.querySelectorAll(
                      '[data-action="home-add-project"], [data-action="home-add-project-row"], [data-action="home-project-menu"], [data-action="prompt-project"]'
                    )];
                    const sessionButton = newSession.find(visible);
                    if (sessionButton instanceof HTMLElement) {
                      sessionButton.dispatchEvent(new PointerEvent('pointerdown', {
                        bubbles: true, button: 0, pointerType: 'mouse'
                      }));
                      sessionButton.dispatchEvent(new PointerEvent('pointerup', {
                        bubbles: true, button: 0, pointerType: 'mouse'
                      }));
                      sessionButton.dispatchEvent(new MouseEvent('click', { bubbles: true, button: 0 }));
                    }
                    return JSON.stringify({
                      newSessionVisible: !!sessionButton,
                      newSessionActivated: !!sessionButton,
                      projectManagementVisible: projectManagement.some(visible),
                    });
                  } catch (error) {
                    return JSON.stringify({ error: String(error) });
                  }
                })()""",
                verify_workspace_controls,
            )
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
