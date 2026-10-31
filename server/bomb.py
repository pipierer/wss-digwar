"""Bomb and explosion server-side state."""

from __future__ import annotations

import time
from typing import List, Optional, Tuple

from .constants import (
    BOMB_BLAST_RANGE,
    BOMB_DAMAGE,
    BOMB_FUSE_MS,
    DIRECTION_VECTORS,
    DIR_DOWN,
    DIR_LEFT,
    DIR_RIGHT,
    DIR_UP,
    EXPLOSION_BLOCKING_TILES,
    EXPLODABLE_TILES,
    EXPLOSION_DURATION_MS,
)


def _now_ms() -> float:
    return time.monotonic() * 1000.0


class Bomb:
    __slots__ = ("id", "owner_id", "x", "y", "placed_at_ms", "explodes_at_ms", "blast_range")

    def __init__(
        self,
        bomb_id: str,
        owner_id: str,
        x: int,
        y: int,
        blast_range: int = BOMB_BLAST_RANGE,
        fuse_ms: int = BOMB_FUSE_MS,
    ):
        self.id = bomb_id
        self.owner_id = owner_id
        self.x = int(x)
        self.y = int(y)
        self.placed_at_ms = _now_ms()
        self.explodes_at_ms = self.placed_at_ms + int(fuse_ms)
        self.blast_range = int(blast_range)

    def should_explode(self, now_ms: float | None = None) -> bool:
        if now_ms is None:
            now_ms = _now_ms()
        return now_ms >= self.explodes_at_ms

    def time_left_ms(self, now_ms: float | None = None) -> int:
        if now_ms is None:
            now_ms = _now_ms()
        return max(0, int(self.explodes_at_ms - now_ms))

    def serialize(self) -> dict:
        return {
            "id": self.id,
            "owner_id": self.owner_id,
            "x": self.x,
            "y": self.y,
            "explodes_in_ms": self.time_left_ms(),
            "blast_range": self.blast_range,
        }


class Explosion:
    """A transient explosion marker, kept until EXPLOSION_DURATION_MS elapses."""

    __slots__ = ("cells", "started_at_ms", "duration_ms")

    def __init__(self, cells: List[Tuple[int, int]], duration_ms: int = EXPLOSION_DURATION_MS):
        # Deduplicate while preserving order.
        seen = set()
        unique: List[Tuple[int, int]] = []
        for c in cells:
            if c not in seen:
                seen.add(c)
                unique.append(c)
        self.cells = unique
        self.started_at_ms = _now_ms()
        self.duration_ms = int(duration_ms)

    def expired(self, now_ms: float | None = None) -> bool:
        if now_ms is None:
            now_ms = _now_ms()
        return now_ms - self.started_at_ms >= self.duration_ms

    def serialize(self) -> dict:
        return {
            "cells": [c[0] for c in self.cells] + [c[1] for c in self.cells],  # flat [x,y,x,y,...]
            "remaining_ms": max(0, int(self.duration_ms - (_now_ms() - self.started_at_ms))),
        }


def compute_blast_cells(
    world,
    bomb_x: int,
    bomb_y: int,
    blast_range: int,
) -> List[Tuple[int, int]]:
    """Return the list of cells affected by a bomb explosion.

    Blast expands in the 4 cardinal directions, stopping at any
    EXPLOSION_BLOCKING tile (WALL, ROCK). DIRT is destroyed (consumed) and
    also stops the blast beyond it.
    """
    cells: List[Tuple[int, int]] = [(bomb_x, bomb_y)]
    for direction in (DIR_UP, DIR_DOWN, DIR_LEFT, DIR_RIGHT):
        dx, dy = DIRECTION_VECTORS[direction]
        cx, cy = bomb_x, bomb_y
        for _ in range(blast_range):
            cx += dx
            cy += dy
            if not world.in_bounds(cx, cy):
                break
            tile = world.get_tile(cx, cy)
            if tile in EXPLOSION_BLOCKING_TILES:
                # Wall / rock: blast does NOT pass through.
                break
            cells.append((cx, cy))
            if tile in EXPLODABLE_TILES:
                # Dirt is destroyed but still blocks blast beyond it.
                break
    return cells
