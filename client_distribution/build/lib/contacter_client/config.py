from __future__ import annotations
import base64
import json


def secret_bytes(value: str) -> bytes:
    try:
        raw = bytes.fromhex(value)
    except ValueError:
        raw = base64.b64decode(value, validate=True)
    if len(raw) < 16:
        raise ValueError("secret must contain at least 16 bytes")
    return raw


def load_json(path: str) -> dict:
    with open(path, encoding="utf-8") as config_file:
        return json.load(config_file)
