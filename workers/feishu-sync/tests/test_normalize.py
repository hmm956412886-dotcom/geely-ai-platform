import json
from pathlib import Path
import unittest

from feishu_sync.normalize import normalize_snapshot


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "docx_snapshot.json"


class NormalizeSnapshotTests(unittest.TestCase):
    def setUp(self) -> None:
        self.snapshot = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))

    def test_normalizes_docx_and_preserves_source_metadata(self) -> None:
        document = normalize_snapshot(self.snapshot)

        self.assertEqual(document["document_id"], "doxcn-test-001")
        self.assertEqual(document["source_type"], "feishu_docx")
        self.assertEqual(document["node_token"], "wikcn-test-001")
        self.assertEqual(document["source_url"], self.snapshot["source_url"])
        self.assertTrue(document["content_hash"])

    def test_builds_heading_paths_for_content_sections(self) -> None:
        document = normalize_snapshot(self.snapshot)

        self.assertEqual(
            document["sections"],
            [
                {
                    "section_id": "section-1",
                    "heading_path": ["第三章 通过标准"],
                    "content": "电机扭矩误差应小于 5%。",
                    "page_no": None,
                    "block_id": "blk-2",
                },
                {
                    "section_id": "section-2",
                    "heading_path": ["第三章 通过标准", "环境条件"],
                    "content": "环境温度应保持在 23 +/- 5 摄氏度。",
                    "page_no": None,
                    "block_id": "blk-4",
                },
            ],
        )

    def test_acl_is_sorted_for_stable_output(self) -> None:
        document = normalize_snapshot(self.snapshot)

        self.assertEqual(
            document["acl"],
            [
                {
                    "principal_type": "department",
                    "principal_id": "dept-test",
                    "permission": "read",
                },
                {
                    "principal_type": "user",
                    "principal_id": "ou_test_user",
                    "permission": "read",
                },
            ],
        )

    def test_content_hash_ignores_acl_and_updated_at(self) -> None:
        first = normalize_snapshot(self.snapshot)
        changed_metadata = dict(self.snapshot)
        changed_metadata["updated_at"] = "2026-07-25T08:00:00Z"
        changed_metadata["acl"] = []

        second = normalize_snapshot(changed_metadata)

        self.assertEqual(first["content_hash"], second["content_hash"])

    def test_rejects_unknown_object_type(self) -> None:
        snapshot = dict(self.snapshot)
        snapshot["obj_type"] = "unknown"

        with self.assertRaisesRegex(ValueError, "Unsupported Feishu object type"):
            normalize_snapshot(snapshot)

    def test_rejects_missing_required_fields(self) -> None:
        snapshot = dict(self.snapshot)
        del snapshot["source_url"]

        with self.assertRaisesRegex(ValueError, "source_url"):
            normalize_snapshot(snapshot)


if __name__ == "__main__":
    unittest.main()

