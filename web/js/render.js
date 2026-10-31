// render.js — main canvas renderer.
//
// Top-down militariste style: muted kaki/gray palette, hard edges, no glow
// except on active bombs (warning) and explosions (impact). The renderer
// is pure: it only reads from World, Players, Interpolator and the current
// FOV mask. It never mutates game state.
//
// Camera follows the local player. Outside the FOV disc, cells are drawn as
// solid fog. Explosions and bombs are clipped to the visible region.

(function (global) {
  "use strict";

  const C = Constants.COLORS;

  class Renderer {
    constructor(canvas) {
      this.canvas = canvas;
      this.ctx = canvas.getContext("2d");
      this.ctx.imageSmoothingEnabled = false;
      this.bombs = [];
      this.explosions = [];
      this.camera = { x: 0, y: 0 };
      this._lastNow = performance.now();
      this._cameraInit = false;     // camera snapped to target on first frame
      this._dpr = Math.max(1, Math.min(2, window.devicePixelRatio || 1));
      this._resize();
      // window resize covers viewport changes (devtools open/close, window
      // resize). ResizeObserver covers canvas visibility changes (screen
      // switches from display:none to display:flex).
      window.addEventListener("resize", () => this._resize());
      if (typeof ResizeObserver !== "undefined") {
        this._resizeObserver = new ResizeObserver(() => this._resize());
        this._resizeObserver.observe(this.canvas);
      }
    }

    // Called by main.js when the game screen becomes visible. Guarantees the
    // canvas has correct dimensions before the first render frame.
    resizeNow() {
      this._resize();
    }

    // Reset the camera so it snaps to the player on the next render instead
    // of lerping from its previous position. Called on game start and on
    // respawn (the player teleports to a new spawn).
    resetCamera() {
      this._cameraInit = false;
    }

    _resize() {
      const w = this.canvas.clientWidth;
      const h = this.canvas.clientHeight;
      // If the canvas is hidden (display:none), clientWidth/Height are 0.
      // Skip the resize in that case; it will be called again when the
      // canvas becomes visible (via ResizeObserver or an explicit resizeNow()).
      if (w === 0 || h === 0) return;
      this.canvas.width = Math.floor(w * this._dpr);
      this.canvas.height = Math.floor(h * this._dpr);
      this.ctx.setTransform(this._dpr, 0, 0, this._dpr, 0, 0);
      this.ctx.imageSmoothingEnabled = false;
      this.viewW = w;
      this.viewH = h;
    }

    setBombs(bombs) { this.bombs = bombs || []; }
    setExplosions(explosions) { this.explosions = explosions || []; }

    render(now) {
      const ctx = this.ctx;
      const ts = Constants.TILE_SIZE;
      const world = global.World;
      const players = global.Players;
      const interp = global.Interpolator;
      const local = players.local;

      // Delta time for frame-rate independent camera lerp.
      const dt = Math.min(64, now - this._lastNow) / 1000;  // seconds, capped
      this._lastNow = now;

      // Background.
      ctx.fillStyle = C.bg;
      ctx.fillRect(0, 0, this.viewW, this.viewH);

      if (!world.width || !world.height) return;

      // Target camera position: centered on the local player (or world
      // center if no local player). We use the interpolated player position
      // so the camera target moves smoothly between cells.
      let targetX, targetY;
      if (local) {
        const lp = interp.getPos(local.id) || { x: local.x, y: local.y };
        targetX = lp.x * ts + ts / 2 - this.viewW / 2;
        targetY = lp.y * ts + ts / 2 - this.viewH / 2;
      } else {
        targetX = (world.width * ts) / 2 - this.viewW / 2;
        targetY = (world.height * ts) / 2 - this.viewH / 2;
      }

      // Smooth camera: lerp the current camera position toward the target.
      // On the first frame (or after a resize/teleport), snap to the target
      // so the camera doesn't slide in from (0,0). Otherwise, lerp with a
      // frame-rate independent factor for a fluid "catch-up" feel.
      if (!this._cameraInit) {
        this.camera.x = targetX;
        this.camera.y = targetY;
        this._cameraInit = true;
      } else {
        // base = 0.18 per frame at 60fps → smooth but responsive.
        // frame-rate independent: alpha = 1 - (1-base)^(dt*60)
        const base = 0.18;
        const alpha = 1 - Math.pow(1 - base, dt * 60);
        this.camera.x += (targetX - this.camera.x) * alpha;
        this.camera.y += (targetY - this.camera.y) * alpha;
      }

      // Clamp camera so we never show past the map edges (when map is larger
      // than the viewport). If map is smaller, center it.
      let camX = this.camera.x;
      let camY = this.camera.y;
      const worldW = world.width * ts;
      const worldH = world.height * ts;
      if (worldW <= this.viewW) camX = (worldW - this.viewW) / 2;
      else camX = Math.max(0, Math.min(camX, worldW - this.viewW));
      if (worldH <= this.viewH) camY = (worldH - this.viewH) / 2;
      else camY = Math.max(0, Math.min(camY, worldH - this.viewH));
      this.camera.x = camX;
      this.camera.y = camY;

      // Visible cell range.
      const x0 = Math.max(0, Math.floor(camX / ts));
      const y0 = Math.max(0, Math.floor(camY / ts));
      const x1 = Math.min(world.width - 1, Math.ceil((camX + this.viewW) / ts));
      const y1 = Math.min(world.height - 1, Math.ceil((camY + this.viewH) / ts));

      // FOV mask (only if there's a local player).
      const mask = FOV.computeMask(world, local);

      // Draw tiles.
      for (let y = y0; y <= y1; y++) {
        for (let x = x0; x <= x1; x++) {
          const visible = !mask || mask[y * world.width + x];
          const sx = Math.round(x * ts - camX);
          const sy = Math.round(y * ts - camY);
          if (!visible) {
            ctx.fillStyle = C.fog;
            ctx.fillRect(sx, sy, ts, ts);
            continue;
          }
          this._drawTile(ctx, x, y, sx, sy, ts);
        }
      }

      // Draw spawn markers (subtle).
      if (mask) {
        for (const [sx, sy] of world.spawns) {
          if (mask[sy * world.width + sx]) {
            ctx.fillStyle = C.spawn;
            ctx.fillRect(Math.round(sx * ts - camX), Math.round(sy * ts - camY), ts, ts);
          }
        }
      }

      // Draw bombs.
      for (const b of this.bombs) {
        if (mask && !mask[b.y * world.width + b.x]) continue;
        this._drawBomb(ctx, b, camX, camY, ts, now);
      }

      // Draw explosions.
      for (const ex of this.explosions) {
        if (!ex.cells) continue;
        // cells is a flat list [x,y,x,y,...]
        const cells = ex.cells;
        for (let i = 0; i + 1 < cells.length; i += 2) {
          const cx = cells[i];
          const cy = cells[i + 1];
          if (mask && !mask[cy * world.width + cx]) continue;
          this._drawExplosionCell(ctx, cx, cy, camX, camY, ts, ex.remaining_ms || 0);
        }
      }

      // Draw players.
      for (const p of players.all()) {
        if (!p.alive) continue;
        if (mask && !mask[p.y * world.width + p.x]) continue;
        const pos = interp.getPos(p.id) || { x: p.x, y: p.y };
        this._drawPlayer(ctx, p, pos, camX, camY, ts, now, p.id === players.localId);
      }

      // Draw dead-player ghosts faintly at their last position (for context).
      for (const p of players.all()) {
        if (p.alive) continue;
        const pos = interp.getPos(p.id);
        if (!pos) continue;
        if (mask && !mask[p.y * world.width + p.x]) continue;
        this._drawDeadGhost(ctx, p, pos, camX, camY, ts);
      }

      // Subtle grid overlay (only on floor, only when visible).
      ctx.strokeStyle = C.grid;
      ctx.lineWidth = 1;
      ctx.beginPath();
      for (let x = x0; x <= x1 + 1; x++) {
        const sx = Math.round(x * ts - camX) + 0.5;
        ctx.moveTo(sx, Math.round(y0 * ts - camY));
        ctx.lineTo(sx, Math.round((y1 + 1) * ts - camY));
      }
      for (let y = y0; y <= y1 + 1; y++) {
        const sy = Math.round(y * ts - camY) + 0.5;
        ctx.moveTo(Math.round(x0 * ts - camX), sy);
        ctx.lineTo(Math.round((x1 + 1) * ts - camX), sy);
      }
      ctx.stroke();
    }

    _drawTile(ctx, x, y, sx, sy, ts) {
      const world = global.World;
      const tile = world.getTile(x, y);
      // Base floor with subtle checker.
      const alt = (x + y) & 1;
      ctx.fillStyle = alt ? C.floor : C.floorAlt;
      ctx.fillRect(sx, sy, ts, ts);
      if (tile === Constants.TILE_WALL) {
        ctx.fillStyle = C.wall;
        ctx.fillRect(sx, sy, ts, ts);
        ctx.fillStyle = C.wallTop;
        ctx.fillRect(sx + 2, sy + 2, ts - 4, ts - 4);
        ctx.fillStyle = "rgba(0,0,0,0.35)";
        ctx.fillRect(sx, sy + ts - 4, ts, 4);
      } else if (tile === Constants.TILE_DIRT) {
        ctx.fillStyle = C.dirt;
        ctx.fillRect(sx, sy, ts, ts);
        ctx.fillStyle = C.dirtTop;
        ctx.fillRect(sx + 3, sy + 3, ts - 6, ts - 6);
        // Texture dots.
        ctx.fillStyle = "rgba(0,0,0,0.25)";
        ctx.fillRect(sx + 6, sy + 8, 2, 2);
        ctx.fillRect(sx + ts - 9, sy + ts - 11, 2, 2);
      } else if (tile === Constants.TILE_ROCK) {
        ctx.fillStyle = C.rock;
        ctx.fillRect(sx, sy, ts, ts);
        ctx.fillStyle = C.rockTop;
        ctx.beginPath();
        ctx.arc(sx + ts / 2, sy + ts / 2, ts * 0.38, 0, Math.PI * 2);
        ctx.fill();
        ctx.strokeStyle = "rgba(0,0,0,0.4)";
        ctx.lineWidth = 1.5;
        ctx.beginPath();
        ctx.arc(sx + ts / 2, sy + ts / 2, ts * 0.38, 0, Math.PI * 2);
        ctx.stroke();
      }
    }

    _drawBomb(ctx, b, camX, camY, ts, now) {
      const cx = Math.round(b.x * ts - camX) + ts / 2;
      const cy = Math.round(b.y * ts - camY) + ts / 2;
      const tl = (b.explodes_in_ms || 0) / 1000;
      // Pulse faster as fuse runs out.
      const pulse = 0.5 + 0.5 * Math.sin(now / 60 + b.x + b.y);
      const radius = ts * 0.32 + (tl < 0.5 ? pulse * 3 : 0);
      // Glow.
      ctx.fillStyle = C.bombGlow;
      ctx.globalAlpha = tl < 0.5 ? 0.45 : 0.25;
      ctx.beginPath();
      ctx.arc(cx, cy, radius + 4, 0, Math.PI * 2);
      ctx.fill();
      ctx.globalAlpha = 1;
      // Body.
      ctx.fillStyle = C.bomb;
      ctx.beginPath();
      ctx.arc(cx, cy, radius, 0, Math.PI * 2);
      ctx.fill();
      // Fuse highlight.
      ctx.fillStyle = "#fff";
      ctx.fillRect(cx - 1, cy - radius - 3, 2, 3);
    }

    _drawExplosionCell(ctx, x, y, camX, camY, ts, remaining) {
      const sx = Math.round(x * ts - camX);
      const sy = Math.round(y * ts - camY);
      const alpha = Math.max(0, Math.min(1, remaining / 450));
      ctx.globalAlpha = alpha;
      ctx.fillStyle = C.explosion;
      ctx.fillRect(sx + 2, sy + 2, ts - 4, ts - 4);
      ctx.fillStyle = C.explosionCore;
      ctx.fillRect(sx + ts * 0.3, sy + ts * 0.3, ts * 0.4, ts * 0.4);
      ctx.globalAlpha = 1;
    }

    _drawPlayer(ctx, p, pos, camX, camY, ts, now, isLocal) {
      const px = Math.round(pos.x * ts - camX) + ts / 2;
      const py = Math.round(pos.y * ts - camY) + ts / 2;
      const r = ts * 0.34;
      // Shadow.
      ctx.fillStyle = "rgba(0,0,0,0.4)";
      ctx.beginPath();
      ctx.ellipse(px, py + r * 0.8, r * 0.9, r * 0.4, 0, 0, Math.PI * 2);
      ctx.fill();
      // Body color.
      let bodyColor;
      if (isLocal) bodyColor = C.playerSelf;
      else if (p.team === 0) bodyColor = C.playerAlly;
      else if (p.team === 1) bodyColor = C.playerEnemy;
      else bodyColor = C.playerEnemy;
      ctx.fillStyle = bodyColor;
      ctx.beginPath();
      ctx.arc(px, py, r, 0, Math.PI * 2);
      ctx.fill();
      // Outline.
      ctx.strokeStyle = "rgba(0,0,0,0.6)";
      ctx.lineWidth = 2;
      ctx.stroke();
      // Facing indicator (small triangle).
      const [dx, dy] = Constants.DIRECTION_VECTORS[p.facing] || [0, 1];
      ctx.fillStyle = "#000";
      ctx.beginPath();
      const fx = px + dx * r * 0.9;
      const fy = py + dy * r * 0.9;
      ctx.arc(fx, fy, 2.5, 0, Math.PI * 2);
      ctx.fill();
      // Name + health bar.
      const nameY = py - r - 14;
      ctx.font = "11px 'Share Tech Mono', monospace";
      ctx.textAlign = "center";
      ctx.fillStyle = "rgba(0,0,0,0.7)";
      const nameW = ctx.measureText(p.name || "").width + 8;
      ctx.fillRect(px - nameW / 2, nameY - 9, nameW, 13);
      ctx.fillStyle = C.hudFg;
      ctx.fillText(p.name || "", px, nameY + 1);
      // Health bar.
      const hpW = ts * 0.9;
      const hpH = 4;
      const hpX = px - hpW / 2;
      const hpY = py + r + 4;
      ctx.fillStyle = "rgba(0,0,0,0.6)";
      ctx.fillRect(hpX, hpY, hpW, hpH);
      const ratio = Math.max(0, Math.min(1, p.health / 100));
      ctx.fillStyle = ratio > 0.5 ? C.hudOk : ratio > 0.25 ? C.hudAccent : C.hudDanger;
      ctx.fillRect(hpX, hpY, hpW * ratio, hpH);
    }

    _drawDeadGhost(ctx, p, pos, camX, camY, ts) {
      const px = Math.round(pos.x * ts - camX) + ts / 2;
      const py = Math.round(pos.y * ts - camY) + ts / 2;
      ctx.globalAlpha = 0.4;
      ctx.fillStyle = C.playerDead;
      ctx.beginPath();
      ctx.arc(px, py, ts * 0.28, 0, Math.PI * 2);
      ctx.fill();
      ctx.globalAlpha = 1;
    }
  }

  global.Renderer = Renderer;
})(typeof window !== "undefined" ? window : this);
