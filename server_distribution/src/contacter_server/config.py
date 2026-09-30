from dataclasses import dataclass
import ssl
from .models import TargetConfig

def secret_bytes(value):
    import base64
    try: raw=bytes.fromhex(value)
    except ValueError: raw=base64.b64decode(value, validate=True)
    if len(raw)<16: raise ValueError('secret must contain at least 16 bytes')
    return raw

def load_json(path):
    import json
    with open(path, encoding='utf-8') as f: return json.load(f)

@dataclass
class TunnelConfig:
    host: str = '0.0.0.0'
    port: int = 4443
    tls_context: ssl.SSLContext | None = None
    stream_secret: bytes = b''

@dataclass
class RelayConfig:
    listen_host: str; listen_port: int; targets: dict; session_idle: float=60; max_payload: int=1200
    tunnel_host: str='0.0.0.0'; tunnel_port: int=4443; tls_context: ssl.SSLContext|None=None; stream_secret: bytes=b''

def load_relay(path):
    d=load_json(path); targets={}
    for tid,x in d.get('targets',{}).items():
        p=x.get('public_port',0)
        policy=x.get('multiple_a_policy',x.get('policy','exclusive'))
        targets[tid]=TargetConfig(tid,secret_bytes(x['b_secret']),secret_bytes(x['a_secret']),p,policy,int(x.get('max_sessions',1)))
    tls=None
    if d.get('tls_cert') and d.get('tls_key'):
        tls=ssl.create_default_context(ssl.Purpose.CLIENT_AUTH); tls.load_cert_chain(d['tls_cert'],d['tls_key'])
    stream_secret=secret_bytes(d['stream_secret']) if d.get('stream_secret') else b''
    return RelayConfig(d.get('listen_host','0.0.0.0'),int(d.get('listen_port',40000)),targets,float(d.get('session_idle_seconds',60)),int(d.get('max_payload_bytes',1200)),d.get('tunnel_host','0.0.0.0'),int(d.get('tunnel_port',4443)),tls,stream_secret)
