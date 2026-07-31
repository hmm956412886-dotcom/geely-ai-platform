"""Bounded JSON snapshots built from CoreTest's already-parsed objects."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any, Iterable


MAX_TEXT_FILE_BYTES = 256 * 1024
SUPPORTED_TEXT_SUFFIXES = {
    ".py", ".json", ".yaml", ".yml", ".xml", ".txt", ".dbc", ".md",
    ".toml", ".ini", ".cfg", ".csv", ".log", ".asc",
}


def project_snapshot(project: Any, files: Iterable[Any], revision: str) -> dict[str, Any]:
    items = [
        {
            "name": str(getattr(item, "filename", "")),
            "category": _category(str(getattr(item, "fileformat", ""))),
            "size_bytes": int(getattr(item, "filesize", 0) or 0),
        }
        for item in list(files)[:200]
    ]
    return {
        "kind": "project",
        "revision": revision,
        "selection": {},
        "data": {
            "name": str(getattr(project, "name", "未选择项目")),
            "running_tasks": sorted(
                str(getattr(task, "value", task)) for task in getattr(project, "tasks", set())
            ),
            "files": items,
        },
    }


def trace_snapshot(
    frames: Iterable[Any], revision: str, *, filename: str = "", selected: Any = None
) -> dict[str, Any]:
    records = list(frames)[-10000:]
    frame_counts = Counter(_frame_id(frame) for frame in records)
    channels = Counter(str(getattr(frame, "channel", "")) for frame in records)
    directions = Counter(str(getattr(frame, "direction", "")) for frame in records)
    timestamps = [
        float(value)
        for frame in records
        if (value := getattr(frame, "timestamp", None)) is not None
    ]
    selection = _frame(selected) if selected is not None else {}
    return {
        "kind": "trace",
        "revision": revision,
        "selection": selection,
        "data": {
            "filename": Path(filename).name if filename else "实时 CAN Trace",
            "total_frames": len(records),
            "duration_seconds": max(timestamps) - min(timestamps) if timestamps else 0,
            "error_frames": sum(bool(getattr(frame, "is_error", False)) for frame in records),
            "top_frame_ids": [
                {"frame_id": key, "count": count} for key, count in frame_counts.most_common(12)
            ],
            "channels": [{"channel": key, "count": count} for key, count in channels.most_common()],
            "directions": [
                {"direction": key, "count": count} for key, count in directions.most_common()
            ],
        },
    }


def dbc_snapshot(
    service: Any,
    revision: str,
    *,
    dbc_name: str,
    node_name: str = "",
    frame_id: int | None = None,
) -> dict[str, Any]:
    frames = (
        service.get_dbc_frames_by_node(dbc_name, node_name)
        if node_name
        else service.get_dbc_frames_by_file(dbc_name)
    )
    frame = service.get_dbc_frame_by_file_and_id(dbc_name, frame_id) if frame_id is not None else None
    signals = []
    if frame is not None:
        signals = [
            {
                "name": str(getattr(signal, "name", "")),
                "start_bit": int(getattr(signal, "start", 0) or 0),
                "length": int(getattr(signal, "length", 0) or 0),
                "scale": getattr(signal, "scale", 0),
                "offset": getattr(signal, "offset", 0),
                "unit": str(getattr(signal, "unit", "")),
                "minimum": getattr(signal, "minimum", None),
                "maximum": getattr(signal, "maximum", None),
                "byte_order": "big" if getattr(signal, "is_big_byte_order", False) else "little",
                "comment": str(getattr(signal, "comment", ""))[:500],
            }
            for signal in frame.get_signals()[:100]
        ]
    selection = {"dbc_name": dbc_name}
    if node_name:
        selection["node_name"] = node_name
    if frame is not None:
        selection.update({"frame_id": _frame_id(frame), "frame_name": str(frame.frame_name)})
    return {
        "kind": "dbc",
        "revision": revision,
        "selection": selection,
        "data": {
            "dbc_name": dbc_name,
            "node_count": len(service.get_dbc_nodes_by_file(dbc_name)),
            "frame_count": len(frames),
            "frame_name": str(getattr(frame, "frame_name", "")),
            "sender": str(getattr(frame, "sender", "")),
            "receivers": sorted(str(value) for value in getattr(frame, "receivers", set())),
            "cycle_time_ms": getattr(frame, "cycle_time", None),
            "signals": signals,
        },
    }


def diagnostic_snapshot(
    revision: str, *, ecu: str, pdx_name: str = "", logs: Iterable[dict[str, Any]] = ()
) -> dict[str, Any]:
    entries = list(logs)[-100:]
    responses = [entry for entry in entries if entry.get("type") == "response"]
    negatives = [entry for entry in responses if not entry.get("is_positive", False)]
    nrcs = Counter(entry.get("nrc") for entry in negatives if entry.get("nrc"))
    return {
        "kind": "diagnostic",
        "revision": revision,
        "selection": {"ecu": ecu, "pdx_name": pdx_name},
        "data": {
            "ecu": ecu,
            "response_count": len(responses),
            "negative_response_count": len(negatives),
            "nrc_counts": [{"nrc": key, "count": count} for key, count in nrcs.most_common()],
            "recent_logs": entries,
        },
    }


def pdx_snapshot(path: Path, revision: str) -> dict[str, Any]:
    database = _load_pdx_file(path)
    ecus = []
    for ecu in list(database.ecus)[:20]:
        services = [str(service.short_name) for service in list(ecu.services)]
        ecus.append(
            {
                "name": str(ecu.short_name),
                "variant_type": str(ecu.variant_type),
                "description": str(ecu.description or "")[:1000],
                "can_request_id": _hex_call(ecu.get_can_receive_id),
                "can_response_id": _hex_call(ecu.get_can_send_id),
                "service_count": len(services),
                "services": services[:50],
            }
        )
    layers = [str(layer.short_name) for layer in list(database.diag_layers)]
    return {
        "kind": "pdx",
        "revision": revision,
        "selection": {"pdx_name": path.name},
        "data": {
            "filename": path.name,
            "ecu_count": len(database.ecus),
            "diagnostic_layer_count": len(layers),
            "diagnostic_layers": layers[:50],
            "ecus": ecus,
        },
    }


def text_file_snapshot(path: Path, revision: str) -> dict[str, Any]:
    if path.suffix.lower() not in SUPPORTED_TEXT_SUFFIXES:
        raise ValueError(f"不支持的文本文件类型：{path.suffix or '无扩展名'}")
    with path.open("rb") as source:
        raw = source.read(MAX_TEXT_FILE_BYTES + 1)
    if len(raw) > MAX_TEXT_FILE_BYTES:
        raise ValueError("文件超过 256 KiB，无法作为 Copilot 上下文")
    try:
        content = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("文件不是 UTF-8 文本") from exc
    return {
        "kind": "file",
        "revision": revision,
        "selection": {"filename": path.name},
        "data": {
            "filename": path.name,
            "suffix": path.suffix.lower(),
            "size_bytes": len(raw),
            "line_count": len(content.splitlines()),
            "content": content,
        },
    }


def _frame(frame: Any) -> dict[str, Any]:
    return {
        "frame_id": _frame_id(frame),
        "frame_name": str(getattr(frame, "frame_name", "")),
        "direction": str(getattr(frame, "direction", "")),
        "channel": str(getattr(frame, "channel", "")),
        "payload_hex": bytes(getattr(frame, "payload", b"") or b"").hex(" ").upper(),
        "timestamp": getattr(frame, "timestamp", None),
    }


def _hex_call(call: Any) -> str | None:
    try:
        value = call()
    except (AttributeError, KeyError, TypeError, ValueError):
        return None
    return f"0x{value:X}" if isinstance(value, int) else None


def _load_pdx_file(path: Path) -> Any:
    import odxtools

    return odxtools.load_pdx_file(str(path))


def _frame_id(frame: Any) -> str:
    value = getattr(frame, "frame_id", None)
    return f"0x{value:X}" if isinstance(value, int) else str(value or "unknown")


def _category(fileformat: str) -> str:
    suffix = fileformat.lower().lstrip(".")
    if suffix in {"asc", "blf"}:
        return "trace"
    return suffix or "other"
