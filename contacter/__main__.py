"""Top-level command dispatcher kept for backwards compatibility."""
from __future__ import annotations

import argparse


def main() -> None:
    parser = argparse.ArgumentParser(prog="contacter")
    sub = parser.add_subparsers(dest="command", required=True)
    server = sub.add_parser("server", help="run the public UDP relay server")
    server.add_argument("--config", required=True)
    client = sub.add_parser("client", help="run the B-side UDP relay client")
    client.add_argument("--config", required=True)
    a_client = sub.add_parser("a-client", help="run the A-side reference client")
    a_client.add_argument("--config", required=True)
    # Legacy aliases remain available while deployments migrate to the split modules.
    relay = sub.add_parser("relay", help=argparse.SUPPRESS)
    relay.add_argument("--config", required=True)
    b_client = sub.add_parser("b-client", help=argparse.SUPPRESS)
    b_client.add_argument("--config", required=True)
    args = parser.parse_args()
    if args.command in ("server", "relay"):
        from .server import main as run
    elif args.command in ("client", "b-client"):
        from .client import main as run
    else:
        from .a_client_app import main as run
    # Rebuild argv for the selected module's own parser, preserving config.
    import sys
    sys.argv = [sys.argv[0], "--config", args.config]
    run()


if __name__ == "__main__":
    main()
