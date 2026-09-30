"""Wire protocol for the Contacter UDP relay."""
from __future__ import annotations
import enum, hmac, hashlib, struct, time
from dataclasses import dataclass

MAGIC = b"CT"
VERSION = 1
TAG_SIZE = 16
# magic, version, type, flags, session id, timestamp, nonce, payload length
HEADER = struct.Struct("!2sBBHQdQH")
MAX_PAYLOAD = 1200

class Message(enum.IntEnum):
    REGISTER = 1
    REGISTER_OK = 2
    KEEPALIVE = 3
    CONNECT = 4
    CONNECT_OK = 5
    OPEN = 6
    DATA = 7
    CLOSE = 8
    ERROR = 9

@dataclass(frozen=True)
class Packet:
    message: Message
    session_id: int
    timestamp: float
    nonce: int
    payload: bytes = b""
    flags: int = 0

def key(secret: bytes, role: str) -> bytes:
    return hmac.new(secret, ("contacter/v1/" + role).encode(), hashlib.sha256).digest()

def encode(packet: Packet, secret: bytes) -> bytes:
    if len(packet.payload) > MAX_PAYLOAD:
        raise ValueError("payload too large")
    header = HEADER.pack(MAGIC, VERSION, int(packet.message), packet.flags,
                         packet.session_id, packet.timestamp, packet.nonce, len(packet.payload))
    body = header + packet.payload
    return body + hmac.new(secret, body, hashlib.sha256).digest()[:TAG_SIZE]

def decode(data: bytes, secret: bytes, *, now: float | None = None, skew: float = 30) -> Packet:
    if len(data) < HEADER.size + TAG_SIZE:
        raise ValueError("truncated packet")
    magic, version, typ, flags, sid, timestamp, nonce, size = HEADER.unpack_from(data)
    if magic != MAGIC or version != VERSION or size > MAX_PAYLOAD:
        raise ValueError("invalid header")
    expected = HEADER.size + size + TAG_SIZE
    if len(data) != expected:
        raise ValueError("invalid length")
    body, tag = data[:-TAG_SIZE], data[-TAG_SIZE:]
    if not hmac.compare_digest(hmac.new(secret, body, hashlib.sha256).digest()[:TAG_SIZE], tag):
        raise ValueError("authentication failed")
    if now is not None and abs(now - timestamp) > skew:
        raise ValueError("stale packet")
    try:
        message = Message(typ)
    except ValueError as exc:
        raise ValueError("unknown message") from exc
    return Packet(message, sid, timestamp, nonce, data[HEADER.size:HEADER.size + size], flags)

def make(message: Message, session_id: int = 0, payload: bytes = b"", flags: int = 0) -> Packet:
    return Packet(message, session_id, time.time(), __import__('secrets').randbits(64), payload, flags)
