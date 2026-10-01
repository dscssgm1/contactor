from __future__ import annotations

import asyncio
import logging
import ssl

from contacter_wire.stream import read_frame, write_frame
from .config import secret_bytes

OPEN, DATA, CLOSE, ERROR = 6, 7, 8, 9
log = logging.getLogger('contacter.b-tunnel')


class _Stream:
    def __init__(self, writer: asyncio.StreamWriter):
        self.writer = writer
        self.task: asyncio.Task | None = None


class OutboundTunnel:
    """B-side outbound TLS tunnel that connects B local services to the relay."""

    def __init__(self, cfg):
        self.cfg = cfg
        self.secret = secret_bytes(cfg['stream_secret'])
        self.reader = None
        self.writer = None
        self.streams: dict[int, _Stream] = {}
        self._lock = asyncio.Lock()

    async def run(self):
        delay = 1.0
        while True:
            try:
                await self._connect()
                delay = 1.0
            except (ConnectionError, asyncio.IncompleteReadError, OSError, ValueError):
                log.warning('tunnel connection lost; reconnecting in %.1fs', delay)
                await self._teardown()
                await asyncio.sleep(delay)
                delay = min(delay * 2, 30.0)

    async def _teardown(self):
        for stream in list(self.streams.values()):
            if stream.task is not None:
                stream.task.cancel()
            stream.writer.close()
        self.streams.clear()
        if self.writer is not None:
            self.writer.close()
            try:
                await self.writer.wait_closed()
            except ConnectionError:
                pass
            self.writer = None

    async def _connect(self):
        context = ssl.create_default_context() if self.cfg.get('tls', True) else None
        if context is not None and self.cfg.get('tls_ca'):
            context.load_verify_locations(self.cfg['tls_ca'])
        self.reader, self.writer = await asyncio.open_connection(
            self.cfg['relay_host'], int(self.cfg['tunnel_port']),
            ssl=context,
            server_hostname=self.cfg.get('tls_server_name') if context else None)
        service = self.cfg.get('service', 'default')
        async with self._lock:
            await write_frame(self.writer, self.secret, OPEN, 0,
                              f"{self.cfg['target_id']}/{service}".encode())
        message, _, payload = await read_frame(self.reader, self.secret)
        if message != OPEN or payload != b'OK':
            raise ConnectionError('tunnel registration rejected')
        log.info('tunnel registered target=%s service=%s', self.cfg['target_id'], service)
        await self._serve()

    async def _send(self, message, sid, payload=b''):
        async with self._lock:
            await write_frame(self.writer, self.secret, message, sid, payload)

    async def _serve(self):
        while True:
            message, sid, payload = await read_frame(self.reader, self.secret)
            stream = self.streams.get(sid)
            if message == OPEN:
                if sid not in self.streams:
                    await self._open_stream(sid)
                continue
            if stream is None:
                continue
            if message == DATA:
                stream.writer.write(payload)
                await stream.writer.drain()
            elif message in (CLOSE, ERROR):
                await self._close_stream(sid)

    async def _open_stream(self, sid):
        try:
            reader, writer = await asyncio.open_connection(
                self.cfg['local_host'], int(self.cfg['local_port']))
        except (ConnectionError, OSError) as exc:
            log.warning('local connect failed for stream %s: %s', sid, exc)
            await self._send(ERROR, sid, b'local connect failed')
            return
        stream = _Stream(writer)
        self.streams[sid] = stream
        stream.task = asyncio.create_task(self._local_to_tunnel(sid, reader))

    async def _local_to_tunnel(self, sid, reader):
        try:
            while True:
                data = await reader.read(65536)
                if not data:
                    break
                await self._send(DATA, sid, data)
            await self._send(CLOSE, sid)
        except (ConnectionError, OSError):
            pass
        finally:
            await self._close_stream(sid)

    async def _close_stream(self, sid):
        stream = self.streams.pop(sid, None)
        if stream is None:
            return
        if stream.task is not None:
            stream.task.cancel()
        stream.writer.close()
        try:
            await stream.writer.wait_closed()
        except (ConnectionError, OSError):
            pass
