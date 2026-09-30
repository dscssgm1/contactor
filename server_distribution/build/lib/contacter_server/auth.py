from __future__ import annotations
import time
from collections import OrderedDict
from contacter_wire.auth import key


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
