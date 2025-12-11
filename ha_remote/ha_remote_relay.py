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
import urllib.parse

DEBUG = os.getenv("HA_REMOTE_DEBUG", "false").lower() == "true"
TUNNEL_HOST = os.getenv("HA_REMOTE_TUNNEL_HOST", "securicloud.me")
TUNNEL_PORT = os.getenv("HA_REMOTE_TUNNEL_PORT", 5001)

REDIRECT_PORT = 8099  # HA Ingress forwards here inside the container

stopping = asyncio.Event()
_live = set()
_httpd = None

ssl_ctx = ssl.create_default_context()


# -----------------------------------------------------------------------------
# LOGGING
# -----------------------------------------------------------------------------

def log(msg: str):
    print(msg)

def debug(msg: str):
    if DEBUG:
        print("[DEBUG]", msg)


# -----------------------------------------------------------------------------
# SUPERVISOR RESTART
# -----------------------------------------------------------------------------

def restart_addon():
    """Triggers Supervisor to restart this add-on after returning HTMX response."""
    try:
        token = os.getenv("SUPERVISOR_TOKEN")
        if not token:
            log("[RESTART] No supervisor token found!")
            return

        url = "http://supervisor/addons/self/restart"
        r = requests.post(url, headers={"Authorization": f"Bearer {token}"}, timeout=5)

        if r.status_code == 200:
            log("[RESTART] Add-on restart triggered.")
        else:
            log(f"[RESTART] Supervisor restart failed: {r.status_code} {r.text}")

    except Exception as e:
        log(f"[RESTART] Exception during restart: {e}")


# -----------------------------------------------------------------------------
# INTERNAL UTILITIES
# -----------------------------------------------------------------------------

def spawn(coro):
    task = asyncio.create_task(coro)
    _live.add(task)
    task.add_done_callback(lambda t: (_live.discard(t), debug(f"Live tasks: {len(_live)}")))
    return task


def handle_stop(*_):
    log("Received stop signal → shutting down")
    stopping.set()
    stop_ingress_redirect_server()


# -----------------------------------------------------------------------------
# HOME ASSISTANT DISCOVERY
# -----------------------------------------------------------------------------

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
            log(f"Supervisor query failed: {e}")

    return "127.0.0.1", 8123


# -----------------------------------------------------------------------------
# INSTANCE ID
# -----------------------------------------------------------------------------

def get_ha_instance_id():
    cached_file = Path("/share/ha_instance_id.json")
    try:
        if cached_file.exists():
            try:
                return json.loads(cached_file.read_text())["instance_id"]
            except Exception:
                pass

        # Generate new ID on startup if missing
        base36 = "0123456789abcdefghijklmnopqrstuvwxyz"
        ha_id = ''.join(secrets.choice(base36) for _ in range(25))
        cached_file.write_text(json.dumps({"instance_id": ha_id}))
        return ha_id

    except Exception:
        return "test1"


# -----------------------------------------------------------------------------
# TUNNEL LOGIC  (unchanged from previous working version)
# -----------------------------------------------------------------------------

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
                    b = await asyncio.wait_for(tunnel_reader.readexactly(2), 5)
                    length = int.from_bytes(b)
                    break
                except asyncio.TimeoutError:
                    tunnel_writer.write(b"\x00\x00")
                    await tunnel_writer.drain()

    except asyncio.CancelledError:
        pass
    except Exception:
        pass

    finally:
        if not ha_writer.is_closing():
            ha_writer.close()
            with contextlib.suppress(Exception):
                await ha_writer.wait_closed()


async def pipe_ha_to_tunnel(ha_reader, tunnel_writer):
    try:
        while not stopping.is_set():
            data = await ha_reader.read(8192)
            if not data:
                break
            tunnel_writer.write(len(data).to_bytes(2, "big"))
            tunnel_writer.write(data)
            await tunnel_writer.drain()

    except asyncio.CancelledError:
        pass
    except Exception:
        pass

    finally:
        if not tunnel_writer.is_closing():
            tunnel_writer.close()
            with contextlib.suppress(Exception):
                await tunnel_writer.wait_closed()


