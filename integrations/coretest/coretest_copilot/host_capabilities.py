"""Bounded read-only queries over CoreTest's existing parsed project services."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Iterable

from .snapshots import (
    SUPPORTED_TEXT_SUFFIXES,
    dbc_snapshot,
    diagnostic_snapshot,
    pdx_snapshot,
    project_snapshot,
    text_file_snapshot,
    trace_snapshot,
)


CAPABILITIES: list[dict[str, Any]] = [
    {
        "name": "project.summary",
        "description": "Return the active CoreTest project and its registered files.",
        "input_schema": {"type": "object", "additionalProperties": False},
    },
    {
        "name": "file.inspect",
        "description": "Parse one UTF-8 text, DBC, configuration, log, or PDX file inside the active project.",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
            "additionalProperties": False,
        },
    },
    {
        "name": "dbc.list",
        "description": "List DBC files already registered by CoreTest and their load state.",
        "input_schema": {"type": "object", "additionalProperties": False},
    },
    {
        "name": "dbc.inspect",
        "description": "Query CoreTest's parsed DBC cache by file, optional node, and optional frame ID.",
        "input_schema": {
            "type": "object",
            "properties": {
                "dbc_name": {"type": "string"},
                "node_name": {"type": "string"},
                "frame_id": {"type": ["integer", "string"]},
            },
            "required": ["dbc_name"],
            "additionalProperties": False,
        },
    },
    {
        "name": "trace.list",
        "description": "List Trace files already registered by CoreTest and their load state.",
        "input_schema": {"type": "object", "additionalProperties": False},
    },
    {
        "name": "trace.inspect",
        "description": "Summarize frames already parsed into CoreTest's Trace cache.",
        "input_schema": {
            "type": "object",
            "properties": {"filename": {"type": "string"}},
            "required": ["filename"],
            "additionalProperties": False,
        },
    },
    {
        "name": "diagnostic.recent",
        "description": "Return bounded recent diagnostic request and response facts observed by CoreTest.",
        "input_schema": {"type": "object", "additionalProperties": False},
    },
]


class CoreTestReadOnlyCapabilities:
    def __init__(
        self,
        *,
        next_revision: Callable[[], str],
        diagnostic_state: Callable[[], tuple[str, str, Iterable[dict[str, Any]]]],
    ) -> None:
        self._next_revision = next_revision
        self._diagnostic_state = diagnostic_state

    def invoke(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        allowed = next(
            item["input_schema"] for item in CAPABILITIES if item["name"] == name
        )
        unknown = set(arguments) - set(allowed.get("properties", {}))
        if unknown:
            raise ValueError(f"unsupported capability arguments: {', '.join(sorted(unknown))}")
        handlers = {
            "project.summary": self._project_summary,
            "file.inspect": self._file_inspect,
            "dbc.list": self._dbc_list,
            "dbc.inspect": self._dbc_inspect,
            "trace.list": self._trace_list,
            "trace.inspect": self._trace_inspect,
            "diagnostic.recent": self._diagnostic_recent,
        }
        return handlers[name](arguments)

    def _project_summary(self, _arguments: dict[str, Any]) -> dict[str, Any]:
        from app.service import project_file_service, project_runtime_service

        return project_snapshot(
            project_runtime_service.get_active_project(),
            project_file_service.get_all_fileinfos(),
            self._next_revision(),
        )

    def _file_inspect(self, arguments: dict[str, Any]) -> dict[str, Any]:
        path = self._project_path(_required_text(arguments, "path"))
        if path.suffix.lower() == ".pdx":
            return pdx_snapshot(path, self._next_revision())
        if path.suffix.lower() not in SUPPORTED_TEXT_SUFFIXES:
            raise ValueError("file type is not available through the read-only host bridge")
        return text_file_snapshot(path, self._next_revision())

    def _dbc_list(self, _arguments: dict[str, Any]) -> dict[str, Any]:
        from app.service import project_dbc_service

        return {
            "kind": "dbc-list",
            "revision": self._next_revision(),
            "data": {
                "files": [
                    {
                        "name": name,
                        "loaded": bool(project_dbc_service.is_file_loaded(name)),
                        "loading": bool(project_dbc_service.is_file_loading(name)),
                    }
                    for name in project_dbc_service.list_filenames()
                ]
            },
        }

    def _dbc_inspect(self, arguments: dict[str, Any]) -> dict[str, Any]:
        from app.service import project_dbc_service

        frame_id = arguments.get("frame_id")
        if isinstance(frame_id, str):
            try:
                frame_id = int(frame_id, 0)
            except ValueError as exc:
                raise ValueError("frame_id must be an integer or 0x-prefixed value") from exc
        if frame_id is not None and not isinstance(frame_id, int):
            raise ValueError("frame_id must be an integer or 0x-prefixed value")
        return dbc_snapshot(
            project_dbc_service,
            self._next_revision(),
            dbc_name=_required_text(arguments, "dbc_name"),
            node_name=_optional_text(arguments, "node_name"),
            frame_id=frame_id,
        )

    def _trace_list(self, _arguments: dict[str, Any]) -> dict[str, Any]:
        from app.service import project_trace_service

        return {
            "kind": "trace-list",
            "revision": self._next_revision(),
            "data": {
                "files": [
                    {
                        "name": name,
                        "loaded": bool(project_trace_service.is_file_loaded(name)),
                        "loading": bool(project_trace_service.is_file_loading(name)),
                    }
                    for name in project_trace_service.list_filenames()
                ]
            },
        }

    def _trace_inspect(self, arguments: dict[str, Any]) -> dict[str, Any]:
        from app.service import project_trace_service

        filename = _required_text(arguments, "filename")
        if filename not in project_trace_service.list_filenames():
            raise ValueError("Trace file is not registered in the active CoreTest project")
        return trace_snapshot(
            project_trace_service.get_all_trace_frames(filename),
            self._next_revision(),
            filename=filename,
        )

    def _diagnostic_recent(self, _arguments: dict[str, Any]) -> dict[str, Any]:
        pdx_name, ecu, logs = self._diagnostic_state()
        return diagnostic_snapshot(
            self._next_revision(), pdx_name=pdx_name, ecu=ecu, logs=logs
        )

    @staticmethod
    def _project_path(relative: str) -> Path:
        from app.service import project_runtime_service

        project = project_runtime_service.get_active_project()
        if project is None or not getattr(project, "url", None):
            raise ValueError("CoreTest has no active project")
        candidate = Path(relative)
        if candidate.is_absolute():
            raise ValueError("file path must be relative to the active project")
        root = Path(project.url).resolve()
        resolved = (root / candidate).resolve()
        try:
            resolved.relative_to(root)
        except ValueError as exc:
            raise ValueError("file path must stay inside the active project") from exc
        if not resolved.is_file():
            raise ValueError("file does not exist in the active project")
        return resolved


def _required_text(arguments: dict[str, Any], name: str) -> str:
    value = arguments.get(name)
    if not isinstance(value, str) or not value.strip() or len(value) > 500:
        raise ValueError(f"{name} is required")
    return value.strip()


def _optional_text(arguments: dict[str, Any], name: str) -> str:
    value = arguments.get(name, "")
    if not isinstance(value, str) or len(value) > 500:
        raise ValueError(f"{name} is invalid")
    return value.strip()
