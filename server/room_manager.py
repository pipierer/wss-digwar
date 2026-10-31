"""Room manager: keeps the registry of all rooms and players."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Dict, Iterable, List, Optional, Tuple

from .constants import MAX_ROOMS, MAX_PLAYERS_PER_SERVER, ROOM_NAME_MAX_LEN
from .player import Player
from .room import Room
from .utils import gen_room_id

logger = logging.getLogger("digwar.room_manager")


class RoomManager:
    """Process-wide registry of rooms and connected players."""

    def __init__(self) -> None:
        self.rooms: Dict[str, Room] = {}
        self.players: Dict[str, Player] = {}
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Players
    # ------------------------------------------------------------------
    def register_player(self, player: Player) -> bool:
        if len(self.players) >= MAX_PLAYERS_PER_SERVER:
            return False
        if player.id in self.players:
            return False
        self.players[player.id] = player
        return True

    def unregister_player(self, player_id: str) -> None:
        player = self.players.pop(player_id, None)
        if player is None:
            return
        # Remove from any room they were in.
        room_id = player.in_room_id
        if room_id and room_id in self.rooms:
            room = self.rooms[room_id]
            room.remove_player(player_id)
            if room.is_empty():
                room.stop()
                del self.rooms[room_id]
                logger.info("room %s closed (empty)", room_id)

    def get_player(self, player_id: str) -> Optional[Player]:
        return self.players.get(player_id)

    # ------------------------------------------------------------------
    # Rooms
    # ------------------------------------------------------------------
    def list_rooms(self) -> List[dict]:
        now = time.monotonic() * 1000.0
        out = []
        for r in self.rooms.values():
            out.append({
                "id": r.id,
                "name": r.name,
                "state": r.state,
                "players": len(r.players),
                "max_players": r.config.max_players,
                "width": r.config.width,
                "height": r.config.height,
                "age_ms": int(now - r.created_at_ms),
            })
        return out

    def create_room(self, host: Player, name: str, config: Optional[dict]) -> Tuple[Optional[Room], str]:
        if len(self.rooms) >= MAX_ROOMS:
            return None, "server full"
        if host.in_room_id and host.in_room_id in self.rooms:
            return None, "already in a room"
        room_id = gen_room_id()
        # Ensure uniqueness (extremely unlikely collision, but be safe).
        while room_id in self.rooms:
            room_id = gen_room_id()
        room = Room(room_id, name[:ROOM_NAME_MAX_LEN], host.id, config)
        if not room.add_player(host):
            return None, "could not join room"
        self.rooms[room_id] = room
        logger.info("room created: %s by %s (%s)", room_id, host.id, room.name)
        return room, ""

    def get_room(self, room_id: str) -> Optional[Room]:
        return self.rooms.get(room_id)

    def join_room(self, player: Player, room_id: str) -> Tuple[Optional[Room], str]:
        if player.in_room_id and player.in_room_id in self.rooms:
            return None, "already in a room"
        room = self.rooms.get(room_id)
        if room is None:
            return None, "room not found"
        if room.state != "lobby":
            return None, "room not in lobby state"
        if not room.add_player(player):
            return None, "room full"
        return room, ""

    def leave_room(self, player: Player) -> None:
        room_id = player.in_room_id
        if not room_id:
            return
        room = self.rooms.get(room_id)
        if room is None:
            player.in_room_id = None
            return
        room.remove_player(player.id)
        player.in_room_id = None
        if room.is_empty():
            room.stop()
            del self.rooms[room_id]
            logger.info("room %s closed (empty)", room_id)

    def room_of(self, player: Player) -> Optional[Room]:
        if not player.in_room_id:
            return None
        return self.rooms.get(player.in_room_id)

    # ------------------------------------------------------------------
    # Snapshot helper for outgoing broadcasts
    # ------------------------------------------------------------------
    def players_in_room(self, room: Room) -> Iterable[Player]:
        for pid in list(room.players.keys()):
            p = self.players.get(pid)
            if p is not None:
                yield p
