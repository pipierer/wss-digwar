"""Server-side constants for digwar.

All gameplay constants live here so they can be tweaked in a single place.
Numeric tile/direction encodings MUST stay in sync with web/js/constants.js.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Network / protocol
# ---------------------------------------------------------------------------

PROTOCOL_VERSION = 1

# Default port used when no PORT env var is set (Render injects PORT).
DEFAULT_PORT = 8765

# Tick rate of the game loop (Hz). Server broadcasts a snapshot at this rate
# only when the world actually changed (diff-based), to save bandwidth.
TICK_RATE = 20                # 50 ms per tick
TICK_DT = 1.0 / TICK_RATE

# Snapshot cadence: even if nothing changes, send a heartbeat snapshot every
# N ticks so the client can resync its clock and detect dropped players.
SNAPSHOT_HEARTBEAT_TICKS = 20  # 1 s

# Connection watchdog.
PING_INTERVAL = 5.0           # seconds
PING_TIMEOUT = 15.0           # seconds without any message -> disconnect
MAX_MESSAGE_SIZE = 1 << 16    # 64 KiB
QUEUE_HIGH_WATERMARK = 32     # drop slow clients above this

# ---------------------------------------------------------------------------
# Tiles
# ---------------------------------------------------------------------------

TILE_FLOOR = 0
TILE_WALL = 1                 # indestructible, blocks movement & explosions
TILE_DIRT = 2                 # destructible by shovel or bomb, blocks movement
TILE_ROCK = 3                 # destructible by bomb only, blocks movement

# Tiles that block walking (everything except FLOOR).
BLOCKING_TILES = frozenset({TILE_WALL, TILE_DIRT, TILE_ROCK})

# Tiles that block explosions (only WALL and ROCK stop blast).
EXPLOSION_BLOCKING_TILES = frozenset({TILE_WALL, TILE_ROCK})

# Tiles that can be destroyed by a shovel (1 hit).
SHOVELABLE_TILES = frozenset({TILE_DIRT})

# Tiles that can be destroyed by an explosion.
EXPLODABLE_TILES = frozenset({TILE_DIRT, TILE_ROCK})

# ---------------------------------------------------------------------------
# Directions (no diagonals: only the 4 cardinal axes)
# ---------------------------------------------------------------------------

DIR_UP = "UP"
DIR_DOWN = "DOWN"
DIR_LEFT = "LEFT"
DIR_RIGHT = "RIGHT"

# (dx, dy) for each direction. y grows downward (screen orientation).
DIRECTION_VECTORS = {
    DIR_UP: (0, -1),
    DIR_DOWN: (0, 1),
    DIR_LEFT: (-1, 0),
    DIR_RIGHT: (1, 0),
}

ALL_DIRECTIONS = (DIR_UP, DIR_DOWN, DIR_LEFT, DIR_RIGHT)

# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

TOOL_SHOVEL = "SHOVEL"        # dig dirt in facing cell
TOOL_KNIFE = "KNIFE"          # melee damage in facing cell
TOOL_BOMB = "BOMB"            # place a bomb at current cell

ALL_TOOLS = (TOOL_SHOVEL, TOOL_KNIFE, TOOL_BOMB)

# ---------------------------------------------------------------------------
# Movement & action cooldowns (milliseconds)
# ---------------------------------------------------------------------------
# These enforce strict one-cell-per-input on the server side. Even if a
# malicious client spams MOVE messages, the server drops any input faster
# than MOVE_COOLDOWN_MS apart.

MOVE_COOLDOWN_MS = 110        # min time between two moves for the same player
TOOL_COOLDOWN_MS = {
    TOOL_SHOVEL: 250,
    TOOL_KNIFE: 400,
    TOOL_BOMB: 600,
}
BOMB_FUSE_MS = 2200           # time before a placed bomb explodes
BOMB_BLAST_RANGE = 2          # cells in each cardinal direction
EXPLOSION_DURATION_MS = 450   # how long an explosion stays visible
BOMB_DAMAGE = 60              # damage at epicenter
KNIFE_DAMAGE = 35             # damage to a player in the facing cell
RESPAWN_DELAY_MS = 2500       # delay before a dead player respawns

# ---------------------------------------------------------------------------
# Player state
# ---------------------------------------------------------------------------

PLAYER_MAX_HEALTH = 100
PLAYER_INITIAL_SCORE = 0
PLAYER_NAME_MAX_LEN = 16

# ---------------------------------------------------------------------------
# Game / round
# ---------------------------------------------------------------------------

DEFAULT_GAME_CONFIG = {
    "width": 17,
    "height": 13,
    "max_players": 4,
    "score_to_win": 5,
    "round_time_limit_s": 180,    # 0 = unlimited
    "move_cooldown_ms": MOVE_COOLDOWN_MS,
    "blast_range": BOMB_BLAST_RANGE,
    "dirt_regen_enabled": False,   # if True, dirt is rebuilt periodically
    "dirt_regen_interval_s": 30,   # regen interval in seconds (when enabled)
}

# Bounds enforced on host-supplied config (configurable mode).
CONFIG_BOUNDS = {
    "width": (7, 41),
    "height": (7, 31),
    "max_players": (2, 8),
    "score_to_win": (1, 50),
    "round_time_limit_s": (0, 1800),
    "move_cooldown_ms": (60, 500),
    "blast_range": (1, 5),
    "dirt_regen_interval_s": (5, 300),
}

# ---------------------------------------------------------------------------
# Lobby / room
# ---------------------------------------------------------------------------

ROOM_ID_LEN = 6
MAX_ROOMS = 200
MAX_PLAYERS_PER_SERVER = 400
ROOM_NAME_MAX_LEN = 24
PRE_GAME_GRACE_MS = 1500       # pause between "START" and first tick

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
