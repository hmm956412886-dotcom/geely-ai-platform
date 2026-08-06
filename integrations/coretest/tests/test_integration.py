from __future__ import annotations

from collections import deque
from pathlib import Path
from tempfile import TemporaryDirectory
from types import ModuleType, SimpleNamespace
import sys
import unittest
from unittest.mock import Mock, patch

from PySide6.QtCore import Qt

from coretest_copilot.integration import (
    CoreTestCopilot,
    _project_identity,
    _resolve_workspace_file,
)


class GeneratedTestSaveTests(unittest.TestCase):
    def test_generated_test_is_saved_inside_active_project(self) -> None:
        with TemporaryDirectory() as directory:
            project = SimpleNamespace(url=directory)
            service = SimpleNamespace(get_active_project=lambda: project)
            download = Mock()
            download.suggestedFileName.return_value = "../test_generated.py"
            copilot = CoreTestCopilot.__new__(CoreTestCopilot)
            copilot._show_error = Mock()

            with patch.dict(sys.modules, {"app.service": _service_module(service)}):
                copilot._save_generated_file(download)

            target = Path(directory) / "generated_tests"
            self.assertTrue(target.is_dir())
            download.setDownloadDirectory.assert_called_once_with(str(target))
            download.setDownloadFileName.assert_called_once_with("test_generated.py")
            download.accept.assert_called_once_with()
            download.cancel.assert_not_called()

    def test_generated_test_save_is_cancelled_without_active_project(self) -> None:
        service = SimpleNamespace(get_active_project=lambda: None)
        download = Mock()
        copilot = CoreTestCopilot.__new__(CoreTestCopilot)
        copilot._show_error = Mock()

        with patch.dict(sys.modules, {"app.service": _service_module(service)}):
            copilot._save_generated_file(download)

        download.cancel.assert_called_once_with()
        download.accept.assert_not_called()
        copilot._show_error.assert_called_once()

    def test_existing_generated_test_gets_a_numbered_filename(self) -> None:
        with TemporaryDirectory() as directory:
            target = Path(directory) / "generated_tests"
            target.mkdir()
            (target / "test_generated.py").write_text("existing", encoding="utf-8")
            project = SimpleNamespace(url=directory)
            service = SimpleNamespace(get_active_project=lambda: project)
            download = Mock()
            download.suggestedFileName.return_value = "test_generated.py"
            copilot = CoreTestCopilot.__new__(CoreTestCopilot)

            with patch.dict(sys.modules, {"app.service": _service_module(service)}):
                copilot._save_generated_file(download)

            download.setDownloadFileName.assert_called_once_with("test_generated_2.py")


class ProjectIdentityTests(unittest.TestCase):
    def test_same_name_projects_in_different_directories_have_distinct_ids(self) -> None:
        with TemporaryDirectory() as first, TemporaryDirectory() as second:
            first_id, first_label = _project_identity(SimpleNamespace(name="vehicle", url=first))
            second_id, second_label = _project_identity(SimpleNamespace(name="vehicle", url=second))

        self.assertEqual(first_label, second_label)
        self.assertNotEqual(first_id, second_id)
        self.assertTrue(first_id.startswith("coretest-"))


class WorkspaceFileLinkTests(unittest.TestCase):
    def test_link_resolves_only_existing_files_inside_active_project(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "generated tests" / "result.py"
            target.parent.mkdir()
            target.write_text("result", encoding="utf-8")
            service = SimpleNamespace(
                get_active_project=lambda: SimpleNamespace(url=directory)
            )

            with patch.dict(sys.modules, {"app.service": _service_module(service)}):
                resolved = _resolve_workspace_file(
                    "/coretest-file/generated%20tests/result.py"
                )
                escaped = _resolve_workspace_file("/coretest-file/../outside.py")
                missing = _resolve_workspace_file("/coretest-file/missing.py")

        self.assertEqual(resolved, target.resolve())
        self.assertIsNone(escaped)
        self.assertIsNone(missing)


class RuntimeBufferTests(unittest.TestCase):
    def test_live_frame_deque_remains_bounded(self) -> None:
        copilot = CoreTestCopilot.__new__(CoreTestCopilot)
        copilot.live_frames = deque(maxlen=10_000)

        copilot._remember_live_frames(list(range(10_050)))

        self.assertEqual(len(copilot.live_frames), 10_000)
        self.assertEqual(copilot.live_frames[0], 50)

    def test_diagnostic_log_deque_remains_bounded(self) -> None:
        copilot = CoreTestCopilot.__new__(CoreTestCopilot)
        copilot.diag_logs = deque(
            ({"message": str(index)} for index in range(100)),
            maxlen=100,
        )

        copilot._diag_info("latest")

        self.assertEqual(len(copilot.diag_logs), 100)
        self.assertEqual(copilot.diag_logs[-1]["message"], "latest")


class AgentStartupTests(unittest.TestCase):
    def test_gateway_waits_for_workspace_publish_before_loading_native_agent(self) -> None:
        copilot = CoreTestCopilot.__new__(CoreTestCopilot)
        copilot.status_text = Mock()
        copilot.status = object()
        copilot.dock = Mock()
        copilot.publish_project = Mock()
        copilot._load_agent = Mock()

        copilot._gateway_ready()

        copilot.publish_project.assert_called_once_with(complete=copilot._load_agent)
        copilot._load_agent.assert_not_called()

    def test_native_agent_is_the_embedded_product_entry(self) -> None:
        native_url = object()
        copilot = CoreTestCopilot.__new__(CoreTestCopilot)
        copilot.dock = Mock()
        copilot.web = Mock()
        copilot.bridge = SimpleNamespace(native_agent_url=native_url)
        copilot._agent_loaded = False

        copilot._load_agent()

        self.assertTrue(copilot._agent_loaded)
        copilot.dock.setWidget.assert_called_once_with(copilot.web)
        copilot.web.setUrl.assert_called_once_with(native_url)


class DockWidthTests(unittest.TestCase):
    def test_width_button_expands_and_restores_the_dock(self) -> None:
        copilot = CoreTestCopilot.__new__(CoreTestCopilot)
        copilot.dock = Mock()
        copilot.expand_button = Mock()
        copilot.window = Mock()

        copilot.dock.width.return_value = 440
        copilot._toggle_dock_width()

        copilot.window.resizeDocks.assert_called_once_with(
            [copilot.dock], [840], Qt.Orientation.Horizontal
        )
        copilot.expand_button.setToolTip.assert_called_with("恢复侧栏宽度")

        copilot.window.reset_mock()
        copilot.dock.width.return_value = 840
        copilot._toggle_dock_width()

        copilot.window.resizeDocks.assert_called_once_with(
            [copilot.dock], [440], Qt.Orientation.Horizontal
        )
        copilot.expand_button.setToolTip.assert_called_with("展开侧栏")


def _service_module(project_runtime_service: object) -> ModuleType:
    module = ModuleType("app.service")
    module.project_runtime_service = project_runtime_service
    return module


if __name__ == "__main__":
    unittest.main()
