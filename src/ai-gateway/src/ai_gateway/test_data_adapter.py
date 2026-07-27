"""Read exported test data files into the TestRunSummary contract."""

from __future__ import annotations

import csv
import importlib.util
import json
from pathlib import Path
from typing import Any


SUPPORTED_SUFFIXES = {".json", ".csv"}
MAX_FILE_BYTES = 20 * 1024 * 1024


def load_test_run_summary(source_file: str) -> dict[str, Any]:
    path = _validate_source_file(source_file)
    if path.suffix.lower() == ".json":
        return _summary_from_json(path)
    if path.suffix.lower() == ".csv":
        return _summary_from_rows(_read_csv(path), source_type="csv", source_ref=str(path))
    raise ValueError(f"unsupported test data file: {path.suffix}")


def compare_test_runs(baseline_file: str, target_file: str) -> dict[str, Any]:
    baseline = load_test_run_summary(baseline_file)
    target = load_test_run_summary(target_file)
    changed_metrics = [
        _metric_delta("total_cases", baseline["total_cases"], target["total_cases"]),
        _metric_delta("passed_cases", baseline["passed_cases"], target["passed_cases"]),
        _metric_delta("failed_cases", baseline["failed_cases"], target["failed_cases"]),
        _metric_delta("pass_rate", baseline["metrics"].get("pass_rate"), target["metrics"].get("pass_rate")),
    ]
    return {
        "baseline_run_id": baseline["run_id"],
        "target_run_id": target["run_id"],
        "summary": _compare_summary(baseline, target),
        "changed_metrics": changed_metrics,
        "baseline": baseline,
        "target": target,
    }


def load_test_data_insights(source_file: str) -> dict[str, Any]:
    path = _validate_source_file(source_file)
    if path.suffix.lower() == ".csv" and importlib.util.find_spec("duckdb"):
        return _duckdb_csv_insights(path)
    return _stdlib_insights(load_test_run_summary(str(path)))


def _validate_source_file(source_file: str) -> Path:
    if not source_file or not source_file.strip():
        raise ValueError("source_file is required")
    path = Path(source_file).expanduser()
    if not path.exists():
        raise ValueError(f"source_file does not exist: {source_file}")
    if not path.is_file():
        raise ValueError(f"source_file is not a file: {source_file}")
    if path.suffix.lower() not in SUPPORTED_SUFFIXES:
        raise ValueError(f"unsupported source_file type: {path.suffix}")
    if path.stat().st_size > MAX_FILE_BYTES:
        raise ValueError("source_file is too large for MVP parser")
    return path


def _duckdb_csv_insights(path: Path) -> dict[str, Any]:
    import duckdb

    source = str(path)
    with duckdb.connect(database=":memory:") as connection:
        row = connection.execute(
            """
            select
              any_value(run_id) as run_id,
              any_value(project_id) as project_id,
              count(*) as total_cases,
              sum(case when lower(trim(status)) in ('pass', 'passed', 'ok', 'success', 'succeeded') then 1 else 0 end) as passed_cases,
              sum(case when lower(trim(status)) in ('fail', 'failed', 'error', 'failed_case') then 1 else 0 end) as failed_cases,
              sum(case when lower(trim(status)) in ('warn', 'warning') then 1 else 0 end) as warning_cases
            from read_csv_auto(?)
            """,
            [source],
        ).fetchone()
        status_rows = connection.execute(
            """
            select
              case
                when lower(trim(status)) in ('pass', 'passed', 'ok', 'success', 'succeeded') then 'passed'
                when lower(trim(status)) in ('fail', 'failed', 'error', 'failed_case') then 'failed'
                when lower(trim(status)) in ('warn', 'warning') then 'warning'
                else 'unknown'
              end as status,
              count(*) as count
            from read_csv_auto(?)
            group by 1
            order by count desc, status
            """,
            [source],
        ).fetchall()
        reason_rows = connection.execute(
            """
            select coalesce(nullif(trim(reason), ''), 'unknown') as reason, count(*) as count
            from read_csv_auto(?)
            where lower(trim(status)) in ('fail', 'failed', 'error', 'failed_case')
            group by 1
            order by count desc, reason
            limit 5
            """,
            [source],
        ).fetchall()

    run_id, project_id, total_cases, passed_cases, failed_cases, warning_cases = row
    return _insights_payload(
        engine="duckdb",
        source_type="csv",
        source_ref=source,
        run_id=run_id or path.stem,
        project_id=project_id,
        total_cases=total_cases,
        passed_cases=passed_cases,
        failed_cases=failed_cases,
        warning_cases=warning_cases,
        status_counts=status_rows,
        failure_reasons=reason_rows,
    )


