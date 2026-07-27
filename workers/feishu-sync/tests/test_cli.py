import io
import json
from pathlib import Path
import tempfile
import unittest

from feishu_sync.cli import main


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


class FakeProvider:
    def __init__(self) -> None:
        self.search_calls: list[tuple[str, int]] = []
        self.fetch_calls: list[str] = []

    def search(self, query: str, *, limit: int) -> list[object]:
        from feishu_sync.provider import KnowledgeHit

        self.search_calls.append((query, limit))
        return [
            KnowledgeHit(
                document_ref="doxcn-001",
                title="测试规范",
                source_url="https://example.feishu.cn/docx/doxcn-001",
                snippet="通过标准",
                source_type="feishu_docx",
            )
        ]

    def fetch(self, document_ref: str) -> dict[str, object]:
        self.fetch_calls.append(document_ref)
        return {
            "document_id": document_ref,
            "source_type": "feishu_docx",
            "title": "测试规范",
            "sections": [],
        }


class CliTests(unittest.TestCase):
    def test_ingest_snapshot_dry_run_prints_normalized_json(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()

        exit_code = main(
            [
                "ingest-snapshot",
                "--input",
                str(FIXTURE_PATH),
                "--dry-run",
            ],
            stdout=stdout,
            stderr=stderr,
        )

        document = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(stderr.getvalue(), "")
        self.assertEqual(document["source_type"], "feishu_docx")
        self.assertEqual(document["document_id"], "doxcn-test-001")

    def test_ingest_snapshot_dry_run_writes_output_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "normalized.json"

            exit_code = main(
                [
                    "ingest-snapshot",
                    "--input",
                    str(FIXTURE_PATH),
                    "--output",
                    str(output_path),
                    "--dry-run",
                ]
            )

            document = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(exit_code, 0)
            self.assertEqual(document["title"], "动力系统测试规范")

    def test_ingest_snapshot_without_database_url_refuses_to_persist(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()

        exit_code = main(
            [
                "ingest-snapshot",
                "--input",
                str(FIXTURE_PATH),
            ],
            stdout=stdout,
            stderr=stderr,
        )

        self.assertEqual(exit_code, 2)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("DATABASE_URL is required", stderr.getvalue())

    def test_ingest_snapshot_persists_when_database_url_is_set(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()
        connection = FakeConnection()

        exit_code = main(
            [
                "ingest-snapshot",
                "--input",
                str(FIXTURE_PATH),
                "--database-url",
                "postgresql://user:pass@localhost:5432/geely_ai",
            ],
            stdout=stdout,
            stderr=stderr,
            connect_database=lambda settings: connection,
        )

        result = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(stderr.getvalue(), "")
        self.assertEqual(result["document_id"], "doxcn-test-001")
        self.assertEqual(result["sync_status"], "normalized")
        self.assertTrue(result["index_job_id"])
        self.assertEqual(connection.commits, 1)

    def test_output_file_does_not_skip_persistence(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()
        connection = FakeConnection()
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "normalized.json"

            exit_code = main(
                [
                    "ingest-snapshot",
                    "--input",
                    str(FIXTURE_PATH),
                    "--output",
                    str(output_path),
                    "--database-url",
                    "postgresql://user:pass@localhost:5432/geely_ai",
                ],
                stdout=stdout,
                stderr=stderr,
                connect_database=lambda settings: connection,
            )

            self.assertEqual(exit_code, 0)
            self.assertTrue(output_path.exists())
            self.assertEqual(connection.commits, 1)

    def test_search_feishu_uses_provider(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()
        provider = FakeProvider()

        exit_code = main(
            [
                "search-feishu",
                "--query",
                "动力系统",
                "--limit",
                "3",
            ],
            stdout=stdout,
            stderr=stderr,
            provider=provider,
        )

        result = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(stderr.getvalue(), "")
        self.assertEqual(provider.search_calls, [("动力系统", 3)])
        self.assertEqual(result[0]["document_ref"], "doxcn-001")

    def test_fetch_feishu_uses_provider(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()
        provider = FakeProvider()

        exit_code = main(
            [
                "fetch-feishu",
                "--doc",
                "doxcn-001",
            ],
            stdout=stdout,
            stderr=stderr,
            provider=provider,
        )

        result = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(stderr.getvalue(), "")
        self.assertEqual(provider.fetch_calls, ["doxcn-001"])
        self.assertEqual(result["document_id"], "doxcn-001")


if __name__ == "__main__":
    unittest.main()
