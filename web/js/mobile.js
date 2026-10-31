// mobile.js — contrôles tactiles pour mobile (joystick style Brawl Stars).
//
// En mode mobile :
//   - Un joystick de déplacement apparaît là où le joueur touche l'écran.
//     Le joueur glisse son doigt pour choisir la direction (la plus proche
//     parmi UP/DOWN/LEFT/RIGHT). Tant que le doigt est appuyé, le joueur
//     avance au rythme du cooldown serveur.
//   - Les boutons outils (pelle / couteau / bombe) restent en overlay et
//     sont repositionnables par drag & drop.
//
// Le joystick ne se déclenche PAS si on tape sur un bouton outil.

(function (global) {
  "use strict";

  const TOOL_BUTTONS = [
    { id: "mb-shovel", tool: "SHOVEL", label: "Pelle" },
    { id: "mb-knife",  tool: "KNIFE",  label: "Couteau" },
    { id: "mb-bomb",   tool: "BOMB",   label: "Bombe" },
  ];

  // Default positions for tool buttons, arranged in a triangle on the
  // right side of the screen:
  //   shovel (top-left of triangle)
  //   knife  (top-right of triangle)
  //   bomb   (bottom-center of triangle)
  const DEFAULT_POSITIONS = {
    "mb-shovel": { left: 24,  bottom: 100 },
    "mb-knife":  { left: 96,  bottom: 100 },
    "mb-bomb":   { left: 60,  bottom: 32  },
  };

  const STORAGE_KEY = "digwar.mobileButtonPositions";
  const MODE_KEY = "digwar.inputMode";   // "pc" | "mobile"

  // Placement mode: when active, tool buttons can be dragged. Activated by
  // tapping the dedicated "Placer" button (gear icon). No timer — stays
  // active until the player taps the button again. Positions are saved to
  // localStorage when the player exits placement mode.
  let placementMode = false;
  let placerBtn = null;
  let placementHintEl = null;

  // Joystick geometry.
  const JOY_RADIUS = 72;          // max distance the stick can travel from base
  const JOY_DEAD_ZONE = 24;       // below this distance, no direction emitted
  const JOY_BASE_RADIUS = 60;     // visual radius of the base circle
  const JOY_STICK_RADIUS = 30;    // visual radius of the moving stick

  let overlay = null;
  let toolButtons = {};        // id -> HTMLElement
  let joyBase = null;          // joystick base circle (visible while active)
  let joyStick = null;         // joystick moving knob
  let active = false;          // module active?
  let lastMoveAt = 0;
  let lastToolAt = { SHOVEL: 0, KNIFE: 0, BOMB: 0 };

  // Joystick state.
  let joyActive = false;       // is the joystick currently being used?
  let joyOriginX = 0;          // touch start X (center of base)
  let joyOriginY = 0;          // touch start Y (center of base)
  let joyPointerId = null;     // which pointer is driving the joystick
  let joyPumpInterval = null;  // setInterval handle for continuous moves
  let joyCurrentDir = null;    // current cardinal direction (UP/DOWN/LEFT/RIGHT)

  // --- Position persistence ---

  function loadPositions() {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (!raw) return { ...DEFAULT_POSITIONS };
      return { ...DEFAULT_POSITIONS, ...JSON.parse(raw) };
    } catch (e) {
      return { ...DEFAULT_POSITIONS };
    }
  }

  function savePositions(positions) {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(positions));
    } catch (e) { /* ignore */ }
  }

  function applyPosition(el, pos) {
    el.style.left = ""; el.style.right = ""; el.style.top = ""; el.style.bottom = "";
    if (pos.left != null)   el.style.left = pos.left + "px";
    if (pos.right != null)  el.style.right = pos.right + "px";
    if (pos.top != null)    el.style.top = pos.top + "px";
    if (pos.bottom != null) el.style.bottom = pos.bottom + "px";
  }

  // --- Tool button drag & drop with placement mode ---
  //
  // Buttons are NOT draggable by default (so the player doesn't move them
  // by accident during a game). To move them, the player taps the "Placer"
  // button (gear icon) to enter placement mode. While in placement mode:
  //   - All tool buttons become draggable.
  //   - Tool buttons do NOT fire their action (so the player can grab them
  //     without using the tool by accident).
  //   - A hint "Mode placement — tape ⚙ quand terminé" is shown.
  // The player taps the "Placer" button again to exit placement mode; at
  // that point positions are saved to localStorage.

  function isPlacementMode() {
    return placementMode;
  }

  function enterPlacementMode() {
    placementMode = true;
    if (placerBtn) placerBtn.classList.add("active");
    // Highlight all tool buttons.
    for (const id in toolButtons) toolButtons[id].classList.add("placement");
    showPlacementHint(true);
  }

  function exitPlacementMode() {
    placementMode = false;
    if (placerBtn) placerBtn.classList.remove("active");
    for (const id in toolButtons) toolButtons[id].classList.remove("placement");
    showPlacementHint(false);
  }

  function togglePlacementMode() {
    if (placementMode) {
      exitPlacementMode();
      // Save all positions when exiting.
      saveAllPositions();
    } else {
      enterPlacementMode();
    }
  }

  function saveAllPositions() {
    // Re-read current positions from the DOM and save.
    const positions = loadPositions();
    for (const id in toolButtons) {
      const el = toolButtons[id];
      const rect = el.getBoundingClientRect();
      positions[id] = { left: Math.round(rect.left), top: Math.round(rect.top) };
    }
    savePositions(positions);
    if (global.Sfx) global.Sfx.click();
  }

  function showPlacementHint(show) {
    if (!placementHintEl) {
      placementHintEl = document.createElement("div");
      placementHintEl.className = "mb-placement-hint";
      placementHintEl.textContent = "Mode placement — tape ⚙ quand terminé";
      document.body.appendChild(placementHintEl);
    }
    placementHintEl.style.display = show ? "block" : "none";
  }

  function makeToolDraggable(el, id, positions) {
    let dragStartX = 0, dragStartY = 0;
    let isPointerDown = false;   // a pointer button is currently held on this el
    let dragging = false;        // the pointer has moved enough to count as a drag
    let moved = false;
    let activePointerId = null;  // which pointer is dragging (multi-touch safety)

    el.addEventListener("pointerdown", (e) => {
      if (!placementMode) return;   // only drag in placement mode
      // Start tracking this pointer. We don't move the button yet — we wait
      // for a pointermove beyond a small threshold to distinguish a click
      // from a drag.
      isPointerDown = true;
      dragging = false;
      moved = false;
      activePointerId = e.pointerId;
      dragStartX = e.clientX;
      dragStartY = e.clientY;
      e.stopPropagation();   // don't trigger the joystick
    });
    el.addEventListener("pointermove", (e) => {
      if (!placementMode) return;
      // Only react if a pointer is actually held down on this button.
      // Without this check, hovering the mouse over the button (desktop)
      // would move it because pointermove fires on hover.
      if (!isPointerDown) return;
      if (e.pointerId !== activePointerId) return;
      const dx = e.clientX - dragStartX;
      const dy = e.clientY - dragStartY;
      // Threshold to start the actual drag (avoids micro-jitter on tap).
      if (!dragging && (Math.abs(dx) > 4 || Math.abs(dy) > 4)) {
        dragging = true;
        moved = true;
        el.classList.add("dragging");
        try { el.setPointerCapture(e.pointerId); } catch (_) {}
      }
      if (dragging) {
        const rect = el.getBoundingClientRect();
        const newLeft = rect.left + dx;
        const newTop = rect.top + dy;
        const clampedLeft = Math.max(8, Math.min(window.innerWidth - rect.width - 8, newLeft));
        const clampedTop = Math.max(8, Math.min(window.innerHeight - rect.height - 8, newTop));
        el.style.left = clampedLeft + "px";
        el.style.right = "";
        el.style.top = clampedTop + "px";
        el.style.bottom = "";
        dragStartX = e.clientX;
        dragStartY = e.clientY;
        e.preventDefault();
      }
    });
    const endDrag = (e) => {
      if (dragging && moved) {
        el.classList.remove("dragging");
        try { el.releasePointerCapture(e.pointerId); } catch (_) {}
        el._suppressClick = true;
        setTimeout(() => { el._suppressClick = false; }, 50);
        e.preventDefault();
      }
      isPointerDown = false;
      dragging = false;
      activePointerId = null;
    };
    el.addEventListener("pointerup", endDrag);
    el.addEventListener("pointercancel", endDrag);
    // If the pointer leaves the button while held (e.g. finger slides off),
    // end the drag too.
    el.addEventListener("lostpointercapture", endDrag);
  }

  function setupToolButton(el, tool) {
    el.addEventListener("click", (e) => {
      if (el._suppressClick) return;
      e.preventDefault();
      e.stopPropagation();
      // In placement mode, do NOT fire the tool — the tap was just to
      // acknowledge the placement.
      if (placementMode) return;
      const now = performance.now();
      const cd = Constants.TOOL_COOLDOWN_MS[tool] || 0;
      if (now - lastToolAt[tool] < cd) return;
      lastToolAt[tool] = now;
      global.Net.send({ type: "USE_TOOL", payload: { tool } });
      if (global.Sfx) {
        if (tool === "SHOVEL") global.Sfx.shovel();
        else if (tool === "KNIFE") global.Sfx.knife();
        else if (tool === "BOMB") global.Sfx.bombPlace();
      }
      el.classList.add("active");
      setTimeout(() => el.classList.remove("active"), 120);
    });
    // Prevent the joystick from starting when pressing a tool button.
    el.addEventListener("pointerdown", (e) => {
      if (placementMode) e.stopPropagation();
      else e.stopPropagation();
    }, { capture: true });
  }

  // --- "Placer" button (gear icon) ---

  function createPlacerButton() {
    placerBtn = document.createElement("button");
    placerBtn.id = "mb-placer";
    placerBtn.className = "mb-button mb-placer";
    placerBtn.textContent = "⚙";
    placerBtn.setAttribute("aria-label", "Placement des boutons");
    // Position: top-right corner.
    placerBtn.style.right = "16px";
    placerBtn.style.top = "16px";
    placerBtn.style.left = "";
    placerBtn.style.bottom = "";
    overlay.appendChild(placerBtn);
    placerBtn.addEventListener("click", (e) => {
      e.preventDefault();
      e.stopPropagation();
      togglePlacementMode();
    });
    // Prevent the joystick from starting when pressing the placer button.
    placerBtn.addEventListener("pointerdown", (e) => e.stopPropagation(), { capture: true });
  }

  // --- Joystick (Brawl Stars style) ---

  function createJoystickVisuals() {
    joyBase = document.createElement("div");
    joyBase.className = "mb-joy-base";
    joyBase.style.display = "none";
    overlay.appendChild(joyBase);

    joyStick = document.createElement("div");
    joyStick.className = "mb-joy-stick";
    joyStick.style.display = "none";
    overlay.appendChild(joyStick);
  }

  function showJoystick(x, y) {
    joyOriginX = x;
    joyOriginY = y;
    joyBase.style.left = (x - JOY_BASE_RADIUS) + "px";
    joyBase.style.top = (y - JOY_BASE_RADIUS) + "px";
    joyBase.style.display = "block";
    joyStick.style.left = (x - JOY_STICK_RADIUS) + "px";
    joyStick.style.top = (y - JOY_STICK_RADIUS) + "px";
    joyStick.style.display = "block";
  }

  function moveJoystick(dx, dy) {
    // Clamp the stick within JOY_RADIUS of the origin.
    const dist = Math.sqrt(dx * dx + dy * dy);
    let sx = dx, sy = dy;
    if (dist > JOY_RADIUS) {
      sx = dx * (JOY_RADIUS / dist);
      sy = dy * (JOY_RADIUS / dist);
    }
    joyStick.style.left = (joyOriginX + sx - JOY_STICK_RADIUS) + "px";
    joyStick.style.top = (joyOriginY + sy - JOY_STICK_RADIUS) + "px";
  }

  function hideJoystick() {
    joyBase.style.display = "none";
    joyStick.style.display = "none";
  }

  // Determine the closest cardinal direction from a (dx, dy) vector.
  // Returns "UP", "DOWN", "LEFT", "RIGHT", or null (if inside dead zone).
  function closestDirection(dx, dy) {
    const dist = Math.sqrt(dx * dx + dy * dy);
    if (dist < JOY_DEAD_ZONE) return null;
    // Compare |dx| vs |dy| to pick the dominant axis.
    if (Math.abs(dx) > Math.abs(dy)) {
      return dx > 0 ? "RIGHT" : "LEFT";
    } else {
      return dy > 0 ? "DOWN" : "UP";
    }
  }

  function sendMove(dir) {
    const now = performance.now();
    if (now - lastMoveAt < Constants.MOVE_COOLDOWN_MS) return;
    lastMoveAt = now;
    global.Net.send({ type: "MOVE", payload: { direction: dir } });
  }

  function startJoystick(clientX, clientY, pointerId) {
    joyActive = true;
    joyPointerId = pointerId;
    joyCurrentDir = null;
    showJoystick(clientX, clientY);
    // Pump at the cooldown rate while held.
    if (joyPumpInterval) clearInterval(joyPumpInterval);
    joyPumpInterval = setInterval(() => {
      if (joyActive && joyCurrentDir) sendMove(joyCurrentDir);
    }, Math.max(30, Constants.MOVE_COOLDOWN_MS - 5));
  }

  function updateJoystick(clientX, clientY) {
    if (!joyActive) return;
    const dx = clientX - joyOriginX;
    const dy = clientY - joyOriginY;
    moveJoystick(dx, dy);
    const dir = closestDirection(dx, dy);
    if (dir !== joyCurrentDir) {
      joyCurrentDir = dir;
      // Immediate move on direction change for responsiveness.
      if (dir) sendMove(dir);
    }
  }

  function endJoystick() {
    joyActive = false;
    joyPointerId = null;
    joyCurrentDir = null;
    if (joyPumpInterval) { clearInterval(joyPumpInterval); joyPumpInterval = null; }
    hideJoystick();
  }

  // Bind joystick to the window. The overlay is pointer-events:none so
  // pointer events pass through to the canvas/HUD; we listen on window and
  // ignore events that originate from a tool button (which stopPropagation
  // in their own handler) or from other interactive elements (HUD buttons).
  function bindJoystickToOverlay() {
    window.addEventListener("pointerdown", (e) => {
      if (!active) return;
      if (joyActive) return;
      // Ignore if the target is a tool button or any element with pointer-events:auto.
      // We check by seeing if the target is (or is inside) a .mb-button.
      if (e.target && e.target.closest && e.target.closest(".mb-button")) return;
      // Ignore if the target is an interactive HUD element (buttons, inputs).
      if (e.target && e.target.closest && e.target.closest("button, input, select, a")) return;
      // Start the joystick at the touch position.
      startJoystick(e.clientX, e.clientY, e.pointerId);
      e.preventDefault();
    });
    window.addEventListener("pointermove", (e) => {
      if (!joyActive || e.pointerId !== joyPointerId) return;
      updateJoystick(e.clientX, e.clientY);
      e.preventDefault();
    }, { passive: false });
    window.addEventListener("pointerup", (e) => {
      if (!joyActive || e.pointerId !== joyPointerId) return;
      endJoystick();
      e.preventDefault();
    });
    window.addEventListener("pointercancel", (e) => {
      if (!joyActive || e.pointerId !== joyPointerId) return;
      endJoystick();
    });
    // Prevent context menu on long press.
    window.addEventListener("contextmenu", (e) => {
      if (joyActive) e.preventDefault();
    });
  }

  // --- Public API ---

  const Mobile = {
    isActive() { return active; },

    getMode() {
      try {
        return localStorage.getItem(MODE_KEY) || "pc";
      } catch (e) { return "pc"; }
    },

    setMode(mode) {
      try { localStorage.setItem(MODE_KEY, mode); } catch (e) {}
    },

    build() {
      if (overlay) return;
      overlay = document.createElement("div");
      overlay.id = "mobile-controls";
      overlay.className = "mobile-controls";
      document.body.appendChild(overlay);

      const positions = loadPositions();

      // Tool buttons (draggable, tappable).
      for (const cfg of TOOL_BUTTONS) {
        const el = document.createElement("button");
        el.id = cfg.id;
        el.className = "mb-button mb-tool";
        el.textContent = cfg.label;
        applyPosition(el, positions[cfg.id] || DEFAULT_POSITIONS[cfg.id]);
        overlay.appendChild(el);
        toolButtons[cfg.id] = el;
        makeToolDraggable(el, cfg.id, positions);
        setupToolButton(el, cfg.tool);
      }

      // Joystick visuals (hidden until the player touches the screen).
      createJoystickVisuals();

      // "Placer" button (gear icon) to toggle placement mode.
      createPlacerButton();

      // Bind the joystick to pointer events on the overlay.
      bindJoystickToOverlay();
    },

    show() {
      if (!overlay) this.build();
      overlay.style.display = "block";
      active = true;
    },

    hide() {
      if (overlay) overlay.style.display = "none";
      active = false;
      // Clean up any in-progress joystick.
      if (joyActive) endJoystick();
      // Exit placement mode if active (positions already saved on exit).
      if (placementMode) exitPlacementMode();
    },

    toggle() {
      if (active) this.hide();
      else this.show();
      return active;
    },
  };

  global.Mobile = Mobile;
})(typeof window !== "undefined" ? window : this);
