from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from types import ModuleType, SimpleNamespace
import sys
import unittest
from unittest.mock import Mock, patch

from coretest_copilot.integration import CoreTestCopilot


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


class RuntimeBufferTests(unittest.TestCase):
    def test_live_frames_keep_only_latest_ten_thousand(self) -> None:
        copilot = CoreTestCopilot.__new__(CoreTestCopilot)
        copilot.live_frames = []

        copilot._remember_live_frames(list(range(10_050)))

        self.assertEqual(len(copilot.live_frames), 10_000)
        self.assertEqual(copilot.live_frames[0], 50)

    def test_diagnostic_logs_keep_only_latest_hundred(self) -> None:
        copilot = CoreTestCopilot.__new__(CoreTestCopilot)
        copilot.diag_logs = [{"message": str(index)} for index in range(100)]

        copilot._diag_info("latest")

        self.assertEqual(len(copilot.diag_logs), 100)
        self.assertEqual(copilot.diag_logs[-1]["message"], "latest")


def _service_module(project_runtime_service: object) -> ModuleType:
    module = ModuleType("app.service")
    module.project_runtime_service = project_runtime_service
    return module


if __name__ == "__main__":
    unittest.main()
