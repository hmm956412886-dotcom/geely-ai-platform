"""Command line entry points for the Feishu sync worker."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys
from typing import Any, Callable, Sequence, TextIO

from .database import DatabaseConfigurationError, connect, load_database_settings
from .normalize import normalize_snapshot
from .provider import FeishuCliError, FeishuCliProvider
from .repository import save_normalized_document


def main(
    argv: Sequence[str] | None = None,
    stdout: TextIO = sys.stdout,
    stderr: TextIO = sys.stderr,
    connect_database: Callable = connect,
    provider: Any | None = None,
) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    knowledge_provider = provider or FeishuCliProvider(
        executable=getattr(args, "lark_cli", None),
        identity=getattr(args, "identity", "user"),
    )
    if args.command == "ingest-snapshot":
        return _ingest_snapshot(args, stdout, stderr, connect_database)
    if args.command == "search-feishu":
        return _search_feishu(args, stdout, stderr, knowledge_provider)
    if args.command == "fetch-feishu":
        return _fetch_feishu(args, stdout, stderr, knowledge_provider)
    parser.print_help()
    return 1


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="feishu-sync",
        description="Feishu knowledge sync worker utilities.",
    )
    subparsers = parser.add_subparsers(dest="command")

    ingest = subparsers.add_parser(
        "ingest-snapshot",
        help="Normalize a local Feishu snapshot file.",
    )
    ingest.add_argument(
        "--input",
        required=True,
        type=Path,
        help="Path to a fetched Feishu snapshot JSON file.",
    )
    ingest.add_argument(
        "--output",
        type=Path,
        help="Optional path for the normalized document JSON.",
    )
    ingest.add_argument(
        "--dry-run",
        action="store_true",
        help="Normalize and print/write JSON without database persistence.",
    )
    ingest.add_argument(
        "--database-url",
        help="PostgreSQL connection URL. Defaults to DATABASE_URL.",
    )

    search = subparsers.add_parser(
        "search-feishu",
        help="Search Feishu through lark-cli.",
    )
    search.add_argument("--query", required=True)
    search.add_argument("--limit", type=int, default=10)
    search.add_argument("--lark-cli")
    search.add_argument("--identity", default="user")

    fetch = subparsers.add_parser(
        "fetch-feishu",
        help="Fetch and normalize one Feishu document through lark-cli.",
    )
    fetch.add_argument("--doc", required=True)
    fetch.add_argument("--lark-cli")
    fetch.add_argument("--identity", default="user")
    return parser


def _ingest_snapshot(
    args: argparse.Namespace,
    stdout: TextIO,
    stderr: TextIO,
    connect_database: Callable,
) -> int:
    snapshot = json.loads(args.input.read_text(encoding="utf-8"))
    document = normalize_snapshot(snapshot)
    encoded = json.dumps(document, ensure_ascii=False, indent=2)

    if args.output:
        args.output.write_text(encoded + "\n", encoding="utf-8")
    elif args.dry_run:
        stdout.write(encoded + "\n")

    if args.dry_run:
        return 0

    try:
        settings = load_database_settings(args.database_url)
        connection = connect_database(settings)
        job_id = save_normalized_document(connection, document)
    except (DatabaseConfigurationError, RuntimeError) as exc:
        stderr.write(f"{exc}\n")
        return 2

    stdout.write(
        json.dumps(
            {
                "document_id": document["document_id"],
                "sync_status": "normalized",
                "index_job_id": job_id,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    )
    return 0


def _search_feishu(
    args: argparse.Namespace,
    stdout: TextIO,
    stderr: TextIO,
    provider: Any,
) -> int:
    try:
        hits = provider.search(args.query, limit=args.limit)
    except (FeishuCliError, ValueError) as exc:
        stderr.write(f"{exc}\n")
        return 2
    stdout.write(
        json.dumps(
            [asdict(hit) for hit in hits],
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    )
    return 0


def _fetch_feishu(
    args: argparse.Namespace,
    stdout: TextIO,
    stderr: TextIO,
    provider: Any,
) -> int:
    try:
        document = provider.fetch(args.doc)
    except (FeishuCliError, ValueError) as exc:
        stderr.write(f"{exc}\n")
        return 2
    stdout.write(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
