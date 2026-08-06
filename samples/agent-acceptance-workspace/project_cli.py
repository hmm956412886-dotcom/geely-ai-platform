from __future__ import annotations

import json
import sys

from calculator import add


def main() -> int:
    if sys.argv[1:] != ["inspect"]:
        print("usage: python project_cli.py inspect", file=sys.stderr)
        return 2
    print(json.dumps({"operation": "add", "sample_result": add(2, 3)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