async def handle_active_connection(tunnel_reader, tunnel_writer, first_chunk):
    ha_reader = ha_writer = None

    try:
        debug("[FORWARD] Opening HA connection...")
        ha_reader, ha_writer = await asyncio.open_connection(LOCAL_HA[0], LOCAL_HA[1])

        t1 = spawn(pipe_tunnel_to_ha(tunnel_reader, tunnel_writer, ha_writer, first_chunk))
        t2 = spawn(pipe_ha_to_tunnel(ha_reader, tunnel_writer))

        done, pending = await asyncio.wait({t1, t2}, return_when=asyncio.FIRST_COMPLETED)

        for p in pending:
            p.cancel()
        await asyncio.gather(*pending, return_exceptions=True)

    except Exception as e:
        log(f"[FORWARD] Error: {e}")

    finally:
        for w in (tunnel_writer, ha_writer):
            if w:
                with contextlib.suppress(Exception):
                    w.close()
                    await w.wait_closed()

        debug("[FORWARD] Session closed")


async def keep_idle_connection(print_conn_logs):
    while not stopping.is_set():
        try:
            if print_conn_logs or DEBUG:
                log(f"[IDLE] Connecting to {TUNNEL_HOST}:{TUNNEL_PORT}")

            reader, writer = await asyncio.open_connection(
                TUNNEL_HOST,
                int(TUNNEL_PORT),
                ssl=ssl_ctx,
                server_hostname=TUNNEL_HOST
            )

            id_bytes = HA_INSTANCE_ID.encode()
            writer.write(len(id_bytes).to_bytes(2, "big"))
            writer.write(id_bytes)
            await writer.drain()

            if print_conn_logs or DEBUG:
                log("[IDLE] Connected. The service is running...")
            print_conn_logs = False

            # Waiting for first two bytes to activate forwarding
            while not stopping.is_set():
                try:
                    first_chunk = await asyncio.wait_for(reader.readexactly(2), 5)
                    break
                except asyncio.TimeoutError:
                    writer.write(b"\x00\x00")
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
            await asyncio.sleep(3)


# -----------------------------------------------------------------------------
# INGRESS UI  (HTMX + confirmation + restart polling)
# -----------------------------------------------------------------------------

class RedirectHandler(BaseHTTPRequestHandler):
    """
    Routes:
      /                   → main web UI
      /reset-confirm      → full-page confirmation dialog
      /reset-now          → delete ID, show restart page, trigger restart
      /check-ready        → HTMX poller, returns main UI once ID is back
    """

    # MAIN PAGE ---------------------------------------------------

    def build_main_page(self) -> str:
        return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>HA Remote Relay</title>
<link rel="stylesheet"
 href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css">
<script src="https://unpkg.com/htmx.org@1.9.10"></script>
</head>
<body>

<div class="container" style="max-width:600px; margin-top:40px;">

  <h3 class="mb-3">HA Remote Relay</h3>

  <div class="alert alert-secondary">
    <b>Instance ID:</b><br>
    <code>{HA_INSTANCE_ID}</code>
  </div>

  <div class="alert alert-info">
    Use <b>Generate New Instance ID</b> if you need to re-register
    this Home Assistant instance with Securicloud.
  </div>

  <button class="btn btn-danger w-100 mb-3"
          hx-get="reset-confirm"
          hx-target="body"
          hx-swap="innerHTML">
      Generate New Instance ID
  </button>

  <button class="btn btn-primary w-100"
          onclick="window.top.open('{regAgentUrl}', '_blank')">
      Register Instance
  </button>

</div>

</body>
</html>
"""

    # CONFIRMATION ---------------------------------------------------

    def build_confirm_page(self) -> str:
        return """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Confirm Reset</title>
<link rel="stylesheet"
 href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css">
<script src="https://unpkg.com/htmx.org@1.9.10"></script>
</head>
<body>

<div class="container" style="max-width:600px; margin-top:60px;">

  <div class="card border-warning">
    <div class="card-header bg-warning">Confirm Instance ID Reset</div>

    <div class="card-body">
      <p>
        This will <b>reset the instance ID</b> for this Home Assistant instance.
        A new ID will be generated after restart.
      </p>
      <p class="text-danger">
        Existing remote access sessions using the old ID will stop working.
      </p>

      <div class="d-flex justify-content-between mt-4">
        <button class="btn btn-secondary"
                hx-get="."
                hx-target="body"
                hx-swap="innerHTML">
          Cancel
        </button>

        <button class="btn btn-danger"
                hx-get="reset-now"
                hx-target="body"
                hx-swap="innerHTML">
          Yes, Reset ID
        </button>
      </div>
    </div>
  </div>

