from __future__ import annotations

import argparse
import asyncio
import logging

from .b_client import BClient
from .config import load_json


def main() -> None:
    parser = argparse.ArgumentParser(description="Contacter B-side UDP relay client")
    parser.add_argument("--config", required=True, help="client JSON configuration")
    parser.add_argument("--log-level", default="INFO", choices=("DEBUG", "INFO", "WARNING", "ERROR"))
    args = parser.parse_args()
    logging.basicConfig(level=getattr(logging, args.log_level), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    asyncio.run(BClient(load_json(args.config)).run())


if __name__ == "__main__":
    main()
