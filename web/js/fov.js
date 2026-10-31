// fov.js — true line-of-sight field-of-view (walls + dirt block vision).
//
// Algorithm: for every cell within `radius` of the player, we cast a ray
// from the player to that cell using Bresenham's line algorithm. If ANY
// cell along the ray (excluding the start, including the target) blocks
// vision, the target cell is hidden — it's behind cover.
//
// Walls, rocks AND dirt block vision. This is essential now that maps are
// fully filled with dirt at game start: without dirt blocking vision, the
// line-of-sight algorithm has nothing to compute against and the FOV
// degenerates back to a plain disc. With dirt blocking vision, players
// must dig to reveal new territory — true tactical fog-of-war.
//
// Result: a true tactical fog-of-war where you only see what your soldier
// could actually see in the field. Corners are dangerous. Flanking works.

(function (global) {
  "use strict";

  // Tiles that block the line of sight.
  // WALL  = indestructible obstacle, blocks vision.
  // ROCK  = destructible by bomb only, blocks vision.
  // DIRT  = diggable with shovel, blocks vision (you can't see through a
  //         pile of dirt; you must dig it to reveal what's behind).
  const VISION_BLOCKING = new Set([
    Constants.TILE_WALL,
    Constants.TILE_ROCK,
    Constants.TILE_DIRT,
  ]);

  const FOV = {
    radius: Constants.FOV_RADIUS,
    enabled: Constants.FOV_USE,

    // Returns true if cell (x, y) is a vision blocker.
    _blocks(x, y, world) {
      return VISION_BLOCKING.has(world.getTile(x, y));
    },

    // Bresenham line check: returns true if there is a clear line of sight
    // from (x0, y0) to (x1, y1). The start cell is never blocking; the end
    // cell is reached (so a wall at the destination IS visible, but you
    // cannot see THROUGH it to cells beyond).
    //
    // Corner-cutting rule: when the ray steps diagonally (both x and y
    // change in the same step), we require that AT LEAST ONE of the two
    // cardinal neighbors (the "shoulders" of the corner) is non-blocking.
    // If both shoulders are blocking, the diagonal is hidden — you cannot
    // peek through the corner of two walls. This prevents seeing the
    // interior angle of a wall corner.
    _hasLineOfSight(x0, y0, x1, y1, world) {
      // Same-cell: always visible.
      if (x0 === x1 && y0 === y1) return true;
      let dx = Math.abs(x1 - x0);
      let dy = Math.abs(y1 - y0);
      let sx = x0 < x1 ? 1 : -1;
      let sy = y0 < y1 ? 1 : -1;
      let err = dx - dy;
      let cx = x0;
      let cy = y0;
      while (true) {
        const prevCx = cx;
        const prevCy = cy;
        const e2 = 2 * err;
        let steppedX = false, steppedY = false;
        if (e2 > -dy) { err -= dy; cx += sx; steppedX = true; }
        if (e2 < dx)  { err += dx; cy += sy; steppedY = true; }
        // Corner-cutting: if this step was diagonal, both shoulders must
        // not be blocking. If they are, the diagonal is forbidden — even
        // if the destination cell itself is the target (you cannot see
        // through the corner of two walls).
        if (steppedX && steppedY) {
          const shoulderA = this._blocks(prevCx, cy, world);
          const shoulderB = this._blocks(cx, prevCy, world);
          if (shoulderA && shoulderB) return false;
        }
        // Did we reach the target? (check AFTER corner-cutting, so a
        // diagonal arrival through a blocked corner is rejected.)
        if (cx === x1 && cy === y1) return true;
        // Standard blocking check on the new (intermediate) cell.
        if (this._blocks(cx, cy, world)) return false;
      }
    },

    // Returns true if cell (x, y) is visible from the player at (cx, cy).
    isVisible(cx, cy, x, y) {
      if (!this.enabled) return true;
      // Same cell: always visible.
      if (cx === x && cy === y) return true;
      // Out of radius: not visible.
      const dx = x - cx;
      const dy = y - cy;
      if (dx * dx + dy * dy > this.radius * this.radius) return false;
      // We can't answer without the world here; conservative answer.
      return true;
    },

    // Compute a per-cell visibility mask for the current world + local player.
    // mask[y * w + x] = 1 if visible, 0 if hidden.
    computeMask(world, localPlayer) {
      if (!this.enabled || !localPlayer) return null;
      const cx = localPlayer.x;
      const cy = localPlayer.y;
      const w = world.width;
      const h = world.height;
      const mask = new Uint8Array(w * h);
      const r = this.radius;
      const r2 = r * r;

      // The player's own cell is always visible.
      mask[cy * w + cx] = 1;

      // For every cell in the bounding box of the FOV disc, cast a ray.
      const x0 = Math.max(0, cx - r);
      const x1 = Math.min(w - 1, cx + r);
      const y0 = Math.max(0, cy - r);
      const y1 = Math.min(h - 1, cy + r);

      for (let y = y0; y <= y1; y++) {
        for (let x = x0; x <= x1; x++) {
          if (x === cx && y === cy) continue;
          const dx = x - cx;
          const dy = y - cy;
          // Circular radius cutoff.
          if (dx * dx + dy * dy > r2) continue;
          // Line-of-sight check.
          if (this._hasLineOfSight(cx, cy, x, y, world)) {
            mask[y * w + x] = 1;
          }
        }
      }
      return mask;
    },
  };

  global.FOV = FOV;
})(typeof window !== "undefined" ? window : this);
