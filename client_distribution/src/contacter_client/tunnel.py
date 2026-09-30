from __future__ import annotations
import asyncio, logging, ssl
from contacter_wire.stream import read_frame, write_frame
from .config import secret_bytes
OPEN, DATA, CLOSE = 6, 7, 8
log=logging.getLogger('contacter.b-tunnel')
class OutboundTunnel:
    def __init__(self,cfg): self.cfg=cfg; self.secret=secret_bytes(cfg['stream_secret']); self.reader=None; self.writer=None; self.local_tasks=set()
    async def run(self):
        context=ssl.create_default_context() if self.cfg.get('tls',True) else None
        self.reader,self.writer=await asyncio.open_connection(self.cfg['relay_host'],int(self.cfg['tunnel_port']),ssl=context,server_hostname=self.cfg.get('tls_server_name') if context else None)
        service=self.cfg.get('service','default'); await write_frame(self.writer,self.secret,OPEN,0,f"{self.cfg['target_id']}/{service}".encode())
        await read_frame(self.reader,self.secret)
        server=await asyncio.start_server(self._local,self.cfg.get('local_host','127.0.0.1'),int(self.cfg['local_port']))
        async with server: await server.serve_forever()
    async def _local(self,reader,writer):
        sid=id(writer)
        try:
            await write_frame(self.writer,self.secret,OPEN,sid,b'')
            async def uplink():
                while True:
                    data=await reader.read(65536)
                    if not data: break
                    await write_frame(self.writer,self.secret,DATA,sid,data)
            await uplink()
        finally:
            await write_frame(self.writer,self.secret,CLOSE,sid,b''); writer.close(); await writer.wait_closed()
