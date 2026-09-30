"""Public UDP relay server entry point.

Run with:
    python -m contacter.server --config relay.json
"""
from __future__ import annotations

import argparse
import asyncio
import logging

from .config import load_relay
from .relay import Relay


def main() -> None:
    parser = argparse.ArgumentParser(description="Contacter public UDP relay server")
    parser.add_argument("--config", required=True, help="relay JSON configuration")
    parser.add_argument("--log-level", default="INFO", choices=("DEBUG", "INFO", "WARNING", "ERROR"))
    args = parser.parse_args()
    logging.basicConfig(level=getattr(logging, args.log_level), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    asyncio.run(Relay(load_relay(args.config)).run())


if __name__ == "__main__":
    main()
