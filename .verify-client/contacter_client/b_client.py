from __future__ import annotations
import asyncio, json, logging, time
from contacter_wire.protocol import Message, decode, encode, make, key
from .config import secret_bytes
log=logging.getLogger('contacter.b')

def jd(x): return json.dumps(x,separators=(',',':')).encode()
class BClient(asyncio.DatagramProtocol):
    def __init__(self, cfg):
        self.cfg=cfg; self.transport=None; self.relay=None; self.secret=secret_bytes(cfg['b_secret']); self.sessions={}; self.local_transports={}
    async def run(self):
        loop=asyncio.get_running_loop()
        self.relay,_=await loop.create_datagram_endpoint(lambda:self, remote_addr=(self.cfg['relay_host'],int(self.cfg['relay_port'])))
        await self.register()
        local_port=int(self.cfg['local_game_port']); self.local_addr=(self.cfg.get('local_game_host','127.0.0.1'),local_port)
        try:
            while True:
                await asyncio.sleep(float(self.cfg.get('keepalive_seconds',15)))
                self.send(Message.KEEPALIVE,0,{'role':'b','target_id':self.cfg['target_id']})
        finally: self.relay.close()
    async def register(self): self.send(Message.REGISTER,0,{'role':'b','target_id':self.cfg['target_id']})
    def send(self,msg,sid,obj=None,payload=b''):
        p=make(msg,sid,jd(obj) if obj is not None else payload); self.relay.sendto(encode(p,key(self.secret,'b')))
    def datagram_received(self,data,addr):
        try: p=decode(data,key(self.secret,'b'),now=time.time())
        except ValueError: return
        if p.message==Message.OPEN: asyncio.create_task(self.open_session(p.session_id))
        elif p.message==Message.DATA and p.session_id in self.sessions: self.local_transports[p.session_id].sendto(p.payload)
        elif p.message==Message.CLOSE: self.close_session(p.session_id)
    async def open_session(self,sid):
        if sid in self.sessions: return
        loop=asyncio.get_running_loop(); proto=LocalBridge(self,sid)
        t,_=await loop.create_datagram_endpoint(lambda:proto, remote_addr=self.local_addr)
        self.sessions[sid]=True; self.local_transports[sid]=t
    def close_session(self,sid):
        t=self.local_transports.pop(sid,None)
        if t: t.close()
        self.sessions.pop(sid,None)
class LocalBridge(asyncio.DatagramProtocol):
    def __init__(self,client,sid): self.client,self.sid=client,sid
    def connection_made(self,t): self.transport=t
    def datagram_received(self,data,addr): self.client.send(Message.DATA,self.sid,payload=data)