</div>

</body>
</html>
"""

    # RESET + AUTO-RESTART PAGE ------------------------------------

    def build_reset_done_page(self) -> str:
        return """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Resetting…</title>
<link rel="stylesheet"
 href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css">
</head>

<body>

<script>
async function checkAlive() {
    try {
        // Try to load the addon root (the same URL we are viewing)
        const r = await fetch(window.location.href, { method: "GET" });

        // When addon is back, this succeeds with status 200
        if (r.ok) {
            window.location.reload();
        }

    } catch (e) {
        // ignore — addon is still restarting
    }
}

// Try every 3 seconds
setInterval(checkAlive, 3000);
</script>

<div class="container" style="max-width:600px; margin-top:60px;">

  <div class="alert alert-warning text-center">
    <h4>Instance ID Reset</h4>
    <p>The instance ID has been removed.</p>
    <p>A new one will be created when the add-on restarts.</p>
    <hr>
    <p>The add-on is restarting…<br>
       This page will refresh automatically when it becomes available.</p>
  </div>

</div>

</body>
</html>
"""

    # ROUTER -------------------------------------------------------

    def do_GET(self):
        debug(f"[INGRESS] Raw path: {self.path}")
        parsed = urllib.parse.urlparse(self.path)
        clean = parsed.path.rstrip("/")

        if clean.endswith("reset-confirm"):
            return self.respond_html(self.build_confirm_page())

        if clean.endswith("reset-now"):
            return self.handle_reset_now()

        if clean.endswith("check-ready"):
            return self.handle_check_ready()

        # default = main page
        return self.respond_html(self.build_main_page())

    # RESPONSE WRAPPER ---------------------------------------------

    def respond_html(self, html: str):
        body = html.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # ----------------------------------------------------------------
    # HANDLERS
    # ----------------------------------------------------------------

    def handle_reset_now(self):
        """Delete ID file → show restart page → trigger restart."""

        try:
            cached = Path("/share/ha_instance_id.json")
            if cached.exists():
                cached.unlink()
            log("[RESET] Instance ID file deleted.")
        except Exception as e:
            log(f"[RESET] Error deleting ID: {e}")

        # First send page
        self.respond_html(self.build_reset_done_page())

        # Then restart asynchronously
        threading.Thread(target=restart_addon, daemon=True).start()

    def handle_check_ready(self):
        """HTMX polling: return main UI when add-on has restarted."""

        # If ID file exists → restart is done
        if Path("/share/ha_instance_id.json").exists():
            new_id = get_ha_instance_id()  # refresh global
            global HA_INSTANCE_ID
            HA_INSTANCE_ID = new_id
            return self.respond_html(self.build_main_page())

        # Still restarting → return same page
        return self.respond_html(self.build_reset_done_page())

    def log_message(self, *args):
        return  # silence BaseHTTPRequestHandler noise


# -----------------------------------------------------------------------------
# INGRESS SERVER
# -----------------------------------------------------------------------------

def start_ingress_redirect_server():
    global _httpd
    try:
        log(f"[INGRESS] Starting admin UI on port {REDIRECT_PORT}")
        _httpd = HTTPServer(("0.0.0.0", REDIRECT_PORT), RedirectHandler)
        log("[INGRESS] Admin UI ready")
        _httpd.serve_forever()
    except Exception as e:
        log(f"[INGRESS] Failed to start admin UI: {e}")

def stop_ingress_redirect_server():
    global _httpd
    if _httpd:
        with contextlib.suppress(Exception):
            log("[INGRESS] Shutting down admin UI")
            _httpd.shutdown()


# -----------------------------------------------------------------------------
# MAIN ASYNC
# -----------------------------------------------------------------------------

async def main():
    signal.signal(signal.SIGTERM, handle_stop)
    signal.signal(signal.SIGINT, handle_stop)

    log(f"[INFO] Instance registration URL: {regAgentUrl}")

    threading.Thread(target=start_ingress_redirect_server, daemon=True).start()
    spawn(keep_idle_connection(True))
    await asyncio.Event().wait()


# -----------------------------------------------------------------------------
# STARTUP
# -----------------------------------------------------------------------------

LOCAL_HA = discover_local_ha()
HA_INSTANCE_ID = get_ha_instance_id()
regAgentUrl = f"https://securicloud.me/add-agent/home_assistant/{HA_INSTANCE_ID}"

asyncio.run(main())
