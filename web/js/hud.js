// hud.js — heads-up display overlay (HTML, not canvas).
//
// Renders score, health, time, current tool, latency and respawn timer.
// Pure DOM updates, no game state mutation.

(function (global) {
  "use strict";

  class Hud {
    constructor(root) {
      this.root = root;
      this._cache = {};
    }

    _ensure(id) {
      if (!this._cache[id]) {
        const el = document.getElementById(id);
        if (el) this._cache[id] = el;
      }
      return this._cache[id];
    }

    update(state) {
      const local = state.local;
      const set = (id, txt) => {
        const el = this._ensure(id);
        if (el && el.textContent !== txt) el.textContent = txt;
      };
      const setHTML = (id, html) => {
        const el = this._ensure(id);
        if (el && el.innerHTML !== html) el.innerHTML = html;
      };

      if (local) {
        set("hud-name", local.name || "");
        set("hud-score", String(local.score | 0));
        set("hud-kills", String(local.kills | 0));
        set("hud-deaths", String(local.deaths | 0));
        const hp = Math.max(0, Math.min(100, local.health | 0));
        set("hud-hp", String(hp));
        const hpBar = this._ensure("hud-hp-bar");
        if (hpBar) hpBar.style.width = hp + "%";
        if (hpBar) hpBar.style.background = hp > 50 ? "#2ecc71" : hp > 25 ? "#e67e22" : "#e74c3c";
        if (!local.alive && local.respawn_in_ms > 0) {
          set("hud-respawn", "Respawn dans " + Math.ceil(local.respawn_in_ms / 1000) + "s");
        } else {
          set("hud-respawn", local.alive ? "" : "En attente de respawn...");
        }
      } else {
        set("hud-name", "—");
        set("hud-score", "0");
        set("hud-kills", "0");
        set("hud-deaths", "0");
        set("hud-hp", "0");
        set("hud-respawn", "");
      }

      // Scoreboard (top 5).
      const board = this._ensure("hud-board");
      if (board) {
        const ranked = state.players.slice().sort((a, b) => (b.score - a.score) || (b.kills - a.kills));
        const top = ranked.slice(0, 5);
        let html = "";
        for (const p of top) {
          const cls = p.id === state.localId ? "me" : "";
          html += `<div class="row ${cls}"><span class="n">${escapeHtml(p.name || "")}</span>` +
                  `<span class="s">${p.score}</span><span class="k">${p.kills}/${p.deaths}</span></div>`;
        }
        if (board.innerHTML !== html) board.innerHTML = html;
      }

      // Time.
      if (state.timeLeftMs != null && state.timeLeftMs >= 0) {
        const s = Math.ceil(state.timeLeftMs / 1000);
        const mm = Math.floor(s / 60);
        const ss = s % 60;
        set("hud-time", `${mm}:${ss.toString().padStart(2, "0")}`);
      } else {
        set("hud-time", "∞");
      }

      // Latency.
      set("hud-ping", state.latencyMs != null ? state.latencyMs + " ms" : "—");
    }
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, c => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    })[c]);
  }

  global.Hud = Hud;
})(typeof window !== "undefined" ? window : this);
