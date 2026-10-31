"""Room / lobby state machine.

A Room owns a set of players in the pre-game lobby and (once started) a
Game instance. The Room is the single source of truth for "who is in this
match" and drives the Game's tick loop while the match is running.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Dict, List, Optional

from .constants import (
    CONFIG_BOUNDS,
    DEFAULT_GAME_CONFIG,
    PRE_GAME_GRACE_MS,
    RESPAWN_DELAY_MS,
    ROOM_NAME_MAX_LEN,
    TICK_DT,
)
from .game import Game, GameConfig
from .player import Player
from .utils import clamp, gen_room_id

logger = logging.getLogger("digwar.room")


def validate_config(raw: Optional[dict]) -> GameConfig:
    """Sanitize host-supplied config against server bounds."""
    cfg = dict(DEFAULT_GAME_CONFIG)
    if raw:
        for k, v in raw.items():
            if k not in cfg:
                continue
            # Booleans stay booleans (don't int() them).
            if k == "dirt_regen_enabled":
                cfg[k] = bool(v)
                continue
            try:
                cfg[k] = int(v)
            except (TypeError, ValueError):
                continue
    # Clamp every numeric field to its declared bounds.
    for k, (low, high) in CONFIG_BOUNDS.items():
        if k in cfg:
            cfg[k] = clamp(int(cfg[k]), low, high)
    return GameConfig(cfg)


class Room:
    """A lobby + match instance."""

    def __init__(self, room_id: str, name: str, host_id: str, raw_config: Optional[dict]):
        self.id = room_id
        self.name = (name or "Room")[:ROOM_NAME_MAX_LEN]
        self.host_id = host_id
        self.config: GameConfig = validate_config(raw_config)
        self.players: Dict[str, Player] = {}
        self.game: Optional[Game] = None
        self.state: str = "lobby"  # lobby | starting | playing | ended
        self.created_at_ms: float = time.monotonic() * 1000.0
        self._task: Optional[asyncio.Task] = None
        self._stop_event = asyncio.Event()
        self._state_dirty = True
        # Per-room broadcast queue (drained by GameServer).
        self.outgoing: List[dict] = []

    # ------------------------------------------------------------------
    # Lobby mutations
    # ------------------------------------------------------------------
    def add_player(self, player: Player) -> bool:
        if len(self.players) >= self.config.max_players:
            return False
        if player.id in self.players:
            return True
        self.players[player.id] = player
        player.in_room_id = self.id
        self._state_dirty = True
        return True

    def remove_player(self, player_id: str) -> None:
        if player_id in self.players:
            del self.players[player_id]
            self._state_dirty = True
        # Reassign host if needed.
        if self.host_id == player_id and self.players:
            self.host_id = next(iter(self.players.keys()))
            self._state_dirty = True
        # If the room is now empty and game finished, mark ended.

    def is_empty(self) -> bool:
        return not self.players

    def is_host(self, player_id: str) -> bool:
        return self.host_id == player_id

    def set_team(self, player: Player, team: Optional[int]) -> None:
        if team is None or team in (0, 1):
            player.team = team
            self._state_dirty = True

    # ------------------------------------------------------------------
    # Game lifecycle
    # ------------------------------------------------------------------
    def can_start(self) -> bool:
        return self.state == "lobby" and len(self.players) >= 1

    def start(self) -> bool:
        if not self.can_start():
            logger.warning("start() refused: state=%s, players=%d", self.state, len(self.players))
            return False
        logger.info("start(): creating Game for room %s", self.id)
        self.state = "starting"
        self._state_dirty = True
        try:
            self.game = Game(self.config, dict(self.players))
            self.game.start()
        except Exception:
            logger.exception("start(): Game creation failed for room %s", self.id)
            self.state = "lobby"
            self._state_dirty = True
            return False
        self.state = "playing"
        # Launch the tick loop.
        self._stop_event.clear()
        self._task = asyncio.create_task(self._run_loop())
        logger.info("start(): room %s now playing, tick loop launched", self.id)
        return True

    def stop(self) -> None:
        self._stop_event.set()
        if self._task is not None:
            self._task.cancel()
            self._task = None
        self.state = "ended"
        self._state_dirty = True

    async def _run_loop(self) -> None:
        """Fixed-timestep game loop."""
        try:
            last = time.monotonic()
            while not self._stop_event.is_set():
                now = time.monotonic()
                dt = now - last
                last = now
                if self.game is not None and not self.game.over:
                    self.game.tick()
                    if self.game.over:
                        # Game ended: broadcast GAME_END so clients show the
                        # victory/defeat overlay. We then wait a few seconds
                        # before resetting the room to lobby, so players have
                        # time to see the result. The reset is done in a
                        # background task so this loop can exit cleanly.
                        winner_id = self.game.winner_id
                        scores = {p.id: p.serialize() for p in self.players.values()}
                        self._broadcast({"type": "GAME_END",
                                         "winner_id": winner_id,
                                         "scores": scores})
                        # Schedule the reset 4 seconds later (non-blocking).
                        asyncio.create_task(self._delayed_reset(4.0))
                        return
                await asyncio.sleep(TICK_DT)
        except asyncio.CancelledError:
            pass
        except Exception:  # pragma: no cover
            logger.exception("room loop crashed: %s", self.id)

    async def _delayed_reset(self, delay_s: float) -> None:
        """Wait `delay_s` seconds then reset the room to lobby. This gives
        clients time to display the GAME_END overlay before the ROOM_STATE
        message switches them back to the room screen."""
        try:
            await asyncio.sleep(delay_s)
            # Only reset if the room is still in a non-lobby state (players
            # may have left in the meantime, which would have already reset
            # or closed the room).
            if self.state in ("playing", "ended"):
                self._reset_to_lobby()
        except asyncio.CancelledError:
            pass

    def _reset_to_lobby(self) -> None:
        """Reset the room to lobby state after a game ends. Players keep their
        id/name/team/score (so the lobby UI shows the scoreboard), but the
        game instance is dropped and a fresh game can be started."""
        self.game = None
        self.state = "lobby"
        # Reset alive/health/position so the lobby player list is clean.
        from .player import Player
        for p in self.players.values():
            p.alive = True
            p.health = 100
            p.respawn_at_ms = 0.0
        self._state_dirty = True
        # Broadcast the fresh lobby state so clients switch back to the room
        # screen and the host can start a new game.
        self._broadcast(self.lobby_state())
        logger.info("room %s reset to lobby after game end", self.id)

    # ------------------------------------------------------------------
    # Outgoing message queue (drained by GameServer per-connection)
    # ------------------------------------------------------------------
    def _broadcast(self, msg: dict) -> None:
        self.outgoing.append(msg)

    def consume_outgoing(self) -> List[dict]:
        if not self.outgoing:
            return []
        out = self.outgoing
        self.outgoing = []
        return out

    # ------------------------------------------------------------------
    # Snapshot
    # ------------------------------------------------------------------
    def lobby_state(self) -> dict:
        return {
            "type": "ROOM_STATE",
            "room": {
                "id": self.id,
                "name": self.name,
                "host_id": self.host_id,
                "state": self.state,
                "config": self.config.to_dict(),
                "players": [
                    {"id": p.id, "name": p.name, "team": p.team,
                     "score": p.score, "alive": p.alive, "is_host": p.id == self.host_id}
                    for p in self.players.values()
                ],
            },
        }

    def game_snapshot(self) -> Optional[dict]:
        if self.game is None:
            return None
        snap = self.game.serialize_snapshot()
        if snap is None:
            return None
        snap["type"] = "SNAPSHOT"
        return snap

    def game_full_state(self) -> Optional[dict]:
        if self.game is None:
            return None
        full = self.game.serialize_full()
        full["type"] = "GAME_START"
        return full
