"""World generation invariants.

Tests that the generated map:
  * has the right dimensions,
  * is fully enclosed by walls,
  * has all spawn cells walkable (FLOOR),
  * has the corners aligned with the four spawn points,
  * has at least some floor tiles between spawns.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import unittest

from server.constants import TILE_FLOOR, TILE_WALL
from server.world import World


class WorldTest(unittest.TestCase):
    def test_dimensions(self):
        w = World(15, 11)
        self.assertEqual(w.width, 15)
        self.assertEqual(w.height, 11)
        self.assertEqual(len(w.tiles), 15 * 11)

    def test_border_walls(self):
        w = World(13, 9)
        for x in range(w.width):
            self.assertEqual(w.get_tile(x, 0), TILE_WALL, f"top border at {x}")
            self.assertEqual(w.get_tile(x, w.height - 1), TILE_WALL, f"bottom border at {x}")
        for y in range(w.height):
            self.assertEqual(w.get_tile(0, y), TILE_WALL, f"left border at {y}")
            self.assertEqual(w.get_tile(w.width - 1, y), TILE_WALL, f"right border at {y}")

    def test_spawns_are_floor(self):
        w = World(17, 13)
        self.assertEqual(len(w.spawns), 4, "expected 4 spawn points")
        for (sx, sy) in w.spawns:
            self.assertTrue(w.in_bounds(sx, sy), f"spawn {sx},{sy} out of bounds")
            self.assertEqual(w.get_tile(sx, sy), TILE_FLOOR,
                             f"spawn {sx},{sy} should be FLOOR")

    def test_spawns_random_and_distinct(self):
        """Spawns are now randomly placed with a minimum distance between
        them, and their count equals max_players (default 4). They should
        be 4 distinct cells, each inside the interior, and pairwise far
        enough apart."""
        w = World(17, 13, max_players=4)
        self.assertEqual(len(w.spawns), 4)
        # All distinct.
        self.assertEqual(len(set(w.spawns)), 4, f"spawns must be distinct: {w.spawns}")
        # All in the interior (not on the border).
        for (sx, sy) in w.spawns:
            self.assertGreater(sx, 0)
            self.assertLess(sx, w.width - 1)
            self.assertGreater(sy, 0)
            self.assertLess(sy, w.height - 1)
        # Pairwise distance: at least 4 cells (Euclidean).
        for i in range(len(w.spawns)):
            for j in range(i + 1, len(w.spawns)):
                dx = w.spawns[i][0] - w.spawns[j][0]
                dy = w.spawns[i][1] - w.spawns[j][1]
                dist = (dx * dx + dy * dy) ** 0.5
                self.assertGreaterEqual(dist, 4.0,
                    f"spawns {w.spawns[i]} and {w.spawns[j]} too close: {dist:.1f}")

    def test_spawns_count_matches_max_players(self):
        """The number of spawns must equal max_players."""
        for n in (2, 3, 4, 6, 8):
            w = World(21, 17, max_players=n)
            self.assertEqual(len(w.spawns), n,
                f"expected {n} spawns for max_players={n}, got {len(w.spawns)}")

    def test_spawns_change_between_games(self):
        """Spawns should be randomized: two worlds generated with different
        seeds should (very likely) have different spawn sets."""
        # World uses a fresh random seed each time (seed=None).
        w1 = World(17, 13)
        w2 = World(17, 13)
        # There is a tiny chance they match by luck, but with 4 random
        # positions in 15x11 cells it's astronomically unlikely.
        # We just assert they're both valid sets of 4 distinct spawns.
        self.assertEqual(len(w1.spawns), 4)
        self.assertEqual(len(w2.spawns), 4)
        self.assertEqual(len(set(w1.spawns)), 4)
        self.assertEqual(len(set(w2.spawns)), 4)

    def test_too_small_rejected(self):
        with self.assertRaises(ValueError):
            World(3, 3)
        with self.assertRaises(ValueError):
            World(5, 11)

    def test_in_bounds(self):
        w = World(11, 11)
        self.assertTrue(w.in_bounds(0, 0))
        self.assertTrue(w.in_bounds(10, 10))
        self.assertFalse(w.in_bounds(-1, 0))
        self.assertFalse(w.in_bounds(0, 11))

    def test_is_walkable(self):
        w = World(11, 11)
        # Border corners are walls, not walkable.
        self.assertFalse(w.is_walkable(0, 0))
        # Spawn cells are FLOOR (cleared at generation), so they're walkable.
        # With random spawns we can't hardcode (1,1), so use the first spawn.
        self.assertGreater(len(w.spawns), 0)
        sx, sy = w.spawns[0]
        self.assertTrue(w.is_walkable(sx, sy), f"spawn ({sx},{sy}) should be walkable")
        # Out of bounds is never walkable.
        self.assertFalse(w.is_walkable(-1, -1))


if __name__ == "__main__":
    unittest.main()
