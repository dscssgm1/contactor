from __future__ import annotations

import base64
import json
import ssl
from dataclasses import dataclass, field

from .models import TargetConfig


def secret_bytes(value):
    try:
        raw = bytes.fromhex(value)
    except ValueError:
        raw = base64.b64decode(value, validate=True)
    if len(raw) < 16:
        raise ValueError('secret must contain at least 16 bytes')
    return raw


def load_json(path):
    with open(path, encoding='utf-8') as f:
        return json.load(f)


@dataclass
class TunnelConfig:
    host: str = '0.0.0.0'
    port: int = 4443
    tls_context: ssl.SSLContext | None = None
    stream_secret: bytes = b''


@dataclass
class RelayConfig:
    listen_host: str
    listen_port: int
    targets: dict
    session_idle: float = 60
    max_payload: int = 1200
    tunnel_host: str = '0.0.0.0'
    tunnel_port: int = 4443
    tls_context: ssl.SSLContext | None = None
    stream_secret: bytes = b''
    http_listen_host: str | None = None
    http_listen_port: int | None = None
    http_routes: list = field(default_factory=list)
    http_limits: dict = field(default_factory=dict)


def load_relay(path):
    d = load_json(path)
    targets = {}
    for tid, x in d.get('targets', {}).items():
        port = int(x.get('public_port', 0))
        if not 0 <= port <= 65535:
            raise ValueError('invalid public_port')
        policy = x.get('multiple_a_policy', x.get('policy', 'exclusive'))
        if policy not in ('exclusive', 'replace', 'shared'):
            raise ValueError('invalid policy')
        targets[tid] = TargetConfig(
            tid, secret_bytes(x['b_secret']), secret_bytes(x['a_secret']),
            port, policy, int(x.get('max_sessions', 1)))

    tls = None
    if d.get('tls_cert') and d.get('tls_key'):
        tls = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
        tls.load_cert_chain(d['tls_cert'], d['tls_key'])
    stream_secret = secret_bytes(d['stream_secret']) if d.get('stream_secret') else b''
    return RelayConfig(
        d.get('listen_host', '0.0.0.0'), int(d.get('listen_port', 40000)), targets,
        float(d.get('session_idle_seconds', 60)), int(d.get('max_payload_bytes', 1200)),
        d.get('tunnel_host', '0.0.0.0'), int(d.get('tunnel_port', 4443)), tls,
        stream_secret, d.get('http_listen_host'), d.get('http_listen_port'),
        d.get('http_routes', []), d.get('http_limits', {}))
