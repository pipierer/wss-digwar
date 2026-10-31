# digwar — tactical WebSocket game

A real-time multiplayer top-down tactical game over WebSocket, hosted on Render.
Server is **fully authoritative**: the client only sends intents (move, use tool),
the server validates every action and broadcasts snapshots. Positions are strict
integers — there is no continuous movement, no diagonal, no fractional cell.

## Features

- **Strict cell-by-cell movement** — one input = exactly one cell. Server enforces
  a cooldown so even a malicious client cannot move faster than the configured
  `MOVE_COOLDOWN_MS`. No diagonal, no gliding, no float positions.
- **Server-authoritative** — all state lives on the server; the client renders
  snapshots, never predicts.
- **Smooth visuals** — the client interpolates between two cells over
  `MOVE_INTERPOLATION_MS` (default 90 ms) so the discrete logic stays clean
  while rendering remains fluid.
- **HTTP + WebSocket on the same port** — powered by aiohttp, so Render's
  healthchecks (GET/HEAD `/health`, HEAD `/`) work without log spam. The bare
  `websockets` library cannot answer HEAD requests, which caused hundreds of
  `ValueError`/`EOFError` lines per minute on Render.
- **Lobby + rooms** — create / join / leave rooms, configurable map size,
  player count, score-to-win, round time limit.
- **Teams** — optional Blue / Red / Solo teams (deathmatch scoring still works).
- **Tools** — shovel (dig dirt), knife (melee), bomb (timed explosion with
  chain reactions and rock/dirt destruction).
- **HUD** — name, score, K/D, health bar, time, latency, scoreboard.
- **Minimap + FOV** — small overview map + fog-of-war disc around the local
  player for tactical awareness.
- **Robust networking** — auto-reconnect, ping/pong watchdog, message queue
  with high-watermark drop for slow clients.

## Project layout

```
digwar_wss/
├── render.yaml              # Render service definition
├── requirements.txt         # Python deps (websockets)
├── .gitignore
├── README.md
├── server/                  # Python authoritative server
│   ├── main.py              # entry point (python -m server.main)
│   ├── server.py            # WebSocket server + static file serving
│   ├── room_manager.py      # global player/room registry
│   ├── room.py              # lobby + game lifecycle per room
│   ├── game.py              # authoritative game logic (movement, tools, bombs)
│   ├── world.py             # grid + map generation
│   ├── player.py            # player server-side state
│   ├── bomb.py              # bomb + explosion + blast computation
│   ├── messages.py          # inbound message validation
│   ├── constants.py         # tunables (cooldowns, sizes, tile ids)
│   └── utils.py             # id/json helpers
├── web/                     # browser client (vanilla JS, no build step)
│   ├── index.html
│   ├── css/style.css
│   └── js/
│       ├── constants.js     # client constants (mirrors server/constants.py)
│       ├── net.js           # WebSocket client + auto-reconnect
│       ├── input.js         # discrete input manager (one-cell-per-press)
│       ├── world.js         # client world mirror
│       ├── player.js        # client player mirror
│       ├── fov.js           # circular FOV / fog of war
│       ├── interpolate.js   # smooth visual position lerp
│       ├── render.js        # main canvas renderer
│       ├── hud.js           # HTML HUD overlay
│       ├── minimap.js       # minimap canvas
│       └── main.js          # screen orchestration + game loop
└── tests/
    ├── test_world.py        # world generation invariants
    ├── test_movement.py     # discrete movement rules
    └── test_game.py         # tool / bomb / scoring integration
```

## Run locally

```bash
cd digwar_wss
pip install -r requirements.txt
python -m server.main
# open http://localhost:8765/
```

## Deploy on Render

1. Push this directory to your GitHub repo (`pipierer/digwar`).
2. In Render: **New → Web Service → connect the repo**.
3. Render auto-detects `render.yaml` at `digwar_wss/render.yaml`.
4. Build: `pip install -r requirements.txt`
5. Start: `python -m server.main`
6. Health check: `GET /health` → `200 OK`

The free tier spins the service down after 15 min of inactivity; the first
request after sleep takes ~30 s to wake up.

## Controls

| Action      | Touches                     |
|-------------|-----------------------------|
| Déplacement | `Z` `Q` `S` `D` ou flèches  |
| Pelle       | `E`                         |
| Couteau     | `F` (ou `Shift gauche`)     |
| Bombe       | `Espace`                    |

## Movement rules (the core invariant)

The server enforces ALL of the following on every `MOVE`:

1. Player must be alive.
2. Direction must be one of `UP / DOWN / LEFT / RIGHT` (no diagonals).
3. Server-side cooldown `MOVE_COOLDOWN_MS` must have elapsed since the
   player's last accepted move (default 110 ms).
4. Target cell must be **in-bounds**.
5. Target cell must be **FLOOR** (no wall, no dirt, no rock).
6. Target cell must not be occupied by another alive player.
7. Target cell must not be occupied by a live bomb.

If any check fails, the move is silently rejected — the player stays put.
There is no client-side prediction: the client only sees the new position
when the next snapshot arrives, then interpolates visually.

## Tests

```bash
cd digwar_wss
python -m pytest tests/ -v
# or, without pytest:
python -m unittest discover -s tests
```

Tests cover: world generation invariants, discrete movement rules (bounds,
walls, dirt, player collisions, bomb blocking, cooldown), bomb blast
computation, kill/score attribution, respawn scheduling.

## License

MIT — see repository for details.
