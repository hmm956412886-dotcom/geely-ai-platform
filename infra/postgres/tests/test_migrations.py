from pathlib import Path
import re
import unittest


MIGRATION = (
    Path(__file__).parents[1]
    / "migrations"
    / "001_init_knowledge_sync.sql"
)


class MigrationShapeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.sql = MIGRATION.read_text(encoding="utf-8").lower()

    def test_defines_first_phase_tables(self) -> None:
        for table in (
            "source_documents",
            "knowledge_sections",
            "source_acl_entries",
            "sync_jobs",
        ):
            with self.subTest(table=table):
                self.assertIn(f"create table if not exists {table}", self.sql)

    def test_acl_filter_index_exists(self) -> None:
        self.assertIn("ix_source_acl_principal", self.sql)
        self.assertIn("principal_type, principal_id, permission", self.sql)

    def test_sections_cascade_with_document(self) -> None:
        pattern = re.compile(
            r"document_id text not null references source_documents"
            r" \(document_id\) on delete cascade"
        )
        self.assertRegex(self.sql, pattern)

    def test_jobs_keep_history_when_document_is_deleted(self) -> None:
        self.assertIn(
            "document_id text references source_documents (document_id) on delete set null",
            self.sql,
        )


if __name__ == "__main__":
    unittest.main()

