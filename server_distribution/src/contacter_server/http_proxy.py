from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Iterable

from .limits import HttpLimits
from .routing import HttpRoute

_HOP = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te", "trailer", "transfer-encoding", "upgrade"}


class HttpProxyError(Exception):
    def __init__(self, status: int, message: str):
        self.status, self.message = status, message


@dataclass
class Request:
    method: str
    target: str
    version: str
    headers: list[tuple[bytes, bytes]]
    body: bytes


def _headers(raw: Iterable[tuple[bytes, bytes]]) -> tuple[list[tuple[bytes, bytes]], dict[str, list[bytes]]]:
    clean, grouped = [], {}
    for name, value in raw:
        key = name.decode("latin1").lower()
        if key in _HOP:
            continue
        clean.append((name, value)); grouped.setdefault(key, []).append(value)
    return clean, grouped


class HttpProxy:
    def __init__(self, routes: list[HttpRoute], limits: HttpLimits | None = None):
        self.routes, self.limits = routes, limits or HttpLimits()

    async def serve(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            request = await asyncio.wait_for(self.read_request(reader), self.limits.read_timeout)
            route = next((r for r in self.routes if r.matches(self.header(request, b"host").decode("latin1"), request.target)), None)
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
            if key.lower() == name.lower(): return value
        return b""

    async def read_request(self, reader: asyncio.StreamReader) -> Request:
        line = await reader.readline()
        if not line or len(line) > self.limits.max_request_line:
            raise HttpProxyError(400, "bad request line")
        try: method, target, version = line.rstrip(b"\r\n").decode("ascii").split(" ")
        except ValueError: raise HttpProxyError(400, "bad request line")
        if method not in ("GET", "POST") or version != "HTTP/1.1": raise HttpProxyError(400, "unsupported request")
        raw, total = [], 0
        while True:
            line = await reader.readline(); total += len(line)
            if total > self.limits.max_header_bytes: raise HttpProxyError(431, "headers too large")
            if line in (b"\r\n", b"\n"): break
            if b":" not in line: raise HttpProxyError(400, "bad header")
            name, value = line.split(b":", 1); name = name.strip(); value = value.strip()
            if not name or any(c < 33 or c > 126 for c in name): raise HttpProxyError(400, "bad header")
            raw.append((name, value))
            if len(raw) > self.limits.max_header_count: raise HttpProxyError(431, "too many headers")
        _, grouped = _headers(raw)
        cls = grouped.get("content-length", [])
        tes = grouped.get("transfer-encoding", [])
        if cls and (len(set(cls)) != 1 or not cls[0].isdigit()): raise HttpProxyError(400, "conflicting content length")
        if cls and tes: raise HttpProxyError(400, "content length with transfer encoding")
        body = b""
        if tes:
            if [x.strip().lower() for x in tes] != [b"chunked"]: raise HttpProxyError(400, "unsupported transfer encoding")
            body = await self.read_chunked(reader)
        elif cls:
            length = int(cls[0])
            if length > self.limits.max_body_bytes: raise HttpProxyError(413, "body too large")
            body = await asyncio.wait_for(reader.readexactly(length), self.limits.read_timeout)
        return Request(method, target, version, raw, body)

    async def read_chunked(self, reader: asyncio.StreamReader) -> bytes:
        out = bytearray()
        while True:
            line = await reader.readline()
            try: size = int(line.split(b";", 1)[0].strip(), 16)
            except ValueError: raise HttpProxyError(400, "bad chunk")
            if size == 0:
                while await reader.readline() not in (b"\r\n", b"\n"): pass
                return bytes(out)
            if len(out) + size > self.limits.max_body_bytes: raise HttpProxyError(413, "body too large")
            out.extend(await reader.readexactly(size))
            if await reader.readexactly(2) != b"\r\n": raise HttpProxyError(400, "bad chunk")

    async def forward(self, route: HttpRoute, request: Request, client: asyncio.StreamWriter) -> None:
        try:
            upstream_r, upstream_w = await asyncio.wait_for(asyncio.open_connection(route.upstream_host, route.upstream_port), self.limits.connect_timeout)
            path = request.target if request.target.startswith("/") else "/"
            headers, _ = _headers(request.headers)
            headers = [(k, v) for k, v in headers if k.lower() not in (b"content-length", b"host")]
            headers += [(b"Host", route.host.encode()), (b"Content-Length", str(len(request.body)).encode()), (b"Connection", b"close")]
            upstream_w.write((f"{request.method} {path} HTTP/1.1\r\n").encode() + b"\r\n".join(k+b": "+v for k,v in headers) + b"\r\n\r\n" + request.body); await upstream_w.drain()
            await self.pipe_response(upstream_r, client)
        except asyncio.TimeoutError: raise HttpProxyError(504, "upstream timeout")
        except (OSError, asyncio.IncompleteReadError): raise HttpProxyError(502, "bad gateway")
        finally:
            if 'upstream_w' in locals(): upstream_w.close(); await upstream_w.wait_closed()

    async def pipe_response(self, reader, writer):
        line = await asyncio.wait_for(reader.readline(), self.limits.read_timeout)
        if not line.startswith(b"HTTP/"): raise HttpProxyError(502, "invalid upstream response")
        raw=[]; total=0
        while True:
            item=await asyncio.wait_for(reader.readline(), self.limits.read_timeout); total += len(item)
            if total > self.limits.max_header_bytes: raise HttpProxyError(502, "upstream headers too large")
            if item in (b"\r\n",b"\n"): break
            if b":" not in item: raise HttpProxyError(502,"invalid upstream header")
            raw.append(tuple(x.strip() for x in item.split(b":",1)))
        clean, grouped = _headers(raw); cls=grouped.get("content-length",[]); tes=grouped.get("transfer-encoding",[])
        if cls and (len(set(cls)) != 1 or not cls[0].isdigit()) or cls and tes: raise HttpProxyError(502,"invalid upstream framing")
        writer.write(line + b"\r\n".join(k+b": "+v for k,v in clean) + b"\r\n\r\n")
        if cls:
            remaining=int(cls[0]);
            if remaining > self.limits.max_body_bytes: raise HttpProxyError(502,"upstream body too large")
            writer.write(await asyncio.wait_for(reader.readexactly(remaining), self.limits.read_timeout))
        elif tes and tes[-1].lower().strip() == b"chunked":
            while True:
                chunk=await asyncio.wait_for(reader.readline(), self.limits.read_timeout); writer.write(chunk)
                size=int(chunk.split(b";",1)[0],16)
                if size == 0: writer.write(await reader.readline()); break
                writer.write(await reader.readexactly(size+2))
        else:
            while data := await asyncio.wait_for(reader.read(65536), self.limits.read_timeout): writer.write(data)
        await writer.drain()

    async def error(self, writer, status, message):
        body = (message + "\n").encode()
        writer.write(f"HTTP/1.1 {status} {message}\r\nContent-Length: {len(body)}\r\nConnection: close\r\nContent-Type: text/plain\r\n\r\n".encode() + body)
        await writer.drain()
