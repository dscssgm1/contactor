from dataclasses import dataclass, field
import time
@dataclass
class Registration:
    target: object; endpoint: tuple|None=None; expires: float=0; generation: int=0
@dataclass
class Session:
    session_id: int; target_id: str; a_endpoint: tuple; b_endpoint: tuple; last_activity: float=field(default_factory=time.monotonic)
