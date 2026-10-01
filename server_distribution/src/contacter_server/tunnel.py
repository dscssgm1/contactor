from __future__ import annotations

import asyncio
import logging
import secrets

from contacter_wire.stream import read_frame, write_frame

log = logging.getLogger('contacter.tunnel')

OPEN, DATA, CLOSE, ERROR = 6, 7, 8, 9


class TunnelStreamWriter:
    """Writes request bytes to a B local service over the tunnel as DATA frames."""

    def __init__(self, peer, sid):
        self._peer = peer
        self._sid = sid
        self._buf = bytearray()
        self._closed = False

    def write(self, data: bytes) -> None:
        if self._closed:
            raise ConnectionError('stream closed')
        self._buf.extend(data)

    async def drain(self) -> None:
        if self._buf:
            chunk = bytes(self._buf)
            self._buf.clear()
            await self._peer.send(DATA, self._sid, chunk)

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        await self._peer.close_stream(self._sid)


class _Stream:
    def __init__(self, reader: asyncio.StreamReader, writer: TunnelStreamWriter):
        self.reader = reader
        self.writer = writer


class _Peer:
    """One authenticated B outbound tunnel connection."""

    def __init__(self, owner, target_id, service, reader, writer, secret):
        self.owner = owner
        self.target_id = target_id
        self.service = service
        self.reader = reader
        self.writer = writer
        self.secret = secret
        self.streams: dict[int, _Stream] = {}
        self._lock = asyncio.Lock()

    async def send(self, message, sid, payload=b''):
        async with self._lock:
            await write_frame(self.writer, self.secret, message, sid, payload)

    async def close(self):
        self.writer.close()
        try:
            await self.writer.wait_closed()
        except ConnectionError:
            pass

    async def close_stream(self, sid):
        stream = self.streams.pop(sid, None)
        if stream is None:
            return
        try:
            await self.send(CLOSE, sid)
        except (ConnectionError, OSError):
            pass

    async def run(self):
        while True:
            message, sid, payload = await read_frame(self.reader, self.secret)
            stream = self.streams.get(sid)
            if stream is None:
                continue
            if message == DATA:
                stream.reader.feed_data(payload)
            elif message in (CLOSE, ERROR):
                stream.reader.feed_eof()
                self.streams.pop(sid, None)


class TunnelServer:
    def __init__(self, config):
        self.config = config
        self.server = None
        self.sessions: dict[tuple[str, str], _Peer] = {}
        self.tasks: set[asyncio.Task] = set()

    async def start(self):
        self.server = await asyncio.start_server(
            self._accept, self.config.tunnel_host, self.config.tunnel_port,
            ssl=self.config.tls_context)
        return self.server

    def _track(self, coro):
        task = asyncio.create_task(coro)
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        return task

    async def _accept(self, reader, writer):
        self._track(self._handle(reader, writer))

    async def _handle(self, reader, writer):
        peer = None
        try:
            message, _, payload = await read_frame(reader, self.config.stream_secret)
            if message != OPEN:
                raise ValueError('expected tunnel registration')
            target_id, service = payload.decode('utf-8').split('/', 1)
            target = self.config.targets.get(target_id)
            services = getattr(target, 'services', {}) if target else {}
            if target is None or service not in services:
                raise ValueError('unauthorized service')
            peer = _Peer(self, target_id, service, reader, writer, self.config.stream_secret)
            old = self.sessions.get((target_id, service))
            if old is not None:
                await old.close()
            self.sessions[(target_id, service)] = peer
            await peer.send(OPEN, 0, b'OK')
            await peer.run()
        except (asyncio.IncompleteReadError, ConnectionError, OSError, ValueError, UnicodeError):
            pass
        finally:
            if peer is not None and self.sessions.get((peer.target_id, peer.service)) is peer:
                self.sessions.pop((peer.target_id, peer.service), None)
            writer.close()
            try:
                await writer.wait_closed()
            except ConnectionError:
                pass

    def _peer(self, target_id, service):
        return self.sessions.get((target_id, service))

    async def open_connection(self, target_id, service):
        """Open a logical stream to a B local service; returns (reader, writer)."""
        peer = self._peer(target_id, service)
        if peer is None:
            raise ConnectionError('service unavailable')
        sid = secrets.randbits(63)
        reader = asyncio.StreamReader()
        writer = TunnelStreamWriter(peer, sid)
        peer.streams[sid] = _Stream(reader, writer)
        try:
            await peer.send(OPEN, sid)
        except (ConnectionError, OSError):
            peer.streams.pop(sid, None)
            raise
        return reader, writer

    async def close_stream(self, target_id, service, sid):
        peer = self._peer(target_id, service)
        if peer is not None:
            await peer.close_stream(sid)

    async def serve_tcp(self, listener, client_reader, client_writer):
        """Forward a public raw TCP connection to a B local service via the tunnel."""
        upstream_w = None
        try:
            upstream_r, upstream_w = await self.open_connection(listener.target_id, listener.service)

            async def pump_up():
                while True:
                    data = await client_reader.read(65536)
                    if not data:
                        break
                    upstream_w.write(data)
                    await upstream_w.drain()

            async def pump_down():
                while True:
                    data = await upstream_r.read(65536)
                    if not data:
                        break
                    client_writer.write(data)
                    await client_writer.drain()

            await asyncio.gather(pump_up(), pump_down())
        except (ConnectionError, OSError):
            pass
        finally:
            if upstream_w is not None:
                try:
                    await upstream_w.close()
                except (ConnectionError, OSError):
                    pass
            client_writer.close()
            try:
                await client_writer.wait_closed()
            except ConnectionError:
                pass
