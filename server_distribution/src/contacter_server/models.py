from dataclasses import dataclass, field
import time


@dataclass
class TargetConfig:
    target_id: str
    b_secret: bytes
    a_secret: bytes
    public_port: int = 0
    policy: str = 'exclusive'
    max_sessions: int = 1
    services: dict = field(default_factory=dict)


@dataclass
class Registration:
    target: object
    endpoint: tuple | None = None
    expires: float = 0
    generation: int = 0


@dataclass
class Session:
    session_id: int
    target_id: str
    a_endpoint: tuple
    b_endpoint: tuple
    last_activity: float = field(default_factory=time.monotonic)
