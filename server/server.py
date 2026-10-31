"""WebSocket + HTTP server built on aiohttp.

Architecture:
  * One `GameServer` instance per process owns the RoomManager.
  * aiohttp.web serves HTTP (static files, /health) AND WebSocket (/ws) on
    the same port. This is more robust than the bare `websockets` library
    which cannot answer HEAD requests sent by Render's healthchecks.
  * Each WebSocket connection is wrapped in a per-connection handler that
    authenticates the player (HELLO), then routes subsequent messages to
    the right room/game.
  * `/health` returns 200 OK so Render's healthcheck is happy.
  * `/` and any static path serves files from web/.

Switching from `websockets` to `aiohttp` fixes:
  * `ValueError: unsupported HTTP method; expected GET; got HEAD`
    (Render's HTTP healthcheck sends HEAD /)
  * `EOFError: stream ends after 0 bytes`
    (Render's TCP healthcheck opens and closes immediately)
  * Both were harmless but spammed the logs.
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Optional

from aiohttp import web, WSMsgType

from .constants import (
    DEFAULT_PORT,
    LOG_FORMAT,
    MAX_MESSAGE_SIZE,
    PING_INTERVAL,
    PING_TIMEOUT,
    PROTOCOL_VERSION,
    QUEUE_HIGH_WATERMARK,
    TICK_DT,
)
from .messages import (
    ProtocolError,
    expect_dict,
    validate_create_room,
    validate_hello,
    validate_move,
    validate_set_team,
    validate_use_tool,
)
from .player import Player
from .room_manager import RoomManager
from .utils import gen_id, json_dumps, json_loads

logger = logging.getLogger("digwar.server")

# Path to the web/ directory (../web relative to this file).
WEB_ROOT = Path(__file__).resolve().parent.parent / "web"

MIME_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".mjs": "application/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".ico": "image/x-icon",
    ".map": "application/json; charset=utf-8",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
    ".ttf": "font/ttf",
}


def _safe_join(root: Path, url_path: str) -> Optional[Path]:
    """Resolve a URL path under root, refusing any traversal."""
    if url_path.startswith("/"):
        url_path = url_path[1:]
    target = (root / url_path).resolve()
    try:
        target.relative_to(root.resolve())
    except ValueError:
        return None
    return target


# ---------------------------------------------------------------------------
# HTTP handlers
# ---------------------------------------------------------------------------

async def health_handler(request: web.Request) -> web.Response:
    """Render healthcheck endpoint."""
    return web.json_response({"status": "ok"})


async def version_handler(request: web.Request) -> web.Response:
    """Diagnostic endpoint: returns the code version + libraries actually
    loaded. Hit /version in the browser to confirm the right code is deployed.
    """
    import sys
    import aiohttp
    try:
        import websockets  # noqa
        ws_version = getattr(websockets, "__version__", "?")
    except ImportError:
        ws_version = "not installed"
    return web.json_response({
        "app": "digwar",
        "version": "1.9.0-smooth-camera",
        "python": sys.version.split()[0],
        "aiohttp": aiohttp.__version__,
        "websockets_lib": ws_version,
        "server_module": "aiohttp.web",
    })


async def static_handler(request: web.Request) -> web.Response:
    """Serve static files from web/. Falls back to index.html for unknown
    routes so the SPA-like client can boot."""
    path = request.match_info.get("path", "")
    if path == "" or path == "/":
        path = "index.html"
    target = _safe_join(WEB_ROOT, path)
    if target is None or not target.exists() or not target.is_file():
        # Fallback: serve index.html for unknown non-asset paths (so the
        # client can boot on any route). For missing assets, 404.
        if path.startswith(("js/", "css/", "img/", "fonts/")):
            return web.Response(status=404, text="Not Found")
        target = _safe_join(WEB_ROOT, "index.html")
        if target is None or not target.exists():
            return web.Response(status=404, text="Not Found")
    mime = MIME_TYPES.get(target.suffix, "application/octet-stream")
    return web.FileResponse(target, headers={"Cache-Control": "no-cache"})


# ---------------------------------------------------------------------------
# WebSocket handler
# ---------------------------------------------------------------------------

class GameServer:
    def __init__(self) -> None:
        self.room_manager = RoomManager()
        self._send_queues: dict[str, asyncio.Queue] = {}

    async def ws_handler(self, request: web.Request) -> web.WebSocketResponse:
        """Per-connection WebSocket handler."""
        ws = web.WebSocketResponse(
            max_msg_size=MAX_MESSAGE_SIZE,
            heartbeat=PING_INTERVAL,
            receive_timeout=PING_TIMEOUT + PING_INTERVAL,
        )
        await ws.prepare(request)

        # Authenticate via HELLO handshake.
        try:
            raw = await asyncio.wait_for(ws.receive(), timeout=10.0)
            if raw.type != WSMsgType.TEXT:
                await ws.close(code=4000, message=b"expected HELLO")
                return ws
            msg = expect_dict(json_loads(raw.data))
        except (asyncio.TimeoutError, Exception):
            await ws.close(code=4001, message=b"hello timeout")
            return ws

        if msg.get("type") != "HELLO":
            await self._safe_send(ws, {"type": "ERROR", "code": "BAD_HELLO",
                                       "message": "first message must be HELLO"})
            await ws.close(code=4002, message=b"bad hello")
            return ws

        try:
            hello = validate_hello(msg.get("payload", {}))
        except ProtocolError as e:
            await self._safe_send(ws, {"type": "ERROR", "code": e.code,
                                       "message": str(e)})
            await ws.close(code=4003, message=b"bad hello payload")
            return ws

        player_id = gen_id("p_", 8)
        player = Player(player_id, hello["name"], ws=ws)
        if not self.room_manager.register_player(player):
            await self._safe_send(ws, {"type": "ERROR", "code": "SERVER_FULL",
                                       "message": "server full"})
            await ws.close(code=4004, message=b"server full")
            return ws

        queue: asyncio.Queue = asyncio.Queue(maxsize=QUEUE_HIGH_WATERMARK)
        self._send_queues[player_id] = queue

        await self._send(ws, {
            "type": "HELLO_ACK",
            "payload": {"player_id": player_id, "version": PROTOCOL_VERSION,
                        "server_tick_rate_hz": int(1.0 / TICK_DT)},
        })
        logger.info("player connected: %s (%s)", player.id, player.name)

        sender_task = asyncio.create_task(self._sender_loop(ws, queue, player_id))
        try:
            await self._receiver_loop(ws, player)
        except Exception:
            logger.exception("receiver loop crashed for %s", player.id)
        finally:
            sender_task.cancel()
            try:
                await sender_task
            except (asyncio.CancelledError, Exception):
                pass
            self._send_queues.pop(player_id, None)
            self.room_manager.unregister_player(player_id)
            try:
                await ws.close()
            except Exception:
                pass
            logger.info("player disconnected: %s", player.id)
        return ws

    # ------------------------------------------------------------------
    # Receiver / sender loops
    # ------------------------------------------------------------------
    async def _receiver_loop(self, ws: web.WebSocketResponse, player: Player) -> None:
        async for raw in ws:
            if raw.type == WSMsgType.TEXT:
                try:
                    msg = expect_dict(json_loads(raw.data))
                except Exception:
                    logger.warning("bad JSON from %s: %r", player.id, raw.data[:200])
                    await self._enqueue(player.id, {"type": "ERROR", "code": "BAD_JSON",
                                                    "message": "invalid JSON"})
                    continue
                mtype = msg.get("type") if isinstance(msg, dict) else "?"
                logger.info("recv %s from %s", mtype, player.id)
                try:
                    await self._dispatch(player, msg)
                except ProtocolError as e:
                    logger.info("protocol error %s from %s: %s", e.code, player.id, e)
                    await self._enqueue(player.id, {"type": "ERROR", "code": e.code,
                                                    "message": str(e)})
                except Exception:
                    logger.exception("dispatch error for %s: %r", player.id, msg)
                    await self._enqueue(player.id, {"type": "ERROR", "code": "INTERNAL",
                                                    "message": "internal error"})
            elif raw.type == WSMsgType.ERROR:
                logger.warning("ws error for %s: %s", player.id, ws.exception())
            elif raw.type in (WSMsgType.CLOSE, WSMsgType.CLOSING, WSMsgType.CLOSED):
                break

    async def _sender_loop(self, ws: web.WebSocketResponse, queue: asyncio.Queue,
                           player_id: str) -> None:
        try:
            while True:
                msg = await queue.get()
                if msg is None:
                    return
                await ws.send_str(json_dumps(msg))
        except asyncio.CancelledError:
            return
        except Exception:
            logger.debug("sender loop ended for %s", player_id)

    # ------------------------------------------------------------------
    # Message dispatch
    # ------------------------------------------------------------------
    async def _dispatch(self, player: Player, msg: dict) -> None:
        mtype = msg.get("type")
        payload = msg.get("payload") or {}

        if mtype == "PING":
            await self._enqueue(player.id, {"type": "PONG"})
            return

        if mtype == "LIST_ROOMS":
            rooms = self.room_manager.list_rooms()
            await self._enqueue(player.id, {"type": "ROOM_LIST", "payload": {"rooms": rooms}})
            return

        if mtype == "CREATE_ROOM":
            data = validate_create_room(payload)
            room, err = self.room_manager.create_room(player, data["name"], data["config"])
            if room is None:
                raise ProtocolError(err, code="CREATE_FAILED")
            await self._broadcast_room_state(room)
            return

        if mtype == "JOIN_ROOM":
            room_id = payload.get("room_id")
            if not isinstance(room_id, str):
                raise ProtocolError("missing room_id")
            room, err = self.room_manager.join_room(player, room_id)
            if room is None:
                raise ProtocolError(err, code="JOIN_FAILED")
            await self._broadcast_room_state(room)
            return

        if mtype == "LEAVE_ROOM":
            self.room_manager.leave_room(player)
            await self._enqueue(player.id, {"type": "ROOM_LEFT"})
            return

        if mtype == "SET_TEAM":
            team = validate_set_team(payload)
            room = self.room_manager.room_of(player)
            if room is None:
                raise ProtocolError("not in a room", code="NOT_IN_ROOM")
            room.set_team(player, team)
            await self._broadcast_room_state(room)
            return

        if mtype == "START_GAME":
            logger.info("START_GAME from %s, looking up room...", player.id)
            room = self.room_manager.room_of(player)
            if room is None:
                logger.warning("START_GAME: %s not in any room (in_room_id=%r)",
                               player.id, player.in_room_id)
                raise ProtocolError("not in a room", code="NOT_IN_ROOM")
            logger.info("START_GAME: %s in room %s (state=%s, host=%s, is_host=%s, players=%d)",
                        player.id, room.id, room.state, room.host_id,
                        room.is_host(player.id), len(room.players))
            if not room.is_host(player.id):
                raise ProtocolError("only host can start", code="NOT_HOST")
            if not room.start():
                logger.warning("START_GAME: room.start() returned False (state=%s, players=%d)",
                               room.state, len(room.players))
                raise ProtocolError("cannot start", code="CANNOT_START")
            logger.info("START_GAME: game started, sending GAME_START to %d players",
                        len(room.players))
            full = room.game_full_state()
            for p in self.room_manager.players_in_room(room):
                await self._enqueue(p.id, full)
            # NOTE: do NOT broadcast ROOM_STATE here. The state is now "playing"
            # and the client would call renderRoomState() -> show("screen-room"),
            # which would override the GAME_START screen switch. The next
            # snapshot will naturally update the players' state.
            return

        if mtype == "MOVE":
            room = self.room_manager.room_of(player)
            if room is None or room.game is None:
                return
            direction = validate_move(payload)
            room.game.try_move(player, direction)
            return

        if mtype == "USE_TOOL":
            room = self.room_manager.room_of(player)
            if room is None or room.game is None:
                return
            data = validate_use_tool(payload)
            room.game.try_use_tool(player, data["tool"], data["direction"])
            return

        if mtype == "CHAT":
            text = payload.get("text")
            if not isinstance(text, str) or len(text) > 200:
                raise ProtocolError("invalid chat text")
            room = self.room_manager.room_of(player)
            if room is None:
                return
            await self._broadcast(room, {"type": "CHAT",
                                         "payload": {"from": player.id, "name": player.name,
                                                     "text": text[:200]}})
            return

        raise ProtocolError(f"unknown message type {mtype!r}", code="UNKNOWN_TYPE")

    # ------------------------------------------------------------------
    # Broadcast helpers
    # ------------------------------------------------------------------
    async def _broadcast_room_state(self, room) -> None:
        state = room.lobby_state()
        await self._broadcast(room, state)

    async def _broadcast(self, room, msg: dict) -> None:
        for p in self.room_manager.players_in_room(room):
            await self._enqueue(p.id, msg)

    async def _enqueue(self, player_id: str, msg: dict) -> None:
        queue = self._send_queues.get(player_id)
        if queue is None:
            return
        try:
            queue.put_nowait(msg)
        except asyncio.QueueFull:
            logger.warning("dropping message for slow client %s", player_id)

    async def _send(self, ws: web.WebSocketResponse, msg: dict) -> None:
        await ws.send_str(json_dumps(msg))

    async def _safe_send(self, ws: web.WebSocketResponse, msg: dict) -> None:
        try:
            await ws.send_str(json_dumps(msg))
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Snapshot pump: broadcast game snapshots every tick.
    # ------------------------------------------------------------------
    async def snapshot_pump(self, app: web.Application) -> None:
        """Background task that drains room.outgoing + sends game snapshots."""
        try:
            while True:
                try:
                    await asyncio.sleep(TICK_DT)
                    for room in list(self.room_manager.rooms.values()):
                        for msg in room.consume_outgoing():
                            await self._broadcast(room, msg)
                        if room.state == "playing" and room.game is not None:
                            snap = room.game_snapshot()
                            if snap is not None:
                                await self._broadcast(room, snap)
                except asyncio.CancelledError:
                    return
                except Exception:
                    logger.exception("snapshot pump error")
                    await asyncio.sleep(1.0)
        except asyncio.CancelledError:
            return


# ---------------------------------------------------------------------------
# App factory + main
# ---------------------------------------------------------------------------

def create_app() -> web.Application:
    app = web.Application(client_max_size=MAX_MESSAGE_SIZE)
    game_server = GameServer()
    app["game_server"] = game_server

    # Routes. add_get() also auto-registers HEAD for the same path, which
    # is exactly what Render's HTTP healthcheck needs.
    app.router.add_get("/health", health_handler)
    app.router.add_get("/version", version_handler)
    app.router.add_get("/ws", game_server.ws_handler)
    # Static: catch-all. Must be last. The {path:.*} matcher catches
    # everything else (/, /index.html, /js/*, /css/*, ...).
    app.router.add_get("/", static_handler)
    app.router.add_get("/{path:.*}", static_handler)

    # Start the snapshot pump on app startup.
    async def _on_startup(app: web.Application) -> None:
        app["pump_task"] = asyncio.create_task(game_server.snapshot_pump(app))

    async def _on_cleanup(app: web.Application) -> None:
        task = app.get("pump_task")
        if task:
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass

    app.on_startup.append(_on_startup)
    app.on_cleanup.append(_on_cleanup)
    return app


async def main() -> None:
    import logging as _logging
    level = os.environ.get("LOG_LEVEL", "INFO").upper()
    _logging.basicConfig(level=getattr(_logging, level, _logging.INFO), format=LOG_FORMAT)
    # Silence aiohttp's noisy access log (we keep error log).
    _logging.getLogger("aiohttp.access").setLevel(_logging.WARNING)

    port = int(os.environ.get("PORT", DEFAULT_PORT))
    host = os.environ.get("HOST", "0.0.0.0")

    app = create_app()
    logger.info("digwar server starting on %s:%d (web root: %s)", host, port, WEB_ROOT)
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    await site.start()
    try:
        await asyncio.Future()  # run forever
    finally:
        await runner.cleanup()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
