import asyncio

# TUNNEL_HOST = "tunnel.cometgps.com"
# TUNNEL_PORT = 2345
TUNNEL_HOST = "127.0.0.1"
TUNNEL_PORT = 2345
CLIENT_ID = "test1".ljust(16, '\0')  # pad with NULs
HA_HOST = "192.168.88.117"
HA_PORT = 8123

async def pipe(reader, writer):
    try:
        while data := await reader.read(8192):
            writer.write(data)
            await writer.drain()
    except Exception:
        pass
    finally:
        writer.close()

async def handle_active_connection(reader_tunnel, writer_tunnel, first_chunk):
    """Forward an active tunnel connection to HA."""
    try:
        print("[FORWARD] Opening HA connection...")
        ha_reader, ha_writer = await asyncio.open_connection(HA_HOST, HA_PORT)
        ha_writer.write(first_chunk)
        await ha_writer.drain()

        task1 = asyncio.create_task(pipe(reader_tunnel, ha_writer))
        task2 = asyncio.create_task(pipe(ha_reader, writer_tunnel))
        await asyncio.wait([task1, task2], return_when=asyncio.FIRST_COMPLETED)
    except Exception as e:
        print(f"[ERROR] {e}")
    finally:
        writer_tunnel.close()
        print("[FORWARD] Session closed")

async def keep_idle_connection():
    """Maintain one idle connection, spawn new one when triggered."""
    while True:
        try:
            print(f"[IDLE] Connecting to {TUNNEL_HOST}:{TUNNEL_PORT}")
            reader, writer = await asyncio.open_connection(TUNNEL_HOST, TUNNEL_PORT)
            writer.write(CLIENT_ID.encode('ascii'))
            await writer.drain()
            print("[IDLE] Connected and identified. Waiting for data...")

            # Wait for first byte from server/user
            first_chunk = await reader.read(1)
            if not first_chunk:
                writer.close()
                await asyncio.sleep(1)
                continue

            # Immediately spawn a new idle connection
            asyncio.create_task(keep_idle_connection())

            # Continue as active handler
            await handle_active_connection(reader, writer, first_chunk)

        except Exception as e:
            print(f"[IDLE] Error: {e}, retry in 3s")
            await asyncio.sleep(3)

asyncio.run(keep_idle_connection())
