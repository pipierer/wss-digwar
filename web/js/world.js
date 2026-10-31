// world.js — client-side mirror of the server World.
//
// The client only stores what the server sends. It never edits tiles on its
// own; the world is replaced wholesale when a SNAPSHOT's world_diff arrives.

(function (global) {
  "use strict";

  class ClientWorld {
    constructor() {
      this.width = 0;
      this.height = 0;
      this.tiles = new Uint8Array(0);   // flat row-major
      this.spawns = [];
    }

    clear() {
      this.width = 0;
      this.height = 0;
      this.tiles = new Uint8Array(0);
      this.spawns = [];
    }

    initFromFull(full) {
      const w = full.width | 0;
      const h = full.height | 0;
      this.width = w;
      this.height = h;
      const arr = full.tiles || [];
      const tiles = new Uint8Array(w * h);
      for (let i = 0; i < tiles.length && i < arr.length; i++) tiles[i] = arr[i] | 0;
      this.tiles = tiles;
      this.spawns = Array.isArray(full.spawns) ? full.spawns.map(s => [s[0] | 0, s[1] | 0]) : [];
    }

    applyDiff(diff) {
      if (!diff) return;
      // Server currently sends full tile list as "diff" (simpler, robust).
      const w = diff.width | 0;
      const h = diff.height | 0;
      if (w !== this.width || h !== this.height) {
        this.width = w;
        this.height = h;
        this.tiles = new Uint8Array(w * h);
      }
      const arr = diff.tiles || [];
      for (let i = 0; i < this.tiles.length && i < arr.length; i++) this.tiles[i] = arr[i] | 0;
    }

    inBounds(x, y) {
      return x >= 0 && y >= 0 && x < this.width && y < this.height;
    }

    getTile(x, y) {
      if (!this.inBounds(x, y)) return Constants.TILE_WALL;
      return this.tiles[y * this.width + x];
    }

    isWalkable(x, y) {
      return this.inBounds(x, y) && this.tiles[y * this.width + x] === Constants.TILE_FLOOR;
    }
  }

  global.World = new ClientWorld();
})(typeof window !== "undefined" ? window : this);
