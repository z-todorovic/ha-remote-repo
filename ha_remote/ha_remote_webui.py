import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlencode
from pathlib import Path

APP_URL = "https://securicloud.me/add-agent/home_assistant/"

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            data = json.loads(Path("/share/ha_remote_instance_id.json").read_text())
            ha_id = data["instance_id"]
        except Exception:
            ha_id = "unknown"

        target = f"{APP_URL}{urlencode({'ha_id': ha_id})}"
        self.send_response(302)
        self.send_header("Location", target)
        self.end_headers()

HTTPServer(("0.0.0.0", 8099), Handler).serve_forever()
