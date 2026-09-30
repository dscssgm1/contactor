from __future__ import annotations
import hashlib
import hmac


def key(secret: bytes, role: str) -> bytes:
    return hmac.new(secret, ("contacter/v1/" + role).encode(), hashlib.sha256).digest()


def secret_bytes(value: str) -> bytes:
    import base64
    try:
        raw = bytes.fromhex(value)
    except ValueError:
        raw = base64.b64decode(value, validate=True)
    if len(raw) < 16:
        raise ValueError("secret must contain at least 16 bytes")
    return raw
