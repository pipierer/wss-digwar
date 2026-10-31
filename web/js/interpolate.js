// interpolate.js — smooth visual interpolation between integer cells.
//
// The server only ever reports integer (x, y) for each player. The client
// keeps the previous cell + the new cell and lerps the render position over
// MOVE_INTERPOLATION_MS so movement looks fluid without ever leaving the
// "one cell per input" rule on the logic side.
//
// If a new target arrives before the previous lerp finished, we re-base from
// the current interpolated position so there is no visible snap. If a target
// is older than MAX_INTERP_LAG_MS we snap immediately to avoid drift.

(function (global) {
  "use strict";

  class Interpolator {
    constructor() {
      this.states = new Map();  // id -> { fromX, fromY, toX, toY, t, dur }
    }

    reset() { this.states.clear(); }

    // Called on every snapshot for every player that changed cell.
    onTarget(id, x, y, now) {
      const prev = this.states.get(id);
      let fromX, fromY;
      if (prev) {
        // Continue from the current interpolated position to avoid snapping.
        const alpha = Math.min(1, prev.t / prev.dur);
        fromX = prev.fromX + (prev.toX - prev.fromX) * alpha;
        fromY = prev.fromY + (prev.toY - prev.fromY) * alpha;
      } else {
        fromX = x;
        fromY = y;
      }
      this.states.set(id, {
        fromX, fromY, toX: x, toY: y,
        t: 0,
        dur: Constants.MOVE_INTERPOLATION_MS,
        startedAt: now,
      });
    }

    // Initialize a player position with no interpolation (first appearance).
    snap(id, x, y) {
      this.states.set(id, {
        fromX: x, fromY: y, toX: x, toY: y,
        t: 1, dur: 1, startedAt: performance.now(),
      });
    }

    // Advance all interpolations by dt ms.
    update(dt) {
      for (const s of this.states.values()) {
        s.t += dt;
      }
    }

    // Get the render position for a player, or null if unknown.
    getPos(id) {
      const s = this.states.get(id);
      if (!s) return null;
      const alpha = Math.min(1, s.t / s.dur);
      return {
        x: s.fromX + (s.toX - s.fromX) * alpha,
        y: s.fromY + (s.toY - s.fromY) * alpha,
      };
    }

    remove(id) { this.states.delete(id); }
  }

  global.Interpolator = new Interpolator();
})(typeof window !== "undefined" ? window : this);
