#!/usr/bin/env python3
import asyncio
import websockets
import socket
import json
import os
import time
import traceback

# --------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------
HA_HOST = os.getenv("HA_REMOTE_HA_HOST", "127.0.0.1")
HA_PORT = int(os.getenv("HA_REMOTE_HA_PORT", "8123"))
SERVER_URL = os.getenv("HA_REMOTE_SERVER", "ws://yourserver/ha-remote/ws/tunnel/test1")

# reconnection interval (seconds)
RETRY_INTERVAL = 5
BUFFER = 65536


# --------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------
async def connect_local_ha():
    """Open a TCP connection to the local Home Assistant."""
    reader, writer = await asyncio.open_connection(HA_HOST, HA_PORT)
    return reader, writer


async def read_from_ha(reader, websocket):
    """Continuously read bytes from HA and forward to cloud."""
    try:
        while True:
            data = await reader.read(BUFFER)
            if not data:
                break
            await websocket.send(data)
    except Exception as e:
        # Network errors simply close loop
        pass


async def read_from_ws(websocket, writer):
    """Continuously read bytes from WebSocket and send to HA."""
    try:
        async for msg in websocket:
            if isinstance(msg, str):
                # JSON or text frames - reserved for control later
                continue
            writer.write(msg)
            await writer.drain()
    except Exception as e:
        pass


async def single_session():
    """One full relay session (until disconnected)."""
    try:
        async with websockets.connect(SERVER_URL, max_size=None) as ws:
            print(f"[HA Remote] Connected to cloud: {SERVER_URL}")

            reader, writer = await connect_local_ha()
            print(f"[HA Remote] Connected to local HA at {HA_HOST}:{HA_PORT}")

            # Run both directions concurrently
            await asyncio.gather(
                read_from_ha(reader, ws),
                read_from_ws(ws, writer)
            )

    except (websockets.exceptions.ConnectionClosedError,
            ConnectionRefusedError,
            socket.error) as e:
        print(f"[HA Remote] Connection lost: {e}")
    except Exception as e:
        print(f"[HA Remote] Unexpected error: {type(e).__name__}: {e}")
        traceback.print_exc()
    finally:
        # ensure sockets close
        await asyncio.sleep(0.1)


async def main():
    print(f"[HA Remote] Starting tunnel -> {SERVER_URL}")
    while True:
        await single_session()
        print(f"[HA Remote] Reconnecting in {RETRY_INTERVAL}s...")
        await asyncio.sleep(RETRY_INTERVAL)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("[HA Remote] Exiting.")
