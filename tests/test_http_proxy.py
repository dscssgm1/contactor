from __future__ import annotations

import asyncio
import unittest

from contacter_server.http_proxy import HttpProxy
from contacter_server.limits import HttpLimits
from contacter_server.routing import HttpRoute


class HttpProxyTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.upstream_requests = []

        async def upstream(reader, writer):
            data = await reader.readuntil(b"\r\n\r\n")
            headers, body = data, b""
            content_length = 0
            for line in headers.split(b"\r\n")[1:]:
                if line.lower().startswith(b"content-length:"):
                    content_length = int(line.split(b":", 1)[1])
            if content_length:
                body = await reader.readexactly(content_length)
            self.upstream_requests.append(headers + body)
            writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\nOK")
            await writer.drain()
            writer.close()
            await writer.wait_closed()

        self.upstream_server = await asyncio.start_server(upstream, "127.0.0.1", 0)
        upstream_port = self.upstream_server.sockets[0].getsockname()[1]

        class FakeTunnel:
            def __init__(self, port):
                self.port = port

            async def open_connection(self, target_id, service):
                return await asyncio.open_connection("127.0.0.1", self.port)

        self.proxy = HttpProxy(
            [HttpRoute("example.test", "/", "office-b", "internal-http")],
            HttpLimits(read_timeout=0.5),
            FakeTunnel(upstream_port),
        )
        self.proxy_server = await asyncio.start_server(self.proxy.serve, "127.0.0.1", 0)
        self.proxy_port = self.proxy_server.sockets[0].getsockname()[1]

    async def asyncTearDown(self):
        self.proxy_server.close()
        await self.proxy_server.wait_closed()
        self.upstream_server.close()
        await self.upstream_server.wait_closed()

    async def request(self, payload: bytes) -> bytes:
        reader, writer = await asyncio.open_connection("127.0.0.1", self.proxy_port)
        writer.write(payload)
        await writer.drain()
        result = await reader.read()
        writer.close()
        await writer.wait_closed()
        return result

    async def test_chunked_request_is_decoded_and_connection_headers_are_sanitized(self):
        response = await self.request(
            b"POST /hello HTTP/1.1\r\n"
            b"Host: example.test\r\n"
            b"Transfer-Encoding: chunked\r\n"
            b"Connection: keep-alive, X-Leak\r\n"
            b"X-Leak: secret\r\n"
            b"\r\n4\r\nbody\r\n0\r\n\r\n"
        )
        self.assertIn(b"200 OK", response)
        upstream = self.upstream_requests[0]
        self.assertIn(b"Content-Length: 4", upstream)
        self.assertIn(b"body", upstream)
        self.assertNotIn(b"X-Leak", upstream)
        self.assertNotIn(b"Transfer-Encoding", upstream)

    async def test_content_length_and_transfer_encoding_are_rejected_before_stripping(self):
        response = await self.request(
            b"POST / HTTP/1.1\r\nHost: example.test\r\n"
            b"Content-Length: 1\r\nTransfer-Encoding: chunked\r\n\r\n"
        )
        self.assertIn(b"400", response)
        self.assertEqual([], self.upstream_requests)

    async def test_missing_or_duplicate_host_is_rejected(self):
        for host_headers in (b"", b"Host: one\r\nHost: two\r\n"):
            response = await self.request(b"GET / HTTP/1.1\r\n" + host_headers + b"\r\n")
            self.assertIn(b"400", response)

    async def test_no_route_is_a_gateway_error(self):
        response = await self.request(b"GET / HTTP/1.1\r\nHost: nowhere.test\r\n\r\n")
        self.assertIn(b"502", response)

    async def test_oversized_chunk_line_is_rejected(self):
        proxy = HttpProxy([], HttpLimits(max_request_line=16))
        reader = asyncio.StreamReader()
        reader.feed_data(b"0" * 17 + b"\r\n")
        reader.feed_eof()
        with self.assertRaises(Exception):
            await proxy.read_chunked(reader)


if __name__ == "__main__":
    unittest.main()
