from __future__ import annotations

from dataclasses import dataclass
from fnmatch import fnmatch
from urllib.parse import urlsplit


@dataclass(frozen=True)
class HttpRoute:
    host: str
    path_prefix: str
    upstream_host: str
    upstream_port: int

    def matches(self, host: str, path: str) -> bool:
        return fnmatch(host.lower().split(":", 1)[0], self.host.lower()) and path.startswith(self.path_prefix)

    @classmethod
    def from_mapping(cls, value: dict) -> "HttpRoute":
        host = str(value.get("host", "*"))
        path = str(value.get("path", value.get("path_prefix", "/")))
        upstream = value.get("upstream")
        if upstream:
            parsed = urlsplit(str(upstream) if "://" in str(upstream) else "http://" + str(upstream))
            uh, port = parsed.hostname, parsed.port or 80
        else:
            uh, port = value.get("upstream_host"), value.get("upstream_port")
        if not uh or not port or not 1 <= int(port) <= 65535 or not path.startswith("/"):
            raise ValueError("invalid HTTP route")
        return cls(host, path, str(uh), int(port))
