from __future__ import annotations

import os
from pathlib import Path
import sys

from PySide6.QtCore import QCoreApplication, QTimer

from coretest_copilot.gateway import GatewayBridge


def main() -> int:
    root = Path(__file__).resolve().parents[2]
    executable = root / "dist" / "geely-ai-gateway" / "geely-ai-gateway.exe"
    if not executable.is_file():
        print(f"FAIL Sidecar executable is missing: {executable}", file=sys.stderr)
        return 1

    os.environ["CORETEST_AI_GATEWAY_EXE"] = str(executable)
    app = QCoreApplication(sys.argv)
    bridge = GatewayBridge(app, base_url="http://127.0.0.1:8877")
    failures: list[str] = []

    def ready() -> None:
        print("PASS CoreTest Connector launched packaged AI Gateway on port 8877")
        bridge.release()
        app.quit()

    def failed(message: str) -> None:
        failures.append(message)
        bridge.release()
        app.quit()

    bridge.on_ready(ready)
    bridge.on_error(failed)
    bridge.start()
    QTimer.singleShot(15000, lambda: failed("packaged AI Gateway startup timeout"))
    app.exec()
    if failures:
        print(f"FAIL Sidecar smoke: {failures[0]}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
