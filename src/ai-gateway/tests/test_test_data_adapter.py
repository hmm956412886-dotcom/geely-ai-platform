from pathlib import Path
import unittest

from ai_gateway.test_data_adapter import compare_test_runs, load_test_data_insights, load_test_run_summary


FIXTURES = Path(__file__).parent / "fixtures"


class TestDataAdapterTests(unittest.TestCase):
    def test_load_json_cases_as_summary(self) -> None:
        summary = load_test_run_summary(str(FIXTURES / "test-run-cases.json"))

        self.assertEqual(summary["run_id"], "RUN_JSON_001")
        self.assertEqual(summary["source"]["type"], "json")
        self.assertEqual(summary["total_cases"], 3)
        self.assertEqual(summary["passed_cases"], 2)
        self.assertEqual(summary["failed_cases"], 1)
        self.assertEqual(summary["metrics"]["pass_rate"], 0.6667)
        self.assertEqual(summary["failures"][0]["case_id"], "TC_001")

    def test_load_csv_cases_as_summary(self) -> None:
        summary = load_test_run_summary(str(FIXTURES / "test-run-cases.csv"))

        self.assertEqual(summary["run_id"], "RUN_CSV_001")
        self.assertEqual(summary["source"]["type"], "csv")
        self.assertEqual(summary["total_cases"], 3)
        self.assertEqual(summary["passed_cases"], 1)
        self.assertEqual(summary["failed_cases"], 1)
        self.assertEqual(summary["metrics"]["warning_cases"], 1)
        self.assertEqual(summary["status"], "failed")

    def test_reject_unsupported_file_type(self) -> None:
        with self.assertRaisesRegex(ValueError, "unsupported"):
            load_test_run_summary(str(FIXTURES / "test-run-cases.txt"))

    def test_compare_test_runs(self) -> None:
        result = compare_test_runs(
            str(FIXTURES / "test-run-cases.csv"),
            str(FIXTURES / "test-run-cases-target.csv"),
        )

        self.assertEqual(result["baseline_run_id"], "RUN_CSV_001")
        self.assertEqual(result["target_run_id"], "RUN_CSV_002")
        self.assertIn("失败用例增加 1 个", result["summary"])
        self.assertEqual(result["changed_metrics"][2]["name"], "failed_cases")
        self.assertEqual(result["changed_metrics"][2]["delta"], 1)

    def test_load_test_data_insights(self) -> None:
        result = load_test_data_insights(str(FIXTURES / "test-run-cases.csv"))

        self.assertIn(result["engine"], {"duckdb", "stdlib"})
        self.assertEqual(result["run_id"], "RUN_CSV_001")
        self.assertEqual(result["total_cases"], 3)
        self.assertEqual(result["failed_cases"], 1)
        self.assertEqual(result["warning_cases"], 1)
        self.assertEqual(result["pass_rate"], 0.3333)
        self.assertEqual(result["failure_reasons"][0]["reason"], "扭矩误差超过阈值")


if __name__ == "__main__":
    unittest.main()
