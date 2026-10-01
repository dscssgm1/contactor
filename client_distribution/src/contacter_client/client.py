from __future__ import annotations

import argparse
import asyncio
import logging

from .b_client import BClient
from .tunnel import OutboundTunnel
from .config import load_json


def main() -> None:
    parser = argparse.ArgumentParser(description="Contacter B-side client")
    parser.add_argument("--config", required=True, help="client JSON configuration")
    parser.add_argument("--log-level", default="INFO", choices=("DEBUG", "INFO", "WARNING", "ERROR"))
    args = parser.parse_args()
    logging.basicConfig(level=getattr(logging, args.log_level), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    config = load_json(args.config)

    async def run():
        tasks = [asyncio.create_task(BClient(config).run())]
        if config.get('stream_secret'):
            tasks.append(asyncio.create_task(OutboundTunnel(config).run()))
        await asyncio.gather(*tasks)

    asyncio.run(run())


if __name__ == "__main__":
    main()
