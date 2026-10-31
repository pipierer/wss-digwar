// player.js — client-side representation of players from snapshots.
//
// Each player is identified by its server-side id. The local player is the
// one matching Net.playerId. Positions are integers; rendering uses the
// Interpolator for smooth visual movement between cells.

(function (global) {
  "use strict";

  class PlayerState {
    constructor() {
      this.players = new Map();    // id -> { ...snapshot fields }
      this.localId = null;
    }

    setLocalId(id) { this.localId = id; }

    get(id) { return this.players.get(id) || null; }
    get local() { return this.players.get(this.localId) || null; }
    all() { return Array.from(this.players.values()); }

    clear() { this.players.clear(); }

    applySnapshot(playersArr) {
      if (!Array.isArray(playersArr)) return;
      const seen = new Set();
      for (const p of playersArr) {
        if (!p || typeof p !== "object") continue;
        const id = p.id;
        if (!id) continue;
        seen.add(id);
        const prev = this.players.get(id);
        // Detect a position change so the interpolator can lerp.
        const changed = !prev || prev.x !== p.x || prev.y !== p.y;
        this.players.set(id, {
          id,
          name: p.name,
          x: p.x | 0,
          y: p.y | 0,
          facing: p.facing,
          alive: !!p.alive,
          health: p.health | 0,
          score: p.score | 0,
          kills: p.kills | 0,
          deaths: p.deaths | 0,
          team: p.team,
          respawn_in_ms: p.respawn_in_ms | 0,
          _changed: changed,
        });
      }
      // Remove players that disappeared from the snapshot.
      for (const id of Array.from(this.players.keys())) {
        if (!seen.has(id)) this.players.delete(id);
      }
    }

    resetForNewGame() {
      this.players.clear();
    }
  }

  global.Players = new PlayerState();
})(typeof window !== "undefined" ? window : this);
