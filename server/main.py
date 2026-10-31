"""Entry point for the digwar WebSocket server.

Run with:  python -m server.main
Render runs the same command (see render.yaml).
"""

from __future__ import annotations

import asyncio

from .server import main

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
