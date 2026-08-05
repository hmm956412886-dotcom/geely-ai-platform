import sys

from ai_gateway.host_cli import main as host_cli_main
from ai_gateway.server import main as server_main


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--host-cli":
        raise SystemExit(host_cli_main(sys.argv[2:]))
    raise SystemExit(server_main())
