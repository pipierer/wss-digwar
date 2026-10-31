"""Game-level integration: tools, bombs, scoring, respawn, end conditions."""

from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import unittest

from server.bomb import compute_blast_cells
from server.constants import (
    BOMB_DAMAGE,
    DIR_DOWN,
    DIR_LEFT,
    DIR_RIGHT,
    DIR_UP,
    EXPLODABLE_TILES,
    KNIFE_DAMAGE,
    PLAYER_MAX_HEALTH,
    RESPAWN_DELAY_MS,
    TILE_DIRT,
    TILE_FLOOR,
    TILE_ROCK,
    TILE_WALL,
    TOOL_BOMB,
    TOOL_KNIFE,
    TOOL_SHOVEL,
)
from server.game import Game, GameConfig
from server.player import Player


def _make_game(width=11, height=11, score_to_win=3, blast_range=2):
    cfg = GameConfig({
        "width": width, "height": height,
        "max_players": 4, "score_to_win": score_to_win,
        "round_time_limit_s": 0, "move_cooldown_ms": 1, "blast_range": blast_range,
    })
    return cfg


def _spawn_player(game, pid, x, y):
    p = Player(pid, pid)
    p.place_at(x, y)
    game.players[pid] = p
    return p


class ShovelTest(unittest.TestCase):
    def test_shovel_destroys_dirt_in_facing_cell(self):
        cfg = _make_game()
        game = Game(cfg, {})
        p = _spawn_player(game, "p1", x=5, y=5)
        game.world.set_tile(6, 5, TILE_DIRT)
        self.assertTrue(game.try_use_tool(p, TOOL_SHOVEL, DIR_RIGHT))
        self.assertEqual(game.world.get_tile(6, 5), TILE_FLOOR)

    def test_shovel_does_nothing_on_wall(self):
        cfg = _make_game()
        game = Game(cfg, {})
        p = _spawn_player(game, "p1", x=1, y=1)
        # (0,1) is a wall.
        self.assertFalse(game.try_use_tool(p, TOOL_SHOVEL, DIR_LEFT))
        self.assertEqual(game.world.get_tile(0, 1), TILE_WALL)

    def test_shovel_does_nothing_on_rock(self):
        cfg = _make_game()
        game = Game(cfg, {})
        p = _spawn_player(game, "p1", x=5, y=5)
        game.world.set_tile(6, 5, TILE_ROCK)
        self.assertFalse(game.try_use_tool(p, TOOL_SHOVEL, DIR_RIGHT))
        self.assertEqual(game.world.get_tile(6, 5), TILE_ROCK)

    def test_shovel_uses_player_facing_if_no_direction_given(self):
        cfg = _make_game()
        game = Game(cfg, {})
        p = _spawn_player(game, "p1", x=5, y=5)
        p.facing = DIR_DOWN
        game.world.set_tile(5, 6, TILE_DIRT)
        self.assertTrue(game.try_use_tool(p, TOOL_SHOVEL))
        self.assertEqual(game.world.get_tile(5, 6), TILE_FLOOR)


class KnifeTest(unittest.TestCase):
    def test_knife_damages_adjacent_player(self):
        cfg = _make_game()
        game = Game(cfg, {})
        p1 = _spawn_player(game, "p1", x=5, y=5)
        p2 = _spawn_player(game, "p2", x=6, y=5)
        hp_before = p2.health
        self.assertTrue(game.try_use_tool(p1, TOOL_KNIFE, DIR_RIGHT))
        self.assertEqual(p2.health, hp_before - KNIFE_DAMAGE)

    def test_knife_kills_and_scores(self):
        cfg = _make_game()
        game = Game(cfg, {})
        p1 = _spawn_player(game, "p1", x=5, y=5)
        p2 = _spawn_player(game, "p2", x=6, y=5)
        p2.health = KNIFE_DAMAGE  # one hit will kill
        self.assertTrue(game.try_use_tool(p1, TOOL_KNIFE, DIR_RIGHT))
        self.assertFalse(p2.alive)
        self.assertEqual(p1.score, 1)
        self.assertEqual(p1.kills, 1)
        self.assertEqual(p2.deaths, 1)

    def test_knife_no_target_returns_false(self):
        cfg = _make_game()
        game = Game(cfg, {})
        p1 = _spawn_player(game, "p1", x=5, y=5)
        self.assertFalse(game.try_use_tool(p1, TOOL_KNIFE, DIR_RIGHT))


