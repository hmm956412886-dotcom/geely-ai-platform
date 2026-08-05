from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from types import ModuleType, SimpleNamespace
import sys
import unittest
from unittest.mock import patch

from coretest_copilot.host_capabilities import CoreTestReadOnlyCapabilities


class HostCapabilityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.revision = 0
        self.capabilities = CoreTestReadOnlyCapabilities(
            next_revision=self._revision,
            diagnostic_state=lambda: ("vehicle.pdx", "ECU1", [{"type": "info"}]),
        )

    def _revision(self) -> str:
        self.revision += 1
        return str(self.revision)

    def test_project_summary_reuses_active_project_services(self) -> None:
        project = SimpleNamespace(name="demo", url="D:/demo", tasks=set())
        files = [SimpleNamespace(filename="vehicle.dbc", fileformat="DBC", filesize=12)]
        services = _services(
            project_runtime_service=SimpleNamespace(get_active_project=lambda: project),
            project_file_service=SimpleNamespace(get_all_fileinfos=lambda: files),
        )

        with patch.dict(sys.modules, {"app.service": services}):
            result = self.capabilities.invoke("project.summary", {})

        self.assertEqual(result["data"]["name"], "demo")
        self.assertEqual(result["data"]["files"][0]["category"], "dbc")

    def test_file_inspect_is_confined_to_active_project(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "sample.c"
            source.write_text("int main(void) { return 0; }\n", encoding="utf-8")
            services = _services(
                project_runtime_service=SimpleNamespace(
                    get_active_project=lambda: SimpleNamespace(url=root)
                )
            )
            with patch.dict(sys.modules, {"app.service": services}):
                result = self.capabilities.invoke("file.inspect", {"path": "sample.c"})
                with self.assertRaisesRegex(ValueError, "inside the active project"):
                    self.capabilities.invoke("file.inspect", {"path": "../outside.c"})

        self.assertEqual(result["data"]["line_count"], 1)
        self.assertNotIn(str(root), str(result))

    def test_dbc_and_trace_queries_use_parsed_service_caches(self) -> None:
        frame = SimpleNamespace(
            frame_id=0x100,
            frame_name="Status",
            sender="ECU1",
            receivers={"ECU2"},
            cycle_time=10,
            get_signals=lambda: [],
            channel="CAN1",
            direction="RX",
            timestamp=1.0,
            is_error=False,
        )
        dbc = SimpleNamespace(
            list_filenames=lambda: ["vehicle.dbc"],
            is_file_loaded=lambda _name: True,
            is_file_loading=lambda _name: False,
            get_dbc_frames_by_node=lambda _dbc, _node: [frame],
            get_dbc_frames_by_file=lambda _dbc: [frame],
            get_dbc_frame_by_file_and_id=lambda _dbc, _id: frame,
            get_dbc_nodes_by_file=lambda _dbc: [SimpleNamespace(name="ECU1")],
        )
        trace = SimpleNamespace(
            list_filenames=lambda: ["capture.asc"],
            is_file_loaded=lambda _name: True,
            is_file_loading=lambda _name: False,
            get_all_trace_frames=lambda _name: [frame],
        )
        services = _services(project_dbc_service=dbc, project_trace_service=trace)

        with patch.dict(sys.modules, {"app.service": services}):
            dbc_result = self.capabilities.invoke(
                "dbc.inspect", {"dbc_name": "vehicle.dbc", "frame_id": "0x100"}
            )
            trace_result = self.capabilities.invoke(
                "trace.inspect", {"filename": "capture.asc"}
            )

        self.assertEqual(dbc_result["selection"]["frame_id"], "0x100")
        self.assertEqual(trace_result["data"]["total_frames"], 1)


def _services(**values: object) -> ModuleType:
    module = ModuleType("app.service")
    for name, value in values.items():
        setattr(module, name, value)
    return module


if __name__ == "__main__":
    unittest.main()
