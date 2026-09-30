from __future__ import annotations
import asyncio, json, logging, time
from .protocol import Message, decode, encode, make, key
from .config import secret_bytes
class AClient(asyncio.DatagramProtocol):
    def __init__(self,cfg): self.cfg=cfg; self.transport=None; self.secret=secret_bytes(cfg['a_secret']); self.sid=0; self.local=None
    async def run(self):
        loop=asyncio.get_running_loop(); self.transport,_=await loop.create_datagram_endpoint(lambda:self, remote_addr=(self.cfg['relay_host'],int(self.cfg['relay_port'])))
        self.send(Message.CONNECT,{'role':'a','target_id':self.cfg['target_id']})
        await asyncio.sleep(float(self.cfg.get('connect_wait_seconds',3)))
        if self.local: self.local.close()
        self.transport.close()
    def send(self,msg,obj=None,payload=b''):
        self.transport.sendto(encode(make(msg,self.sid,json.dumps(obj,separators=(',',':')).encode() if obj else payload),key(self.secret,'a')))
    def datagram_received(self,data,addr):
        try: p=decode(data,key(self.secret,'a'),now=time.time())
        except ValueError: return
        if p.message==Message.CONNECT_OK:
            self.sid=p.session_id
            if self.cfg.get('local_listen_port'):
                asyncio.create_task(self.listen_local())
        elif p.message==Message.DATA and self.local: self.local.sendto(p.payload)
        elif p.message==Message.ERROR: logging.error('relay error: %s',p.payload.decode(errors='replace'))
    async def listen_local(self):
        loop=asyncio.get_running_loop(); self.local,_=await loop.create_datagram_endpoint(lambda:ALocal(self),local_addr=(self.cfg.get('local_listen_host','127.0.0.1'),int(self.cfg['local_listen_port'])))
class ALocal(asyncio.DatagramProtocol):
    def __init__(self,client): self.client=client
    def datagram_received(self,data,addr): self.client.send(Message.DATA,payload=data)
