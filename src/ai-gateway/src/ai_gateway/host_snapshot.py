"""Bounded, session-isolated facts captured from a trusted desktop host."""

from __future__ import annotations

import json
import os
from threading import Lock
from typing import Any

from .host_context import get_host_context, normalize_host_session_id


DEFAULT_MAX_SNAPSHOT_BYTES = 1024 * 1024
ALLOWED_KINDS = {"project", "trace", "dbc", "diagnostic", "pdx"}
ALLOWED_FIELDS = {"kind", "revision", "captured_at", "selection", "data"}

_snapshots: dict[str, dict[str, Any]] = {}
_lock = Lock()


def update_host_snapshot(
    payload: dict[str, Any], host_session_id: str | None = None
) -> dict[str, Any]:
    unknown = set(payload) - ALLOWED_FIELDS
    if unknown:
        raise ValueError(f"unsupported host snapshot fields: {', '.join(sorted(unknown))}")
    kind = str(payload.get("kind") or "").strip().lower()
    if kind not in ALLOWED_KINDS:
        raise ValueError(f"unsupported host snapshot kind: {kind or 'empty'}")
    revision = str(payload.get("revision") or "").strip()
    if not revision or len(revision) > 80:
        raise ValueError("snapshot revision is required and must be at most 80 characters")
    data = payload.get("data")
    if not isinstance(data, dict):
        raise ValueError("snapshot data must be a JSON object")
    selection = payload.get("selection")
    if selection is not None and not isinstance(selection, dict):
        raise ValueError("snapshot selection must be a JSON object")

    snapshot = {
        "kind": kind,
        "revision": revision,
        "captured_at": _optional_text(payload.get("captured_at")),
        "selection": selection or {},
        "data": data,
    }
    try:
        encoded = json.dumps(snapshot, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError("snapshot must contain JSON-compatible values") from exc
    if len(encoded) > _positive_env("AI_GATEWAY_MAX_HOST_SNAPSHOT_BYTES", DEFAULT_MAX_SNAPSHOT_BYTES):
        raise ValueError("host snapshot exceeds the configured size limit")

    session_id = normalize_host_session_id(host_session_id)
    get_host_context(session_id)
    with _lock:
        _snapshots[session_id] = snapshot
    return {"host_session_id": session_id, **snapshot, "size_bytes": len(encoded)}


def get_host_snapshot(host_session_id: str | None = None) -> dict[str, Any]:
    session_id = normalize_host_session_id(host_session_id)
    with _lock:
        snapshot = _snapshots.get(session_id)
        return {"host_session_id": session_id, **snapshot} if snapshot else {
            "host_session_id": session_id,
            "kind": None,
            "revision": None,
            "captured_at": None,
            "selection": {},
            "data": {},
        }


def analyze_host_snapshot(
    question: str, host_session_id: str | None = None
) -> dict[str, Any]:
    snapshot = get_host_snapshot(host_session_id)
    kind = snapshot["kind"]
    if kind is None:
        raise ValueError("the host has not published a current snapshot")
    data = snapshot["data"]
    answer = {
        "trace": _trace_answer,
        "dbc": _dbc_answer,
        "diagnostic": _diagnostic_answer,
        "project": _project_answer,
        "pdx": _pdx_answer,
    }[kind](data, snapshot["selection"])
    return {
        "answer": answer,
        "question": question.strip(),
        "snapshot": snapshot,
        "warnings": [],
        "citations": [],
    }


def release_host_snapshot(host_session_id: str | None) -> bool:
    session_id = normalize_host_session_id(host_session_id)
    with _lock:
        return _snapshots.pop(session_id, None) is not None


def reset_host_snapshots() -> None:
    with _lock:
        _snapshots.clear()


def _trace_answer(data: dict[str, Any], selection: dict[str, Any]) -> str:
    total = _integer(data.get("total_frames"))
    errors = _integer(data.get("error_frames"))
    duration = _number(data.get("duration_seconds"))
    top_ids = _format_counts(data.get("top_frame_ids"), "frame_id")
    selected = selection.get("frame_id")
    detail = f" 当前选中帧为 {selected}。" if selected else ""
    return (
        f"当前 Trace 共 {total} 帧，覆盖 {duration:.3f} 秒，检测到 {errors} 个错误帧。"
        f" 高频 Frame ID：{top_ids or '暂无'}。{detail}"
        "建议优先检查错误帧、异常高频报文以及与 DBC 周期定义不一致的帧。"
    )


def _dbc_answer(data: dict[str, Any], selection: dict[str, Any]) -> str:
    dbc = str(data.get("dbc_name") or "当前 DBC")
    frame = selection.get("frame_name") or data.get("frame_name")
    signals = data.get("signals") if isinstance(data.get("signals"), list) else []
    signal_names = "、".join(str(item.get("name")) for item in signals[:8] if isinstance(item, dict))
    if frame:
        return (
            f"{dbc} 当前帧 {frame} 包含 {len(signals)} 个信号：{signal_names or '暂无信号'}。"
            "排查时应核对发送节点、周期、字节序、缩放、单位和有效范围。"
        )
    return f"{dbc} 当前包含 {_integer(data.get('node_count'))} 个节点和 {_integer(data.get('frame_count'))} 个帧。"


def _diagnostic_answer(data: dict[str, Any], selection: dict[str, Any]) -> str:
    responses = _integer(data.get("response_count"))
    negatives = _integer(data.get("negative_response_count"))
    nrcs = _format_counts(data.get("nrc_counts"), "nrc")
    ecu = selection.get("ecu") or data.get("ecu") or "当前 ECU"
    return (
        f"{ecu} 已记录 {responses} 个诊断响应，其中 {negatives} 个负响应。"
        f" NRC 分布：{nrcs or '无'}。建议从最近一个负响应对应的服务、会话状态和安全访问条件开始排查。"
    )


def _project_answer(data: dict[str, Any], selection: dict[str, Any]) -> str:
    files = data.get("files") if isinstance(data.get("files"), list) else []
    categories: dict[str, int] = {}
    for item in files:
        if isinstance(item, dict):
            category = str(item.get("category") or "other")
            categories[category] = categories.get(category, 0) + 1
    counts = "、".join(f"{name} {count} 个" for name, count in sorted(categories.items()))
    return f"当前项目包含 {len(files)} 个受支持文件（{counts or '暂无文件'}），可选择 DBC、Trace 或诊断页面继续分析。"


def _pdx_answer(data: dict[str, Any], selection: dict[str, Any]) -> str:
    name = str(selection.get("pdx_name") or data.get("filename") or "当前 PDX")
    if error := data.get("parse_error"):
        return f"{name} 已被选中，但解析失败：{error}"
    ecus = data.get("ecus") if isinstance(data.get("ecus"), list) else []
    ecu_names = "、".join(
        str(ecu.get("name")) for ecu in ecus[:10] if isinstance(ecu, dict) and ecu.get("name")
    )
    services = sum(_integer(ecu.get("service_count")) for ecu in ecus if isinstance(ecu, dict))
    return (
        f"{name} 已完成解析，包含 {_integer(data.get('ecu_count'))} 个 ECU 变体、"
        f"{_integer(data.get('diagnostic_layer_count'))} 个诊断层和 {services} 个 ECU 服务。"
        f"ECU：{ecu_names or '未识别'}。可继续询问具体服务、CAN 地址和测试关注点。"
    )


def _format_counts(value: Any, label_key: str) -> str:
    if not isinstance(value, list):
        return ""
    parts = []
    for item in value[:8]:
        if isinstance(item, dict):
            label = item.get(label_key)
            count = item.get("count")
            if label is not None and count is not None:
                parts.append(f"{label}（{_integer(count)} 帧）")
    return "、".join(parts)


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _integer(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _number(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _positive_env(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError as exc:
        raise ValueError(f"{name} must be a positive integer") from exc
    if value < 1:
        raise ValueError(f"{name} must be a positive integer")
    return value