def _stdlib_insights(summary: dict[str, Any]) -> dict[str, Any]:
    status_counts = [
        ("failed", summary["failed_cases"]),
        ("passed", summary["passed_cases"]),
        ("warning", summary["metrics"].get("warning_cases", 0)),
    ]
    reasons: dict[str, int] = {}
    for failure in summary["failures"]:
        reason = failure.get("reason") or "unknown"
        reasons[reason] = reasons.get(reason, 0) + 1
    return _insights_payload(
        engine="stdlib",
        source_type=summary["source"]["type"],
        source_ref=summary["source"]["ref"],
        run_id=summary["run_id"],
        project_id=summary.get("project_id"),
        total_cases=summary["total_cases"],
        passed_cases=summary["passed_cases"],
        failed_cases=summary["failed_cases"],
        warning_cases=summary["metrics"].get("warning_cases", 0),
        status_counts=[item for item in status_counts if item[1]],
        failure_reasons=sorted(reasons.items(), key=lambda item: (-item[1], item[0]))[:5],
    )


def _insights_payload(
    *,
    engine: str,
    source_type: str,
    source_ref: str,
    run_id: Any,
    project_id: Any,
    total_cases: Any,
    passed_cases: Any,
    failed_cases: Any,
    warning_cases: Any,
    status_counts: list[tuple[Any, Any]],
    failure_reasons: list[tuple[Any, Any]],
) -> dict[str, Any]:
    total = int(total_cases or 0)
    passed = int(passed_cases or 0)
    failed = int(failed_cases or 0)
    warnings = int(warning_cases or 0)
    return {
        "run_id": str(run_id),
        "project_id": project_id,
        "source": {"type": source_type, "ref": source_ref},
        "engine": engine,
        "total_cases": total,
        "passed_cases": passed,
        "failed_cases": failed,
        "warning_cases": warnings,
        "pass_rate": round(passed / total, 4) if total else 0,
        "status_counts": [{"status": str(status), "count": int(count or 0)} for status, count in status_counts],
        "failure_reasons": [{"reason": str(reason), "count": int(count or 0)} for reason, count in failure_reasons],
    }


def _summary_from_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as file:
        payload = json.load(file)
    if isinstance(payload, dict) and _looks_like_summary(payload):
        summary = dict(payload)
        summary["source"] = {"type": "json", "ref": str(path)}
        return _normalize_summary(summary)
    if isinstance(payload, dict):
        rows = payload.get("cases")
        if not isinstance(rows, list):
            raise ValueError("JSON test data must contain a cases array or TestRunSummary fields")
        return _summary_from_rows(rows, source_type="json", source_ref=str(path), defaults=payload)
    if isinstance(payload, list):
        return _summary_from_rows(payload, source_type="json", source_ref=str(path))
    raise ValueError("JSON test data must be an object or array")


