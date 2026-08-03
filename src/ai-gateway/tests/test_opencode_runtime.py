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
    find_opencode_command,
    load_opencode_config,
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

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self) -> bytes:
        return self.body


class StreamingResponse(FakeResponse):
    def read(self, size=-1) -> bytes:
        chunk, self.body = self.body[:size], self.body[size:]
        return chunk


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
            self.assertEqual(provider["permission"]["apply_patch"], "deny")
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
                                            "title": str(Path(directory) / "sample.py"),
                                            "output": "loaded",
                                        },
                                    }
                                ]
                            }
                        ]
                    ).encode("utf-8")
                )
            if "/permission?directory=" in request.full_url:
                return FakeResponse(
                    b'[{"id":"per-1","sessionID":"session-1",'
                    b'"permission":"bash","patterns":["python -m pytest"]}]'
                )
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
                        "resources": ["python -m pytest"],
                    }
                ],
            )
            runtime.reply_permission("host-a", "per-1", "once")
            self.assertTrue(runtime.abort("host-a"))
            activity = runtime.activity("host-a")
            self.assertEqual(activity[0]["tool"], "read")
            self.assertEqual(activity[0]["title"], ".\\sample.py")
            self.assertNotIn(str(Path(directory).resolve()), json.dumps(activity))
            diff = runtime.diff("host-a")
            self.assertEqual(len(diff), 1)
            self.assertEqual(diff[0]["path"], "src/sample.py")
            self.assertEqual(diff[0]["additions"], 1)
            self.assertNotIn(str(Path(directory).resolve()), json.dumps(diff))
            self.assertNotIn("D:\\private", json.dumps(diff))
            self.assertTrue(runtime.revert("host-a"))
            self.assertEqual(runtime.diff("host-a"), [])
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
        self.assertEqual(permissions["edit"], "ask")
        self.assertEqual(permissions["bash"], "ask")
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
        self.assertNotIn("bash", prompt_body["tools"])
        self.assertNotIn("edit", prompt_body["tools"])
        self.assertFalse(prompt_body["tools"]["apply_patch"])
        self.assertFalse(prompt_body["tools"]["write"])
        self.assertTrue(prompt_body["tools"]["read"])


if __name__ == "__main__":
    unittest.main()
