from __future__ import annotations
import time
from collections import OrderedDict

class ReplayCache:
    def __init__(self, ttl=60, limit=10000):
        self.ttl, self.limit, self._items = ttl, limit, OrderedDict()
    def seen(self, identity, nonce, now=None):
        now = time.monotonic() if now is None else now
        key = (identity, nonce)
        old = [k for k, expiry in self._items.items() if expiry <= now]
        for k in old: self._items.pop(k, None)
        if key in self._items: return True
        self._items[key] = now + self.ttl
        while len(self._items) > self.limit: self._items.popitem(last=False)
        return False
