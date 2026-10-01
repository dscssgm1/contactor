from __future__ import annotations

import argparse
import asyncio
import logging

from .config import load_relay
from .relay import Relay
from .tunnel import TunnelServer
from .http_proxy import HttpProxy
from .limits import HttpLimits
from .routing import HttpRoute


def main() -> None:
    parser = argparse.ArgumentParser(description="Contacter public relay server")
    parser.add_argument("--config", required=True, help="relay JSON configuration")
    parser.add_argument("--log-level", default="INFO", choices=("DEBUG", "INFO", "WARNING", "ERROR"))
    args = parser.parse_args()
    logging.basicConfig(level=getattr(logging, args.log_level), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    config = load_relay(args.config)

    async def run():
        relay = Relay(config)
        tunnel = None
        tasks = [asyncio.create_task(relay.run())]

        if config.stream_secret:
            tunnel = TunnelServer(config)
            await tunnel.start()

        if config.http_listen_port:
            routes = [HttpRoute.from_mapping(r) for r in config.http_routes]
            proxy = HttpProxy(routes, HttpLimits.from_mapping(config.http_limits), tunnel)
            http_server = await asyncio.start_server(
                proxy.serve, config.http_listen_host or config.listen_host, int(config.http_listen_port))
            tasks.append(asyncio.create_task(http_server.serve_forever()))

        for listener in config.tcp_listeners:
            if tunnel is None:
                raise ValueError("tcp_listeners require a stream_secret")
            tcp_server = await asyncio.start_server(
                lambda r, w, l=listener: tunnel.serve_tcp(l, r, w),
                listener.listen_host, listener.listen_port)
            tasks.append(asyncio.create_task(tcp_server.serve_forever()))

        if len(tasks) > 1:
            await asyncio.gather(*tasks)
        else:
            await tasks[0]

    asyncio.run(run())


if __name__ == "__main__":
    main()
