// input.js — discrete, server-paced input manager.
//
// STRICT RULES (enforced client-side, mirrored server-side):
//   * One key press -> exactly one MOVE message -> at most one cell move.
//   * No diagonals: only the 4 cardinal directions.
//   * Auto-repeat while a key is held is paced by MOVE_COOLDOWN_MS so the
//     server-side cooldown never rejects inputs (matches server timing).
//   * If several direction keys are held, only ONE axis is used: the most
//     recently pressed key wins (stable, predictable).
//   * Tool keys are edge-triggered (one action per keydown, no repeat).
//
// The client NEVER moves the player locally. It only sends intents and
// waits for the next snapshot to reflect the new position.

(function (global) {
  "use strict";

  const KEY_TO_DIR = {
    "ArrowUp": "UP", "KeyW": "UP", "KeyZ": "UP",
    "ArrowDown": "DOWN", "KeyS": "DOWN",
    "ArrowLeft": "LEFT", "KeyA": "LEFT", "KeyQ": "LEFT",
    "ArrowRight": "RIGHT", "KeyD": "RIGHT",
  };

  const TOOL_KEYS = {
    "Space": "BOMB",
    "KeyE": "SHOVEL",
    "KeyF": "KNIFE",
    "ShiftLeft": "KNIFE",
  };

  class InputManager {
    constructor(net) {
      this.net = net;
      this.heldKeys = new Set();      // currently held direction keys
      this.pressOrder = [];           // most-recent-first ordering of held dir keys
      this.lastMoveAt = 0;
      this.lastToolAt = { SHOVEL: 0, KNIFE: 0, BOMB: 0 };
      this.enabled = false;
      this._onStatus = null;
      this._boundDown = this._onKeyDown.bind(this);
      this._boundUp = this._onKeyUp.bind(this);
      this._boundBlur = this._clear.bind(this);
    }

    attach() {
      window.addEventListener("keydown", this._boundDown);
      window.addEventListener("keyup", this._boundUp);
      window.addEventListener("blur", this._boundBlur);
      this.enabled = true;
    }

    detach() {
      window.removeEventListener("keydown", this._boundDown);
      window.removeEventListener("keyup", this._boundUp);
      window.removeEventListener("blur", this._boundBlur);
      this.enabled = false;
      this._clear();
    }

    onStatus(cb) { this._onStatus = cb; }

    // Auto-repeat pump: called from the main loop with the current timestamp.
    pump(now) {
      if (!this.enabled) return;
      const dir = this._activeDirection();
      if (!dir) return;
      if (now - this.lastMoveAt < Constants.MOVE_COOLDOWN_MS) return;
      this._sendMove(dir, now);
    }

    _onKeyDown(ev) {
      if (!this.enabled) return;
      // Ignore key repeats from the OS for direction keys: we do our own pacing.
      const dir = KEY_TO_DIR[ev.code];
      if (dir) {
        ev.preventDefault();
        if (ev.repeat) return;            // OS auto-repeat -> ignore, we pump ourselves
        if (!this.heldKeys.has(ev.code)) {
          this.heldKeys.add(ev.code);
          this.pressOrder.push(ev.code);
        }
        // Immediate first move on keydown edge.
        const now = performance.now();
        if (now - this.lastMoveAt >= Constants.MOVE_COOLDOWN_MS) {
          this._sendMove(this._activeDirection(), now);
        }
        return;
      }
      const tool = TOOL_KEYS[ev.code];
      if (tool) {
        ev.preventDefault();
        if (ev.repeat) return;            // edge-triggered only
        const now = performance.now();
        const cd = Constants.TOOL_COOLDOWN_MS[tool] || 0;
        if (now - this.lastToolAt[tool] < cd) return;
        this.lastToolAt[tool] = now;
        this.net.send({ type: "USE_TOOL", payload: { tool } });
        // Son local immédiat (réponse au joueur avant la validation serveur).
        if (global.Sfx) {
          if (tool === "SHOVEL") global.Sfx.shovel();
          else if (tool === "KNIFE") global.Sfx.knife();
          else if (tool === "BOMB") global.Sfx.bombPlace();
        }
        if (this._onStatus) this._onStatus("tool", { tool });
      }
    }

    _onKeyUp(ev) {
      this.heldKeys.delete(ev.code);
      // Remove from pressOrder too.
      const i = this.pressOrder.indexOf(ev.code);
      if (i !== -1) this.pressOrder.splice(i, 1);
    }

    _clear() {
      this.heldKeys.clear();
      this.pressOrder.length = 0;
    }

    _activeDirection() {
      // Most recently pressed still-held direction key wins (single axis).
      for (let i = this.pressOrder.length - 1; i >= 0; i--) {
        const code = this.pressOrder[i];
        if (this.heldKeys.has(code)) {
          return KEY_TO_DIR[code];
        }
      }
      return null;
    }

    _sendMove(direction, now) {
      if (!direction) return;
      this.lastMoveAt = now;
      this.net.send({ type: "MOVE", payload: { direction } });
    }
  }

  global.Input = new InputManager(global.Net);
})(typeof window !== "undefined" ? window : this);
