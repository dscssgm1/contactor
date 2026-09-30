from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Iterable

from .limits import HttpLimits
from .routing import HttpRoute

_HOP = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
}


class HttpProxyError(Exception):
    def __init__(self, status: int, message: str):
        self.status, self.message = status, message
        super().__init__(message)


@dataclass
class Request:
    method: str
    target: str
    version: str
    headers: list[tuple[bytes, bytes]]
    body: bytes


def _connection_tokens(raw: Iterable[tuple[bytes, bytes]]) -> set[str]:
    tokens: set[str] = set()
    for name, value in raw:
        if name.lower() == b"connection":
            tokens.update(token.strip().lower() for token in value.decode("latin1").split(",") if token.strip())
    return tokens


def _headers(raw: Iterable[tuple[bytes, bytes]], *, preserve_framing: bool = False) -> tuple[list[tuple[bytes, bytes]], dict[str, list[bytes]]]:
    raw = list(raw)
    grouped: dict[str, list[bytes]] = {}
    for name, value in raw:
        grouped.setdefault(name.decode("latin1").lower(), []).append(value)
    blocked = _connection_tokens(raw) | (_HOP - {"transfer-encoding"} if preserve_framing else _HOP)
    clean = [
        (name, value)
        for name, value in raw
        if name.decode("latin1").lower() not in blocked
    ]
    return clean, grouped


