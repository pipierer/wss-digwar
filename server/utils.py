"""Small server-side helpers."""

from __future__ import annotations

import json
import os
import random
import string
from typing import Any


def gen_id(prefix: str = "", length: int = 8) -> str:
    """Generate a short random id with an optional prefix."""
    alphabet = string.ascii_lowercase + string.digits
    body = "".join(random.choices(alphabet, k=length))
    return f"{prefix}{body}" if prefix else body


def gen_room_id() -> str:
    from .constants import ROOM_ID_LEN
    return gen_id(length=ROOM_ID_LEN).upper()


def clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, value))


def env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def json_dumps(obj: Any) -> str:
    """Compact JSON encoder used for all WS messages."""
    return json.dumps(obj, separators=(",", ":"))


def json_loads(raw: str | bytes) -> Any:
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="strict")
    return json.loads(raw)
