from __future__ import annotations
import base64
import hashlib
import hmac
import time
from collections import OrderedDict


def key(secret: bytes, role: str) -> bytes:
    return hmac.new(secret, ("contacter/v1/" + role).encode(), hashlib.sha256).digest()


def secret_bytes(value: str) -> bytes:
    try:
        raw = bytes.fromhex(value)
    except ValueError:
        raw = base64.b64decode(value, validate=True)
    if len(raw) < 16:
        raise ValueError("secret must contain at least 16 bytes")
    return raw


class ReplayCache:
    def __init__(self, ttl=60, limit=10000):
        self.ttl, self.limit, self._items = ttl, limit, OrderedDict()

    def seen(self, identity, nonce, now=None):
        now = time.monotonic() if now is None else now
        cache_key = (identity, nonce)
        for old_key, expiry in list(self._items.items()):
            if expiry <= now:
                self._items.pop(old_key, None)
        if cache_key in self._items:
            return True
        self._items[cache_key] = now + self.ttl
        while len(self._items) > self.limit:
            self._items.popitem(last=False)
        return False
