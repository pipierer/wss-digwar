"""Authoritative game logic.

All gameplay decisions happen here. The server enforces:

* Strict one-cell-per-input movement (no diagonals, no fractions, no gliding).
* Server-side cooldowns so a malicious client cannot spam moves.
* Bounds + collision checks on every action.
* Atomic state transitions (a move is applied or rejected as a whole).
* Deterministic respawn / score / death bookkeeping.

The Game owns the World, Players, Bombs and Explosions for a single match.
It runs a fixed-tick loop driven by the Room.
"""

from __future__ import annotations

import logging
import time
from typing import Dict, List, Optional, Tuple

from .bomb import Bomb, Explosion, compute_blast_cells
from .constants import (
    BOMB_BLAST_RANGE,
    BOMB_DAMAGE,
    BOMB_FUSE_MS,
    BOMB_FUSE_MS as _BOMB_FUSE_MS,
    DEFAULT_GAME_CONFIG,
    DIR_DOWN,
    DIRECTION_VECTORS,
    EXPLODABLE_TILES,
    EXPLOSION_DURATION_MS,
    KNIFE_DAMAGE,
    MOVE_COOLDOWN_MS,
    PLAYER_MAX_HEALTH,
    RESPAWN_DELAY_MS,
    TILE_DIRT,
    TILE_FLOOR,
    TILE_ROCK,
    TILE_WALL,
    TOOL_BOMB,
    TOOL_KNIFE,
    TOOL_SHOVEL,
    TOOL_COOLDOWN_MS,
    SHOVELABLE_TILES,
)
from .player import Player
from .utils import gen_id
from .world import World

logger = logging.getLogger("digwar.game")


class GameConfig:
    """Validated match configuration."""

    __slots__ = (
        "width", "height", "max_players", "score_to_win",
        "round_time_limit_s", "move_cooldown_ms", "blast_range",
        "bomb_fuse_ms", "explosion_duration_ms",
        "dirt_regen_enabled", "dirt_regen_interval_s",
    )

    def __init__(self, raw: Optional[dict] = None):
        cfg = dict(DEFAULT_GAME_CONFIG)
        if raw:
            for k, v in raw.items():
                if k in cfg:
                    cfg[k] = v
        self.width = int(cfg["width"])
        self.height = int(cfg["height"])
        self.max_players = int(cfg["max_players"])
        self.score_to_win = int(cfg["score_to_win"])
        self.round_time_limit_s = int(cfg["round_time_limit_s"])
        self.move_cooldown_ms = int(cfg["move_cooldown_ms"])
        self.blast_range = int(cfg.get("blast_range", BOMB_BLAST_RANGE))
        self.bomb_fuse_ms = int(BOMB_FUSE_MS)
        self.explosion_duration_ms = int(EXPLOSION_DURATION_MS)
        # Dirt regen mode: if enabled, all dirt is rebuilt every N seconds.
        self.dirt_regen_enabled = bool(cfg.get("dirt_regen_enabled", False))
        self.dirt_regen_interval_s = int(cfg.get("dirt_regen_interval_s", 30))

    def to_dict(self) -> dict:
        return {
            "width": self.width,
            "height": self.height,
            "max_players": self.max_players,
            "score_to_win": self.score_to_win,
            "round_time_limit_s": self.round_time_limit_s,
            "move_cooldown_ms": self.move_cooldown_ms,
            "blast_range": self.blast_range,
            "bomb_fuse_ms": self.bomb_fuse_ms,
            "explosion_duration_ms": self.explosion_duration_ms,
            "dirt_regen_enabled": self.dirt_regen_enabled,
            "dirt_regen_interval_s": self.dirt_regen_interval_s,
        }


