from __future__ import annotations

from dataclasses import dataclass
from fnmatch import fnmatch


@dataclass(frozen=True)
class HttpRoute:
    host: str
    path_prefix: str
    target_id: str
    service: str = 'default'

    def matches(self, host: str, path: str) -> bool:
        return fnmatch(host.lower().split(":", 1)[0], self.host.lower()) and path.startswith(self.path_prefix)

    @classmethod
    def from_mapping(cls, value: dict) -> "HttpRoute":
        host = str(value.get("host", "*"))
        path = str(value.get("path", value.get("path_prefix", "/")))
        target_id = value.get("target_id")
        if not target_id or not path.startswith("/"):
            raise ValueError("invalid HTTP route")
        return cls(host, path, str(target_id), str(value.get("service", "default")))
