"""Run a host-software integration flow against a local AI Gateway."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import webbrowser

from python_host_sdk import GeelyAIGatewayClient, HostContext


def main() -> None:
    args = parse_args()
    repo_root = Path(__file__).resolve().parents[2]
    source_file = args.source_file or str(repo_root / "src/ai-gateway/tests/fixtures/test-run-cases.csv")
    target_file = args.target_file or str(repo_root / "src/ai-gateway/tests/fixtures/test-run-cases-target.csv")

    client = GeelyAIGatewayClient(args.gateway_url)
    source_asset_id = client.register_asset(source_file)["result"]["asset_id"]
    target_asset_id = client.register_asset(target_file)["result"]["asset_id"]
    context = HostContext(
        project_id=args.project_id,
        run_id=args.run_id,
        source_asset_id=source_asset_id,
        target_asset_id=target_asset_id,
        user_id=args.user_id,
    )

    print_json("health", client.health())
    print_json("update_host_context", client.update_host_context(context))
    print_json("plugin_manifest", client.plugin_manifest())
    print_json("tools", client.tools())
    print_json("analyze", client.analyze(source_asset_id=source_asset_id, question=args.question))
    print_json("insights", client.insights(source_asset_id=source_asset_id))
    print_json(
        "compare",
        client.compare(baseline_asset_id=source_asset_id, target_asset_id=target_asset_id),
    )

    if args.open_copilot:
        webbrowser.open(client.copilot_url)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Simulate a host software AI plugin flow.")
    parser.add_argument("--gateway-url", default="http://127.0.0.1:8765")
    parser.add_argument("--project-id", default="GEELY_TEST")
    parser.add_argument("--run-id", default="RUN_HOST_DEMO")
    parser.add_argument("--source-file", default="")
    parser.add_argument("--target-file", default="")
    parser.add_argument("--user-id", default="demo_user")
    parser.add_argument("--question", default="Analyze current test failures and suggest next troubleshooting steps.")
    parser.add_argument("--open-copilot", action="store_true")
    return parser.parse_args()


def print_json(title: str, payload: dict) -> None:
    print(f"\n## {title}")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
