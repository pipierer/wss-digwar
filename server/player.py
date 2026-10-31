"""Player server-side state.

Positions are STRICT integers. There is no float position anywhere on the
server; visual interpolation is purely a client concern. A player's last
move time enforces a server-side cooldown so a malicious client cannot
spam moves faster than MOVE_COOLDOWN_MS.
"""

from __future__ import annotations

import time
from typing import Optional

from .constants import (
    DIR_DOWN,
    DIRECTION_VECTORS,
    PLAYER_INITIAL_SCORE,
    PLAYER_MAX_HEALTH,
    PLAYER_NAME_MAX_LEN,
)


def _monotonic_ms() -> float:
    return time.monotonic() * 1000.0


class Player:
    __slots__ = (
        "id",
        "name",
        "x",
        "y",
        "facing",
        "alive",
        "health",
        "score",
        "kills",
        "deaths",
        "team",
        "last_move_ms",
        "last_tool_ms",
        "last_tool",
        "respawn_at_ms",
        "spawn_index",
        "last_damaged_by",
        "in_room_id",
        "ws",
        "connected",
    )

    def __init__(self, player_id: str, name: str, ws: object | None = None):
        self.id = player_id
        self.name = (name or "anon")[:PLAYER_NAME_MAX_LEN]
        self.x: int = 0
        self.y: int = 0
        self.facing: str = DIR_DOWN
        self.alive: bool = True
        self.health: int = PLAYER_MAX_HEALTH
        self.score: int = PLAYER_INITIAL_SCORE
        self.kills: int = 0
        self.deaths: int = 0
        self.team: Optional[int] = None
        self.last_move_ms: float = 0.0
        self.last_tool_ms: float = 0.0
        self.last_tool: Optional[str] = None
        self.respawn_at_ms: float = 0.0
        self.spawn_index: int = 0
        self.last_damaged_by: Optional[str] = None
        self.in_room_id: Optional[str] = None
        self.ws = ws
        self.connected: bool = True

    # ------------------------------------------------------------------
    # Mutators (called only by Game with validated inputs)
    # ------------------------------------------------------------------
    def place_at(self, x: int, y: int, facing: str = DIR_DOWN) -> None:
        self.x = int(x)
        self.y = int(y)
        self.facing = facing
        self.health = PLAYER_MAX_HEALTH
        self.alive = True
        self.last_damaged_by = None

    def kill(self) -> None:
        self.alive = False
        self.health = 0
        self.deaths += 1
        self.respawn_at_ms = _monotonic_ms()  # Game will offset by RESPAWN_DELAY

    def damage(self, amount: int, attacker_id: Optional[str]) -> bool:
        """Apply damage. Returns True if the player just died."""
        if not self.alive:
            return False
        self.health = max(0, self.health - int(amount))
        if attacker_id is not None:
            self.last_damaged_by = attacker_id
        if self.health <= 0:
            self.kill()
            return True
        return False

    def add_score(self, points: int) -> None:
        self.score += int(points)

    def can_move_now(self, cooldown_ms: int) -> bool:
        return (_monotonic_ms() - self.last_move_ms) >= cooldown_ms

    def can_use_tool_now(self, tool: str, cooldowns: dict) -> bool:
        cd = cooldowns.get(tool, 0)
        return (_monotonic_ms() - self.last_tool_ms) >= cd

    def stamp_move(self) -> None:
        self.last_move_ms = _monotonic_ms()

    def stamp_tool(self, tool: str) -> None:
        self.last_tool_ms = _monotonic_ms()
        self.last_tool = tool

    def set_facing(self, direction: str) -> None:
        if direction in DIRECTION_VECTORS:
            self.facing = direction

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------
    def serialize(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "x": self.x,
            "y": self.y,
            "facing": self.facing,
            "alive": self.alive,
            "health": self.health,
            "score": self.score,
            "kills": self.kills,
            "deaths": self.deaths,
            "team": self.team,
            "respawn_in_ms": max(0, int(self.respawn_at_ms - _monotonic_ms())) if not self.alive else 0,
        }