def _read_csv(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def _summary_from_rows(
    rows: list[Any],
    *,
    source_type: str,
    source_ref: str,
    defaults: dict[str, Any] | None = None,
) -> dict[str, Any]:
    defaults = defaults or {}
    cases = [_normalize_case(row) for row in rows if isinstance(row, dict)]
    total_cases = len(cases)
    passed_cases = sum(1 for case in cases if case["status"] == "passed")
    failed_cases = sum(1 for case in cases if case["status"] == "failed")
    warning_cases = sum(1 for case in cases if case["status"] == "warning")
    status = _overall_status(total_cases, failed_cases, warning_cases)
    return {
        "run_id": str(defaults.get("run_id") or _first_value(cases, "run_id") or Path(source_ref).stem),
        "source": {"type": source_type, "ref": source_ref},
        "project_id": defaults.get("project_id") or _first_value(cases, "project_id"),
        "status": status,
        "started_at": defaults.get("started_at"),
        "finished_at": defaults.get("finished_at"),
        "total_cases": total_cases,
        "passed_cases": passed_cases,
        "failed_cases": failed_cases,
        "metrics": {
            "pass_rate": round(passed_cases / total_cases, 4) if total_cases else 0,
            "warning_cases": warning_cases,
        },
        "failures": [
            {"case_id": case["case_id"], "name": case["name"], "reason": case.get("reason")}
            for case in cases
            if case["status"] == "failed"
        ],
    }


def _looks_like_summary(payload: dict[str, Any]) -> bool:
    return {"run_id", "total_cases", "passed_cases", "failed_cases"}.issubset(payload)


def _normalize_summary(summary: dict[str, Any]) -> dict[str, Any]:
    total_cases = int(summary.get("total_cases") or 0)
    passed_cases = int(summary.get("passed_cases") or 0)
    failed_cases = int(summary.get("failed_cases") or 0)
    metrics = dict(summary.get("metrics") or {})
    metrics.setdefault("pass_rate", round(passed_cases / total_cases, 4) if total_cases else 0)
    summary["total_cases"] = total_cases
    summary["passed_cases"] = passed_cases
    summary["failed_cases"] = failed_cases
    summary["metrics"] = metrics
    summary.setdefault("status", "failed" if failed_cases else "passed")
    summary.setdefault("failures", [])
    return summary


def _normalize_case(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "run_id": _string_or_none(row.get("run_id")),
        "project_id": _string_or_none(row.get("project_id")),
        "case_id": str(row.get("case_id") or row.get("id") or ""),
        "name": str(row.get("name") or row.get("case_name") or row.get("case_id") or "unknown"),
        "status": _normalize_status(row.get("status") or row.get("result")),
        "reason": _string_or_none(row.get("reason") or row.get("message") or row.get("error")),
    }


def _normalize_status(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {"pass", "passed", "ok", "success", "succeeded"}:
        return "passed"
    if normalized in {"fail", "failed", "error", "failed_case"}:
        return "failed"
    if normalized in {"warn", "warning"}:
        return "warning"
    return "unknown"


def _overall_status(total_cases: int, failed_cases: int, warning_cases: int) -> str:
    if failed_cases:
        return "failed"
    if warning_cases:
        return "warning"
    if total_cases:
        return "passed"
    return "unknown"


def _first_value(rows: list[dict[str, Any]], key: str) -> str | None:
    for row in rows:
        value = row.get(key)
        if value:
            return str(value)
    return None


def _string_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _metric_delta(name: str, baseline: Any, target: Any) -> dict[str, Any]:
    delta = None
    if isinstance(baseline, (int, float)) and isinstance(target, (int, float)):
        delta = round(target - baseline, 4)
    return {"name": name, "baseline": baseline, "target": target, "delta": delta}


def _compare_summary(baseline: dict[str, Any], target: dict[str, Any]) -> str:
    failed_delta = target["failed_cases"] - baseline["failed_cases"]
    pass_rate_delta = round(target["metrics"].get("pass_rate", 0) - baseline["metrics"].get("pass_rate", 0), 4)
    if failed_delta > 0:
        direction = f"失败用例增加 {failed_delta} 个"
    elif failed_delta < 0:
        direction = f"失败用例减少 {abs(failed_delta)} 个"
    else:
        direction = "失败用例数量持平"
    return f"{direction}，通过率变化 {pass_rate_delta:+.2%}。"
