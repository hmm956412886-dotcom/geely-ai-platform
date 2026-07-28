"""CoreTest QDockWidget, lifecycle, and read-only signal adapter."""

from __future__ import annotations

from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QDockWidget, QLabel, QPushButton, QVBoxLayout, QWidget
from PySide6.QtWebEngineWidgets import QWebEngineView

from .gateway import GatewayBridge
from .snapshots import dbc_snapshot, diagnostic_snapshot, project_snapshot, trace_snapshot


class CoreTestCopilot:
    def __init__(self, window: Any) -> None:
        self.window = window
        self.revision = 0
        self.trace_filename = ""
        self.diag_ecu = ""
        self.diag_pdx = ""
        self.diag_logs: deque[dict[str, Any]] = deque(maxlen=100)
        self.live_frames: deque[Any] = deque(maxlen=10000)
        self.bridge = GatewayBridge(window)
        self._build_dock()
        self._bind_signals()
        self.bridge.on_ready(self._gateway_ready)
        self.bridge.on_error(self._show_error)
        QApplication.instance().aboutToQuit.connect(self.bridge.release)
        self.bridge.start()

    def _build_dock(self) -> None:
        self.dock = QDockWidget("CoreTest Copilot", self.window)
        self.dock.setObjectName("coretest-copilot-dock")
        self.dock.setAllowedAreas(Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea)
        self.dock.setMinimumWidth(360)
        self.web = QWebEngineView(self.dock)
        self.web.page().profile().downloadRequested.connect(self._save_generated_file)
        self.status = QWidget(self.dock)
        layout = QVBoxLayout(self.status)
        layout.setContentsMargins(24, 24, 24, 24)
        self.status_text = QLabel("正在启动 AI Gateway...", self.status)
        self.status_text.setWordWrap(True)
        retry = QPushButton("重试", self.status)
        retry.clicked.connect(self.bridge.retry)
        layout.addStretch(1)
        layout.addWidget(self.status_text)
        layout.addWidget(retry)
        layout.addStretch(1)
        self.dock.setWidget(self.status)
        self.window.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.dock)
        self.window.menuBar().addAction(self.dock.toggleViewAction())
        self.window.resizeDocks([self.dock], [440], Qt.Orientation.Horizontal)

    def _bind_signals(self) -> None:
        from app.service import can_channel_service, diag_runtime_session_service, project_runtime_service

        self.window.main_tabs.currentChanged.connect(self.publish_current_view)
        for tabs in (
            self.window.file_tabs,
            self.window.node_tabs,
            self.window.diagnostic_tabs,
            self.window.trace_tabs,
        ):
            tabs.currentChanged.connect(self.publish_current_view)
        project_runtime_service.project_changed.connect(lambda _event: self.publish_project())

        tree = self.window.file_dbc_view.dbc_tree_view
        tree.dbc_clicked.connect(lambda dbc: self.publish_dbc(dbc_name=dbc))
        tree.node_clicked.connect(lambda dbc, node: self.publish_dbc(dbc_name=dbc, node_name=node))
        tree.frame_clicked.connect(lambda dbc, frame: self.publish_dbc(dbc_name=dbc, frame_id=frame))
        self.window.can_trace_view.table_view.parse_requested.connect(self.publish_live_trace)
        self.window.replay_view.trace_tree_view.trace_loaded.connect(self.publish_trace_file)
        self.window.replay_view.frame_detail.row_clicked.connect(self.publish_replay_frame)
        self.window.diag_task_view.ecu_list.ecu_selected.connect(self.publish_diagnostic)
        can_channel_service.can_frames_updated.connect(self._remember_live_frames)
        diag_runtime_session_service.log_request.connect(self._diag_request)
        diag_runtime_session_service.log_response.connect(self._diag_response)
        diag_runtime_session_service.log_info.connect(self._diag_info)

    def _gateway_ready(self) -> None:
        self.dock.setWidget(self.web)
        self.web.setUrl(self.bridge.copilot_url)
        self.publish_project()

    def _show_error(self, message: str) -> None:
        self.status_text.setText(f"AI Copilot 暂不可用\n\n{message}")
        self.dock.setWidget(self.status)

    def publish_current_view(self, _index: int = 0) -> None:
        if not self.bridge.ready:
            return
        self.publish_project()

    def publish_project(self) -> None:
        from app.service import project_file_service, project_runtime_service

        project = project_runtime_service.get_active_project()
        snapshot = project_snapshot(project, project_file_service.get_all_fileinfos(), self._revision())
        self._publish(snapshot, selection_label=self._current_view())

    def publish_live_trace(self, selected: Any) -> None:
        snapshot = trace_snapshot(self.live_frames, self._revision(), selected=selected)
        self._publish(snapshot, selection_label=snapshot["selection"].get("frame_id", "实时 Trace"))

    def publish_trace_file(self, filename: str) -> None:
        from app.service import project_trace_service

        self.trace_filename = filename
        frames = project_trace_service.get_all_trace_frames(filename)
        self._publish(trace_snapshot(frames, self._revision(), filename=filename), selection_label=filename)

    def publish_replay_frame(self, frame: Any) -> None:
        from app.service import project_trace_service

        frames = project_trace_service.get_all_trace_frames(self.trace_filename)
        snapshot = trace_snapshot(
            frames, self._revision(), filename=self.trace_filename, selected=frame
        )
        self._publish(snapshot, selection_label=snapshot["selection"].get("frame_id", "Trace"))

    def publish_dbc(self, *, dbc_name: str, node_name: str = "", frame_id: int | None = None) -> None:
        from app.service import project_dbc_service

        snapshot = dbc_snapshot(
            project_dbc_service,
            self._revision(),
            dbc_name=dbc_name,
            node_name=node_name,
            frame_id=frame_id,
        )
        label = snapshot["selection"].get("frame_name") or node_name or dbc_name
        self._publish(snapshot, selection_label=label)

    def publish_diagnostic(self, pdx_name: str, ecu: str) -> None:
        self.diag_pdx, self.diag_ecu = pdx_name, ecu
        snapshot = diagnostic_snapshot(
            self._revision(), ecu=ecu, pdx_name=pdx_name, logs=self.diag_logs
        )
        self._publish(snapshot, selection_label=ecu or "诊断任务")

    def _diag_request(self, ecu: str, service: str, request: bytes, tx_id: int, rx_id: int) -> None:
        self.diag_logs.append(
            {"type": "request", "ecu": ecu, "service": service, "payload_hex": request.hex(" ").upper(), "tx_id": f"0x{tx_id:X}", "rx_id": f"0x{rx_id:X}"}
        )
        self.publish_diagnostic(self.diag_pdx, ecu or self.diag_ecu)

    def _diag_response(self, ecu: str, service: str, response: bytes, positive: bool, tx_id: int, rx_id: int) -> None:
        nrc = f"0x{response[2]:02X}" if not positive and len(response) > 2 else None
        self.diag_logs.append(
            {"type": "response", "ecu": ecu, "service": service, "payload_hex": response.hex(" ").upper(), "is_positive": positive, "nrc": nrc, "tx_id": f"0x{tx_id:X}", "rx_id": f"0x{rx_id:X}"}
        )
        self.publish_diagnostic(self.diag_pdx, ecu or self.diag_ecu)

    def _diag_info(self, message: str) -> None:
        self.diag_logs.append({"type": "info", "message": str(message)[:1000]})

    def _remember_live_frames(self, frames: list[Any]) -> None:
        self.live_frames.extend(frames)

    def _save_generated_file(self, download: Any) -> None:
        from app.service import project_runtime_service

        project = project_runtime_service.get_active_project()
        if project is None:
            download.cancel()
            self._show_error("请先打开项目，再保存生成的测试代码。")
            return
        target = Path(project.url) / "generated_tests"
        target.mkdir(parents=True, exist_ok=True)
        download.setDownloadDirectory(str(target))
        download.setDownloadFileName(Path(download.suggestedFileName()).name)
        download.accept()

    def _publish(self, snapshot: dict[str, Any], *, selection_label: str) -> None:
        from app.service import project_runtime_service

        project = project_runtime_service.get_active_project()
        context = {
            "host_application": "HK CoreTest",
            "project_id": str(getattr(project, "name", "未选择项目")),
            "run_id": snapshot["kind"],
            "current_view": self._current_view(),
            "selection_kind": snapshot["kind"],
            "selection_label": str(selection_label),
            "snapshot_revision": snapshot["revision"],
        }
        snapshot["captured_at"] = datetime.now(timezone.utc).isoformat()
        self.bridge.publish(context, snapshot)

    def _current_view(self) -> str:
        main = self.window.main_tabs.tabText(self.window.main_tabs.currentIndex())
        current = self.window.main_tabs.currentWidget()
        if hasattr(current, "tabText"):
            return f"{main} / {current.tabText(current.currentIndex())}"
        return main

    def _revision(self) -> str:
        self.revision += 1
        return str(self.revision)
