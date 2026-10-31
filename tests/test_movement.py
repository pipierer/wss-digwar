"""Discrete movement invariants — the core rule of the project.

Every test here documents one clause of the strict movement contract:
  * 1 input == 1 cell,
  * no diagonal,
  * no out-of-bounds,
  * no walking into walls / dirt / rocks,
  * no two players on the same cell,
  * no walking onto a live bomb,
  * cooldown enforced server-side.
"""

from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import unittest

from server.constants import (
    DIR_DOWN,
    DIR_LEFT,
    DIR_RIGHT,
    DIR_UP,
    MOVE_COOLDOWN_MS,
    TILE_DIRT,
    TILE_FLOOR,
    TILE_ROCK,
    TILE_WALL,
    TOOL_BOMB,
)
from server.game import Game, GameConfig
from server.player import Player


def _make_game(width=11, height=11, max_players=4, cooldown_ms=MOVE_COOLDOWN_MS):
    cfg = GameConfig({
        "width": width,
        "height": height,
        "max_players": max_players,
        "score_to_win": 5,
        "round_time_limit_s": 0,
        "move_cooldown_ms": cooldown_ms,
        "blast_range": 2,
    })
    return cfg


def _spawn_player(game, pid="p1", x=1, y=1):
    p = Player(pid, pid)
    p.place_at(x, y)
    game.players[pid] = p
    return p


def _clear(game, *cells):
    """Force a list of (x, y) cells to FLOOR so tests are deterministic.

    World generation scatters dirt with 18% density; without this helper a
    movement test would flake whenever the random generator happened to put
    dirt on the target cell.
    """
    for (x, y) in cells:
        game.world.set_tile(x, y, TILE_FLOOR)


class MovementBoundsTest(unittest.TestCase):
    def test_move_one_cell_up(self):
        cfg = _make_game()
        game = Game(cfg, {})
        p = _spawn_player(game, "p1", x=5, y=5)
        _clear(game, (5, 4))
        ok = game.try_move(p, DIR_UP)
        self.assertTrue(ok)
        self.assertEqual((p.x, p.y), (5, 4))

    def test_move_one_cell_down(self):
        cfg = _make_game()
        game = Game(cfg, {})
        p = _spawn_player(game, "p1", x=5, y=5)
        _clear(game, (5, 6))
        ok = game.try_move(p, DIR_DOWN)
        self.assertTrue(ok)
        self.assertEqual((p.x, p.y), (5, 6))

    def test_move_one_cell_left(self):
        cfg = _make_game()
        game = Game(cfg, {})
        p = _spawn_player(game, "p1", x=5, y=5)
        # Ensure target cell is FLOOR (world gen may have placed dirt there).
        game.world.set_tile(4, 5, TILE_FLOOR)
        ok = game.try_move(p, DIR_LEFT)
        self.assertTrue(ok)
        self.assertEqual((p.x, p.y), (4, 5))

    def test_move_one_cell_right(self):
        cfg = _make_game()
        game = Game(cfg, {})
        p = _spawn_player(game, "p1", x=5, y=5)
        game.world.set_tile(6, 5, TILE_FLOOR)
        ok = game.try_move(p, DIR_RIGHT)
        self.assertTrue(ok)
        self.assertEqual((p.x, p.y), (6, 5))

    def test_no_diagonal_direction(self):
        """Only the 4 cardinals are valid; anything else is rejected."""
        cfg = _make_game()
        game = Game(cfg, {})
        p = _spawn_player(game, "p1", x=5, y=5)
        for bad in ("UP_LEFT", "DOWN_RIGHT", "up", "", None, 42):
            self.assertFalse(game.try_move(p, bad), f"should reject {bad!r}")
        # Position unchanged.
        self.assertEqual((p.x, p.y), (5, 5))


