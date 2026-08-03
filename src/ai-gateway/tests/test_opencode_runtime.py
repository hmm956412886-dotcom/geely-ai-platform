import json
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from ai_gateway.model_client import ModelConfig
from ai_gateway.opencode_runtime import (
    OpenCodeConfig,
    OpenCodeRuntime,
    _install_opencode,
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


class FakeOpenCodeApi:
    def __init__(self) -> None:
        self.requests = []

    def __call__(self, request, **_kwargs):
        self.requests.append(request)
        if request.get_method() == "PUT":
            return FakeResponse(b"true")
        return FakeResponse(b'{"healthy":true,"version":"1.2.3"}')


class OpenCodeRuntimeTests(unittest.TestCase):
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

        with self.assertRaisesRegex(ValueError, "127.0.0.1"):
            load_opencode_config({"OPENCODE_HOST": "0.0.0.0"})

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

    def test_start_uses_workspace_and_secret_free_provider_file(self) -> None:
        calls = []
        process = FakeProcess()

        def start_process(args, **kwargs):
            calls.append((args, kwargs))
            return process

        with TemporaryDirectory() as directory:
            api = FakeOpenCodeApi()
            runtime = OpenCodeRuntime(
                config=OpenCodeConfig(command="opencode-test", port=4901),
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
                status = runtime.start(Path(directory))
            runtime.start(Path(directory))
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
            self.assertEqual(kwargs["cwd"], str(Path(directory).resolve()))
            self.assertEqual(kwargs["env"]["OPENCODE_SERVER_PASSWORD"], "runtime-secret")
            for name in ("DATA", "CONFIG", "CACHE", "STATE"):
                self.assertTrue(
                    kwargs["env"][f"XDG_{name}_HOME"].startswith(
                        str(config_path.parent)
                    )
                )
            self.assertNotIn("CORETEST_OPENCODE_MODEL_API_KEY", kwargs["env"])
            self.assertNotIn("AI_GATEWAY_HOST_TOKEN", kwargs["env"])
            self.assertNotIn("UNRELATED_PRIVATE_VALUE", kwargs["env"])
            self.assertNotIn("model-secret", config_text)
            self.assertNotIn("apiKey", provider["provider"]["coretest"]["options"])
            self.assertEqual(provider["model"], "coretest/demo-model")
            self.assertEqual(provider["permission"]["edit"], "ask")
            self.assertEqual(provider["permission"]["apply_patch"], "allow")
            self.assertEqual(provider["permission"]["write"], "deny")
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
            self.assertFalse(config_path.exists())

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
            self.assertEqual(runtime.status()["error"], "OpenCode model authentication failed")
            self.assertNotIn("model-secret", json.dumps(runtime.status()))

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
                                                Path(directory).resolve().as_posix().split(":/", 1)[-1]
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
                        f"{Path(directory).resolve().as_posix()}/tests/test_sample.py",
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
                                "file": str(Path(directory) / "src" / "sample.py"),
                                "patch": (
                                    f"--- {Path(directory) / 'src' / 'sample.py'}\n"
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
            self.assertEqual(
                runtime.pending_permissions("host-a"),
                [
                    {
                        "id": "per-1",
                        "permission": "bash",
                        "resources": [
                            "tests/test_sample.py",
                            "[工作区外路径已隐藏]",
                            "python -m pytest",
                        ],
                    }
                ],
            )
            runtime.reply_permission("host-a", "per-1", "once")
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
        self.assertEqual(permissions["edit"], "ask")
        self.assertEqual(permissions["bash"], "ask")
        self.assertEqual(permissions["write"], "deny")
        self.assertEqual(permissions["task"], "deny")
        self.assertEqual(permissions["external_directory"], "deny")
        prompts = [
            request
            for request in requests
            if request.full_url.endswith("/session/session-1/message")
        ]
        self.assertEqual(len(prompts), 3)
        prompt_body = json.loads(prompts[0].data.decode("utf-8"))
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
                    "type": "message.part.delta",
                    "properties": {"sessionID": "session-1", "delta": "hello"},
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
                                "title": str(Path(directory) / "sample.py"),
                                "output": "loaded",
                            },
                        },
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
            self.assertIn({"type": "text_delta", "delta": "hello"}, streamed)
            tool = next(event for event in streamed if event["type"] == "tool")
            self.assertEqual(tool["title"], "./sample.py")
            self.assertNotIn(str(Path(directory).resolve()), json.dumps(streamed))
            permission = next(event for event in streamed if event["type"] == "permission")
            self.assertEqual(permission["permission"]["id"], "per-1")
            self.assertEqual(streamed[-1], {"type": "completed", "answer": "hello"})
            self.assertEqual(runtime.pending_permissions("host-a"), [permission["permission"]])
            runtime.reply_permission("host-a", "per-1", "once")
            self.assertEqual(runtime.pending_permissions("host-a"), [])

        urls = [request.full_url for request in requests]
        event_index = next(index for index, url in enumerate(urls) if "/event?" in url)
        prompt_index = next(index for index, url in enumerate(urls) if "/prompt_async?" in url)
        self.assertLess(event_index, prompt_index)


if __name__ == "__main__":
    unittest.main()
