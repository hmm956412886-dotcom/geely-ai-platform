import json
from pathlib import Path
import unittest

from feishu_sync.normalize import normalize_snapshot
from feishu_sync.repository import save_normalized_document


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "docx_snapshot.json"


class FakeCursor:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[object, ...]]] = []

    def __enter__(self) -> "FakeCursor":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        return None

    def execute(self, sql: str, params: tuple[object, ...] = ()) -> None:
        self.calls.append((" ".join(sql.split()).lower(), params))


class FakeConnection:
    def __init__(self) -> None:
        self.cursor_instance = FakeCursor()
        self.commits = 0
        self.rollbacks = 0

    def cursor(self) -> FakeCursor:
        return self.cursor_instance

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1


class FailingCursor(FakeCursor):
    def execute(self, sql: str, params: tuple[object, ...] = ()) -> None:
        super().execute(sql, params)
        if "delete from knowledge_sections" in " ".join(sql.split()).lower():
            raise RuntimeError("database failed")


class FailingConnection(FakeConnection):
    def __init__(self) -> None:
        super().__init__()
        self.cursor_instance = FailingCursor()


class RepositoryTests(unittest.TestCase):
    def setUp(self) -> None:
        snapshot = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
        self.document = normalize_snapshot(snapshot)

    def test_saves_document_snapshot_and_creates_index_job(self) -> None:
        connection = FakeConnection()

        job_id = save_normalized_document(connection, self.document)

        calls = connection.cursor_instance.calls
        self.assertTrue(job_id)
        self.assertEqual(connection.commits, 1)
        self.assertEqual(connection.rollbacks, 0)
        self.assertEqual(len(calls), 8)
        self.assertIn("insert into source_documents", calls[0][0])
        self.assertIn("delete from knowledge_sections", calls[1][0])
        self.assertIn("insert into knowledge_sections", calls[2][0])
        self.assertIn("insert into knowledge_sections", calls[3][0])
        self.assertIn("delete from source_acl_entries", calls[4][0])
        self.assertIn("insert into source_acl_entries", calls[5][0])
        self.assertIn("insert into source_acl_entries", calls[6][0])
        self.assertIn("insert into sync_jobs", calls[-1][0])

    def test_document_upsert_uses_normalized_metadata(self) -> None:
        connection = FakeConnection()

        save_normalized_document(connection, self.document)

        params = connection.cursor_instance.calls[0][1]
        self.assertEqual(params[0], "doxcn-test-001")
        self.assertEqual(params[1], "feishu_docx")
        self.assertEqual(params[3], "wikcn-test-001")
        self.assertEqual(params[9], "normalized")

    def test_section_ids_are_namespaced_by_document_id(self) -> None:
        connection = FakeConnection()

        save_normalized_document(connection, self.document)

        first_section_params = connection.cursor_instance.calls[2][1]
        self.assertEqual(first_section_params[0], "doxcn-test-001:section-1")
        self.assertEqual(first_section_params[1], "doxcn-test-001")
        self.assertEqual(first_section_params[2], 1)
        self.assertEqual(first_section_params[3], ["第三章 通过标准"])
        self.assertEqual(len(first_section_params[5]), 64)

    def test_rolls_back_when_any_statement_fails(self) -> None:
        connection = FailingConnection()

        with self.assertRaisesRegex(RuntimeError, "database failed"):
            save_normalized_document(connection, self.document)

        self.assertEqual(connection.commits, 0)
        self.assertEqual(connection.rollbacks, 1)


if __name__ == "__main__":
    unittest.main()
