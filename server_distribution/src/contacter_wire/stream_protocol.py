"""Length-prefixed multiplexed stream protocol.

Each frame is encoded as a four-byte big-endian body length followed by a
one-byte frame type, an eight-byte stream identifier, and an opaque payload.
The parser accepts arbitrary chunks and returns every complete frame found.
"""
from __future__ import annotations

import enum
import struct
from dataclasses import dataclass


PREFIX = struct.Struct("!I")
HEADER = struct.Struct("!BQ")
HEADER_SIZE = HEADER.size
MAX_FRAME_SIZE = 16 * 1024 * 1024
MAX_PAYLOAD_SIZE = MAX_FRAME_SIZE - HEADER_SIZE


class ProtocolError(ValueError):
    """Raised when a stream frame is malformed or violates a protocol limit."""


class FrameType(enum.IntEnum):
    OPEN = 1
    DATA = 2
    CLOSE = 3
    ERROR = 4
    PING = 5
    PONG = 6


@dataclass(frozen=True)
class Frame:
    frame_type: FrameType
    stream_id: int = 0
    payload: bytes = b""

    @property
    def type(self) -> FrameType:
        return self.frame_type


def _coerce_frame(frame_or_type, stream_id: int = 0, payload: bytes = b"") -> Frame:
    if isinstance(frame_or_type, Frame):
        if stream_id != 0 or payload != b"":
            raise ProtocolError("frame arguments cannot be combined with Frame")
        return frame_or_type
    try:
        frame_type = FrameType(frame_or_type)
    except (TypeError, ValueError) as exc:
        raise ProtocolError("unknown frame type") from exc
    return Frame(frame_type, stream_id, payload)


def encode_frame(frame_or_type, stream_id: int = 0, payload: bytes = b"") -> bytes:
    """Encode a Frame, or ``(frame_type, stream_id, payload)``."""
    frame = _coerce_frame(frame_or_type, stream_id, payload)
    if not isinstance(frame.payload, (bytes, bytearray, memoryview)):
        raise ProtocolError("payload must be bytes-like")
    if not isinstance(frame.stream_id, int) or isinstance(frame.stream_id, bool) or not 0 <= frame.stream_id <= 0xFFFFFFFFFFFFFFFF:
        raise ProtocolError("invalid stream id")
    payload = bytes(frame.payload)
    if len(payload) > MAX_PAYLOAD_SIZE:
        raise ProtocolError("payload too large")
    body = HEADER.pack(int(frame.frame_type), frame.stream_id) + payload
    return PREFIX.pack(len(body)) + body


def decode_frame(data: bytes, *, max_frame_size: int = MAX_FRAME_SIZE) -> Frame:
    """Decode exactly one complete frame."""
    if not isinstance(data, (bytes, bytearray, memoryview)):
        raise ProtocolError("frame must be bytes-like")
    raw = bytes(data)
    if len(raw) < PREFIX.size:
        raise ProtocolError("truncated frame prefix")
    (size,) = PREFIX.unpack_from(raw)
    if size < HEADER_SIZE:
        raise ProtocolError("invalid frame length")
    if size > max_frame_size:
        raise ProtocolError("frame too large")
    if len(raw) != PREFIX.size + size:
        raise ProtocolError("invalid frame length")
    try:
        typ, stream_id = HEADER.unpack_from(raw, PREFIX.size)
        frame_type = FrameType(typ)
    except (struct.error, ValueError) as exc:
        raise ProtocolError("invalid frame header") from exc
    return Frame(frame_type, stream_id, raw[PREFIX.size + HEADER_SIZE:])


class StreamParser:
    """Incrementally parse sticky and partial length-prefixed frames."""

    def __init__(self, *, max_frame_size: int = MAX_FRAME_SIZE):
        if max_frame_size < HEADER_SIZE:
            raise ValueError("max_frame_size is too small")
        self.max_frame_size = max_frame_size
        self._buffer = bytearray()

    def feed(self, data: bytes) -> list[Frame]:
        if not isinstance(data, (bytes, bytearray, memoryview)):
            raise ProtocolError("input must be bytes-like")
        self._buffer.extend(data)
        frames = []
        while len(self._buffer) >= PREFIX.size:
            (size,) = PREFIX.unpack_from(self._buffer)
            if size < HEADER_SIZE:
                raise ProtocolError("invalid frame length")
            if size > self.max_frame_size:
                raise ProtocolError("frame too large")
            total = PREFIX.size + size
            if len(self._buffer) < total:
                break
            raw = bytes(self._buffer[:total])
            del self._buffer[:total]
            frames.append(decode_frame(raw, max_frame_size=self.max_frame_size))
        return frames

    def close(self) -> None:
        """Reject a truncated frame at end of stream."""
        if self._buffer:
            raise ProtocolError("truncated frame")

    @property
    def buffered_bytes(self) -> int:
        return len(self._buffer)


# Short aliases for callers that prefer encode/decode naming.
encode = encode_frame
decode = decode_frame
Parser = StreamParser
