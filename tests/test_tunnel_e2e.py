from __future__ import annotations

import asyncio
import unittest

from contacter_server.config import RelayConfig, secret_bytes
from contacter_server.models import TargetConfig
from contacter_server.tunnel import TunnelServer
from contacter_server.http_proxy import HttpProxy
from contacter_server.limits import HttpLimits
from contacter_server.routing import HttpRoute
from contacter_client.tunnel import OutboundTunnel

SECRET = secret_bytes("aa" * 32)


class TunnelEndToEndTests(unittest.IsolatedAsyncioTestCase):
    async def test_http_request_reaches_b_local_service_through_tunnel(self):
        # B's local HTTP service.
        async def local_http(reader, writer):
            await reader.readuntil(b"\r\n\r\n")
            body = b"hello-from-b"
            writer.write(
                b"HTTP/1.1 200 OK\r\nContent-Length: " + str(len(body)).encode() +
                b"\r\nConnection: close\r\n\r\n" + body)
            await writer.drain()
            writer.close()
            await writer.wait_closed()

        local_server = await asyncio.start_server(local_http, "127.0.0.1", 0)
        local_port = local_server.sockets[0].getsockname()[1]

        target = TargetConfig("office-b", SECRET, SECRET, 0, "exclusive", 1,
                              {"internal-http": "http"})
        config = RelayConfig(
            "127.0.0.1", 40000, {"office-b": target},
            tunnel_host="127.0.0.1", tunnel_port=0, stream_secret=SECRET)

        tunnel = TunnelServer(config)
        await tunnel.start()
        tunnel_port = tunnel.server.sockets[0].getsockname()[1]

        b_cfg = {
            "stream_secret": "aa" * 32,
            "relay_host": "127.0.0.1",
            "tunnel_port": tunnel_port,
            "tls": False,
            "target_id": "office-b",
            "service": "internal-http",
            "local_host": "127.0.0.1",
            "local_port": local_port,
        }
        b_task = asyncio.create_task(OutboundTunnel(b_cfg).run())

        proxy = HttpProxy(
            [HttpRoute("example.test", "/", "office-b", "internal-http")],
            HttpLimits(read_timeout=2.0, connect_timeout=2.0),
            tunnel,
        )
        proxy_server = await asyncio.start_server(proxy.serve, "127.0.0.1", 0)
        proxy_port = proxy_server.sockets[0].getsockname()[1]

        # Wait for B to register before the first request is routed.
        for _ in range(50):
            if ("office-b", "internal-http") in tunnel.sessions:
                break
            await asyncio.sleep(0.05)

        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", proxy_port)
            writer.write(b"GET /hello HTTP/1.1\r\nHost: example.test\r\n\r\n")
            await writer.drain()
            response = await reader.read()
            writer.close()
            await writer.wait_closed()
            self.assertIn(b"200 OK", response)
            self.assertIn(b"hello-from-b", response)
        finally:
            b_task.cancel()
            proxy_server.close()
            await proxy_server.wait_closed()
            local_server.close()
            await local_server.wait_closed()

    async def test_raw_tcp_echo_reaches_b_local_service_through_tunnel(self):
        async def local_echo(reader, writer):
            data = await reader.read(65536)
            writer.write(data)
            await writer.drain()
            writer.close()
            await writer.wait_closed()

        local_server = await asyncio.start_server(local_echo, "127.0.0.1", 0)
        local_port = local_server.sockets[0].getsockname()[1]

        target = TargetConfig("office-b", SECRET, SECRET, 0, "exclusive", 1,
                              {"db": "tcp"})
        config = RelayConfig(
            "127.0.0.1", 40000, {"office-b": target},
            tunnel_host="127.0.0.1", tunnel_port=0, stream_secret=SECRET)

        tunnel = TunnelServer(config)
        await tunnel.start()
        tunnel_port = tunnel.server.sockets[0].getsockname()[1]

        b_cfg = {
            "stream_secret": "aa" * 32,
            "relay_host": "127.0.0.1",
            "tunnel_port": tunnel_port,
            "tls": False,
            "target_id": "office-b",
            "service": "db",
            "local_host": "127.0.0.1",
            "local_port": local_port,
        }
        b_task = asyncio.create_task(OutboundTunnel(b_cfg).run())

        class Listener:
            target_id = "office-b"
            service = "db"

        tcp_server = await asyncio.start_server(
            lambda r, w: tunnel.serve_tcp(Listener(), r, w), "127.0.0.1", 0)
        tcp_port = tcp_server.sockets[0].getsockname()[1]

        for _ in range(50):
            if ("office-b", "db") in tunnel.sessions:
                break
            await asyncio.sleep(0.05)

        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", tcp_port)
            writer.write(b"ping")
            await writer.drain()
            data = await reader.read(4)
            writer.close()
            await writer.wait_closed()
            self.assertEqual(b"ping", data)
        finally:
            b_task.cancel()
            tcp_server.close()
            await tcp_server.wait_closed()
            local_server.close()
            await local_server.wait_closed()


if __name__ == "__main__":
    unittest.main()
