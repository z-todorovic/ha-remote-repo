#!/usr/bin/env python3
import os
import asyncio
import requests
import websockets
import sys

# ==============================================================
#  HA Remote Relay - Version 1.2 (debug edition)
#  Transparent tunnel between Home Assistant and remote server
# ==============================================================

def discover_local_ha():
    """Detect HA host and port via Supervisor API or environment."""
    api = os.getenv("SUPERVISOR_API")
    token = os.getenv("SUPERVISOR_TOKEN")
    if api and token:
        try:
            r = requests.get(
                f"{api}/core/info",
                headers={"Authorization": f"Bearer {token}"},
                timeout=5,
            )
            data = r.json().get("data", {})
            host = data.get("host", "127.0.0.1")
            port = int(data.get("port", 8123))
            print(f"[HA Remote] Discovered HA core at {host}:{port}")
            return host, port
        except Exception as e:
            print(f"[HA Remote] Supervisor query failed ({e}), falling back.")
    host = os.getenv("HA_REMOTE_HA_HOST", "127.0.0.1").strip()
    port_str = os.getenv("HA_REMOTE_HA_PORT", "8123").strip()
    try:
        port = int(port_str)
    except ValueError:
        print(f"[HA Remote] Warning: invalid port '{port_str}', using 8123")
        port = 8123
    return host, port


SERVER = os.getenv("HA_REMOTE_SERVER", "ws://localhost:8080/ha-remote/ws/tunnel/test1").strip()
LOCAL_HA = discover_local_ha()


async def bridge(ws, reader, writer):
    """Bidirectional binary bridge between WebSocket and local TCP socket."""
    async def ws_to_tcp():
        async for msg in ws:
            if isinstance(msg, bytes):
                writer.write(msg)
                await writer.drain()

    async def tcp_to_ws():
        while True:
            data = await reader.read(4096)
            if not data:
                break
            await ws.send(data)

    await asyncio.gather(ws_to_tcp(), tcp_to_ws())


async def main():
    reconnect_delay = 5
    print("[HA Remote] Entered main() loop")

    while True:
        try:
            print(f"[HA Remote] Trying to connect to {SERVER}")
            async with websockets.connect(
                SERVER, max_size=None, ping_interval=20, ping_timeout=20
            ) as ws:
                print(f"[HA Remote] Connected to {SERVER}")
                reader, writer = await asyncio.open_connection(*LOCAL_HA)
                print(f"[HA Remote] Connected to local HA at {LOCAL_HA[0]}:{LOCAL_HA[1]}")
                await bridge(ws, reader, writer)
        except Exception as e:
            print(f"[HA Remote] Disconnected or failed: {type(e).__name__} - {e}")
            await asyncio.sleep(reconnect_delay)


if __name__ == "__main__":
    print(f"[HA Remote] Starting tunnel -> {SERVER}")
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("[HA Remote] Interrupted, exiting.")
        sys.exit(0)
    except Exception as e:
        print(f"[HA Remote] Fatal error: {e}")
        sys.exit(1)
