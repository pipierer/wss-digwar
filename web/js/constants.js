// constants.js — client-side constants, kept in sync with server/constants.py
//
// All numeric encodings (tiles, directions) MUST match the server. The client
// only renders server-authoritative state; it never predicts game outcomes.

(function (global) {
  "use strict";

  // ----- Protocol -----------------------------------------------------------
  const PROTOCOL_VERSION = 1;

  // ----- Tiles --------------------------------------------------------------
  const TILE_FLOOR = 0;
  const TILE_WALL = 1;
  const TILE_DIRT = 2;
  const TILE_ROCK = 3;

  // ----- Directions (no diagonals) -----------------------------------------
  const DIR_UP = "UP";
  const DIR_DOWN = "DOWN";
  const DIR_LEFT = "LEFT";
  const DIR_RIGHT = "RIGHT";

  const DIRECTION_VECTORS = {
    UP: [0, -1],
    DOWN: [0, 1],
    LEFT: [-1, 0],
    RIGHT: [1, 0],
  };

  // ----- Tools --------------------------------------------------------------
  const TOOL_SHOVEL = "SHOVEL";
  const TOOL_KNIFE = "KNIFE";
  const TOOL_BOMB = "BOMB";

  // ----- Movement timing (client mirrors server cooldown for input pacing) -
  const MOVE_COOLDOWN_MS = 110;
  const TOOL_COOLDOWN_MS = {
    SHOVEL: 250,
    KNIFE: 400,
    BOMB: 600,
  };

  // ----- Rendering ----------------------------------------------------------
  const TILE_SIZE = 36;            // px per cell on the main canvas
  const MINIMAP_TILE_SIZE = 3;     // px per cell on the minimap
  const MOVE_INTERPOLATION_MS = 90; // visual lerp duration between two cells
  const MAX_INTERP_LAG_MS = 220;   // discard stale interpolation target

  // ----- FOV ----------------------------------------------------------------
  const FOV_RADIUS = 6;            // cells visible around the local player
  const FOV_USE = true;            // toggle fog of war

  // ----- Palette (top-down militariste) ------------------------------------
  const COLORS = {
    bg: "#0d1117",
    floor: "#3a4030",
    floorAlt: "#33382a",
    wall: "#5a5a52",
    wallTop: "#7c7c70",
    dirt: "#6b4f2a",
    dirtTop: "#8a6a36",
    rock: "#4a4a48",
    rockTop: "#6a6a66",
    grid: "rgba(0,0,0,0.18)",
    playerSelf: "#d9e2ec",
    playerEnemy: "#c0392b",
    playerAlly: "#3a7bd5",
    playerDead: "rgba(120,120,120,0.4)",
    bomb: "#222",
    bombGlow: "#e67e22",
    explosion: "#f1c40f",
    explosionCore: "#e74c3c",
    hudBg: "rgba(13,17,23,0.85)",
    hudFg: "#d9e2ec",
    hudAccent: "#e67e22",
    hudDanger: "#e74c3c",
    hudOk: "#2ecc71",
    fog: "rgba(8,10,14,0.94)",
    spawn: "rgba(231,76,60,0.15)",
  };

  // ----- UI -----------------------------------------------------------------
  const TEAM_COLORS = ["#3a7bd5", "#c0392b"];

  global.Constants = {
    PROTOCOL_VERSION,
    TILE_FLOOR, TILE_WALL, TILE_DIRT, TILE_ROCK,
    DIR_UP, DIR_DOWN, DIR_LEFT, DIR_RIGHT,
    DIRECTION_VECTORS,
    TOOL_SHOVEL, TOOL_KNIFE, TOOL_BOMB,
    MOVE_COOLDOWN_MS, TOOL_COOLDOWN_MS,
    TILE_SIZE, MINIMAP_TILE_SIZE, MOVE_INTERPOLATION_MS, MAX_INTERP_LAG_MS,
    FOV_RADIUS, FOV_USE,
    COLORS, TEAM_COLORS,
  };
})(typeof window !== "undefined" ? window : this);
