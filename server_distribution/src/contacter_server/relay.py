from __future__ import annotations
import asyncio, json, logging, secrets, time
from contacter_wire.protocol import Message, Packet, decode, encode, make
from contacter_wire.auth import key
from .auth import ReplayCache
from .models import Registration, Session
from .config import RelayConfig

log=logging.getLogger('contacter.relay')

def jdump(obj): return json.dumps(obj, separators=(',',':')).encode()
def jload(data): return json.loads(data.decode())

class Endpoint(asyncio.DatagramProtocol):
    def __init__(self, relay, kind, target_id=None): self.relay,self.kind,self.target_id=relay,kind,target_id; self.transport=None
    def connection_made(self, transport): self.transport=transport
    def datagram_received(self, data, addr): asyncio.create_task(self.relay.receive(self.kind,self.target_id,data,addr,self.transport))
    def error_received(self, exc): log.warning('%s UDP error: %s', self.kind, exc)

class Relay:
    def __init__(self, config):
        self.config=config; self.registrations={}; self.sessions={}; self.transports=[]; self.replay=ReplayCache(); self.running=True
    async def run(self):
        from .tunnel import TunnelServer
        self.tunnel = TunnelServer(self.config)
        if self.config.stream_secret:
            await self.tunnel.start()
        loop=asyncio.get_running_loop()
        t,_=await loop.create_datagram_endpoint(lambda:Endpoint(self,'control'), local_addr=(self.config.listen_host,self.config.listen_port)); self.transports.append(t)
        for tid,target in self.config.targets.items():
            if target.public_port:
                t,_=await loop.create_datagram_endpoint(lambda tid=tid:Endpoint(self,'public',tid), local_addr=(self.config.listen_host,target.public_port)); self.transports.append(t)
        log.info('relay listening on %s:%s',self.config.listen_host,self.config.listen_port)
        try:
            while self.running:
                await asyncio.sleep(1); self.cleanup()
        finally:
            for t in self.transports: t.close()
    def cleanup(self):
        now=time.monotonic()
        for tid,r in list(self.registrations.items()):
            if r.expires < now:
                self.registrations.pop(tid,None)
                for sid,s in list(self.sessions.items()):
                    if s.target_id==tid: self.sessions.pop(sid,None)
        for sid,s in list(self.sessions.items()):
            if now-s.last_activity > self.config.session_idle: self.sessions.pop(sid,None)
    async def receive(self, kind, tid, data, addr, transport):
        if kind=='public': return await self.public_data(tid,data,addr,transport)
        await self.control(data,addr,transport)
    async def control(self,data,addr,transport):
        # Identify target from JSON envelope before authentication; secrets are selected by target_id in payload.
        try:
            if len(data)<40: return
            raw=data[0:4]
            # protocol header payload starts at HEADER.size, safely decoded only after selecting a configured key
            from contacter_wire.protocol import HEADER
            payload_len=HEADER.unpack_from(data)[-1]; body=data[HEADER.size:HEADER.size+payload_len]; obj=jload(body)
            tid=obj.get('target_id'); role=obj.get('role')
            target=self.config.targets.get(tid)
            if not target: return
            secret=key(target.b_secret if role=='b' else target.a_secret, role)
            p=decode(data,secret,now=time.time())
            if self.replay.seen((role,tid,addr),p.nonce): return
        except Exception:
            # DATA/CLOSE frames contain opaque game bytes, so they cannot carry a
            # JSON target selector. Resolve their key from an already authenticated
            # B registration or A session endpoint instead.
            try:
                for candidate_id, registration in self.registrations.items():
                    if registration.endpoint == addr:
                        target = registration.target
                        tid, role = candidate_id, 'b'
                        p = decode(data, key(target.b_secret, 'b'), now=time.time())
                        break
                else:
                    match = next((session for session in self.sessions.values() if session.a_endpoint == addr), None)
                    if match is None:
                        return
                    tid, role = match.target_id, 'a'
                    target = self.config.targets[tid]
                    p = decode(data, key(target.a_secret, 'a'), now=time.time())
                if p.message not in (Message.DATA, Message.CLOSE):
                    return
                if self.replay.seen((role, tid, addr), p.nonce):
                    return
            except Exception:
                return
        if p.message in (Message.REGISTER,Message.KEEPALIVE) and role=='b':
            r=self.registrations.setdefault(tid,Registration(target)); r.endpoint=addr; r.expires=time.monotonic()+45; r.generation+=1
            out=make(Message.REGISTER_OK,p.session_id,jdump({'target_id':tid,'public_port':target.public_port}))
            transport.sendto(encode(out,key(target.b_secret,'b')),addr); return
        if p.message==Message.CONNECT and role=='a':
            r=self.registrations.get(tid)
            if not r or r.expires < time.monotonic(): return self.send_error(transport,addr,target,p.session_id,'target_unavailable')
            active=[s for s in self.sessions.values() if s.target_id==tid]
            if target.policy=='exclusive' and active: return self.send_error(transport,addr,target,p.session_id,'target_busy')
            if len(active)>=target.max_sessions: return self.send_error(transport,addr,target,p.session_id,'target_busy')
            sid=secrets.randbits(64); s=Session(sid,tid,addr,r.endpoint); self.sessions[sid]=s
            transport.sendto(encode(make(Message.CONNECT_OK,sid,jdump({'target_id':tid,'public_port':target.public_port})),key(target.a_secret,'a')),addr)
            # Tell B to create a local bridge for this A session.
            b=make(Message.OPEN,sid,jdump({'target_id':tid})); transport.sendto(encode(b,key(target.b_secret,'b')),r.endpoint)
            return
        if p.message in (Message.DATA,Message.CLOSE):
            s=self.sessions.get(p.session_id)
            if not s or s.target_id!=tid: return
            if role=='a' and addr==s.a_endpoint:
                s.last_activity=time.monotonic(); r=self.registrations.get(tid)
                if r: transport.sendto(encode(Packet(p.message,p.session_id,p.timestamp,p.nonce,p.payload,p.flags),key(r.target.b_secret,'b')),r.endpoint)
            elif role=='b' and addr==s.b_endpoint:
                s.last_activity=time.monotonic(); target=self.config.targets[tid]
                if p.message==Message.CLOSE: self.sessions.pop(s.session_id,None)
                transport.sendto(p.payload if False else encode(Packet(p.message,p.session_id,p.timestamp,p.nonce,p.payload,p.flags),key(target.a_secret,'a')),s.a_endpoint)
    async def public_data(self,tid,data,addr,transport):
        # Transparent mode: the endpoint must already be authorized by a CONNECT request.
        candidates=[s for s in self.sessions.values() if s.target_id==tid and s.a_endpoint==addr]
        if not candidates: return
        s=candidates[0]; r=self.registrations.get(tid)
        if not r: return
        s.last_activity=time.monotonic(); transport.sendto(encode(make(Message.DATA,s.session_id,data),key(self.config.targets[tid].b_secret,'b')),r.endpoint)
    def send_error(self,transport,addr,target,sid,code):
        transport.sendto(encode(make(Message.ERROR,sid,jdump({'error':code})),key(target.a_secret,'a')),addr)
