from __future__ import annotations
import base64, json
from dataclasses import dataclass
from contacter_wire.auth import secret_bytes

def secret_bytes(value):
    try:
        raw = bytes.fromhex(value)
    except ValueError:
        raw = base64.b64decode(value, validate=True)
    if len(raw) < 16: raise ValueError('secret must contain at least 16 bytes')
    return raw

def load_json(path):
    with open(path, encoding='utf-8') as f: return json.load(f)

@dataclass
class TargetConfig:
    target_id: str; b_secret: bytes; a_secret: bytes; public_port: int
    policy: str = 'exclusive'; max_sessions: int = 1

@dataclass
class RelayConfig:
    listen_host: str; listen_port: int; targets: dict; session_idle: float = 60; max_payload: int = 1200

def load_relay(path):
    d=load_json(path); targets={}
    for tid, x in d.get('targets', {}).items():
        p=x.get('public_port', 0)
        if not 0 <= p <= 65535: raise ValueError('invalid public_port')
        policy=x.get('multiple_a_policy', x.get('policy','exclusive'))
        if policy not in ('exclusive','replace','shared'): raise ValueError('invalid policy')
        targets[tid]=TargetConfig(tid, secret_bytes(x['b_secret']), secret_bytes(x['a_secret']), p, policy, int(x.get('max_sessions',1)))
    return RelayConfig(d.get('listen_host','0.0.0.0'), int(d.get('listen_port',40000)), targets, float(d.get('session_idle_seconds',60)), int(d.get('max_payload_bytes',1200)))
