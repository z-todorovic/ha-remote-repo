import contextlib
import io
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

stopping = asyncio.Event()
_live = set()

def _get_ha_instance_id():
    # The Supervisor token is automatically available as an environment variable
    supervisor_token = os.environ.get('SUPERVISOR_TOKEN')
    if not supervisor_token:
        return "Error: SUPERVISOR_TOKEN not found."

    # The internal URL to access the Home Assistant Core API via the Supervisor proxy
    api_url = "http://supervisor/core/api/config"

    # Headers for authentication
    headers = {
        "Authorization": f"Bearer {supervisor_token}",
        "Content-Type": "application/json"
    }

    try:
        # Make the request to the API
        response = requests.get(api_url, headers=headers)
        response.raise_for_status() # Raise an exception for bad status codes (4xx or 5xx)

        # Parse the JSON response
        config_data = response.json()

        # The 'location_name' is often used as a unique identifier, but a true 'instance ID' 
        # is part of the system info, not config.
        # A better endpoint might be /api/discovery_info if you can use the websocket API.
        # Let's stick with /api/config for general unique info.
        
        # NOTE: There is no single field explicitly named "instance_id" in /api/config.
        # A combination of system unique information is usually used.
        # For general identification, the 'version' and 'location_name' can be useful.
        # If you need a guaranteed UUID, you need to access a different endpoint.

        # Accessing the Supervisor API directly might provide a more specific system ID.
        # Let's try the Supervisor API's /info endpoint
        supervisor_api_url = "http://supervisor/supervisor/info"
        supervisor_response = requests.get(supervisor_api_url, headers=headers)
        supervisor_response.raise_for_status()
        supervisor_data = supervisor_response.json()

        # The 'supervisor_data' contains information about the supervisor, 
        # including a unique ID for the host/system.
        # Look for a unique system identifier here.
        # Based on documentation, the 'host_id' or 'system_uuid' might be the intended value.
        system_uuid = supervisor_data.get('data', {}).get('host_id', 'Unknown ID') # Or 'system_uuid' depending on API version

        return system_uuid

    except requests.exceptions.RequestException as e:
        return f"Error connecting to Home Assistant API: {e}"
    except json.JSONDecodeError as e:
        return f"Error decoding JSON response: {e}"
    
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
            reader, writer = await asyncio.open_connection(TUNNEL_HOST, TUNNEL_PORT)
            id_bytes = HA_INSTANCE_ID.encode("utf-8")
            writer.write(bytes([len(id_bytes)]))
            writer.write(id_bytes)
            await writer.drain()
            print("[IDLE] Connected and identified. Waiting for data...")
            print(f"Live tasks: {len(_live)}")
            # for t in asyncio.all_tasks():
            #     if not t.done():
            #         print(t)
            #         t.print_stack(limit=10)
            #         break
                    
            # Wait for first byte from server/user
            while not stopping.is_set():
                try:
                    first_chunk = await asyncio.wait_for(reader.readexactly(2), 5)
                    break
                except asyncio.TimeoutError:
                    writer.write(b'\x00')
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
    print(f"REAL HA INSTANCE ID: {_get_ha_instance_id()}")
    print(f"HA instance ID: {HA_INSTANCE_ID}")
    print(f"Local HA: {LOCAL_HA[0]}:{LOCAL_HA[1]}")
    spawn(keep_idle_connection())
    await asyncio.Event().wait()

LOCAL_HA = discover_local_ha()
HA_INSTANCE_ID = get_ha_instance_id()
# LOCAL_HA = "192.168.88.117", 8123
# HA_INSTANCE_ID = "7433b6d93787482d87bbbfe937fcd369"


asyncio.run(main())
