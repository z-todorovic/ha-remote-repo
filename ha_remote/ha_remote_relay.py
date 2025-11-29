import contextlib
import io
import os
import ssl
import requests
import asyncio
import json
import uuid
import signal
import sys
from pathlib import Path

TUNNEL_HOST = os.getenv("HA_REMOTE_TUNNEL_HOST", "tunnel.securicloud.me")
TUNNEL_PORT = os.getenv("HA_REMOTE_TUNNEL_PORT", 443)
# TUNNEL_HOST = "127.0.0.1"
# TUNNEL_PORT = 2345

stopping = asyncio.Event()
_live = set()
ssl_ctx = ssl.create_default_context()  

def spawn(coro):
    task = asyncio.create_task(coro)
    _live.add(task)
    task.add_done_callback(lambda task: (_live.discard(task), print(f"Live tasks: {len(_live)}")))
    return task

def handle_stop(*_):
    print("Received stop signal → shutting down")
    stopping.set()
    # sys.exit(0)

def discover_local_ha():
    api = os.getenv("SUPERVISOR_API")
    token = os.getenv("SUPERVISOR_TOKEN")
    if api and token:
        try:
            r = requests.get(f"{api}/core/info",
                             headers={"Authorization": f"Bearer {token}"},
                             timeout=5)
            data = r.json().get("data", {})
            return data.get("host", "127.0.0.1"), int(data.get("port", 8123))
        except Exception as e:
            print("Supervisor query failed:", e)
    # fallback (Core install / Windows test)
    return "127.0.0.1", 8123

def get_ha_instance_id():
    cachedInstanceIdFile  = Path("/share/ha_instance_id.json")
    try:
        if cachedInstanceIdFile.exists():
            try:
                return json.loads(cachedInstanceIdFile.read_text())["instance_id"]
            except Exception:
                pass
        ha_id = uuid.uuid4().hex
        cachedInstanceIdFile.write_text(json.dumps({"instance_id": ha_id}))
        return ha_id
    except Exception:
        return "test1"

async def pipe_tunnel_to_ha(tunnel_reader, tunnel_writer, ha_writer, first_chunk):
    try:
        length = int.from_bytes(first_chunk)
        while not stopping.is_set():
            if length > 0:
                data = await tunnel_reader.readexactly(length)
                ha_writer.write(data)
                await ha_writer.drain()
            while not stopping.is_set():
                try:
                    bytes = await asyncio.wait_for(tunnel_reader.readexactly(2), 5)
                    length = int.from_bytes(bytes)
                    break
                except asyncio.TimeoutError:
                    tunnel_writer.write(b'\x00\x00')
                    await tunnel_writer.drain()
    except asyncio.CancelledError:
        pass
    except Exception as ex:
        pass
    finally:
        if not ha_writer.is_closing():
            ha_writer.close()
            try:
                await ha_writer.wait_closed()
            except Exception:
                pass

async def pipe_ha_to_tunnel(ha_reader, tunnel_writer):
    try:
        while not stopping.is_set():
            data = await ha_reader.read(8192)
            if not data:
                break
            data_length = len(data)
            bytes = data_length.to_bytes(2, 'big')
            tunnel_writer.write(bytes)
            tunnel_writer.write(data)
            await tunnel_writer.drain()
    except asyncio.CancelledError:
        pass
    except Exception as ex:
        pass
    finally:
        if not tunnel_writer.is_closing():
            tunnel_writer.close()
            try:
                await tunnel_writer.wait_closed()
            except Exception:
                pass

async def handle_active_connection(tunnel_reader, tunnel_writer, first_chunk):
    """Forward an active tunnel connection to HA."""
    try:
        print("[FORWARD] Opening HA connection...")
        ha_reader, ha_writer = await asyncio.open_connection(LOCAL_HA[0], LOCAL_HA[1])

        task1 = spawn(pipe_tunnel_to_ha(tunnel_reader, tunnel_writer, ha_writer, first_chunk))
        task2 = spawn(pipe_ha_to_tunnel(ha_reader, tunnel_writer))
        # await asyncio.wait([task1, task2], return_when=asyncio.FIRST_COMPLETED)
        done, pending = await asyncio.wait({task1, task2}, return_when=asyncio.FIRST_COMPLETED)
        for p in pending:
            p.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
    except Exception as e:
        print(f"[ERROR] {e}")
    finally:
        for w in (tunnel_writer, ha_writer):
            try:
                w.close()
                await w.wait_closed()
            except Exception:
                pass
        print("[FORWARD] Session closed")

async def keep_idle_connection():
    """Maintain one idle connection, spawn new one when triggered."""
    while not stopping.is_set():
        try:
            print(f"[IDLE] Connecting to {TUNNEL_HOST}:{TUNNEL_PORT}")
            reader, writer = await asyncio.open_connection(
                TUNNEL_HOST,
                TUNNEL_PORT,
                ssl=ssl_ctx,
                server_hostname=TUNNEL_HOST
            )
            id_bytes = HA_INSTANCE_ID.encode("utf-8")
            writer.write(len(id_bytes).to_bytes(2, 'big'))
            writer.write(id_bytes)
            await writer.drain()
            print("[IDLE] Connected and identified. Waiting for data...")
            print(f"Live tasks: {len(_live)}")

            first_chunk = False
            # Wait for first bytes from server/user
            while not stopping.is_set():
                try:
                    first_chunk = await asyncio.wait_for(reader.readexactly(2), 5)
                    break
                except asyncio.TimeoutError:
                    writer.write(b'\x00\x00')
                    await writer.drain()

            if not first_chunk or stopping.is_set():
                writer.close()
                await asyncio.sleep(1)
                continue

            spawn(keep_idle_connection())

            await handle_active_connection(reader, writer, first_chunk)
            break

        except Exception as e:
            print(f"[IDLE] Error: {e}, retry in 3s")
            if "GeneratorExit" in str(e) or stopping.is_set():
                break 
            await asyncio.sleep(3)

async def main():
    signal.signal(signal.SIGTERM, handle_stop)
    signal.signal(signal.SIGINT, handle_stop)
    print(f"HA instance ID: {HA_INSTANCE_ID}")
    print(f"Local HA: {LOCAL_HA[0]}:{LOCAL_HA[1]}")
    spawn(keep_idle_connection())
    await asyncio.Event().wait()

# LOCAL_HA = discover_local_ha()
# HA_INSTANCE_ID = get_ha_instance_id()
LOCAL_HA = "192.168.88.117", 8123
HA_INSTANCE_ID = "3787482d87bbbfe937fcd3697433b6d9"


asyncio.run(main())
