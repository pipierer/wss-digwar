"""Message validation helpers.

The server never trusts the client. Every incoming message is validated
here before the dispatcher mutates any game state.
"""

from __future__ import annotations

from typing import Any, Optional

from .constants import (
    ALL_DIRECTIONS,
    ALL_TOOLS,
    PROTOCOL_VERSION,
    PLAYER_NAME_MAX_LEN,
    ROOM_NAME_MAX_LEN,
)


class ProtocolError(Exception):
    def __init__(self, message: str, code: str = "BAD_REQUEST"):
        super().__init__(message)
        self.code = code


def expect_str(value: Any, max_len: int) -> str:
    if not isinstance(value, str):
        raise ProtocolError("expected string")
    if len(value) > max_len:
        raise ProtocolError("string too long")
    return value


def expect_int(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ProtocolError("expected int")
    return value


def expect_dict(value: Any) -> dict:
    if not isinstance(value, dict):
        raise ProtocolError("expected object")
    return value


def validate_hello(payload: dict) -> dict:
    name = expect_str(payload.get("name", "anon"), PLAYER_NAME_MAX_LEN)
    version = payload.get("version", PROTOCOL_VERSION)
    if not isinstance(version, int):
        version = PROTOCOL_VERSION
    return {"name": name, "version": version}


def validate_create_room(payload: dict) -> dict:
    name = expect_str(payload.get("name", "Room"), ROOM_NAME_MAX_LEN)
    config = payload.get("config") or {}
    config = expect_dict(config) if config else {}
    # Only accept the keys we know; bounds clamped by Room.validate_config.
    allowed = {
        "width", "height", "max_players", "score_to_win",
        "round_time_limit_s", "move_cooldown_ms", "blast_range",
        "dirt_regen_enabled", "dirt_regen_interval_s",
    }
    clean = {k: v for k, v in config.items() if k in allowed}
    # Coerce the boolean flag explicitly (JSON bool stays bool).
    if "dirt_regen_enabled" in clean:
        clean["dirt_regen_enabled"] = bool(clean["dirt_regen_enabled"])
    return {"name": name, "config": clean}


def validate_move(payload: dict) -> str:
    direction = payload.get("direction")
    if direction not in ALL_DIRECTIONS:
        raise ProtocolError("invalid direction", code="BAD_DIRECTION")
    return direction


def validate_use_tool(payload: dict) -> dict:
    tool = payload.get("tool")
    if tool not in ALL_TOOLS:
        raise ProtocolError("invalid tool", code="BAD_TOOL")
    direction = payload.get("direction")
    if direction is not None and direction not in ALL_DIRECTIONS:
        raise ProtocolError("invalid direction", code="BAD_DIRECTION")
    return {"tool": tool, "direction": direction}


def validate_set_team(payload: dict) -> Optional[int]:
    team = payload.get("team")
    if team is None:
        return None
    if team not in (0, 1):
        raise ProtocolError("invalid team", code="BAD_TEAM")
    return int(team)
