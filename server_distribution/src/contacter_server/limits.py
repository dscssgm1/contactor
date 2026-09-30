from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class HttpLimits:
    max_request_line: int = 8192
    max_header_bytes: int = 65536
    max_header_count: int = 100
    max_body_bytes: int = 16 * 1024 * 1024
    connect_timeout: float = 5.0
    read_timeout: float = 30.0

    @classmethod
    def from_mapping(cls, value: dict | None) -> "HttpLimits":
        value = value or {}
        result = cls(**{k: value[k] for k in cls.__dataclass_fields__ if k in value})
        if any(v <= 0 for v in (result.max_request_line, result.max_header_bytes, result.max_header_count, result.max_body_bytes)):
            raise ValueError("HTTP limits must be positive")
        if result.connect_timeout <= 0 or result.read_timeout <= 0:
            raise ValueError("HTTP timeouts must be positive")
        return result