class MovementCollisionTest(unittest.TestCase):
    def test_cannot_walk_into_wall(self):
        cfg = _make_game()
        game = Game(cfg, {})
        # (0,0) is a wall (border). Put player at (1,1) and try LEFT.
        p = _spawn_player(game, "p1", x=1, y=1)
        self.assertFalse(game.try_move(p, DIR_LEFT))
        self.assertEqual((p.x, p.y), (1, 1))

    def test_cannot_walk_into_dirt(self):
        cfg = _make_game()
        game = Game(cfg, {})
        p = _spawn_player(game, "p1", x=5, y=5)
        game.world.set_tile(6, 5, TILE_DIRT)
        self.assertFalse(game.try_move(p, DIR_RIGHT))
        self.assertEqual((p.x, p.y), (5, 5))

    def test_cannot_walk_into_rock(self):
        cfg = _make_game()
        game = Game(cfg, {})
        p = _spawn_player(game, "p1", x=5, y=5)
        game.world.set_tile(5, 4, TILE_ROCK)
        self.assertFalse(game.try_move(p, DIR_UP))
        self.assertEqual((p.x, p.y), (5, 5))

    def test_cannot_walk_out_of_bounds(self):
        cfg = _make_game()
        game = Game(cfg, {})
        # Player at corner spawn (1,1) cannot go up (would be wall) — try
        # a custom small map and put player against the edge.
        p = _spawn_player(game, "p1", x=1, y=1)
        # UP and LEFT are walls. Verify they fail.
        self.assertFalse(game.try_move(p, DIR_UP))
        self.assertFalse(game.try_move(p, DIR_LEFT))

    def test_cannot_walk_onto_other_player(self):
        cfg = _make_game()
        game = Game(cfg, {})
        p1 = _spawn_player(game, "p1", x=5, y=5)
        p2 = _spawn_player(game, "p2", x=6, y=5)
        self.assertFalse(game.try_move(p1, DIR_RIGHT))
        self.assertEqual((p1.x, p1.y), (5, 5))

    def test_can_walk_onto_dead_player_cell(self):
        """A dead player does not block movement."""
        cfg = _make_game()
        game = Game(cfg, {})
        p1 = _spawn_player(game, "p1", x=5, y=5)
        p2 = _spawn_player(game, "p2", x=6, y=5)
        p2.alive = False
        _clear(game, (6, 5))
        self.assertTrue(game.try_move(p1, DIR_RIGHT))
        # Note: dead player keeps its old (x,y) but is not considered blocking.
        self.assertEqual((p1.x, p1.y), (6, 5))


class MovementCooldownTest(unittest.TestCase):
    def test_cooldown_blocks_spam(self):
        # 50 ms cooldown so the test runs fast.
        cfg = _make_game(cooldown_ms=50)
        game = Game(cfg, {})
        p = _spawn_player(game, "p1", x=5, y=5)
        _clear(game, (5, 4))
        self.assertTrue(game.try_move(p, DIR_UP))      # (5,4)
        # Immediate second move must be rejected by cooldown.
        self.assertFalse(game.try_move(p, DIR_UP))
        self.assertEqual((p.x, p.y), (5, 4))

    def test_cooldown_elapses(self):
        cfg = _make_game(cooldown_ms=30)
        game = Game(cfg, {})
        p = _spawn_player(game, "p1", x=5, y=5)
        _clear(game, (5, 4), (5, 3))
        self.assertTrue(game.try_move(p, DIR_UP))      # (5,4)
        time.sleep(0.04)                               # 40 ms > 30 ms
        self.assertTrue(game.try_move(p, DIR_UP))      # (5,3)
        self.assertEqual((p.x, p.y), (5, 3))

    def test_dead_player_cannot_move(self):
        cfg = _make_game()
        game = Game(cfg, {})
        p = _spawn_player(game, "p1", x=5, y=5)
        p.alive = False
        self.assertFalse(game.try_move(p, DIR_UP))
        self.assertEqual((p.x, p.y), (5, 5))


class MovementIntegerInvariantTest(unittest.TestCase):
    def test_positions_stay_integer(self):
        """After any number of accepted moves, position is always (int, int)."""
        cfg = _make_game(cooldown_ms=1)
        game = Game(cfg, {})
        p = _spawn_player(game, "p1", x=5, y=5)
        # Clear a 4x4 walkable area around the start so the loop can move.
        _clear(game, (5, 4), (5, 3), (6, 5), (7, 5), (5, 6), (5, 7), (4, 5), (3, 5))
        for _ in range(20):
            for d in (DIR_UP, DIR_RIGHT, DIR_DOWN, DIR_LEFT):
                if game.try_move(p, d):
                    time.sleep(0.002)
            self.assertIsInstance(p.x, int)
            self.assertIsInstance(p.y, int)
        # Position may not return to (5,5) if a move was blocked by a wall
        # pillar; the invariant we care about is integer-typed coordinates.


class MovementBombBlockTest(unittest.TestCase):
    def test_cannot_walk_onto_bomb(self):
        cfg = _make_game()
        game = Game(cfg, {})
        p = _spawn_player(game, "p1", x=5, y=5)
        # Place a bomb at (5,5); fuse won't fire during this test.
        self.assertTrue(game.try_use_tool(p, TOOL_BOMB))
        # Try to move onto (5,5) from (4,5): place a second player there.
        p2 = _spawn_player(game, "p2", x=4, y=5)
        # Bomb is at (5,5) which is where p1 is. Walking from (4,5) RIGHT -> (5,5).
        self.assertFalse(game.try_move(p2, DIR_RIGHT))
        self.assertEqual((p2.x, p2.y), (4, 5))


if __name__ == "__main__":
    unittest.main()
