import contextlib
import os
import secrets
import ssl
import requests
import asyncio
import json
import signal
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

DEBUG = os.getenv("HA_REMOTE_DEBUG", "false").lower() == "true"
TUNNEL_HOST = os.getenv("HA_REMOTE_TUNNEL_HOST", "tunnel.securicloud.me")
TUNNEL_PORT = os.getenv("HA_REMOTE_TUNNEL_PORT", 443)
# TUNNEL_HOST = "127.0.0.1"
# TUNNEL_PORT = 2345

REDIRECT_PORT = int(os.getenv("INGRESS_PORT", "8099"))

stopping = asyncio.Event()
_live = set()

ssl_ctx = ssl.create_default_context()


def log(msg):
    print(msg)


def debug(msg):
    if DEBUG:
        print("[DEBUG]", msg)


def spawn(coro):
    task = asyncio.create_task(coro)
    _live.add(task)
    task.add_done_callback(
        lambda task: (
            _live.discard(task),
            debug(f"Live tasks: {len(_live)}")
        )
    )
    return task


def handle_stop(*_):
    log("Received stop signal → shutting down")
    stopping.set()
    global _httpd
    # Try to stop HTTP redirect server gracefully
    if _httpd is not None:
        with contextlib.suppress(Exception):
            log("[REDIRECT] Shutting down redirect server")
            _httpd.shutdown()
    # sys.exit(0)


def discover_local_ha():
    api = os.getenv("SUPERVISOR_API")
    token = os.getenv("SUPERVISOR_TOKEN")
    if api and token:
        try:
            r = requests.get(
                f"{api}/core/info",
                headers={"Authorization": f"Bearer {token}"},
                timeout=5
            )
            data = r.json().get("data", {})
            return data.get("host", "127.0.0.1"), int(data.get("port", 8123))
        except Exception as e:
            log("Supervisor query failed:", e)
    # fallback (Core install / Windows test)
    return "127.0.0.1", 8123


def get_ha_instance_id():
    cachedInstanceIdFile = Path("/share/ha_instance_id.json")
    try:
        if cachedInstanceIdFile.exists():
            try:
                return json.loads(cachedInstanceIdFile.read_text())["instance_id"]
            except Exception:
                pass
        base62 = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
        ha_id = ''.join(secrets.choice(base62) for _ in range(22))
        cachedInstanceIdFile.write_text(json.dumps({"instance_id": ha_id}))
        return ha_id
    except Exception:
        return "test1"


def start_redirect_server():
    global _httpd
    try:
        _httpd = HTTPServer(("0.0.0.0", REDIRECT_PORT), RedirectHandler)
        log(f"[REDIRECT] Listening on 0.0.0.0:{REDIRECT_PORT}")
        _httpd.serve_forever()
    except Exception as e:
        log(f"[REDIRECT] Failed to start redirect server: {e}")


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
        debug("[FORWARD] Opening HA connection...")
        ha_reader, ha_writer = await asyncio.open_connection(LOCAL_HA[0], LOCAL_HA[1])

        task1 = spawn(
            pipe_tunnel_to_ha(tunnel_reader, tunnel_writer, ha_writer, first_chunk)
        )
        task2 = spawn(
            pipe_ha_to_tunnel(ha_reader, tunnel_writer)
        )
        done, pending = await asyncio.wait(
            {task1, task2}, return_when=asyncio.FIRST_COMPLETED
        )
        for p in pending:
            p.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
    except Exception as e:
        log(f"[FORWARD] Error: {e}")
    finally:
        for w in (tunnel_writer, ha_writer):
            try:
                w.close()
                await w.wait_closed()
            except Exception:
                pass
        debug("[FORWARD] Session closed")


async def keep_idle_connection(print_conn_logs):
    """Maintain one idle connection, spawn new one when triggered."""
    while not stopping.is_set():
        try:
            if print_conn_logs or DEBUG:
                log(f"[IDLE] Connecting to {TUNNEL_HOST}:{TUNNEL_PORT}")
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
            if print_conn_logs or DEBUG:
                log("[IDLE] Connected. The service is running...")
            print_conn_logs = False
            debug(f"[INFO] Live tasks: {len(_live)}")

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

            spawn(keep_idle_connection(False))

            await handle_active_connection(reader, writer, first_chunk)
            break

        except Exception as e:
            log(f"[IDLE] Error: {e}, retry in 3s")
            print_conn_logs = True
            if "GeneratorExit" in str(e) or stopping.is_set():
                break
            await asyncio.sleep(3)


async def main():
    signal.signal(signal.SIGTERM, handle_stop)
    signal.signal(signal.SIGINT, handle_stop)

    debug(f"[INFO] HA instance ID: {HA_INSTANCE_ID}")
    debug(f"[INFO] Local HA: {LOCAL_HA[0]}:{LOCAL_HA[1]}")
    log(f"[INFO] Instance registration URL: {regAgentUrl}")

    # Start ingress redirect server
    threading.Thread(target=start_ingress_redirect_server, daemon=True).start()

    # Start tunnel logic
    spawn(keep_idle_connection(True))

    # Keep running forever
    await asyncio.Event().wait()


# ------------------------
# INGRESS REDIRECT SERVER
# ------------------------

_httpd = None

class RedirectHandler(BaseHTTPRequestHandler):

    def do_GET(self):
        # HTML that BREAKS OUT of the Home Assistant iframe
        body = f"""
        <html>
          <head>
            <script>
              window.top.open("{regAgentUrl}", "_blank");
            </script>
          </head>
          <body>
            <p>Opening Securicloud…</p>
            <p><a href="{regAgentUrl}">Click here if you are not redirected automatically.</a></p>
          </body>
        </html>
        """.encode("utf-8")

        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            debug(f"[INGRESS REDIRECT] Served HTML redirect to {regAgentUrl}")
        except Exception as e:
            log(f"[INGRESS REDIRECT] Error: {e}")

    def log_message(self, *args):
        # silence noisy HTTP logs
        return


def start_ingress_redirect_server():
    """Runs the HTTP redirect server on the Home Assistant Ingress port."""
    global _httpd
    try:
        port = int(os.getenv("INGRESS_PORT", "8099"))  # HA provides this
        debug(f"[INGRESS REDIRECT] Starting on port {port}")
        _httpd = HTTPServer(("0.0.0.0", port), RedirectHandler)
        _httpd.serve_forever()
    except Exception as e:
        log(f"[INGRESS REDIRECT] Failed to start: {e}")


def stop_ingress_redirect_server():
    """Shuts down the redirect server safely."""
    global _httpd
    if _httpd:
        with contextlib.suppress(Exception):
            log("[INGRESS REDIRECT] Shutting down")
            _httpd.shutdown()


LOCAL_HA = discover_local_ha()
HA_INSTANCE_ID = get_ha_instance_id()
regAgentUrl = f"https://securicloud.me/add-agent/home_assistant/{HA_INSTANCE_ID}"
# LOCAL_HA = "192.168.88.117", 8123
# HA_INSTANCE_ID = "3787482d87bbbfe937fcd3697433b6d9"

asyncio.run(main())