class HttpProxy:
    def __init__(self, routes: list[HttpRoute], limits: HttpLimits | None = None):
        self.routes, self.limits = routes, limits or HttpLimits()

    async def _readline(self, reader: asyncio.StreamReader, *, limit: int, status: int = 400) -> bytes:
        line = await asyncio.wait_for(reader.readline(), self.limits.read_timeout)
        if not line or len(line) > limit:
            raise HttpProxyError(status, "truncated or oversized line")
        return line

    async def _readexactly(self, reader: asyncio.StreamReader, size: int) -> bytes:
        return await asyncio.wait_for(reader.readexactly(size), self.limits.read_timeout)

    async def serve(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            request = await self.read_request(reader)
            host = self.header(request, b"host").decode("latin1")
            route = next((r for r in self.routes if r.matches(host, request.target)), None)
            if route is None:
                raise HttpProxyError(502, "no route")
            await self.forward(route, request, writer)
        except asyncio.TimeoutError:
            await self.error(writer, 504, "gateway timeout")
        except HttpProxyError as exc:
            await self.error(writer, exc.status, exc.message)
        except (ConnectionError, asyncio.IncompleteReadError):
            await self.error(writer, 502, "bad gateway")
        finally:
            writer.close()
            await writer.wait_closed()

    def header(self, request: Request, name: bytes) -> bytes:
        for key, value in request.headers:
            if key.lower() == name.lower():
                return value
        return b""

    async def read_request(self, reader: asyncio.StreamReader) -> Request:
        line = await self._readline(reader, limit=self.limits.max_request_line)
        if not line.endswith(b"\r\n"):
            raise HttpProxyError(400, "bad request line")
        try:
            method, target, version = line[:-2].decode("ascii").split(" ")
        except (UnicodeDecodeError, ValueError):
            raise HttpProxyError(400, "bad request line")
        if method not in ("GET", "POST") or version != "HTTP/1.1" or not target:
            raise HttpProxyError(400, "unsupported request")

        raw: list[tuple[bytes, bytes]] = []
        total = 0
        while True:
            line = await self._readline(reader, limit=self.limits.max_header_bytes)
            total += len(line)
            if total > self.limits.max_header_bytes:
                raise HttpProxyError(431, "headers too large")
            if line == b"\r\n":
                break
            if not line.endswith(b"\r\n") or b":" not in line:
                raise HttpProxyError(400, "bad header")
            name, value = line[:-2].split(b":", 1)
            name, value = name.strip(), value.strip()
            if not name or any(c < 33 or c > 126 for c in name):
                raise HttpProxyError(400, "bad header")
            raw.append((name, value))
            if len(raw) > self.limits.max_header_count:
                raise HttpProxyError(431, "too many headers")

        _, grouped = _headers(raw)
        hosts = grouped.get("host", [])
        if len(hosts) != 1 or not hosts[0].strip():
            raise HttpProxyError(400, "missing or duplicate host")
        cls = grouped.get("content-length", [])
        tes = grouped.get("transfer-encoding", [])
        if cls and (len(set(cls)) != 1 or not cls[0].isdigit()):
            raise HttpProxyError(400, "conflicting content length")
        if cls and tes:
            raise HttpProxyError(400, "content length with transfer encoding")
        body = b""
        if tes:
            if len(tes) != 1 or [x.strip().lower() for x in tes[0].split(b",")] != [b"chunked"]:
                raise HttpProxyError(400, "unsupported transfer encoding")
            body = await self.read_chunked(reader, status=400)
        elif cls:
            length = int(cls[0])
            if length > self.limits.max_body_bytes:
                raise HttpProxyError(413, "body too large")
            body = await self._readexactly(reader, length)
        return Request(method, target, version, raw, body)

    async def read_chunked(self, reader: asyncio.StreamReader, *, status: int = 400) -> bytes:
        out = bytearray()
        trailer_count = 0
        while True:
            line = await self._readline(reader, limit=self.limits.max_request_line, status=status)
            if not line.endswith(b"\r\n"):
                raise HttpProxyError(status, "bad chunk")
            size_text = line[:-2].split(b";", 1)[0].strip()
            try:
                size = int(size_text, 16)
            except ValueError:
                raise HttpProxyError(status, "bad chunk")
            if size < 0:
                raise HttpProxyError(status, "bad chunk")
            if size == 0:
                while True:
                    trailer = await self._readline(reader, limit=self.limits.max_header_bytes, status=status)
                    if trailer == b"\r\n":
                        return bytes(out)
                    trailer_count += 1
                    if trailer_count > self.limits.max_header_count:
                        raise HttpProxyError(status, "too many trailers")
                    if not trailer.endswith(b"\r\n") or b":" not in trailer[:-2]:
                        raise HttpProxyError(status, "bad chunk trailer")
            if len(out) + size > self.limits.max_body_bytes:
                raise HttpProxyError(413 if status == 400 else status, "body too large")
            out.extend(await self._readexactly(reader, size))
            if await self._readexactly(reader, 2) != b"\r\n":
                raise HttpProxyError(status, "bad chunk")

    async def forward(self, route: HttpRoute, request: Request, client: asyncio.StreamWriter) -> None:
        upstream_w = None
        try:
            upstream_r, upstream_w = await asyncio.wait_for(
                asyncio.open_connection(route.upstream_host, route.upstream_port), self.limits.connect_timeout
            )
            path = request.target if request.target.startswith("/") else "/"
            headers, _ = _headers(request.headers)
            headers = [(k, v) for k, v in headers if k.lower() not in (b"content-length", b"host")]
            # Chunked requests are decoded and sent with a bounded, canonical length.
            headers += [(b"Host", route.host.encode("latin1")), (b"Content-Length", str(len(request.body)).encode("ascii")), (b"Connection", b"close")]
            upstream_w.write(
                (f"{request.method} {path} HTTP/1.1\r\n").encode("ascii")
                + b"\r\n".join(k + b": " + v for k, v in headers)
                + b"\r\n\r\n"
                + request.body
            )
            await asyncio.wait_for(upstream_w.drain(), self.limits.read_timeout)
            await self.pipe_response(upstream_r, client)
        except asyncio.TimeoutError:
            raise HttpProxyError(504, "upstream timeout")
        except (OSError, asyncio.IncompleteReadError):
            raise HttpProxyError(502, "bad gateway")
        finally:
            if upstream_w is not None:
                upstream_w.close()
                await upstream_w.wait_closed()

    async def pipe_response(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        line = await self._readline(reader, limit=self.limits.max_request_line, status=502)
        if not line.endswith(b"\r\n"):
            raise HttpProxyError(502, "invalid upstream status")
        try:
            version, code_text, reason = line[:-2].decode("latin1").split(" ", 2)
            code = int(code_text)
        except (UnicodeError, ValueError):
            raise HttpProxyError(502, "invalid upstream status")
        if version != "HTTP/1.1" or not 100 <= code <= 599:
            raise HttpProxyError(502, "invalid upstream status")

        raw: list[tuple[bytes, bytes]] = []
        total = 0
        while True:
            item = await self._readline(reader, limit=self.limits.max_header_bytes, status=502)
            total += len(item)
            if total > self.limits.max_header_bytes:
                raise HttpProxyError(502, "upstream headers too large")
            if item == b"\r\n":
                break
            if not item.endswith(b"\r\n") or b":" not in item:
                raise HttpProxyError(502, "invalid upstream header")
            name, value = item[:-2].split(b":", 1)
            if not name.strip() or any(c < 33 or c > 126 for c in name.strip()):
                raise HttpProxyError(502, "invalid upstream header")
            raw.append((name.strip(), value.strip()))
            if len(raw) > self.limits.max_header_count:
                raise HttpProxyError(502, "too many upstream headers")

        clean, grouped = _headers(raw, preserve_framing=True)
        cls, tes = grouped.get("content-length", []), grouped.get("transfer-encoding", [])
        if cls and (len(set(cls)) != 1 or not cls[0].isdigit()):
            raise HttpProxyError(502, "invalid upstream framing")
        if cls and tes:
            raise HttpProxyError(502, "invalid upstream framing")
        chunked = False
        if tes:
            if len(tes) != 1 or [x.strip().lower() for x in tes[0].split(b",")] != [b"chunked"]:
                raise HttpProxyError(502, "unsupported upstream transfer encoding")
            chunked = True
        if cls:
            remaining = int(cls[0])
            if remaining > self.limits.max_body_bytes:
                raise HttpProxyError(502, "upstream body too large")
            body = await self._readexactly(reader, remaining)
        elif chunked:
            body = await self._read_chunked_response(reader)
        elif code in (204, 304) or 100 <= code < 200:
            body = b""
        else:
            parts: list[bytes] = []
            total_body = 0
            while True:
                data = await asyncio.wait_for(reader.read(65536), self.limits.read_timeout)
                if not data:
                    break
                total_body += len(data)
                if total_body > self.limits.max_body_bytes:
                    raise HttpProxyError(502, "upstream body too large")
                parts.append(data)
            body = b"".join(parts)
        writer.write(line + b"\r\n".join(k + b": " + v for k, v in clean) + b"\r\n\r\n" + body)
        await asyncio.wait_for(writer.drain(), self.limits.read_timeout)

    async def _read_chunked_response(self, reader: asyncio.StreamReader) -> bytes:
        out = bytearray()
        total = 0
        trailer_count = 0
        while True:
            line = await self._readline(reader, limit=self.limits.max_request_line, status=502)
            if not line.endswith(b"\r\n"):
                raise HttpProxyError(502, "invalid upstream chunk")
            try:
                size = int(line[:-2].split(b";", 1)[0].strip(), 16)
            except ValueError:
                raise HttpProxyError(502, "invalid upstream chunk")
            if size < 0:
                raise HttpProxyError(502, "invalid upstream chunk")
            out.extend(line)
            if size:
                total += size
                if total > self.limits.max_body_bytes:
                    raise HttpProxyError(502, "upstream body too large")
                out.extend(await self._readexactly(reader, size))
                if await self._readexactly(reader, 2) != b"\r\n":
                    raise HttpProxyError(502, "invalid upstream chunk")
                out.extend(b"\r\n")
            else:
                while True:
                    trailer = await self._readline(reader, limit=self.limits.max_header_bytes, status=502)
                    if trailer != b"\r\n":
                        trailer_count += 1
                        if trailer_count > self.limits.max_header_count or not trailer.endswith(b"\r\n") or b":" not in trailer[:-2]:
                            raise HttpProxyError(502, "invalid upstream trailer")
                    out.extend(trailer)
                    if trailer == b"\r\n":
                        return bytes(out)

    async def error(self, writer: asyncio.StreamWriter, status: int, message: str) -> None:
        body = (message + "\n").encode("ascii", "replace")
        writer.write(
            f"HTTP/1.1 {status} {message}\r\nContent-Length: {len(body)}\r\nConnection: close\r\nContent-Type: text/plain\r\n\r\n".encode("ascii")
            + body
        )
        await writer.drain()
