"""Headless product smoke test for the installed CoreTest Copilot Dock."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys
from urllib.request import urlopen

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication


def main() -> int:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu")
    root = Path(__file__).resolve().parents[2]
    customer_root = root / "customer-data" / "hk-coretest-ai"
    os.environ.setdefault("CORETEST_AI_PLATFORM_ROOT", str(root))
    sys.path.insert(0, str(customer_root))

    from app.view.window import MainWindow

    app = QApplication(sys.argv)
    window = MainWindow()
    window.resize(1280, 800)
    failures: list[str] = []

    def verify_dom(text: object) -> None:
        try:
            assert window.copilot.dock.objectName() == "coretest-copilot-dock"
            assert window.copilot.bridge.ready
            assert window.copilot.web.url().path() == "/copilot-shell/"
            page_text = str(text)
            for label in ("CoreTest Copilot", "HK CoreTest", "添加参考文件", "生成测试"):
                assert label in page_text, f"missing WebEngine content: {label}"
            base = window.copilot.bridge.base_url
            session = window.copilot.bridge.session_id
            with urlopen(f"{base}/api/v1/host/context?host_session_id={session}", timeout=3) as response:
                context = json.load(response)["result"]
            with urlopen(f"{base}/api/v1/host/snapshot?host_session_id={session}", timeout=3) as response:
                snapshot = json.load(response)["result"]
            assert context["host_application"] == "HK CoreTest"
            assert context["current_view"] == "文件管理 / 首页"
            assert snapshot["kind"] == "project"
            screenshot = Path(os.getenv("TEMP", ".")) / "coretest-copilot-smoke.png"
            assert window.grab().save(str(screenshot))
            print(f"PASS CoreTest Copilot headless smoke: {screenshot}")
        except Exception as exc:
            failures.append(str(exc) or type(exc).__name__)
        finally:
            window.copilot.bridge.release()
            window.close()
            app.quit()

    def verify_loaded(ok: bool) -> None:
        if not ok:
            failures.append("Copilot WebEngine page failed to load")
            window.copilot.bridge.release()
            app.quit()
            return
        QTimer.singleShot(
            1200,
            lambda: window.copilot.web.page().runJavaScript("document.body.innerText", verify_dom),
        )

    window.copilot.web.loadFinished.connect(verify_loaded)

    def timeout() -> None:
        failures.append("Gateway or WebEngine startup timeout")
        window.copilot.bridge.release()
        app.quit()

    QTimer.singleShot(12000, timeout)
    app.exec()
    if failures:
        print(f"FAIL CoreTest Copilot headless smoke: {failures[0]}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
