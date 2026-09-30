from __future__ import annotations

import argparse
import asyncio
import logging

from .config import load_relay
from .relay import Relay
from .http_proxy import HttpProxy
from .limits import HttpLimits
from .routing import HttpRoute


def main() -> None:
    parser = argparse.ArgumentParser(description="Contacter public UDP relay server")
    parser.add_argument("--config", required=True, help="relay JSON configuration")
    parser.add_argument("--log-level", default="INFO", choices=("DEBUG", "INFO", "WARNING", "ERROR"))
    args = parser.parse_args()
    logging.basicConfig(level=getattr(logging, args.log_level), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    config = load_relay(args.config)
    async def run():
        relay = Relay(config)
        tasks = [asyncio.create_task(relay.run())]
        if config.http_listen_port:
            routes = [HttpRoute.from_mapping(r) for r in config.http_routes]
            proxy = HttpProxy(routes, HttpLimits.from_mapping(config.http_limits))
            http_server = await asyncio.start_server(proxy.serve, config.http_listen_host or config.listen_host, int(config.http_listen_port))
            async with http_server:
                await http_server.serve_forever()
        else:
            await tasks[0]
    asyncio.run(run())


if __name__ == "__main__":
    main()
