"""A-side reference client entry point.

Run with:
    python -m contacter.a_client_app --config a-client.json
"""
from __future__ import annotations

import argparse
import asyncio
import logging

from .a_client import AClient
from .config import load_json


def main() -> None:
    parser = argparse.ArgumentParser(description="Contacter A-side UDP client")
    parser.add_argument("--config", required=True, help="A client JSON configuration")
    parser.add_argument("--log-level", default="INFO", choices=("DEBUG", "INFO", "WARNING", "ERROR"))
    args = parser.parse_args()
    logging.basicConfig(level=getattr(logging, args.log_level), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    asyncio.run(AClient(load_json(args.config)).run())


if __name__ == "__main__":
    main()
