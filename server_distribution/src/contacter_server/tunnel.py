from __future__ import annotations
import asyncio, logging, ssl
from contacter_wire.stream import read_frame, write_frame
from .config import secret_bytes
log = logging.getLogger('contacter.tunnel')
OPEN, DATA, CLOSE, ERROR = 6, 7, 8, 9

class TunnelServer:
    def __init__(self, config):
        self.config=config; self.server=None; self.registry={}; self.tasks=set()
    async def start(self):
        self.server=await asyncio.start_server(self._accept, self.config.tunnel_host, self.config.tunnel_port, ssl=self.config.tls_context)
        return self.server
    async def _accept(self, reader, writer):
        task=asyncio.create_task(self._handle(reader, writer)); self.tasks.add(task); task.add_done_callback(self.tasks.discard)
    async def _handle(self, reader, writer):
        target=None; service=None
        try:
            # First frame is an authenticated registration: payload target_id/service.
            message, sid, payload = await read_frame(reader, self.config.stream_secret)
            if message != OPEN: raise ValueError('expected tunnel registration')
            target_id, service = payload.decode().split('/', 1)
            target=self.config.targets.get(target_id)
            if not target: raise ValueError('unknown target')
            self.registry[(target_id, service)] = writer
            await write_frame(writer, self.config.stream_secret, OPEN, 0, b'OK')
            while True:
                message, sid, payload=await read_frame(reader, self.config.stream_secret)
                peer=self.registry.get((target_id, service))
                if peer is not writer and peer is not None:
                    await write_frame(peer, self.config.stream_secret, message, sid, payload)
                elif message == CLOSE: break
        except (asyncio.IncompleteReadError, ConnectionError, ValueError):
            pass
        finally:
            if target and self.registry.get((target_id, service)) is writer: self.registry.pop((target_id, service), None)
            writer.close(); await writer.wait_closed()
