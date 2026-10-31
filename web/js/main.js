// main.js — entry point, screen orchestration, game loop.
//
// Screens:
//   * #screen-connect : pick a name + connect
//   * #screen-lobby   : room list / create / join
//   * #screen-room    : pre-game lobby (chat, teams, start button)
//   * #screen-game    : canvas + HUD + minimap
//
// The game loop runs at requestAnimationFrame and only renders; it never
// mutates authoritative state. Inputs are forwarded to Input.pump().

(function (global) {
  "use strict";

  let net = global.Net;
  let input = global.Input;
  let world = global.World;
  let players = global.Players;
  let interp = global.Interpolator;

  let renderer = null;
  let hud = null;

  let bombs = [];
  let explosions = [];
  let timeLeftMs = -1;
  let gameRunning = false;
  let endScreenVisible = false;   // true while the GAME_END overlay is shown
  let lastFrame = performance.now();
  let pingTimer = null;
  let currentRoom = null;

  // -------------------------------------------------------------------------
  // Boot
  // -------------------------------------------------------------------------
  document.addEventListener("DOMContentLoaded", () => {
    show("screen-connect");
    bindConnect();
    bindLobby();
    bindRoom();
    bindGame();
    bindModeToggle();
  });

  // -------------------------------------------------------------------------
  // Mode PC / Mobile toggle
  // -------------------------------------------------------------------------
  function bindModeToggle() {
    const btn = document.getElementById("toggle-mode-btn");
    const hint = document.getElementById("mobile-hint");
    if (!btn) return;
    const updateLabel = () => {
      const mode = global.Mobile.getMode();
      btn.textContent = "Mode: " + (mode === "mobile" ? "Mobile" : "PC");
      if (hint) hint.style.display = (mode === "mobile") ? "block" : "none";
    };
    updateLabel();
    btn.addEventListener("click", () => {
      const current = global.Mobile.getMode();
      const next = current === "mobile" ? "pc" : "mobile";
      global.Mobile.setMode(next);
      updateLabel();
      // If a game is running, apply immediately.
      if (gameRunning) {
        if (next === "mobile") global.Mobile.show();
        else global.Mobile.hide();
      }
      if (global.Sfx) global.Sfx.click();
    });
  }

  function bindConnect() {
    const nameInput = document.getElementById("name-input");
    const connectBtn = document.getElementById("connect-btn");
    const saved = net._loadName();
    if (saved) nameInput.value = saved;
    connectBtn.addEventListener("click", () => {
      const name = (nameInput.value || "").trim().slice(0, 16) || "soldier";
      net.saveName(name);
      const url = deriveWsUrl();
      net.onMessage(onNetMessage);
      net.onStatus(onNetStatus);
      net.connect(url);
      setConnectStatus("Connexion...");
    });
    nameInput.addEventListener("keydown", (e) => {
      if (e.key === "Enter") connectBtn.click();
    });
  }

  function deriveWsUrl() {
    const loc = window.location;
    const proto = loc.protocol === "https:" ? "wss:" : "ws:";
    // WebSocket lives at /ws (HTTP routes /, /health, /js/*, /css/* are
    // served by aiohttp on the same port).
    return `${proto}//${loc.host}/ws`;
  }

  function setConnectStatus(txt, isError) {
    const el = document.getElementById("connect-status");
    if (el) {
      el.textContent = txt;
      el.style.color = isError ? "#e74c3c" : "#9fb3c8";
    }
  }

  function onNetStatus(status, extra) {
    if (status === "authenticated") {
      show("screen-lobby");
      requestRoomList();
      startPing();
      if (global.Sfx) global.Sfx.connect();
    } else if (status === "connected") {
      setConnectStatus("Authentification...");
    } else if (status === "reconnecting") {
      setConnectStatus(`Reconnexion dans ${Math.round((extra.delayMs || 0) / 100) / 10}s...`, true);
    } else if (status === "disconnected") {
      if (gameRunning) {
        setOverlay("Connexion perdue, reconnexion...", true);
      }
    } else if (status === "error") {
      setConnectStatus("Erreur réseau", true);
    }
  }

  function startPing() {
    if (pingTimer) clearInterval(pingTimer);
    pingTimer = setInterval(() => net.ping(), 2000);
  }

  // -------------------------------------------------------------------------
  // Lobby (room list + create)
  // -------------------------------------------------------------------------
  let listRefreshTimer = null;

  function bindLobby() {
    document.getElementById("refresh-rooms").addEventListener("click", requestRoomList);
    document.getElementById("create-room-btn").addEventListener("click", () => {
      const name = (document.getElementById("new-room-name").value || "").trim().slice(0, 24) || "Room";
      const cfg = {
        width: parseInt(document.getElementById("cfg-width").value, 10),
        height: parseInt(document.getElementById("cfg-height").value, 10),
        max_players: parseInt(document.getElementById("cfg-max").value, 10),
        score_to_win: parseInt(document.getElementById("cfg-score").value, 10),
        round_time_limit_s: parseInt(document.getElementById("cfg-time").value, 10),
        dirt_regen_enabled: document.getElementById("cfg-regen").checked,
        dirt_regen_interval_s: parseInt(document.getElementById("cfg-regen-interval").value, 10),
      };
      net.send({ type: "CREATE_ROOM", payload: { name, config: cfg } });
    });
    document.getElementById("quick-join-btn").addEventListener("click", () => {
      const items = document.querySelectorAll(".room-row");
      if (items.length === 0) return;
      // Join the first room in "lobby" state.
      for (const it of items) {
        const id = it.getAttribute("data-id");
        const state = it.getAttribute("data-state");
        if (state === "lobby") {
          net.send({ type: "JOIN_ROOM", payload: { room_id: id } });
          return;
        }
      }
    });
  }

  function requestRoomList() {
    net.send({ type: "LIST_ROOMS" });
    if (listRefreshTimer) clearInterval(listRefreshTimer);
    listRefreshTimer = setInterval(() => {
      if (net.authenticated && document.getElementById("screen-lobby").classList.contains("active")) {
        net.send({ type: "LIST_ROOMS" });
      } else {
        clearInterval(listRefreshTimer);
        listRefreshTimer = null;
      }
    }, 4000);
  }

  function renderRoomList(rooms) {
    const list = document.getElementById("room-list");
    if (!list) return;
    if (!rooms || rooms.length === 0) {
      list.innerHTML = `<div class="empty">Aucune room. Crée la tienne ↑</div>`;
      return;
    }
    let html = "";
    for (const r of rooms) {
      const full = r.players >= r.max_players;
      const canJoin = r.state === "lobby" && !full;
      html += `<div class="room-row" data-id="${r.id}" data-state="${r.state}">` +
              `<div class="info"><b>${escapeHtml(r.name)}</b> <span class="muted">#${r.id}</span>` +
              ` <span class="badge">${r.state}</span></div>` +
              `<div class="meta">${r.width}×${r.height} · ${r.players}/${r.max_players} joueurs</div>` +
              `<button class="join-btn" ${canJoin ? "" : "disabled"} data-id="${r.id}">${canJoin ? "Rejoindre" : (full ? "Plein" : "En cours")}</button>` +
              `</div>`;
    }
    list.innerHTML = html;
    for (const btn of list.querySelectorAll(".join-btn")) {
      btn.addEventListener("click", () => {
        net.send({ type: "JOIN_ROOM", payload: { room_id: btn.getAttribute("data-id") } });
      });
    }
  }

  // -------------------------------------------------------------------------
  // Room (pre-game)
  // -------------------------------------------------------------------------
  function bindRoom() {
    document.getElementById("leave-room-btn").addEventListener("click", () => {
      net.send({ type: "LEAVE_ROOM" });
    });
    document.getElementById("team-blue-btn").addEventListener("click", () => {
      net.send({ type: "SET_TEAM", payload: { team: 0 } });
    });
    document.getElementById("team-red-btn").addEventListener("click", () => {
      net.send({ type: "SET_TEAM", payload: { team: 1 } });
    });
    document.getElementById("team-none-btn").addEventListener("click", () => {
      net.send({ type: "SET_TEAM", payload: { team: null } });
    });
    const startBtn = document.getElementById("start-game-btn");
    startBtn.addEventListener("click", () => {
      console.log("[START_GAME] bouton cliqué", {
        playerId: net.playerId,
        authenticated: net.authenticated,
        wsState: net.ws ? net.ws.readyState : "no-ws",
        wsReadyOpen: net.ws ? net.ws.readyState === WebSocket.OPEN : false,
        currentRoom,
      });
      if (startBtn.disabled) {
        console.warn("[START_GAME] bouton DISABLED, click ignoré");
        return;
      }
      const ok = net.send({ type: "START_GAME" });
      console.log("[START_GAME] net.send retourne:", ok);
      if (!ok) {
        flashError("Impossible d'envoyer START_GAME (WS non connectée). État: " +
                   (net.ws ? net.ws.readyState : "null"));
      }
    });
    const chatInput = document.getElementById("chat-input");
    if (chatInput) {
      chatInput.addEventListener("keydown", (e) => {
        if (e.key === "Enter") {
          const txt = (chatInput.value || "").trim().slice(0, 200);
          if (txt) net.send({ type: "CHAT", payload: { text: txt } });
          chatInput.value = "";
        }
      });
    }
  }

  function renderRoomState(room) {
    // Defensive: if a game is running, ignore late ROOM_STATE messages
    // (they could override the game screen). Only show the room screen if
    // the room is actually in lobby state.
    if (gameRunning && room && room.state === "playing") {
      console.log("[ROOM_STATE] ignored (game is running, room.state=playing)");
      return;
    }
    // If the end-screen overlay is currently visible (we just got GAME_END),
    // do NOT switch back to the room screen yet — the server sends the
    // ROOM_STATE reset ~4s after GAME_END, but the overlay might still be
    // visible. We update currentRoom silently so the data is fresh, but we
    // let showEndScreen's timeout hide the overlay first.
    if (endScreenVisible) {
      console.log("[ROOM_STATE] buffered (end screen visible), not switching screen");
      currentRoom = room;
      return;
    }
    currentRoom = room;
    show("screen-room");
    document.getElementById("room-title").textContent = `${room.name} (#${room.id})`;
    document.getElementById("room-meta").textContent =
      `${room.config.width}×${room.config.height} · ${room.players.length}/${room.config.max_players} · cible ${room.config.score_to_win} pts`;
    const isHost = room.players.find(p => p.id === net.playerId && p.is_host);
    const startBtn = document.getElementById("start-game-btn");
    startBtn.disabled = !isHost || room.state !== "lobby";
    startBtn.textContent = isHost ? "Lancer la partie" : "En attente de l'hôte...";
    console.log("[ROOM_STATE] room=", room.id, "state=", room.state,
                "myId=", net.playerId, "host=", room.host_id,
                "isHost=", !!isHost, "btnDisabled=", startBtn.disabled,
                "players=", room.players.length);

    const list = document.getElementById("room-players");
    let html = "";
    for (const p of room.players) {
      const teamTag = p.team === 0 ? '<span class="t blue">Bleu</span>'
                    : p.team === 1 ? '<span class="t red">Rouge</span>'
                    : '<span class="t none">Solo</span>';
      const hostTag = p.is_host ? '<span class="host">★ hôte</span>' : '';
      const meTag = p.id === net.playerId ? '<span class="me">(toi)</span>' : '';
      html += `<div class="rp"><span class="n">${escapeHtml(p.name)}</span> ${teamTag} ${hostTag} ${meTag}</div>`;
    }
    list.innerHTML = html;
  }

  function appendChat(from, name, text) {
    const box = document.getElementById("room-chat");
    if (!box) return;
    const div = document.createElement("div");
    div.className = "chat-msg";
    div.innerHTML = `<span class="from">${escapeHtml(name || from)}</span>: ${escapeHtml(text)}`;
    box.appendChild(div);
    box.scrollTop = box.scrollHeight;
    // Cap history.
    while (box.children.length > 50) box.removeChild(box.firstChild);
  }

  // -------------------------------------------------------------------------
  // Game
  // -------------------------------------------------------------------------
  function bindGame() {
    const canvas = document.getElementById("game-canvas");
    renderer = new global.Renderer(canvas);
    hud = new global.Hud(document.getElementById("hud"));
    document.getElementById("back-to-lobby").addEventListener("click", () => {
      net.send({ type: "LEAVE_ROOM" });
    });
    requestAnimationFrame(loop);
  }

  function loop(now) {
    const dt = Math.min(64, now - lastFrame);
    lastFrame = now;
    interp.update(dt);
    input.pump(now);
    if (gameRunning) {
      // Safety net: if the canvas hasn't been sized yet (e.g. startGame ran
      // before layout), force a resize now. This prevents the "blank canvas
      // until devtools toggle" bug.
      if (renderer && (!renderer.viewW || !renderer.viewH)) renderer.resizeNow();
      renderer.setBombs(bombs);
      renderer.setExplosions(explosions);
      renderer.render(now);
      hud.update({
        local: players.local,
        localId: net.playerId,
        players: players.all(),
        timeLeftMs,
        latencyMs: net.latencyMs,
      });
    }
    requestAnimationFrame(loop);
  }

  function setOverlay(text, isError) {
    const ov = document.getElementById("game-overlay");
    if (!ov) return;
    if (text) {
      ov.style.display = "flex";
      ov.querySelector(".text").textContent = text;
      ov.classList.toggle("error", !!isError);
    } else {
      ov.style.display = "none";
    }
  }

  // -------------------------------------------------------------------------
  // Network message router
  // -------------------------------------------------------------------------
  function onNetMessage(msg) {
    console.log("[NET recv]", msg.type, msg);
    switch (msg.type) {
      case "HELLO_ACK": break; // handled in net.js status
      case "ROOM_LIST":
        renderRoomList(msg.payload && msg.payload.rooms);
        break;
      case "ROOM_STATE":
        renderRoomState(msg.room);
        break;
      case "ROOM_LEFT":
        show("screen-lobby");
        requestRoomList();
        break;
      case "CHAT":
        if (msg.payload) appendChat(msg.payload.from, msg.payload.name, msg.payload.text);
        break;
      case "GAME_START":
        console.log("[GAME_START] reçu, world=", msg.world && msg.world.width, "x", msg.world && msg.world.height,
                    "players=", (msg.players || []).length);
        startGame(msg);
        break;
      case "SNAPSHOT":
        applySnapshot(msg);
        break;
      case "GAME_END":
        showEndScreen(msg);
        break;
      case "ERROR":
        if (msg.message) flashError(msg.message);
        break;
      default:
        break;
    }
  }

  function startGame(msg) {
    // Initialize world from full state.
    if (msg.world) world.initFromFull(msg.world);
    // Initialize players.
    players.setLocalId(net.playerId);
    players.applySnapshot(msg.players || []);
    // Snap interpolator to initial positions.
    interp.reset();
    for (const p of players.all()) interp.snap(p.id, p.x, p.y);
    bombs = msg.bombs || [];
    explosions = msg.explosions || [];
    timeLeftMs = msg.time_left_ms != null ? msg.time_left_ms : -1;
    gameRunning = true;
    show("screen-game");
    input.attach();
    setOverlay("");
    // Activate mobile controls if the user selected Mobile mode.
    if (global.Mobile && global.Mobile.getMode() === "mobile") {
      global.Mobile.show();
    }
    // Force canvas resize now that screen-game is visible. The canvas was
    // created at boot while screen-game was display:none, so its
    // clientWidth/Height were 0. We need a fresh measure before the first
    // render frame. requestAnimationFrame ensures the browser has applied
    // the new display:flex layout before we measure.
    requestAnimationFrame(() => {
      if (renderer) {
        renderer.resizeNow();
        renderer.resetCamera();   // snap camera to player on game start
      }
    });
  }

  function applySnapshot(msg) {
    if (!gameRunning) return;
    if (msg.world_diff) world.applyDiff(msg.world_diff);
    // Detect changed players BEFORE applying so we can feed the interpolator.
    const prev = new Map();
    for (const p of players.all()) prev.set(p.id, { x: p.x, y: p.y, health: p.health, alive: p.alive });
    players.applySnapshot(msg.players || []);
    const now = performance.now();
    for (const p of players.all()) {
      const old = prev.get(p.id);
      if (p._changed && old) {
        interp.onTarget(p.id, p.x, p.y, now);
      } else if (!old) {
        interp.snap(p.id, p.x, p.y);
      }
    }

    // --- Détection des événements sonores (comparaison prev/new) ---
    if (global.Sfx) {
      // 1. Nouvelles explosions : on compare les cellules d'explosion.
      const prevExplosionCells = new Set();
      for (const ex of explosions) {
        if (ex.cells) for (let i = 0; i + 1 < ex.cells.length; i += 2) {
          prevExplosionCells.add(ex.cells[i] + "," + ex.cells[i + 1]);
        }
      }
      const newExplosions = (msg.explosions || []).filter(ex => {
        if (!ex.cells) return false;
        for (let i = 0; i + 1 < ex.cells.length; i += 2) {
          if (!prevExplosionCells.has(ex.cells[i] + "," + ex.cells[i + 1])) {
            return true;  // au moins une cellule nouvelle = nouvelle explosion
          }
        }
        return false;
      });
      if (newExplosions.length > 0) global.Sfx.explosion();

      // 2. Dégâts subis par le joueur local : health a baissé.
      const localAfter = players.local;
      if (localAfter && prev.has(localAfter.id)) {
        const localBefore = prev.get(localAfter.id);
        if (localAfter.health < localBefore.health) {
          if (localAfter.alive) global.Sfx.damage();
          else global.Sfx.death();
        } else if (!localBefore.alive && localAfter.alive) {
          // Respawn !
          global.Sfx.respawn();
          // Reset the camera so it snaps to the new spawn position instead
          // of sliding from the death location.
          if (renderer) renderer.resetCamera();
          if (interp) interp.snap(localAfter.id, localAfter.x, localAfter.y);
        }
      }
    }

    bombs = msg.bombs || [];
    explosions = msg.explosions || [];
    timeLeftMs = msg.time_left_ms != null ? msg.time_left_ms : -1;
    if (msg.over) {
      // Server says game over; wait for GAME_END.
    }
  }

  function showEndScreen(msg) {
    gameRunning = false;
    input.detach();
    if (global.Mobile) global.Mobile.hide();
    endScreenVisible = true;
    const winner = msg.winner_id ? players.get(msg.winner_id) : null;
    const local = players.local;
    const youWon = winner && local && winner.id === local.id;
    setOverlay(youWon ? "Victoire !" : winner ? `Défaite. Gagnant : ${winner.name}` : "Match nul", !youWon);
    // Son de victoire/défaite.
    if (global.Sfx) {
      if (youWon) global.Sfx.win();
      else if (winner) global.Sfx.lose();
    }
    // The server resets the room to lobby state ~4s after GAME_END and sends
    // a ROOM_STATE message. We keep the overlay visible for 4s so players
    // see the result, then hide it and switch to the room screen.
    setTimeout(() => {
      endScreenVisible = false;
      setOverlay("");
      show("screen-room");
    }, 4000);
  }

  // -------------------------------------------------------------------------
  // DOM helpers
  // -------------------------------------------------------------------------
  function show(id) {
    const screens = ["screen-connect", "screen-lobby", "screen-room", "screen-game"];
    for (const s of screens) {
      const el = document.getElementById(s);
      if (el) el.classList.toggle("active", s === id);
    }
  }

  function flashError(text) {
    console.error("[SERVER ERROR]", text);
    let banner = document.getElementById("error-banner");
    if (!banner) {
      banner = document.createElement("div");
      banner.id = "error-banner";
      banner.className = "error-banner";
      document.body.appendChild(banner);
    }
    banner.textContent = text;
    banner.style.opacity = "1";
    // Persist longer (8s) so the user has time to read server errors.
    clearTimeout(banner._t);
    banner._t = setTimeout(() => { banner.style.opacity = "0"; }, 8000);
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, c => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    })[c]);
  }
})(typeof window !== "undefined" ? window : this);
