// net.js — WebSocket client wrapper.
//
// Responsibilities:
//   * Maintain a single WS connection with auto-reconnect.
//   * Send JSON messages with a monotonic seq counter.
//   * Dispatch incoming messages to a registered handler.
//   * Track round-trip latency for clock sync / interp tuning.

(function (global) {
  "use strict";

  const RECONNECT_DELAYS = [500, 1000, 2000, 4000, 8000];

  class NetClient {
    constructor() {
      this.ws = null;
      this.url = null;
      this.connected = false;
      this.authenticated = false;
      this.playerId = null;
      this.seq = 0;
      this.latencyMs = 0;
      this._reconnectIndex = 0;
      this._reconnectTimer = null;
      this._pingSentAt = 0;
      this._handler = null;
      this._statusHandler = null;
      this._draining = false;
    }

    connect(url) {
      this.url = url;
      this._open();
    }

    onMessage(handler) { this._handler = handler; }
    onStatus(handler) { this._statusHandler = handler; }

    _open() {
      try {
        this.ws = new WebSocket(this.url);
      } catch (err) {
        this._scheduleReconnect();
        return;
      }
      this.ws.binaryType = "arraybuffer";

      this.ws.onopen = () => {
        this.connected = true;
        this._reconnectIndex = 0;
        this._emitStatus("connected");
        // Send HELLO immediately.
        const name = this._loadName();
        this.send({ type: "HELLO", payload: { name, version: Constants.PROTOCOL_VERSION } });
      };

      this.ws.onmessage = (ev) => this._onMessage(ev.data);

      this.ws.onerror = () => {
        this._emitStatus("error");
      };

      this.ws.onclose = () => {
        this.connected = false;
        this.authenticated = false;
        this.ws = null;
        this._emitStatus("disconnected");
        this._scheduleReconnect();
      };
    }

    _onMessage(raw) {
      let msg;
      try {
        msg = JSON.parse(raw);
      } catch (err) {
        console.warn("net: bad JSON", err);
        return;
      }
      if (!msg || typeof msg !== "object") return;

      switch (msg.type) {
        case "HELLO_ACK":
          this.authenticated = true;
          this.playerId = (msg.payload && msg.payload.player_id) || null;
          this._emitStatus("authenticated");
          break;
        case "PONG":
          this.latencyMs = performance.now() - this._pingSentAt;
          break;
        case "ERROR":
          console.warn("server error:", msg);
          break;
      }
      if (this._handler) {
        try { this._handler(msg); } catch (err) { console.error("handler error", err); }
      }
    }

    send(msg) {
      if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return false;
      if (msg && typeof msg === "object") {
        if (!("seq" in msg) && msg.type !== "HELLO") msg.seq = ++this.seq;
      }
      try {
        this.ws.send(JSON.stringify(msg));
        return true;
      } catch (err) {
        console.warn("net: send failed", err);
        return false;
      }
    }

    ping() {
      if (!this.connected) return;
      this._pingSentAt = performance.now();
      this.send({ type: "PING" });
    }

    _scheduleReconnect() {
      if (this._reconnectTimer) return;
      const delay = RECONNECT_DELAYS[Math.min(this._reconnectIndex, RECONNECT_DELAYS.length - 1)];
      this._reconnectIndex++;
      this._emitStatus("reconnecting", { delayMs: delay });
      this._reconnectTimer = setTimeout(() => {
        this._reconnectTimer = null;
        this._open();
      }, delay);
    }

    _emitStatus(status, extra) {
      if (this._statusHandler) {
        try { this._statusHandler(status, extra || {}); } catch (e) { console.error(e); }
      }
    }

    _loadName() {
      try {
        return localStorage.getItem("digwar.name") || ("soldier-" + Math.floor(Math.random() * 9000 + 1000));
      } catch (e) {
        return "soldier-" + Math.floor(Math.random() * 9000 + 1000);
      }
    }

    saveName(name) {
      try { localStorage.setItem("digwar.name", name); } catch (e) { /* ignore */ }
    }

    close() {
      if (this._reconnectTimer) {
        clearTimeout(this._reconnectTimer);
        this._reconnectTimer = null;
      }
      if (this.ws) {
        try { this.ws.close(); } catch (e) {}
        this.ws = null;
      }
    }
  }

  global.Net = new NetClient();
})(typeof window !== "undefined" ? window : this);
