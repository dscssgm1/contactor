from __future__ import annotations
import asyncio, hmac, hashlib, struct

MAX_FRAME = 1024 * 1024
_HEADER = struct.Struct('!BQI')
_PREFIX = struct.Struct('!I')
_TAG = 16

async def read_frame(reader: asyncio.StreamReader, secret: bytes):
    raw = await reader.readexactly(_PREFIX.size)
    size = _PREFIX.unpack(raw)[0]
    if size < _HEADER.size + _TAG or size > MAX_FRAME:
        raise ValueError('invalid frame size')
    body = await reader.readexactly(size)
    data, tag = body[:-_TAG], body[-_TAG:]
    expected = hmac.new(secret, data, hashlib.sha256).digest()[:_TAG]
    if not hmac.compare_digest(tag, expected):
        raise ValueError('stream authentication failed')
    message, session_id, payload_size = _HEADER.unpack(data[:_HEADER.size])
    payload = data[_HEADER.size:]
    if payload_size != len(payload):
        raise ValueError('invalid frame length')
    return message, session_id, payload

async def write_frame(writer: asyncio.StreamWriter, secret: bytes, message: int, session_id: int = 0, payload: bytes = b''):
    data = _HEADER.pack(message, session_id, len(payload)) + payload
    body = data + hmac.new(secret, data, hashlib.sha256).digest()[:_TAG]
    writer.write(_PREFIX.pack(len(body)) + body)
    await writer.drain()
