from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from ai_gateway.workspace import (
    get_workspace_path,
    get_workspace_status,
    register_workspace,
    release_workspace,
    reset_workspaces,
)


class WorkspaceTests(unittest.TestCase):
    def tearDown(self) -> None:
        reset_workspaces()

    def test_register_keeps_absolute_path_private(self) -> None:
        with TemporaryDirectory() as directory:
            result = register_workspace(
                {"project_root": directory}, "workspace-session"
            )

            self.assertTrue(result["registered"])
            self.assertEqual(result["workspace_name"], Path(directory).name)
            self.assertNotIn("project_root", result)
            self.assertEqual(
                get_workspace_path("workspace-session"), Path(directory).resolve()
            )
            self.assertNotIn(
                str(Path(directory).resolve()),
                str(get_workspace_status("workspace-session")),
            )

    def test_register_rejects_unknown_fields_and_missing_directory(self) -> None:
        with self.assertRaisesRegex(ValueError, "unsupported"):
            register_workspace({"project_root": "D:/missing", "extra": True}, "session")
        with self.assertRaisesRegex(ValueError, "existing directory"):
            register_workspace({"project_root": "D:/missing"}, "session")

    def test_release_removes_only_requested_session(self) -> None:
        with TemporaryDirectory() as directory:
            register_workspace({"project_root": directory}, "first")
            register_workspace({"project_root": directory}, "second")

            self.assertTrue(release_workspace("first"))
            self.assertFalse(get_workspace_status("first")["registered"])
            self.assertTrue(get_workspace_status("second")["registered"])

    def test_gateway_rejects_a_second_workspace_root(self) -> None:
        with TemporaryDirectory() as first, TemporaryDirectory() as second:
            register_workspace({"project_root": first}, "first")

            with self.assertRaisesRegex(ValueError, "another workspace"):
                register_workspace({"project_root": second}, "second")


if __name__ == "__main__":
    unittest.main()
