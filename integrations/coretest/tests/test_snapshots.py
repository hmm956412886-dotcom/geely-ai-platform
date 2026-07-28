from __future__ import annotations

from dataclasses import dataclass, field
import unittest

from coretest_copilot.snapshots import diagnostic_snapshot, project_snapshot, trace_snapshot


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


if __name__ == "__main__":
    unittest.main()