class BombTest(unittest.TestCase):
    def test_place_bomb_at_player_cell(self):
        cfg = _make_game()
        game = Game(cfg, {})
        p = _spawn_player(game, "p1", x=5, y=5)
        self.assertTrue(game.try_use_tool(p, TOOL_BOMB))
        self.assertEqual(len(game.bombs), 1)
        self.assertEqual((game.bombs[0].x, game.bombs[0].y), (5, 5))
        self.assertEqual(game.bombs[0].owner_id, "p1")

    def test_only_one_bomb_per_player(self):
        cfg = _make_game()
        game = Game(cfg, {})
        p = _spawn_player(game, "p1", x=5, y=5)
        self.assertTrue(game.try_use_tool(p, TOOL_BOMB))
        # Second bomb attempt (after cooldown) must fail: one per player.
        # Force cooldown to elapse.
        p.last_tool_ms = 0
        self.assertFalse(game.try_use_tool(p, TOOL_BOMB))
        self.assertEqual(len(game.bombs), 1)

    def test_bomb_explodes_after_fuse(self):
        cfg = _make_game(blast_range=2)
        game = Game(cfg, {})
        p = _spawn_player(game, "p1", x=5, y=5)
        # Place a bomb with a very short fuse by directly mutating.
        from server.bomb import Bomb
        b = Bomb("b1", p.id, 5, 5, blast_range=2, fuse_ms=10)
        game.bombs.append(b)
        # Wait past the fuse, then tick.
        time.sleep(0.02)
        game.tick()
        self.assertEqual(len(game.bombs), 0)
        self.assertEqual(len(game.explosions), 1)
        # Player should have taken damage (standing on the bomb cell).
        self.assertLess(p.health, PLAYER_MAX_HEALTH)

    def test_blast_blocked_by_wall(self):
        cfg = _make_game()
        game = Game(cfg, {})
        # Build a wall corridor: bomb at (5,5), wall at (5,3). Blast up should
        # stop at the wall and not reach (5,2).
        cells = compute_blast_cells(game.world, 5, 5, blast_range=3)
        coords = set(cells)
        # (5,5),(5,4) should be in the blast; (5,3) is a wall (border is at y=0
        # so y=3 should be floor in an 11x11 map; we manually place a wall).
        game.world.set_tile(5, 3, TILE_WALL)
        cells2 = compute_blast_cells(game.world, 5, 5, blast_range=3)
        coords2 = set(cells2)
        # Wall stops the blast: (5,2) must NOT be in cells2.
        self.assertNotIn((5, 2), coords2)
        self.assertNotIn((5, 3), coords2)

    def test_blast_destroys_dirt_and_stops(self):
        cfg = _make_game()
        game = Game(cfg, {})
        # Place dirt at (5,4) — blast up from (5,5) should consume (5,4) and
        # stop before (5,3).
        game.world.set_tile(5, 4, TILE_DIRT)
        cells = compute_blast_cells(game.world, 5, 5, blast_range=3)
        self.assertIn((5, 4), cells)
        self.assertNotIn((5, 3), cells)

    def test_chain_reaction(self):
        cfg = _make_game()
        game = Game(cfg, {})
        from server.bomb import Bomb
        # Clear a corridor along x=1 so the blast can propagate from (1,1)
        # to (1,3) without being blocked by dirt.
        for y in range(1, 5):
            game.world.set_tile(1, y, TILE_FLOOR)
        b1 = Bomb("b1", "p1", 1, 1, blast_range=3, fuse_ms=10)
        b2 = Bomb("b2", "p1", 1, 3, blast_range=3, fuse_ms=5000)  # far in future
        game.bombs.append(b1)
        game.bombs.append(b2)
        time.sleep(0.02)
        game.tick()
        # Both bombs should be gone (chain reaction).
        self.assertEqual(len(game.bombs), 0)

    def test_bomb_kill_awards_score(self):
        cfg = _make_game()
        game = Game(cfg, {})
        from server.bomb import Bomb
        p1 = _spawn_player(game, "p1", x=5, y=5)
        p2 = _spawn_player(game, "p2", x=6, y=5)
        # One bomb deals 60 damage; lower p2's HP so a single blast kills.
        p2.health = 50
        b = Bomb("b1", p1.id, 5, 5, blast_range=2, fuse_ms=10)
        game.bombs.append(b)
        # Move p1 off the bomb cell so only p2 is hit cleanly.
        p1.x = 1
        p1.y = 1
        time.sleep(0.02)
        game.tick()
        self.assertFalse(p2.alive)
        self.assertEqual(p1.score, 1)


class RespawnTest(unittest.TestCase):
    def test_dead_player_respawns_after_delay(self):
        cfg = _make_game()
        game = Game(cfg, {})
        p = _spawn_player(game, "p1", x=5, y=5)
        # Manually schedule respawn with a tiny delay by editing the field.
        p.kill()
        p.respawn_at_ms = time.monotonic() * 1000.0 + 10
        time.sleep(0.02)
        game.tick()
        self.assertTrue(p.alive)
        self.assertEqual(p.health, PLAYER_MAX_HEALTH)
        # Position reset to a spawn cell (random since respawn is now random).
        self.assertIn((p.x, p.y), game.world.spawns,
                      f"respawned at {(p.x, p.y)} which is not a spawn cell")


class EndConditionTest(unittest.TestCase):
    def test_score_to_win_ends_game(self):
        cfg = _make_game(score_to_win=2)
        game = Game(cfg, {})
        p1 = _spawn_player(game, "p1", x=5, y=5)
        p2 = _spawn_player(game, "p2", x=6, y=5)
        p1.add_score(1)
        game._check_end_conditions()
        self.assertFalse(game.over)
        p1.add_score(1)
        game._check_end_conditions()
        self.assertTrue(game.over)
        self.assertEqual(game.winner_id, "p1")


class SerializationTest(unittest.TestCase):
    def test_snapshot_is_json_serializable(self):
        import json
        cfg = _make_game()
        game = Game(cfg, {})
        _spawn_player(game, "p1", x=5, y=5)
        snap = game.serialize_snapshot()
        # Must round-trip through JSON without error.
        s = json.dumps(snap)
        back = json.loads(s)
        self.assertEqual(back["type"] if "type" in back else "SNAPSHOT", "SNAPSHOT")


if __name__ == "__main__":
    unittest.main()
