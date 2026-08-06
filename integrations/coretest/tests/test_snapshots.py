from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch
import unittest

from coretest_copilot.snapshots import (
    diagnostic_snapshot,
    pdx_snapshot,
    project_snapshot,
    text_file_snapshot,
    trace_snapshot,
)


@dataclass
class Item:
    name: str = "P"
    filename: str = "trace.asc"
    fileformat: str = "ASC"
    filesize: int = 12
    tasks: set = field(default_factory=set)
    frame_id: int = 0x123
    timestamp: float = 1.0
    direction: str = "RX"
    channel: str = "0"
    is_error: bool = False
    payload: bytes = b"\x01\x02"


class SnapshotTests(unittest.TestCase):
    def test_project_does_not_expose_absolute_paths(self) -> None:
        payload = project_snapshot(Item(), [Item()], "1")
        self.assertEqual(payload["data"]["files"][0]["category"], "trace")
        self.assertNotIn("filepath", payload["data"]["files"][0])

    def test_trace_is_bounded_and_summarized(self) -> None:
        frames = [Item(timestamp=float(index)) for index in range(10020)]
        payload = trace_snapshot(frames, "2", selected=frames[-1])
        self.assertEqual(payload["data"]["total_frames"], 10000)
        self.assertEqual(payload["selection"]["frame_id"], "0x123")
        self.assertEqual(payload["selection"]["payload_hex"], "01 02")

    def test_text_file_snapshot_contains_bounded_utf8_content(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "calculator.py"
            path.write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")

            payload = text_file_snapshot(path, "3")

        self.assertEqual(payload["kind"], "file")
        self.assertEqual(payload["selection"]["filename"], "calculator.py")
        self.assertIn("def add", payload["data"]["content"])
        self.assertEqual(payload["data"]["line_count"], 2)

    def test_diagnostic_counts_negative_responses(self) -> None:
        payload = diagnostic_snapshot(
            "3",
            ecu="VCU",
            logs=[
                {"type": "response", "is_positive": False, "nrc": "0x22"},
                {"type": "response", "is_positive": True, "nrc": None},
            ],
        )
        self.assertEqual(payload["data"]["negative_response_count"], 1)
        self.assertEqual(payload["data"]["nrc_counts"][0]["nrc"], "0x22")

    @patch("coretest_copilot.snapshots._load_pdx_file")
    def test_pdx_uses_odxtools_and_exposes_bounded_diagnostic_summary(self, load_pdx) -> None:
        ecu = SimpleNamespace(
            short_name="vehicle_ecu",
            variant_type="ECU-VARIANT",
            description="Vehicle control unit",
            services=[SimpleNamespace(short_name=f"service_{index}") for index in range(80)],
            get_can_receive_id=lambda: 0x700,
            get_can_send_id=lambda: 0x708,
        )
        load_pdx.return_value = SimpleNamespace(
            ecus=[ecu],
            diag_layers=[ecu, SimpleNamespace(short_name="protocol")],
        )

        payload = pdx_snapshot(Path("vehicle.pdx"), "4")

        load_pdx.assert_called_once_with(Path("vehicle.pdx"))
        self.assertEqual(payload["kind"], "pdx")
        self.assertEqual(payload["selection"]["pdx_name"], "vehicle.pdx")
        self.assertEqual(payload["data"]["ecu_count"], 1)
        self.assertEqual(payload["data"]["ecus"][0]["can_request_id"], "0x700")
        self.assertEqual(payload["data"]["ecus"][0]["service_count"], 80)
        self.assertEqual(len(payload["data"]["ecus"][0]["services"]), 50)


if __name__ == "__main__":
    unittest.main()