class Game:
    """A single match instance."""

    def __init__(self, config: GameConfig, players: Dict[str, Player]):
        self.config = config
        self.world = World(config.width, config.height, seed=None,
                           max_players=config.max_players)
        self.players: Dict[str, Player] = players
        self.bombs: List[Bomb] = []
        self.explosions: List[Explosion] = []

        self.started_at_ms: float = 0.0
        self.ended_at_ms: float = 0.0
        self.over: bool = False
        self.winner_id: Optional[str] = None
        self.last_snapshot_tick: int = -1
        self.tick_count: int = 0
        self._dirty: bool = True          # snapshot worth sending
        self._last_snapshot_ms: float = 0.0
        self._heartbeat_ms: float = 1000.0  # send a snapshot at least every 1s
        # Dirt regen timer: when enabled, dirt is rebuilt at this timestamp.
        self._next_dirt_regen_ms: float = 0.0

        # Reset per-game stats for every player. Without this, scores from a
        # previous game would carry over and `_check_end_conditions` would
        # immediately end the new game (since the previous winner's score is
        # already >= score_to_win).
        for p in self.players.values():
            p.score = 0
            p.kills = 0
            p.deaths = 0
            p.alive = True
            p.health = PLAYER_MAX_HEALTH
            p.respawn_at_ms = 0.0
            p.last_damaged_by = None

        # Pre-assign spawn indices to players in a stable order.
        ordered = sorted(self.players.values(), key=lambda p: p.id)
        for i, p in enumerate(ordered):
            p.spawn_index = i
            self._spawn_player(p, immediate=True)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def start(self) -> None:
        self.started_at_ms = time.monotonic() * 1000.0
        self.over = False
        self.winner_id = None
        # Schedule the first dirt regen tick (if enabled).
        if self.config.dirt_regen_enabled:
            self._next_dirt_regen_ms = self.started_at_ms + self.config.dirt_regen_interval_s * 1000
            logger.info("dirt regen enabled: every %ds", self.config.dirt_regen_interval_s)
        logger.info("game started: %dx%d, %d players",
                    self.config.width, self.config.height, len(self.players))

    def elapsed_ms(self) -> float:
        if self.started_at_ms == 0:
            return 0
        return time.monotonic() * 1000.0 - self.started_at_ms

    def time_left_ms(self) -> float:
        if self.config.round_time_limit_s <= 0:
            return float("inf")
        return max(0.0, self.config.round_time_limit_s * 1000 - self.elapsed_ms())

    # ------------------------------------------------------------------
    # Spawning
    # ------------------------------------------------------------------
    def _spawn_player(self, player: Player, immediate: bool = False,
                      random_spawn: bool = False) -> None:
        """Place the player on a spawn cell.

        - immediate=True (game start): use the player's assigned spawn_index
          so each player starts at a deterministic, distinct position.
        - random_spawn=True (respawn after death): pick a RANDOM spawn cell
          so the player does not always reappear at the same spot.
        """
        import random as _random
        if random_spawn and self.world.spawns:
            spawn = self.world.get_random_spawn(_random.Random())
        else:
            spawn = self.world.get_spawn(player.spawn_index)
        # Ensure spawn cell is floor; if dirt covered it, clear it.
        self.world.set_tile(spawn[0], spawn[1], TILE_FLOOR)
        player.place_at(spawn[0], spawn[1], facing=DIR_DOWN)
        player.last_move_ms = 0.0
        player.last_tool_ms = 0.0
        self._dirty = True

    def _respawn_pending(self) -> List[Player]:
        now = time.monotonic() * 1000.0
        out: List[Player] = []
        for p in self.players.values():
            if not p.alive and p.respawn_at_ms > 0 and now >= p.respawn_at_ms:
                out.append(p)
        return out

    def _schedule_respawn(self, player: Player) -> None:
        player.respawn_at_ms = time.monotonic() * 1000.0 + RESPAWN_DELAY_MS

    # ------------------------------------------------------------------
    # Movement (the critical path)
    # ------------------------------------------------------------------
    def try_move(self, player: Player, direction: str) -> bool:
        """Validate and apply a one-cell move.

        Strict rules enforced:
          * Player must be alive.
          * Direction must be one of the 4 cardinals (no diagonals).
          * Server-side cooldown must have elapsed.
          * Target cell must be in-bounds and walkable (FLOOR).
          * Target cell must not be occupied by another alive player.
          * Target cell must not be occupied by a live bomb.
        On success the player's (x, y) becomes the new integer cell and the
        facing is updated. Returns True on success, False otherwise.
        """
        if self.over:
            return False
        if not player.alive:
            return False
        if direction not in DIRECTION_VECTORS:
            return False
        # Cooldown: only enforced when the player actually MOVES. Turning in
        # place (facing change) is always allowed so the player can orient
        # toward a wall to dig it, even if the move itself is blocked.
        can_move = player.can_move_now(self.config.move_cooldown_ms)

        dx, dy = DIRECTION_VECTORS[direction]
        new_x = player.x + dx
        new_y = player.y + dy

        # Always update facing first, even if the move is blocked. This way
        # the player can turn toward a wall/dirt and then use the shovel to
        # destroy it. The move itself is rejected below if blocked.
        if player.facing != direction:
            player.facing = direction
            self._dirty = True

        # If on cooldown, do not move (but facing was already updated above).
        if not can_move:
            return False

        # Bounds (defensive: get_tile already returns WALL OOB).
        if not self.world.in_bounds(new_x, new_y):
            return False
        # Tile walkability (no walls, dirt, rocks).
        if self.world.get_tile(new_x, new_y) != TILE_FLOOR:
            return False
        # Other alive player on the target cell?
        for other in self.players.values():
            if other is player:
                continue
            if other.alive and other.x == new_x and other.y == new_y:
                return False
        # Live bomb on target?
        for b in self.bombs:
            if b.x == new_x and b.y == new_y:
                return False

        # All checks passed: apply atomically.
        player.x = new_x
        player.y = new_y
        # facing was already set above.
        player.stamp_move()
        self._dirty = True
        return True

    # ------------------------------------------------------------------
    # Tools
    # ------------------------------------------------------------------
    def try_use_tool(self, player: Player, tool: str, direction: Optional[str] = None) -> bool:
        if self.over or not player.alive:
            return False
        if tool not in (TOOL_SHOVEL, TOOL_KNIFE, TOOL_BOMB):
            return False
        if not player.can_use_tool_now(tool, TOOL_COOLDOWN_MS):
            return False

        # Use provided direction if valid, else player's current facing.
        facing = direction if direction in DIRECTION_VECTORS else player.facing

        if tool == TOOL_SHOVEL:
            ok = self._use_shovel(player, facing)
        elif tool == TOOL_KNIFE:
            ok = self._use_knife(player, facing)
        else:  # TOOL_BOMB
            ok = self._use_bomb(player)
        if ok:
            player.set_facing(facing)
            player.stamp_tool(tool)
            self._dirty = True
        return ok

    def _use_shovel(self, player: Player, facing: str) -> bool:
        dx, dy = DIRECTION_VECTORS[facing]
        tx, ty = player.x + dx, player.y + dy
        if not self.world.in_bounds(tx, ty):
            return False
        if self.world.get_tile(tx, ty) in SHOVELABLE_TILES:
            self.world.set_tile(tx, ty, TILE_FLOOR)
            return True
        return False

    def _use_knife(self, player: Player, facing: str) -> bool:
        dx, dy = DIRECTION_VECTORS[facing]
        tx, ty = player.x + dx, player.y + dy
        hit = False
        for other in self.players.values():
            if other is player or not other.alive:
                continue
            if other.x == tx and other.y == ty:
                died = other.damage(KNIFE_DAMAGE, attacker_id=player.id)
                hit = True
                if died:
                    self._on_kill(attacker=player, victim=other, cause="KNIFE")
        return hit

    def _use_bomb(self, player: Player) -> bool:
        # One bomb per cell at a time.
        for b in self.bombs:
            if b.x == player.x and b.y == player.y:
                return False
        # Limit per player: at most 1 active bomb.
        if any(b.owner_id == player.id for b in self.bombs):
            return False
        bomb = Bomb(
            bomb_id=gen_id("b_", 6),
            owner_id=player.id,
            x=player.x,
            y=player.y,
            blast_range=self.config.blast_range,
            fuse_ms=self.config.bomb_fuse_ms,
        )
        self.bombs.append(bomb)
        return True

    # ------------------------------------------------------------------
    # Tick / explosions
    # ------------------------------------------------------------------
    def _regen_dirt(self) -> None:
        """Rebuild all dirt to its initial state (dirt regen mode).

        Players currently standing on a cell that becomes dirt again are
        moved to a random spawn cell so they don't get stuck inside a
        dirt block. Bombs on dirt-restored cells are detonated immediately
        (their support was dug out from under them, conceptually).
        """
        logger.info("dirt regen: restoring initial tile state")
        self.world.restore_initial_dirt()
        # Move any player whose cell is no longer FLOOR to a random spawn.
        import random as _random
        for p in self.players.values():
            if not p.alive:
                continue
            if self.world.get_tile(p.x, p.y) != TILE_FLOOR:
                self._spawn_player(p, immediate=True, random_spawn=True)
        # Detonate any bomb whose cell is no longer FLOOR (rare, but safe).
        for b in list(self.bombs):
            if self.world.get_tile(b.x, b.y) != TILE_FLOOR:
                b.explodes_at_ms = time.monotonic() * 1000.0  # explode now
        self._dirty = True

    def tick(self) -> None:
        if self.over:
            return
        self.tick_count += 1
        now = time.monotonic() * 1000.0

        # Detonate bombs whose fuse elapsed.
        detonated: List[Bomb] = [b for b in self.bombs if b.should_explode(now)]
        if detonated:
            self._detonate(detonated, now)

        # Expire explosions.
        self.explosions = [e for e in self.explosions if not e.expired(now)]

        # Dirt regen mode: rebuild all dirt to its initial state.
        if (self.config.dirt_regen_enabled
                and self._next_dirt_regen_ms > 0
                and now >= self._next_dirt_regen_ms):
            self._regen_dirt()
            self._next_dirt_regen_ms = now + self.config.dirt_regen_interval_s * 1000

        # Respawn players whose timer elapsed.
        for p in self._respawn_pending():
            # Respawn on a RANDOM spawn cell (not the player's original one)
            # so deaths don't always send you back to the same spot.
            self._spawn_player(p, immediate=True, random_spawn=True)

        # Check end conditions.
        self._check_end_conditions()

    def _detonate(self, bombs: List[Bomb], now: float) -> None:
        # Chain-reaction: a bomb caught in another blast explodes immediately.
        to_detonate = list(bombs)
        processed_ids = set()
        affected_cells: List[Tuple[int, int]] = []
        destroyed_cells: List[Tuple[int, int]] = []

        while to_detonate:
            b = to_detonate.pop()
            if b.id in processed_ids:
                continue
            processed_ids.add(b.id)
            self.bombs.remove(b)

            cells = compute_blast_cells(self.world, b.x, b.y, b.blast_range)
            for c in cells:
                affected_cells.append(c)
                tile = self.world.get_tile(c[0], c[1])
                if tile in EXPLODABLE_TILES:
                    self.world.set_tile(c[0], c[1], TILE_FLOOR)
                    destroyed_cells.append(c)
            # Chain: any other bomb in the blast zone explodes next iteration.
            for other in list(self.bombs):
                if any(other.x == c[0] and other.y == c[1] for c in cells):
                    if other not in to_detonate:
                        to_detonate.append(other)

        # Apply damage to players in affected cells.
        for p in self.players.values():
            if not p.alive:
                continue
            for c in affected_cells:
                if p.x == c[0] and p.y == c[1]:
                    # Find owner of the bomb that hit this cell (first match).
                    owner_id = self._find_bomb_owner_for_cell(c, bombs)
                    attacker = self.players.get(owner_id) if owner_id else None
                    died = p.damage(BOMB_DAMAGE, attacker_id=owner_id)
                    if died and attacker is not None and attacker is not p:
                        self._on_kill(attacker=attacker, victim=p, cause="BOMB")
                    elif died and attacker is None:
                        # Self-damage from own bomb with no attacker fallback.
                        self._on_kill(attacker=p, victim=p, cause="BOMB_SELF")
                    break

        # Spawn explosion marker for rendering.
        self.explosions.append(Explosion(affected_cells, self.config.explosion_duration_ms))
        self._dirty = True

    def _find_bomb_owner_for_cell(self, cell: Tuple[int, int], bombs: List[Bomb]) -> Optional[str]:
        # Best-effort attribution: first bomb whose blast covers this cell.
        for b in bombs:
            cells = compute_blast_cells(self.world, b.x, b.y, b.blast_range)
            if cell in cells:
                return b.owner_id
        return None

    def _on_kill(self, attacker: Player, victim: Player, cause: str) -> None:
        attacker.add_score(1)
        attacker.kills += 1
        self._schedule_respawn(victim)
        self._dirty = True
        logger.debug("kill: %s -> %s (%s)", attacker.id, victim.id, cause)

    # ------------------------------------------------------------------
    # End conditions
    # ------------------------------------------------------------------
    def _check_end_conditions(self) -> None:
        if self.over:
            return
        # Score win.
        for p in self.players.values():
            if p.score >= self.config.score_to_win:
                self._end(winner_id=p.id)
                return
        # Time limit.
        if self.time_left_ms() <= 0:
            # Highest score wins; ties broken by kills then id.
            ranked = sorted(
                self.players.values(),
                key=lambda p: (-p.score, -p.kills, p.id),
            )
            self._end(winner_id=ranked[0].id if ranked else None)
            return
        # Time-based snapshot heartbeat: if the round has a time limit, the
        # displayed clock needs to update. Mark dirty at most once per second.
        if self.config.round_time_limit_s > 0:
            now = time.monotonic() * 1000.0
            if now - self._last_snapshot_ms > self._heartbeat_ms:
                self._dirty = True

    def _end(self, winner_id: Optional[str]) -> None:
        self.over = True
        self.ended_at_ms = time.monotonic() * 1000.0
        self.winner_id = winner_id
        self._dirty = True
        logger.info("game over: winner=%s", winner_id)

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------
    def serialize_full(self) -> dict:
        return {
            "world": self.world.serialize_full(),
            "players": [p.serialize() for p in self.players.values()],
            "bombs": [b.serialize() for b in self.bombs],
            "explosions": [e.serialize() for e in self.explosions],
            "config": self.config.to_dict(),
            "time_left_ms": int(self.time_left_ms()) if self.time_left_ms() != float("inf") else -1,
            "over": self.over,
            "winner_id": self.winner_id,
        }

    def serialize_snapshot(self) -> Optional[dict]:
        """Return a snapshot if the game state is worth broadcasting, else None.

        A snapshot is sent when:
          * the game was mutated since the last snapshot (_dirty flag), or
          * more than _heartbeat_ms has elapsed since the last snapshot.
        Returning None lets the snapshot pump skip the broadcast entirely,
        saving bandwidth for idle rooms.
        """
        now = time.monotonic() * 1000.0
        if not self._dirty and (now - self._last_snapshot_ms) < self._heartbeat_ms:
            return None
        self._dirty = False
        self._last_snapshot_ms = now
        return {
            "players": [p.serialize() for p in self.players.values()],
            "bombs": [b.serialize() for b in self.bombs],
            "explosions": [e.serialize() for e in self.explosions],
            "world_diff": self.world.serialize_diff(),  # may be None
            "tick": self.tick_count,
            "time_left_ms": int(self.time_left_ms()) if self.time_left_ms() != float("inf") else -1,
            "over": self.over,
            "winner_id": self.winner_id,
        }
