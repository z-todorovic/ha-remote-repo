import os
import requests
import asyncio
import json
import uuid
import signal
import sys
from pathlib import Path

TUNNEL_HOST = os.getenv("HA_REMOTE_TUNNEL_HOST", "tunnel.cometgps.com")
TUNNEL_PORT = os.getenv("HA_REMOTE_TUNNEL_PORT", 2345)
# TUNNEL_HOST = "127.0.0.1"
# TUNNEL_PORT = 2345

def handle_stop(*_):
    print("Received stop signal → shutting down")
    sys.exit(0)

signal.signal(signal.SIGTERM, handle_stop)
signal.signal(signal.SIGINT, handle_stop)

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
    except:
        return "test1"

async def pipe(reader, writer):
    try:
        while True:
            data = await reader.read(8192)
            if not data:
                break
            writer.write(data)
            await writer.drain()
    except (asyncio.CancelledError, GeneratorExit):
        # loop is shutting down or task cancelled
        pass
    except Exception:
        pass
    finally:
        if not writer.is_closing():
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass

async def handle_active_connection(reader_tunnel, writer_tunnel, first_chunk):
    try:
        print("[FORWARD] Opening HA connection...")
        ha_reader, ha_writer = await asyncio.open_connection(LOCAL_HA[0], LOCAL_HA[1])
        ha_writer.write(first_chunk)
        await ha_writer.drain()

        t1 = asyncio.create_task(pipe(reader_tunnel, ha_writer))
        t2 = asyncio.create_task(pipe(ha_reader, writer_tunnel))

        done, pending = await asyncio.wait(
            {t1, t2},
            return_when=asyncio.FIRST_COMPLETED,
        )

        # one direction is done → kill the other direction too
        for p in pending:
            p.cancel()
        # make sure the cancelled one actually finishes
        await asyncio.gather(*pending, return_exceptions=True)

    except Exception as e:
        print(f"[ERROR] {e}")
    finally:
        writer_tunnel.close()
        try:
            await writer_tunnel.wait_closed()
        except Exception:
            pass
        print("[FORWARD] Session closed")

async def keep_idle_connection():
    try:
        while not stopping.is_set():
            try:
                reader, writer = await asyncio.open_connection(TUNNEL_HOST, TUNNEL_PORT)
                id_bytes = HA_INSTANCE_ID.encode()
                writer.write(bytes([len(id_bytes)]))
                writer.write(id_bytes)
                await writer.drain()

                while not stopping.is_set():
                    try:
                        first_chunk = await asyncio.wait_for(reader.read(1), 5)
                        break
                    except asyncio.TimeoutError:
                        writer.write(b"\x00")
                        await writer.drain()
                else:
                    break

                if not first_chunk or stopping.is_set():
                    writer.close()
                    await asyncio.sleep(1)
                    continue

                spawn(keep_idle_connection())     # your safe task spawner
                await handle_active_connection(reader, writer, first_chunk)
            except (asyncio.CancelledError, GeneratorExit):
                # shutdown requested
                break
            except Exception as e:
                if stopping.is_set():
                    break
                print(f"[IDLE] Error: {e}, retry in 3s")
                await asyncio.sleep(3)
    finally:
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass
        
async def main():
    print(f"HA instance ID: {HA_INSTANCE_ID}")
    print(f"Local HA: {LOCAL_HA[0]}:{LOCAL_HA[1]}")
    asyncio.create_task(keep_idle_connection())
    await asyncio.Event().wait()

LOCAL_HA = discover_local_ha()
HA_INSTANCE_ID = get_ha_instance_id()

asyncio.run(main())
