"""World / map state.

The world is a 2D grid of integer tile types. Generation produces a
symmetric, fair map: border of indestructible walls, a few internal pillars,
dirt piles distributed deterministically, and one spawn point per quadrant
so players start far apart.
"""

from __future__ import annotations

import random
from typing import Iterable, List, Tuple

from .constants import (
    BLOCKING_TILES,
    DIRECTION_VECTORS,
    TILE_DIRT,
    TILE_FLOOR,
    TILE_ROCK,
    TILE_WALL,
)


class World:
    """A rectangular grid of tiles.

    Coordinates are integer (x, y) with x in [0, width), y in [0, height).
    y grows downward (matches canvas convention).
    """

    __slots__ = ("width", "height", "tiles", "spawns", "_dirty", "initial_tiles")

    def __init__(self, width: int, height: int, seed: int | None = None,
                 max_players: int = 4):
        if width < 7 or height < 7:
            raise ValueError(f"world too small: {width}x{height}")
        self.width = int(width)
        self.height = int(height)
        self.tiles: List[int] = [TILE_FLOOR] * (self.width * self.height)
        self.spawns: List[Tuple[int, int]] = []
        self._dirty = True
        self.initial_tiles: List[int] = []
        self._generate(seed, max_players)

    # ------------------------------------------------------------------
    # Generation
    # ------------------------------------------------------------------
    def _generate(self, seed: int | None, max_players: int = 4) -> None:
        rng = random.Random(seed)
        w, h = self.width, self.height

        # Border walls (indestructible, frame the map).
        for x in range(w):
            self._set(x, 0, TILE_WALL)
            self._set(x, h - 1, TILE_WALL)
        for y in range(h):
            self._set(0, y, TILE_WALL)
            self._set(w - 1, y, TILE_WALL)

        # Compute random spawn cells (exactly max_players, far apart).
        spawn_corners = self._compute_spawns(w, h, rng, max_players)
        # Each spawn is a 1x1 floor cell. The 3x3 safe zone is gone: only
        # the spawn cell itself is floor at start; everything else is dirt.
        spawn_set = set(spawn_corners)

        # --- Fill the ENTIRE interior with DIRT (diggable with shovel) ---
        # Every interior cell that is not a spawn becomes dirt at the start.
        # Players must dig their way out. No internal walls, no rocks —
        # everything is destructible with a shovel (or a bomb).
        for y in range(1, h - 1):
            for x in range(1, w - 1):
                if (x, y) in spawn_set:
                    continue
                self._set(x, y, TILE_DIRT)

        # Carve 2 starting corridors from each spawn (one horizontal + one
        # vertical) so the player can move at game start without being
        # immediately walled in. Without these, the player would be stuck on
        # a 1x1 floor cell surrounded by dirt on all 4 sides.
        for sx, sy in spawn_corners:
            for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                nx, ny = sx + dx, sy + dy
                if self.in_bounds(nx, ny) and self._get(nx, ny) == TILE_DIRT:
                    self._set(nx, ny, TILE_FLOOR)

        self.spawns = spawn_corners
        # Save the initial tile state so the "dirt regen" mode can restore it.
        self.initial_tiles = list(self.tiles)
        self._dirty = True

    def _ensure_connectivity(self, spawns, rng: "random.Random") -> None:
        """BFS from spawn 0; if any other spawn is unreachable, carve a
        straight tunnel through whatever is blocking."""
        if not spawns:
            return
        start = spawns[0]
        reachable = self._bfs_reachable(start)
        for target in spawns[1:]:
            if target not in reachable:
                self._carve_tunnel(start, target, rng)
                # Re-run BFS in case carving opened new paths.
                reachable = self._bfs_reachable(start)

    def _bfs_reachable(self, start) -> set:
        """Return the set of FLOOR cells reachable from `start` (4-directional)."""
        from collections import deque
        seen = {start}
        q = deque([start])
        while q:
            x, y = q.popleft()
            for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                nx, ny = x + dx, y + dy
                if (nx, ny) in seen:
                    continue
                if not self.in_bounds(nx, ny):
                    continue
                if self._get(nx, ny) != TILE_FLOOR:
                    continue
                seen.add((nx, ny))
                q.append((nx, ny))
        return seen

    def _carve_tunnel(self, a, b, rng: "random.Random") -> None:
        """Carve an L-shaped tunnel from a to b through walls/dirt (not rocks).
        Rocks are left intact (they require a bomb)."""
        ax, ay = a
        bx, by = b
        # Random L-shape: horizontal first or vertical first.
        if rng.random() < 0.5:
            self._carve_h(ax, bx, ay)
            self._carve_v(ay, by, bx)
        else:
            self._carve_v(ay, by, ax)
            self._carve_h(ax, bx, by)

    def _carve_h(self, x0: int, x1: int, y: int) -> None:
        lo, hi = min(x0, x1), max(x0, x1)
        for x in range(lo, hi + 1):
            if self.in_bounds(x, y) and self._get(x, y) in (TILE_WALL, TILE_DIRT):
                self._set(x, y, TILE_FLOOR)

    def _carve_v(self, y0: int, y1: int, x: int) -> None:
        lo, hi = min(y0, y1), max(y0, y1)
        for y in range(lo, hi + 1):
            if self.in_bounds(x, y) and self._get(x, y) in (TILE_WALL, TILE_DIRT):
                self._set(x, y, TILE_FLOOR)

    def _compute_spawns(self, w: int, h: int, rng: "random.Random",
                        max_players: int = 4) -> List[Tuple[int, int]]:
        """Pick exactly `max_players` random spawn cells, far apart from
        each other.

        Algorithm: rejection sampling. We pick random interior cells and
        keep them only if they are at least `min_distance` cells away (Euclidean)
        from all already-placed spawns. This guarantees spawns are spread
        out across the map. Falls back to relaxing the distance if the map
        is too small to fit all spawns.

        We also divide the map into `max_players` horizontal bands and
        initially bias each spawn toward its own band, so even with relaxed
        distances players start in different regions.
        """
        n = max(2, min(int(max_players), 8))
        # Minimum Euclidean distance between two spawns. Scaled to map size:
        # roughly the map diagonal divided by (n+1), with a floor of 4.
        diagonal = (w * w + h * h) ** 0.5
        min_distance = max(4.0, diagonal / (n + 1))

        spawns: List[Tuple[int, int]] = []
        # We try multiple rounds with progressively relaxed distance.
        for attempt_round in range(4):
            distance = min_distance * (0.8 ** attempt_round)
            spawns = []
            max_tries_per_spawn = 200
            for i in range(n):
                # Bias spawn i toward band i (horizontal strip).
                band_h = max(1, (h - 2) // n)
                y_lo = 1 + i * band_h
                y_hi = min(h - 2, y_lo + band_h - 1)
                if y_lo > y_hi: y_lo, y_hi = y_hi, y_lo
                placed = False
                for _ in range(max_tries_per_spawn):
                    sx = rng.randint(1, w - 2)
                    sy = rng.randint(y_lo, y_hi)
                    # Check distance to all existing spawns.
                    ok = True
                    for (ox, oy) in spawns:
                        ddx = sx - ox
                        ddy = sy - oy
                        if (ddx * ddx + ddy * ddy) < (distance * distance):
                            ok = False
                            break
                    if ok:
                        spawns.append((sx, sy))
                        placed = True
                        break
                if not placed:
                    # Could not place with current distance; restart the
                    # outer loop with a relaxed distance.
                    break
            if len(spawns) == n:
                break  # success

        # Final safety: if we still don't have enough spawns (very small map),
        # just place them at random without distance constraint.
        while len(spawns) < n:
            sx = rng.randint(1, w - 2)
            sy = rng.randint(1, h - 2)
            if (sx, sy) not in spawns:
                spawns.append((sx, sy))

        # Shuffle so the assignment to player indices is random.
        rng.shuffle(spawns)
        return spawns

    # ------------------------------------------------------------------
    # Tile access
    # ------------------------------------------------------------------
    def _idx(self, x: int, y: int) -> int:
        return y * self.width + x

    def _get(self, x: int, y: int) -> int:
        return self.tiles[self._idx(x, y)]

    def _set(self, x: int, y: int, tile: int) -> None:
        self.tiles[self._idx(x, y)] = tile
        self._dirty = True

    def in_bounds(self, x: int, y: int) -> bool:
        return 0 <= x < self.width and 0 <= y < self.height

    def get_tile(self, x: int, y: int) -> int:
        if not self.in_bounds(x, y):
            return TILE_WALL
        return self._get(x, y)

    def set_tile(self, x: int, y: int, tile: int) -> None:
        if not self.in_bounds(x, y):
            return
        self._set(x, y, tile)

    def is_blocking(self, x: int, y: int) -> bool:
        return self.get_tile(x, y) in BLOCKING_TILES

    def is_walkable(self, x: int, y: int) -> bool:
        """A cell is walkable iff it is in-bounds and a FLOOR tile."""
        return self.in_bounds(x, y) and self._get(x, y) == TILE_FLOOR

    def get_spawn(self, index: int) -> Tuple[int, int]:
        if not self.spawns:
            return (1, 1)
        return self.spawns[index % len(self.spawns)]

    def get_random_spawn(self, rng: "random.Random") -> Tuple[int, int]:
        """Return a random spawn cell. Used for respawn-after-death so the
        player does not always reappear at the same spot."""
        if not self.spawns:
            return (1, 1)
        return rng.choice(self.spawns)

    def restore_initial_dirt(self) -> None:
        """Restore all tiles to their initial state (as generated at game
        start). Used by the 'dirt regen' mode: every X seconds, all dirt that
        was dug up or destroyed by bombs is rebuilt. Spawns and corridors
        are preserved (they are part of the initial state)."""
        if not self.initial_tiles:
            return
        self.tiles = list(self.initial_tiles)
        self._dirty = True

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------
    def serialize_full(self) -> dict:
        """Full snapshot for GAME_START messages."""
        self._dirty = False
        return {
            "width": self.width,
            "height": self.height,
            "tiles": self.tiles,
            "spawns": list(self.spawns),
        }

    def serialize_diff(self) -> dict | None:
        """Return changed tiles since the last call, or None if no change.

        Diff format: {"cells": [x, y, tile, x, y, tile, ...]} (flat list,
        3 ints per cell). The client reconstructs the diff.
        """
        if not self._dirty:
            return None
        # We don't track per-cell dirtiness: send full tile list when dirty
        # but keep the "diff" semantics so the protocol stays simple. The
        # client always replaces its full tile array on a diff.
        self._dirty = False
        return {"width": self.width, "height": self.height, "tiles": self.tiles}

    def mark_dirty(self) -> None:
        self._dirty = True
