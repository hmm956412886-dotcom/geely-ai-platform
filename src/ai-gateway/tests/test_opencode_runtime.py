import json
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from ai_gateway.host_bridge import HostBridgeConfig
from ai_gateway.model_client import ModelConfig
from ai_gateway.opencode_runtime import (
    OpenCodeConfig,
    OpenCodeRuntime,
    _install_opencode,
    _provider_probe_file,
    _verify_bundled_opencode,
    find_opencode_command,
    load_opencode_config,
    resolve_opencode_command,
)


class FakeProcess:
    def __init__(self) -> None:
        self.returncode = None
        self.terminated = False

    def poll(self):
        return self.returncode

    def terminate(self) -> None:
        self.terminated = True
        self.returncode = 0

    def wait(self, timeout=None):
        return self.returncode


class FakeResponse:
    def __init__(self, body: bytes) -> None:
        self.body = body
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self) -> bytes:
        return self.body

    def close(self) -> None:
        self.closed = True


class StreamingResponse(FakeResponse):
    def read(self, size=-1) -> bytes:
        chunk, self.body = self.body[:size], self.body[size:]
        return chunk

    def readline(self) -> bytes:
        if not self.body:
            return b""
        boundary = self.body.find(b"\n") + 1
        if boundary == 0:
            boundary = len(self.body)
        line, self.body = self.body[:boundary], self.body[boundary:]
        return line


class NativeResponse(StreamingResponse):
    def __init__(self, body: bytes, content_type: str) -> None:
        super().__init__(body)
        self.status = 200
        self.headers = {"Content-Type": content_type, "Cache-Control": "no-cache"}


class StalledStreamingResponse(FakeResponse):
    def readline(self) -> bytes:
        raise TimeoutError("stream stalled")


class FakeOpenCodeApi:
    def __init__(self) -> None:
        self.requests = []

    def __call__(self, request, **_kwargs):
        self.requests.append(request)
        if request.get_method() == "PUT":
            return FakeResponse(b"true")
        return FakeResponse(b'{"healthy":true,"version":"1.2.3"}')


class OpenCodeRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self._state_directory = TemporaryDirectory()
        self._state_environment = patch.dict(
            "os.environ",
            {"CORETEST_OPENCODE_HOME": self._state_directory.name},
            clear=False,
        )
        self._state_environment.start()

    def tearDown(self) -> None:
        self._state_environment.stop()
        self._state_directory.cleanup()

    def test_install_opencode_verifies_and_extracts_pinned_archive(self) -> None:
        archive = BytesIO()
        with ZipFile(archive, "w") as bundle:
            bundle.writestr("opencode.exe", b"verified-runtime")
        payload = archive.getvalue()

        with TemporaryDirectory() as directory:
            target = Path(directory) / "version" / "opencode.exe"
            _install_opencode(
                target,
                url="https://example.test/opencode.zip",
                expected_sha256=sha256(payload).hexdigest(),
                opener=lambda *_args, **_kwargs: StreamingResponse(payload),
            )

            self.assertEqual(target.read_bytes(), b"verified-runtime")

        with TemporaryDirectory() as directory:
            with self.assertRaisesRegex(RuntimeError, "SHA-256"):
                _install_opencode(
                    Path(directory) / "opencode.exe",
                    expected_sha256="0" * 64,
                    opener=lambda *_args, **_kwargs: StreamingResponse(payload),
                )

    def test_load_config_accepts_only_localhost(self) -> None:
        config = load_opencode_config(
            {"OPENCODE_COMMAND": "custom-opencode", "OPENCODE_PORT": "4900"}
        )

        self.assertEqual(config.command, "custom-opencode")
        self.assertEqual(config.host, "127.0.0.1")
        self.assertEqual(config.port, 4900)
        self.assertEqual(config.stream_idle_timeout_seconds, 300)
        self.assertEqual(config.turn_timeout_seconds, 1800)

        with self.assertRaisesRegex(ValueError, "127.0.0.1"):
            load_opencode_config({"OPENCODE_HOST": "0.0.0.0"})

        with self.assertRaisesRegex(ValueError, "turn timeout"):
            load_opencode_config(
                {
                    "OPENCODE_STREAM_IDLE_TIMEOUT_SECONDS": "300",
                    "OPENCODE_TURN_TIMEOUT_SECONDS": "120",
                }
            )

    def test_load_config_uses_available_port_when_not_explicitly_configured(self) -> None:
        with patch(
            "ai_gateway.opencode_runtime._available_loopback_port",
            return_value=4917,
        ):
            config = load_opencode_config({})

        self.assertEqual(config.port, 4917)

    def test_native_ui_proxy_forces_workspace_and_blocks_dangerous_routes(self) -> None:
        requests = []

        def open_native(request, **_kwargs):
            requests.append(request)
            return NativeResponse(
                json.dumps(
                    {"directory": str(runtime._workspace), "sessions": []}
                ).encode("utf-8"),
                "application/json",
            )

        runtime = OpenCodeRuntime(urlopen=open_native)
        runtime._require_healthy = lambda: None
        with TemporaryDirectory() as directory:
            runtime._workspace = Path(directory).resolve()
            response = runtime.native_request(
                "GET",
                "/session?directory=C%3A%5Cwrong&workspace=outside&limit=10",
            )

            self.assertNotIn(str(runtime._workspace), response.body.decode("utf-8"))
            self.assertIn("CoreTest Workspace", response.body.decode("utf-8"))
            requested_url = requests[0].full_url
            self.assertNotIn("wrong", requested_url)
            self.assertNotIn("workspace=outside", requested_url)
            self.assertIn("limit=10", requested_url)
            self.assertIn("directory=", requested_url)
            runtime.native_request("GET", "/path?directory=CoreTest%20Workspace")
            path_url = requests[1].full_url
            self.assertNotIn("CoreTest%20Workspace", path_url)
            self.assertIn("directory=", path_url)
            runtime.native_request(
                "GET", "/experimental/resource?directory=outside"
            )
            resource_url = requests[2].full_url
            self.assertNotIn("outside", resource_url)
            self.assertIn("directory=", resource_url)
            with self.assertRaisesRegex(PermissionError, "disabled"):
                runtime.native_request("POST", "/pty", b"{}")
            with self.assertRaisesRegex(PermissionError, "disabled"):
                runtime.native_request("POST", "/session/session-1/share", b"{}")
            with self.assertRaisesRegex(PermissionError, "disabled"):
                runtime.native_request("POST", "/mcp", b"{}")

    def test_native_ui_proxy_streams_sse_and_redacts_workspace(self) -> None:
        upstream = NativeResponse(b"", "text/event-stream")
        runtime = OpenCodeRuntime(urlopen=lambda *_args, **_kwargs: upstream)
        runtime._require_healthy = lambda: None
        with TemporaryDirectory() as directory:
            runtime._workspace = Path(directory).resolve()
            upstream.body = (
                "data: "
                + json.dumps(
                    {
                        "path": str(runtime._workspace),
                        "text": f"[result]({runtime._workspace}/generated.py:3)",
                    }
                )
                + "\n\n"
            ).encode("utf-8")
            proxied = runtime.native_request("GET", "/event?directory=outside")
            streamed = b"".join(proxied.stream or ())

        self.assertEqual(proxied.content_type, "text/event-stream")
        self.assertNotIn(str(runtime._workspace).encode("utf-8"), streamed)
        self.assertIn(b"CoreTest Workspace", streamed)
        self.assertIn(
            b"[result](/coretest-file/generated.py?line=3)",
            streamed,
        )
        self.assertTrue(upstream.closed)

    def test_native_ui_proxy_rewrites_workspace_markdown_file_links(self) -> None:
        runtime = OpenCodeRuntime()
        with TemporaryDirectory() as directory:
            runtime._workspace = Path(directory).resolve()
            file_path = runtime._workspace / "generated tests" / "result.py"
            file_path.parent.mkdir()
            file_path.write_text("result", encoding="utf-8")
            raw = json.dumps(
                {
                    "directory": str(runtime._workspace),
                    "text": f"[result.py]({file_path}:12)",
                    "relative_text": "[result.py](generated%20tests/result.py:12)",
                }
            ).encode("utf-8")

            sanitized = json.loads(
                runtime._sanitize_native_body(raw, "application/json").decode("utf-8")
            )

        self.assertEqual(sanitized["directory"], "CoreTest Workspace")
        self.assertEqual(
            sanitized["text"],
            "[result.py](/coretest-file/generated%20tests/result.py?line=12)",
        )
        self.assertEqual(
            sanitized["relative_text"],
            "[result.py](/coretest-file/generated%20tests/result.py?line=12)",
        )
        self.assertNotIn(str(runtime._workspace), json.dumps(sanitized))

    def test_native_ui_provider_catalog_only_exposes_managed_providers(self) -> None:
        upstream = {
            "all": [
                {"id": "opencode", "name": "OpenCode Zen"},
                {"id": "coretest", "name": "CoreTest configured model"},
            ],
            "default": {"opencode": "free-model", "coretest": "demo-model"},
            "connected": ["opencode", "coretest"],
        }
        runtime = OpenCodeRuntime(
            urlopen=lambda *_args, **_kwargs: FakeResponse(
                json.dumps(upstream).encode("utf-8")
            )
        )
        runtime._require_healthy = lambda: None
        with TemporaryDirectory() as directory:
            root = Path(directory)
            runtime._workspace = root
            runtime._config_path = root / "opencode.json"
            runtime._config_path.write_text(
                json.dumps(
                    {
                        "provider": {
                            "coretest": {
                                "models": {"demo-model": {"name": "Demo"}}
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )

            response = runtime.native_request("GET", "/provider")

        payload = json.loads(response.body)
        self.assertEqual([item["id"] for item in payload["all"]], ["coretest"])
        self.assertEqual(payload["default"], {"coretest": "demo-model"})
        self.assertEqual(payload["connected"], ["coretest"])

    def test_native_ui_only_accepts_safe_openai_compatible_provider_mutations(self) -> None:
        requests = []

        def open_native(request, **_kwargs):
            requests.append(request)
            return NativeResponse(b"true", "application/json")

        runtime = OpenCodeRuntime(urlopen=open_native)
        runtime._require_healthy = lambda: None
        with TemporaryDirectory() as directory:
            runtime._workspace = Path(directory)
            runtime.native_request(
                "PUT",
                "/auth/provider-a",
                b'{"type":"api","key":"secret"}',
            )
            runtime.native_request(
                "PATCH",
                "/config",
                json.dumps(
                    {
                        "provider": {
                            "provider-a": {
                                "npm": "@ai-sdk/openai-compatible",
                                "name": "Provider A",
                                "options": {"baseURL": "https://api.example.com/v1"},
                                "models": {"model-a": {"name": "Model A"}},
                            }
                        },
                        "disabled_providers": [],
                    }
                ).encode("utf-8"),
            )

            with self.assertRaisesRegex(PermissionError, "request headers"):
                runtime.native_request(
                    "PATCH",
                    "/config",
                    json.dumps(
                        {
                            "provider": {
                                "provider-a": {
                                    "npm": "@ai-sdk/openai-compatible",
                                    "name": "Provider A",
                                    "options": {
                                        "baseURL": "https://api.example.com/v1",
                                        "headers": {"X-Admin": "secret"},
                                    },
                                    "models": {"model-a": {"name": "Model A"}},
                                }
                            }
                        }
                    ).encode("utf-8"),
                )
            with self.assertRaisesRegex(PermissionError, "config fields"):
                runtime.native_request("PATCH", "/config", b'{"permission":{}}')
            with self.assertRaisesRegex(ValueError, "API key"):
                runtime.native_request(
                    "PUT", "/auth/provider-a", b'{"type":"oauth","key":"secret"}'
                )

        self.assertEqual([request.get_method() for request in requests], ["PUT", "PATCH"])

    def test_model_env_file_does_not_place_opencode_state_in_project(self) -> None:
        with TemporaryDirectory() as directory:
            config = load_opencode_config(
                {
                    "LOCALAPPDATA": directory,
                    "AI_MODEL_CONFIG_FILE": "D:/customer/project/.env",
                }
            )

            self.assertEqual(
                config.state_root,
                (Path(directory) / "HK-CoreTest" / "opencode").resolve(),
            )

    def test_command_probe_does_not_install_missing_auto_runtime(self) -> None:
        with TemporaryDirectory() as directory, patch(
            "ai_gateway.opencode_runtime.os.name", "nt"
        ), patch(
            "ai_gateway.opencode_runtime.sys.executable",
            str(Path(directory) / "python.exe"),
        ), patch(
            "ai_gateway.opencode_runtime.shutil.which", return_value=None
        ), patch.dict(
            "os.environ", {"LOCALAPPDATA": directory}, clear=False
        ):
            self.assertIsNone(find_opencode_command("auto"))

    def test_missing_runtime_does_not_download_without_developer_opt_in(self) -> None:
        with patch(
            "ai_gateway.opencode_runtime.find_opencode_command", return_value=None
        ), patch(
            "ai_gateway.opencode_runtime._install_opencode"
        ) as install, patch.dict(
            "os.environ", {"OPENCODE_ALLOW_DOWNLOAD": ""}, clear=False
        ):
            self.assertIsNone(resolve_opencode_command("auto"))
        install.assert_not_called()

    def test_bundled_runtime_rejects_an_unlocked_executable(self) -> None:
        with TemporaryDirectory() as directory:
            executable = Path(directory) / "opencode.exe"
            executable.write_bytes(b"tampered")
            with self.assertRaisesRegex(RuntimeError, "SHA-256"):
                _verify_bundled_opencode(executable)

    def test_start_uses_registered_user_workspace_and_persistent_provider_config(self) -> None:
        calls = []
        process = FakeProcess()

        def start_process(args, **kwargs):
            calls.append((args, kwargs))
            return process

        with TemporaryDirectory() as directory:
            api = FakeOpenCodeApi()
            state_root = Path(directory) / "opencode-state"
            workspace = Path(directory) / "workspace"
            workspace.mkdir()
            source_file = workspace / "sample.py"
            source_file.write_text("ORIGINAL = True\n", encoding="utf-8")
            runtime = OpenCodeRuntime(
                config=OpenCodeConfig(
                    command="opencode-test", port=4901, state_root=state_root
                ),
                model_config=ModelConfig(
                    "https://api.example.com/v1", "model-secret", "demo-model"
                ),
                process_factory=start_process,
                command_resolver=lambda _command: "C:/tools/opencode.exe",
                urlopen=api,
                password_factory=lambda: "runtime-secret",
            )

            with patch.dict(
                "os.environ",
                {
                    "AI_GATEWAY_HOST_TOKEN": "host-secret",
                    "UNRELATED_PRIVATE_VALUE": "private",
                },
                clear=False,
            ):
                status = runtime.start(workspace)
            runtime.start(workspace)
            self.assertEqual(len(calls), 1)
            args, kwargs = calls[0]
            config_path = Path(kwargs["env"]["OPENCODE_CONFIG"])
            config_text = config_path.read_text(encoding="utf-8")
            provider = json.loads(config_text)

            self.assertEqual(
                args,
                [
                    "C:/tools/opencode.exe",
                    "serve",
                    "--hostname",
                    "127.0.0.1",
                    "--port",
                    "4901",
                ],
            )
            self.assertEqual(Path(kwargs["cwd"]), workspace.resolve())
            Path(kwargs["cwd"], "sample.py").write_text(
                "ORIGINAL = False\n", encoding="utf-8"
            )
            self.assertEqual(source_file.read_text(encoding="utf-8"), "ORIGINAL = False\n")
            self.assertEqual(kwargs["env"]["OPENCODE_SERVER_PASSWORD"], "runtime-secret")
            for name in ("DATA", "CONFIG", "CACHE", "STATE"):
                self.assertTrue(kwargs["env"][f"XDG_{name}_HOME"].startswith(str(state_root)))
            self.assertNotIn("CORETEST_OPENCODE_MODEL_API_KEY", kwargs["env"])
            self.assertNotIn("AI_GATEWAY_HOST_TOKEN", kwargs["env"])
            self.assertNotIn("UNRELATED_PRIVATE_VALUE", kwargs["env"])
            self.assertNotIn("model-secret", config_text)
            self.assertNotIn("apiKey", provider["provider"]["coretest"]["options"])
            self.assertEqual(provider["model"], "coretest/demo-model")
            self.assertEqual(provider["permission"]["edit"], "allow")
            self.assertEqual(provider["permission"]["apply_patch"], "allow")
            self.assertEqual(provider["permission"]["write"], "allow")
            self.assertEqual(provider["permission"]["bash"], "allow")
            self.assertEqual(provider["permission"]["webfetch"], "deny")
            self.assertEqual(provider["permission"]["external_directory"], "deny")
            self.assertTrue(status["running"])
            self.assertNotIn(str(Path(directory).resolve()), json.dumps(status))

            health = runtime.health()
            self.assertTrue(health["healthy"])
            self.assertEqual(health["version"], "1.2.3")
            auth_request = next(item for item in api.requests if item.get_method() == "PUT")
            self.assertTrue(auth_request.full_url.endswith("/auth/coretest"))
            self.assertEqual(
                json.loads(auth_request.data.decode("utf-8")),
                {"type": "api", "key": "model-secret"},
            )

            runtime.stop()
            self.assertTrue(process.terminated)
            self.assertTrue(config_path.exists())
            self.assertTrue(workspace.exists())

    def test_start_exposes_only_scoped_read_only_host_cli_to_opencode(self) -> None:
        calls = []
        with TemporaryDirectory() as directory:
            workspace = Path(directory) / "workspace"
            workspace.mkdir()
            state_root = Path(directory) / "state"
            runtime = OpenCodeRuntime(
                config=OpenCodeConfig(
                    command="opencode-test", port=4902, state_root=state_root
                ),
                process_factory=lambda args, **kwargs: (
                    calls.append((args, kwargs)) or FakeProcess()
                ),
                command_resolver=lambda _command: "C:/tools/opencode.exe",
            )

            runtime.start(
                workspace,
                host_bridge=HostBridgeConfig(
                    "http://127.0.0.1:43123", "scoped-read-only-token"
                ),
            )

            environment = calls[0][1]["env"]
            cli_directory = Path(environment["PATH"].split(";", 1)[0])
            self.assertEqual(
                environment["CORETEST_HOST_BRIDGE_URL"], "http://127.0.0.1:43123"
            )
            self.assertEqual(
                environment["CORETEST_HOST_BRIDGE_TOKEN"], "scoped-read-only-token"
            )
            self.assertTrue((cli_directory / "coretest-host.cmd").is_file())
            self.assertNotIn("AI_GATEWAY_HOST_TOKEN", environment)

    def test_provider_management_uses_native_opencode_config_and_auth(self) -> None:
        process = FakeProcess()
        config = {
            "model": "provider-a/model-a",
            "provider": {
                "provider-a": {
                    "npm": "@ai-sdk/openai-compatible",
                    "name": "Provider A",
                    "options": {"baseURL": "https://a.example/v1"},
                    "models": {"model-a": {"name": "Model A"}},
                }
            },
        }
        connected = {"provider-a"}
        requests = []

        def merge(target, update):
            for key, value in update.items():
                if isinstance(value, dict) and isinstance(target.get(key), dict):
                    merge(target[key], value)
                else:
                    target[key] = value

        def api(request, **_kwargs):
            requests.append(request)
            path = request.full_url.split("4097", 1)[-1]
            method = request.get_method()
            payload = json.loads(request.data.decode("utf-8")) if request.data else None
            if path == "/global/health":
                return FakeResponse(b'{"healthy":true,"version":"1.18.10"}')
            if path == "/config" and method == "GET":
                return FakeResponse(json.dumps(config).encode("utf-8"))
            if path == "/config" and method == "PATCH":
                merge(config, payload)
                return FakeResponse(json.dumps(payload).encode("utf-8"))
            if path == "/provider":
                return FakeResponse(
                    json.dumps({"all": [], "default": {}, "connected": sorted(connected)}).encode("utf-8")
                )
            if path.startswith("/auth/") and method == "PUT":
                connected.add(path.rsplit("/", 1)[-1])
                return FakeResponse(b"true")
            if path.startswith("/auth/") and method == "DELETE":
                connected.discard(path.rsplit("/", 1)[-1])
                return FakeResponse(b"true")
            if path == "/session" and method == "POST":
                return FakeResponse(b'{"id":"provider-check"}')
            if path == "/session/provider-check/message" and method == "POST":
                return FakeResponse(b'{"parts":[{"type":"text","text":"OK"}]}')
            if path.startswith("/session/provider-check/message?directory=") and method == "GET":
                return FakeResponse(
                    b'[{"parts":['
                    b'{"type":"tool","tool":"read","state":{"status":"completed"}},'
                    b'{"type":"text","text":"OK"}]}]'
                )
            if path == "/session/provider-check" and method == "DELETE":
                return FakeResponse(b"true")
            raise AssertionError(f"unexpected OpenCode request: {method} {path}")

        with TemporaryDirectory() as directory:
            workspace = Path(directory) / "workspace"
            workspace.mkdir()
            (workspace / "README.md").write_text("provider probe\n", encoding="utf-8")
            runtime = OpenCodeRuntime(
                config=OpenCodeConfig(state_root=Path(directory) / "state"),
                model_config=ModelConfig(None, None, None),
                process_factory=lambda *_args, **_kwargs: process,
                command_resolver=lambda _command: "C:/tools/opencode.exe",
                urlopen=api,
            )
            runtime.start(workspace)

            saved = runtime.save_provider(
                {
                    "id": "provider-b",
                    "name": "Provider B",
                    "base_url": "https://b.example/v1",
                    "api_key": "provider-b-secret",
                    "models": [{"id": "model-b", "name": "Model B"}],
                    "activate": True,
                }
            )

            self.assertEqual(saved["active_provider_id"], "provider-b")
            self.assertEqual(saved["active_model_id"], "model-b")
            self.assertEqual(len(saved["providers"]), 2)
            self.assertNotIn("provider-b-secret", json.dumps(saved))
            provider_b = next(item for item in saved["providers"] if item["id"] == "provider-b")
            self.assertTrue(provider_b["api_key_configured"])

            tested = runtime.test_provider("provider-b", "model-b")
            self.assertTrue(tested["ok"])
            test_request = next(
                request
                for request in requests
                if request.get_method() == "POST"
                and request.full_url.endswith("/session/provider-check/message")
            )
            self.assertEqual(
                json.loads(test_request.data.decode("utf-8"))["model"],
                {"providerID": "provider-b", "modelID": "model-b"},
            )
            self.assertIn(
                "README.md",
                json.loads(test_request.data.decode("utf-8"))["parts"][0]["text"],
            )

            selected = runtime.activate_provider("provider-a", "model-a")
            self.assertEqual(selected["active_provider_id"], "provider-a")
            runtime.activate_provider("provider-b", "model-b")
            runtime.delete_provider("provider-b")
            catalog = runtime.providers()
            self.assertEqual([item["id"] for item in catalog["providers"]], ["provider-a"])
            self.assertEqual(catalog["active_provider_id"], "provider-a")
            self.assertNotIn("provider-b", connected)
            self.assertIn("provider-b", config["disabled_providers"])
            runtime.stop()

    def test_provider_probe_file_selects_small_text_file_without_mutating_workspace(self) -> None:
        with TemporaryDirectory() as directory:
            workspace = Path(directory)
            (workspace / "config.db").write_bytes(b"database")
            data = workspace / "dbc_files"
            data.mkdir()
            expected = data / "vehicle.dbc"
            expected.write_text("VERSION \"\"\n", encoding="utf-8")

            self.assertEqual(_provider_probe_file(workspace), expected)
            self.assertEqual(
                sorted(path.name for path in workspace.iterdir()),
                ["config.db", "dbc_files"],
            )

    def test_legacy_provider_is_migrated_once_and_user_disable_persists(self) -> None:
        with TemporaryDirectory() as directory:
            state_root = Path(directory)
            config_path = state_root / "config" / "opencode.json"
            config_path.parent.mkdir(parents=True)
            config_path.write_text(
                json.dumps(
                    {
                        "model": "coretest/old-model",
                        "provider": {},
                        "disabled_providers": ["coretest"],
                    }
                ),
                encoding="utf-8",
            )
            runtime = OpenCodeRuntime(
                model_config=ModelConfig(
                    "https://api.example.com/v1", "secret", "new-model"
                )
            )

            runtime._prepare_config(state_root)
            migrated = json.loads(config_path.read_text(encoding="utf-8"))
            self.assertEqual(migrated["model"], "coretest/new-model")
            self.assertIn("coretest", migrated["provider"])
            self.assertNotIn("coretest", migrated["disabled_providers"])
            self.assertTrue((config_path.parent / ".legacy-provider-imported").is_file())

            migrated["disabled_providers"] = ["coretest"]
            config_path.write_text(json.dumps(migrated), encoding="utf-8")
            runtime._prepare_config(state_root)
            restarted = json.loads(config_path.read_text(encoding="utf-8"))
            self.assertIn("coretest", restarted["disabled_providers"])

    def test_provider_validation_rejects_invalid_configurations(self) -> None:
        runtime = OpenCodeRuntime()
        valid = {
            "id": "provider-a",
            "name": "Provider A",
            "base_url": "https://api.example.com/v1",
            "api_key": "secret",
            "models": [{"id": "model-a", "name": "Model A"}],
        }
        invalid_updates = [
            ({**valid, "id": "invalid provider"}, "provider id"),
            ({**valid, "base_url": "file:///tmp/model"}, "http or https"),
            (
                {
                    **valid,
                    "models": [
                        {"id": "duplicate", "name": "One"},
                        {"id": "duplicate", "name": "Two"},
                    ],
                },
                "unique",
            ),
        ]
        for update, message in invalid_updates:
            with self.subTest(update=update), self.assertRaisesRegex(ValueError, message):
                runtime.save_provider(update)

    def test_start_rejects_non_directory_workspace(self) -> None:
        runtime = OpenCodeRuntime(
            command_resolver=lambda _command: "C:/tools/opencode.exe"
        )

        with self.assertRaisesRegex(ValueError, "workspace"):
            runtime.start(Path("missing-workspace"))

    def test_health_fails_closed_when_model_authentication_fails(self) -> None:
        process = FakeProcess()

        def api(request, **_kwargs):
            if request.get_method() == "PUT":
                raise OSError("connection failed")
            return FakeResponse(b'{"healthy":true,"version":"1.2.3"}')

        with TemporaryDirectory() as directory:
            runtime = OpenCodeRuntime(
                config=OpenCodeConfig(command="opencode-test"),
                model_config=ModelConfig(
                    "https://api.example.com/v1", "model-secret", "demo-model"
                ),
                process_factory=lambda *_args, **_kwargs: process,
                command_resolver=lambda _command: "C:/tools/opencode.exe",
                urlopen=api,
            )
            runtime.start(directory)

            health = runtime.health()

            self.assertFalse(health["healthy"])
            self.assertEqual(runtime.status()["error"], "CoreTest Agent model authentication failed")
            self.assertNotIn("model-secret", json.dumps(runtime.status()))
            runtime.stop()

    def test_prompt_creates_and_reuses_read_only_session(self) -> None:
        process = FakeProcess()
        requests = []
        health_attempts = 0

        def api(request, **_kwargs):
            nonlocal health_attempts
            requests.append(request)
            if request.full_url.endswith("/global/health"):
                health_attempts += 1
                if health_attempts == 1:
                    raise OSError("OpenCode is still starting")
                return FakeResponse(b'{"healthy":true,"version":"1.18.10"}')
            if request.full_url.endswith("/auth/coretest"):
                return FakeResponse(b"true")
            if request.full_url.endswith("/session"):
                return FakeResponse(b'{"id":"session-1"}')
            if request.full_url.endswith("/session/session-1/message"):
                return FakeResponse(
                    b'{"info":{"parentID":"message-1"},'
                    b'"parts":[{"type":"text","text":"workspace answer"}]}'
                )
            if "/session/session-1/message?directory=" in request.full_url:
                return FakeResponse(
                    json.dumps(
                        [
                            {
                                "parts": [
                                    {
                                        "id": "part-1",
                                        "type": "tool",
                                        "tool": "read",
                                        "state": {
                                            "status": "completed",
                                            "title": (
                                                runtime._workspace.as_posix().split(":/", 1)[-1]
                                                + "/sample.py"
                                            ),
                                            "output": "loaded",
                                        },
                                    }
                                ]
                            }
                        ]
                    ).encode("utf-8")
                )
            if "/permission?directory=" in request.full_url:
                return FakeResponse(json.dumps([{
                    "id": "per-1",
                    "sessionID": "session-1",
                    "permission": "bash",
                    "patterns": [
                        f"{runtime._workspace.as_posix()}/tests/test_sample.py",
                        "../outside.txt",
                        "python -m pytest",
                    ],
                }]).encode("utf-8"))
            if "/permission/per-1/reply?directory=" in request.full_url:
                return FakeResponse(b"true")
            if "/session/session-1/abort?directory=" in request.full_url:
                return FakeResponse(b"true")
            if "/session/session-1/diff?directory=" in request.full_url:
                return FakeResponse(
                    json.dumps(
                        [
                            {
                                "file": str(runtime._workspace / "src" / "sample.py"),
                                "patch": (
                                    f"--- {runtime._workspace / 'src' / 'sample.py'}\n"
                                    "+D:\\private\\secret.txt\n"
                                    "+print('ok')\n"
                                ),
                                "additions": 1,
                                "deletions": 0,
                                "status": "modified",
                            },
                            {
                                "file": str(Path(directory).parent / "secret.txt"),
                                "patch": "+secret\n",
                                "additions": 1,
                                "deletions": 0,
                                "status": "modified",
                            },
                        ]
                    ).encode("utf-8")
                )
            if "/session/session-1/revert?directory=" in request.full_url:
                return FakeResponse(b'{"id":"session-1"}')
            if request.get_method() == "DELETE":
                return FakeResponse(b"true")
            raise AssertionError(request.full_url)

        with TemporaryDirectory() as directory:
            runtime = OpenCodeRuntime(
                model_config=ModelConfig(
                    "https://api.example.com/v1", "secret", "demo-model"
                ),
                process_factory=lambda *_args, **_kwargs: process,
                command_resolver=lambda _command: "C:/tools/opencode.exe",
                urlopen=api,
            )
            runtime.start(directory)

            self.assertEqual(
                runtime.prompt(
                    "host-a", "inspect the project", system="read only", history=[]
                ),
                "workspace answer",
            )
            self.assertEqual(
                runtime.prompt(
                    "host-a",
                    "continue",
                    system="read only",
                    history=[{"role": "user", "content": "first"}],
                ),
                "workspace answer",
            )
            self.assertEqual(runtime.pending_permissions("host-a"), [])
            self.assertTrue(runtime.abort("host-a"))
            activity = runtime.activity("host-a")
            self.assertEqual(activity[0]["tool"], "read")
            self.assertEqual(activity[0]["title"], "./sample.py")
            self.assertNotIn(str(Path(directory).resolve()), json.dumps(activity))
            diff = runtime.diff("host-a")
            self.assertTrue(diff["revert_available"])
            self.assertIsNone(diff["revert_reason"])
            self.assertEqual(len(diff["files"]), 1)
            self.assertEqual(diff["files"][0]["path"], "src/sample.py")
            self.assertEqual(diff["files"][0]["additions"], 1)
            self.assertNotIn(str(Path(directory).resolve()), json.dumps(diff))
            self.assertNotIn("D:\\private", json.dumps(diff))
            self.assertTrue(runtime.revert("host-a"))
            self.assertEqual(
                runtime.diff("host-a"),
                {
                    "files": [],
                    "revert_available": False,
                    "revert_reason": "no_turn",
                },
            )
            self.assertEqual(
                runtime.prompt(
                    "host-a",
                    "fresh",
                    system="read only",
                    history=[],
                    new_session=True,
                ),
                "workspace answer",
            )
            runtime.release_session("host-a")
            runtime.stop()

        self.assertGreaterEqual(health_attempts, 2)

        session_creates = [
            request
            for request in requests
            if request.get_method() == "POST" and request.full_url.endswith("/session")
        ]
        self.assertEqual(len(session_creates), 2)
        session_body = json.loads(session_creates[0].data.decode("utf-8"))
        permissions = {
            item["permission"]: item["action"]
            for item in session_body["permission"]
        }
        self.assertEqual(permissions["read"], "allow")
        self.assertEqual(permissions["apply_patch"], "allow")
        self.assertEqual(permissions["edit"], "allow")
        self.assertEqual(permissions["bash"], "allow")
        self.assertEqual(permissions["write"], "allow")
        self.assertEqual(permissions["webfetch"], "deny")
        self.assertEqual(permissions["task"], "deny")
        self.assertEqual(permissions["external_directory"], "deny")
        prompts = [
            request
            for request in requests
            if request.full_url.endswith("/session/session-1/message")
        ]
        self.assertEqual(len(prompts), 3)
        prompt_body = json.loads(prompts[0].data.decode("utf-8"))
        self.assertEqual(
            prompt_body["model"],
            {"providerID": "coretest", "modelID": "demo-model"},
        )
        self.assertEqual(prompt_body["system"], "read only")
        self.assertEqual(prompt_body["parts"], [{"type": "text", "text": "inspect the project"}])
        self.assertNotIn("tools", prompt_body)

    def test_non_git_edit_is_reported_as_not_revertible(self) -> None:
        process = FakeProcess()
        requests = []
        write_completed = False

        def api(request, **_kwargs):
            requests.append(request)
            if request.full_url.endswith("/global/health"):
                return FakeResponse(b'{"healthy":true,"version":"1.18.10"}')
            if request.full_url.endswith("/auth/coretest"):
                return FakeResponse(b"true")
            if request.full_url.endswith("/session"):
                return FakeResponse(b'{"id":"session-1"}')
            if request.full_url.endswith("/session/session-1/message"):
                return FakeResponse(
                    b'{"info":{"parentID":"message-1"},'
                    b'"parts":[{"type":"text","text":"updated"}]}'
                )
            if "/session/session-1/diff?directory=" in request.full_url:
                return FakeResponse(b"[]")
            if "/session/session-1/message?directory=" in request.full_url:
                tool = "edit" if write_completed else "read"
                return FakeResponse(
                    json.dumps(
                        [
                            {
                                "info": {"parentID": "message-1"},
                                "parts": [
                                    {
                                        "id": "tool-1",
                                        "type": "tool",
                                        "tool": tool,
                                        "state": {
                                            "status": "completed",
                                            "title": "sample.py",
                                        },
                                    }
                                ],
                            }
                        ]
                    ).encode("utf-8")
                )
            if request.get_method() == "DELETE":
                return FakeResponse(b"true")
            raise AssertionError(request.full_url)

        with TemporaryDirectory() as directory:
            runtime = OpenCodeRuntime(
                model_config=ModelConfig(
                    "https://api.example.com/v1", "secret", "demo-model"
                ),
                process_factory=lambda *_args, **_kwargs: process,
                command_resolver=lambda _command: "C:/tools/opencode.exe",
                urlopen=api,
            )
            runtime.start(directory)
            runtime.prompt("host-a", "update sample.py", system="", history=[])

            self.assertEqual(
                runtime.diff("host-a"),
                {
                    "files": [],
                    "revert_available": False,
                    "revert_reason": "no_file_changes",
                },
            )
            write_completed = True
            self.assertEqual(
                runtime.diff("host-a"),
                {
                    "files": [],
                    "revert_available": False,
                    "revert_reason": "workspace_has_no_git_baseline",
                },
            )
            self.assertFalse(runtime.revert("host-a"))
            runtime.stop()

        self.assertFalse(
            any("/revert?" in request.full_url for request in requests),
            "unavailable revert must not call OpenCode",
        )

    def test_stream_prompt_subscribes_before_async_prompt_and_sanitizes_events(self) -> None:
        process = FakeProcess()
        requests = []

        with TemporaryDirectory() as directory:
            events = [
                {"type": "server.connected", "properties": {}},
                {
                    "type": "message.updated",
                    "properties": {
                        "sessionID": "session-1",
                        "info": {"role": "assistant", "parentID": "message-1"},
                    },
                },
                {
                    "type": "message.part.updated",
                    "properties": {
                        "sessionID": "session-1",
                        "part": {
                            "id": "reasoning-1",
                            "messageID": "assistant-1",
                            "type": "reasoning",
                            "text": "",
                        },
                    },
                },
                {
                    "type": "message.part.delta",
                    "properties": {
                        "sessionID": "session-1",
                        "messageID": "assistant-1",
                        "partID": "reasoning-1",
                        "field": "text",
                        "delta": "**检查工程**",
                    },
                },
                {
                    "type": "message.part.updated",
                    "properties": {
                        "sessionID": "session-1",
                        "part": {
                            "id": "step-1",
                            "messageID": "assistant-1",
                            "type": "step-start",
                        },
                    },
                },
                {
                    "type": "todo.updated",
                    "properties": {
                        "sessionID": "session-1",
                        "todos": [
                            {"content": "读取文件", "status": "completed", "priority": "high"},
                            {"content": "总结结果", "status": "in_progress", "priority": "medium"},
                        ],
                    },
                },
                {
                    "type": "message.part.updated",
                    "properties": {
                        "sessionID": "session-1",
                        "part": {
                            "id": "text-1",
                            "messageID": "assistant-1",
                            "type": "text",
                            "text": "",
                        },
                    },
                },
                {
                    "type": "message.part.delta",
                    "properties": {
                        "sessionID": "session-1",
                        "messageID": "assistant-1",
                        "partID": "text-1",
                        "delta": "hello",
                    },
                },
                {
                    "type": "message.part.updated",
                    "properties": {
                        "sessionID": "session-1",
                        "part": {
                            "id": "part-1",
                            "type": "tool",
                            "tool": "read",
                            "state": {
                                "status": "completed",
                                "title": "./sample.py",
                                "output": "loaded",
                            },
                        },
                    },
                },
                {
                    "type": "message.part.delta",
                    "properties": {
                        "sessionID": "session-1",
                        "messageID": "assistant-2",
                        "partID": "text-2",
                        "delta": "final answer",
                    },
                },
                {
                    "type": "permission.asked",
                    "properties": {
                        "id": "per-1",
                        "sessionID": "session-1",
                        "permission": "bash",
                        "patterns": ["python -m pytest"],
                    },
                },
                {"type": "session.idle", "properties": {"sessionID": "session-1"}},
            ]
            event_body = "".join(
                f"data: {json.dumps(event)}\n\n" for event in events
            ).encode("utf-8")

            def api(request, **_kwargs):
                requests.append(request)
                if request.full_url.endswith("/global/health"):
                    return FakeResponse(b'{"healthy":true,"version":"1.18.10"}')
                if request.full_url.endswith("/auth/coretest"):
                    return FakeResponse(b"true")
                if request.full_url.endswith("/session"):
                    return FakeResponse(b'{"id":"session-1"}')
                if "/event?directory=" in request.full_url:
                    return StreamingResponse(event_body)
                if "/prompt_async?directory=" in request.full_url:
                    return FakeResponse(b"")
                if "/permission?directory=" in request.full_url:
                    raise OSError("OpenCode cannot list an edit permission")
                if "/permission/per-1/reply?directory=" in request.full_url:
                    return FakeResponse(b"true")
                raise AssertionError(request.full_url)

            runtime = OpenCodeRuntime(
                model_config=ModelConfig(
                    "https://api.example.com/v1", "secret", "demo-model"
                ),
                process_factory=lambda *_args, **_kwargs: process,
                command_resolver=lambda _command: "C:/tools/opencode.exe",
                urlopen=api,
            )
            runtime.start(directory)

            streamed = list(
                runtime.stream_prompt(
                    "host-a", "inspect", system="read only", history=[]
                )
            )

            self.assertEqual(streamed[0], {"type": "started"})
            self.assertIn(
                {
                    "type": "reasoning_delta",
                    "delta": "**检查工程**",
                    "segment_id": "assistant-1:reasoning-1",
                },
                streamed,
            )
            self.assertIn(
                {"type": "step", "id": "step-1", "status": "running", "title": "开始执行"},
                streamed,
            )
            self.assertIn(
                {
                    "type": "todo",
                    "todos": [
                        {"content": "读取文件", "status": "completed", "priority": "high"},
                        {"content": "总结结果", "status": "in_progress", "priority": "medium"},
                    ],
                },
                streamed,
            )
            self.assertIn(
                {
                    "type": "text_delta",
                    "delta": "hello",
                    "segment_id": "assistant-1:text-1",
                },
                streamed,
            )
            self.assertIn(
                {
                    "type": "text_delta",
                    "delta": "\n\nfinal answer",
                    "segment_id": "assistant-2:text-2",
                },
                streamed,
            )
            tool = next(event for event in streamed if event["type"] == "tool")
            self.assertEqual(tool["title"], "./sample.py")
            self.assertNotIn(str(Path(directory).resolve()), json.dumps(streamed))
            self.assertFalse(any(event["type"] == "permission" for event in streamed))
            self.assertEqual(
                streamed[-1],
                {"type": "completed", "answer": "hello\n\nfinal answer"},
            )
            self.assertEqual(runtime.pending_permissions("host-a"), [])
            permission_reply = next(
                request
                for request in requests
                if "/permission/per-1/reply?directory=" in request.full_url
            )
            self.assertEqual(
                json.loads(permission_reply.data.decode("utf-8")),
                {"reply": "reject"},
            )
            runtime.stop()

        urls = [request.full_url for request in requests]
        event_index = next(index for index, url in enumerate(urls) if "/event?" in url)
        prompt_index = next(index for index, url in enumerate(urls) if "/prompt_async?" in url)
        self.assertLess(event_index, prompt_index)
        stream_request = requests[prompt_index]
        stream_body = json.loads(stream_request.data.decode("utf-8"))
        self.assertEqual(
            stream_body["model"],
            {"providerID": "coretest", "modelID": "demo-model"},
        )

    def test_stream_disconnect_aborts_and_releases_bad_session(self) -> None:
        process = FakeProcess()
        requests = []

        with TemporaryDirectory() as directory:
            def api(request, **_kwargs):
                requests.append(request)
                if request.full_url.endswith("/global/health"):
                    return FakeResponse(b'{"healthy":true,"version":"1.18.10"}')
                if request.full_url.endswith("/auth/coretest"):
                    return FakeResponse(b"true")
                if request.full_url.endswith("/session") and request.get_method() == "POST":
                    return FakeResponse(b'{"id":"session-1"}')
                if "/event?directory=" in request.full_url:
                    return StreamingResponse(
                        b'data: {"type":"server.connected","properties":{}}\n\n'
                    )
                if "/prompt_async?directory=" in request.full_url:
                    return FakeResponse(b"")
                if "/abort?directory=" in request.full_url:
                    return FakeResponse(b"true")
                if request.full_url.endswith("/session/session-1"):
                    return FakeResponse(b"true")
                raise AssertionError(request.full_url)

            runtime = OpenCodeRuntime(
                model_config=ModelConfig(
                    "https://api.example.com/v1", "secret", "demo-model"
                ),
                process_factory=lambda *_args, **_kwargs: process,
                command_resolver=lambda _command: "C:/tools/opencode.exe",
                urlopen=api,
            )
            runtime.start(directory)

            with self.assertRaisesRegex(RuntimeError, "disconnected"):
                list(runtime.stream_prompt("host-a", "inspect", system="system", history=[]))

            self.assertIsNone(runtime._session_id("host-a"))

        urls = [request.full_url for request in requests]
        self.assertTrue(any("/abort?directory=" in url for url in urls))
        self.assertTrue(any(url.endswith("/session/session-1") for url in urls))

    def test_closing_stream_after_started_aborts_and_releases_session(self) -> None:
        process = FakeProcess()
        requests = []

        with TemporaryDirectory() as directory:
            def api(request, **_kwargs):
                requests.append(request)
                if request.full_url.endswith("/global/health"):
                    return FakeResponse(b'{"healthy":true,"version":"1.18.10"}')
                if request.full_url.endswith("/auth/coretest"):
                    return FakeResponse(b"true")
                if request.full_url.endswith("/session") and request.get_method() == "POST":
                    return FakeResponse(b'{"id":"session-1"}')
                if "/event?directory=" in request.full_url:
                    return StreamingResponse(b"")
                if "/prompt_async?directory=" in request.full_url:
                    return FakeResponse(b"")
                if "/abort?directory=" in request.full_url:
                    return FakeResponse(b"true")
                if request.full_url.endswith("/session/session-1"):
                    return FakeResponse(b"true")
                raise AssertionError(request.full_url)

            runtime = OpenCodeRuntime(
                model_config=ModelConfig(
                    "https://api.example.com/v1", "secret", "demo-model"
                ),
                process_factory=lambda *_args, **_kwargs: process,
                command_resolver=lambda _command: "C:/tools/opencode.exe",
                urlopen=api,
            )
            runtime.start(directory)
            stream = runtime.stream_prompt(
                "host-a", "inspect", system="system", history=[]
            )

            self.assertEqual(next(stream), {"type": "started"})
            stream.close()

            self.assertIsNone(runtime._session_id("host-a"))

        urls = [request.full_url for request in requests]
        self.assertTrue(any("/abort?directory=" in url for url in urls))
        self.assertTrue(any(url.endswith("/session/session-1") for url in urls))

    def test_stalled_stream_aborts_and_releases_bad_session(self) -> None:
        process = FakeProcess()
        requests = []

        with TemporaryDirectory() as directory:
            def api(request, **_kwargs):
                requests.append(request)
                if request.full_url.endswith("/global/health"):
                    return FakeResponse(b'{"healthy":true,"version":"1.18.10"}')
                if request.full_url.endswith("/auth/coretest"):
                    return FakeResponse(b"true")
                if request.full_url.endswith("/session") and request.get_method() == "POST":
                    return FakeResponse(b'{"id":"session-1"}')
                if "/event?directory=" in request.full_url:
                    return StalledStreamingResponse(b"")
                if "/prompt_async?directory=" in request.full_url:
                    return FakeResponse(b"")
                if "/abort?directory=" in request.full_url:
                    return FakeResponse(b"true")
                if request.full_url.endswith("/session/session-1"):
                    return FakeResponse(b"true")
                raise AssertionError(request.full_url)

            runtime = OpenCodeRuntime(
                model_config=ModelConfig(
                    "https://api.example.com/v1", "secret", "demo-model"
                ),
                process_factory=lambda *_args, **_kwargs: process,
                command_resolver=lambda _command: "C:/tools/opencode.exe",
                urlopen=api,
            )
            runtime.start(directory)

            with self.assertRaisesRegex(RuntimeError, "no progress"):
                list(runtime.stream_prompt("host-a", "inspect", system="system", history=[]))

            self.assertIsNone(runtime._session_id("host-a"))

        self.assertTrue(any("/abort?directory=" in item.full_url for item in requests))


if __name__ == "__main__":
    unittest.main()
