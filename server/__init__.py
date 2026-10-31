"""digwar_wss server package.

A real-time multiplayer WebSocket game with strict cell-by-cell movement.
Server is authoritative: the client only sends intents (move, use_tool), the
server validates everything and broadcasts snapshots.
"""

__version__ = "1.0.0"
