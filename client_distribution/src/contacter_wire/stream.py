from __future__ import annotations
import asyncio, hmac, hashlib, struct
MAX_FRAME = 1024 * 1024
_HEADER = struct.Struct('!BQI')
_PREFIX = struct.Struct('!I')
_TAG = 16
async def read_frame(reader, secret):
    size = _PREFIX.unpack(await reader.readexactly(4))[0]
    if size < _HEADER.size + _TAG or size > MAX_FRAME: raise ValueError('invalid frame size')
    body = await reader.readexactly(size); data, tag = body[:-_TAG], body[-_TAG:]
    if not hmac.compare_digest(tag, hmac.new(secret, data, hashlib.sha256).digest()[:_TAG]): raise ValueError('stream authentication failed')
    message, sid, plen = _HEADER.unpack(data[:_HEADER.size]); payload = data[_HEADER.size:]
    if plen != len(payload): raise ValueError('invalid frame length')
    return message, sid, payload
async def write_frame(writer, secret, message, session_id=0, payload=b''):
    data = _HEADER.pack(message, session_id, len(payload)) + payload
    body = data + hmac.new(secret, data, hashlib.sha256).digest()[:_TAG]
    writer.write(_PREFIX.pack(len(body)) + body); await writer.drain()
