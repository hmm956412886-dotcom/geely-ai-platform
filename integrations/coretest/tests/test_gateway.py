from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from PySide6.QtCore import QByteArray, QUrl
from PySide6.QtNetwork import QNetworkReply

from coretest_copilot.gateway import (
    GatewayBridge,
    _configuration_file,
    _gateway_executable,
    _load_env_values,
    _server_arguments,
)


class GatewayConfigTests(unittest.TestCase):
    def test_copilot_url_uses_token_loaded_for_sidecar(self) -> None:
        bridge = GatewayBridge.__new__(GatewayBridge)
        bridge.base_url = "http://127.0.0.1:8765"
        bridge.session_id = "coretest-session"
        bridge._access_token = "token with spaces"

        self.assertEqual(
            bridge.copilot_url,
            QUrl(
                "http://127.0.0.1:8765/copilot-shell/?host_session_id=coretest-session"
                "#access_token=token%20with%20spaces"
            ),
        )

    def test_publish_updates_context_only_after_snapshot_succeeds(self) -> None:
        bridge = GatewayBridge.__new__(GatewayBridge)
        calls = []

        def request(method, path, payload=None, *, privileged=False, success=None):
            calls.append((method, path, payload, privileged))
            if success:
                success({"result": payload})

        bridge.request = request
        bridge.publish({"selection_kind": "dbc"}, {"kind": "dbc", "revision": "2"})

        self.assertEqual([call[1] for call in calls], ["/api/v1/host/snapshot", "/api/v1/host/context"])
        self.assertTrue(calls[0][3])
        self.assertFalse(calls[1][3])

    def test_publish_registers_workspace_before_snapshot(self) -> None:
        bridge = GatewayBridge.__new__(GatewayBridge)
        calls = []

        def request(method, path, payload=None, *, privileged=False, success=None):
            calls.append((method, path, payload, privileged))
            if success:
                success({"result": payload})

        bridge.request = request
        bridge.publish(
            {"selection_kind": "project"},
            {"kind": "project", "revision": "1"},
            workspace_root="D:/projects/demo",
        )

        self.assertEqual(
            [call[1] for call in calls],
            [
                "/api/v1/host/workspace",
                "/api/v1/host/snapshot",
                "/api/v1/host/context",
            ],
        )
        self.assertEqual(calls[0][2], {"project_root": "D:/projects/demo"})
        self.assertTrue(calls[0][3])

    def test_load_env_values_reads_only_assignments(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            path.write_text(
                "# CoreTest model settings\nAI_MODEL_BASE_URL=https://api.example.com\ninvalid\nOPENCODE_COMMAND=opencode.exe\n",
                encoding="utf-8",
            )

            values = _load_env_values(path)

        self.assertEqual(values["AI_MODEL_BASE_URL"], "https://api.example.com")
        self.assertEqual(values["OPENCODE_COMMAND"], "opencode.exe")
        self.assertNotIn("invalid", values)

    def test_load_env_values_ignores_missing_file(self) -> None:
        self.assertEqual(_load_env_values(Path("missing.env")), {})

    def test_configuration_file_accepts_legacy_env_file(self) -> None:
        with TemporaryDirectory() as directory:
            app_root = Path(directory)
            legacy = app_root / ".env"
            legacy.write_text("AI_MODEL_NAME=demo-model\n", encoding="utf-8")
            fake_module = app_root / "app" / "coretest_copilot" / "gateway.py"
            with patch(
                "coretest_copilot.gateway.Path.cwd", return_value=app_root / "workspace"
            ), patch(
                "coretest_copilot.gateway.Path.resolve",
                return_value=fake_module,
            ):
                resolved = _configuration_file(None, None)

        self.assertEqual(resolved, legacy)

    def test_configuration_file_honors_explicit_path(self) -> None:
        with TemporaryDirectory() as directory:
            configured = Path(directory) / "settings" / "model.env"
            with patch.dict(
                "os.environ", {"AI_MODEL_CONFIG_FILE": str(configured)}, clear=False
            ):
                resolved = _configuration_file(None, None)

            self.assertEqual(resolved, configured.resolve())
            self.assertTrue(configured.parent.is_dir())

    def test_configuration_file_defaults_to_local_app_data(self) -> None:
        with TemporaryDirectory() as directory:
            fake_module = Path(directory) / "app" / "coretest_copilot" / "gateway.py"
            with patch.dict(
                "os.environ",
                {"LOCALAPPDATA": directory, "AI_MODEL_CONFIG_FILE": ""},
                clear=False,
            ), patch(
                "coretest_copilot.gateway.Path.cwd", return_value=Path(directory) / "work"
            ), patch(
                "coretest_copilot.gateway.Path.resolve", return_value=fake_module
            ):
                resolved = _configuration_file(None, None)

        self.assertEqual(resolved, Path(directory) / "HK-CoreTest" / "ai-model.env")

    def test_gateway_executable_uses_configured_sidecar(self) -> None:
        with TemporaryDirectory() as directory:
            executable = Path(directory) / "geely-ai-gateway.exe"
            executable.touch()
            with patch.dict(
                "os.environ", {"CORETEST_AI_GATEWAY_EXE": str(executable)}, clear=False
            ):
                resolved = _gateway_executable()

        self.assertEqual(resolved, executable.resolve())

    def test_gateway_executable_finds_sidecar_next_to_packaged_coretest(self) -> None:
        with TemporaryDirectory() as directory:
            app_dir = Path(directory)
            executable = app_dir / "ai-gateway" / "geely-ai-gateway.exe"
            executable.parent.mkdir()
            executable.touch()
            with patch.dict("os.environ", {}, clear=True), patch(
                "coretest_copilot.gateway.sys.executable", str(app_dir / "HK-CoreTest.exe")
            ):
                resolved = _gateway_executable()

        self.assertEqual(resolved, executable.resolve())

    def test_server_arguments_follow_bridge_base_url(self) -> None:
        self.assertEqual(
            _server_arguments("http://127.0.0.1:8877"),
            ["--host", "127.0.0.1", "--port", "8877"],
        )

    def test_gateway_error_response_is_reported_to_host(self) -> None:
        bridge = GatewayBridge.__new__(GatewayBridge)
        errors = []
        bridge._error_callbacks = [errors.append]
        reply = unittest.mock.Mock()
        reply.readAll.return_value = QByteArray(
            b'{"error":{"message":"snapshot exceeds size limit"}}'
        )
        reply.error.return_value = QNetworkReply.NetworkError.ConnectionRefusedError
        reply.errorString.return_value = "connection refused"

        bridge._finished(reply, None)

        self.assertEqual(errors, ["snapshot exceeds size limit"])
        reply.deleteLater.assert_called_once_with()

    def test_release_requests_runtime_cleanup_before_stopping_gateway(self) -> None:
        bridge = GatewayBridge.__new__(GatewayBridge)
        bridge.ready = True
        reply = unittest.mock.Mock()
        reply.isFinished.return_value = True
        bridge.request = unittest.mock.Mock(return_value=reply)
        bridge.stop_process = unittest.mock.Mock()

        bridge.release()

        bridge.request.assert_called_once_with(
            "DELETE", "/api/v1/host/session", privileged=True
        )
        bridge.stop_process.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
