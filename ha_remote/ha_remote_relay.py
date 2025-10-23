#!/usr/bin/env python3
import os
import asyncio
import websockets
import base64
import json
import socket
import traceback
import time

SERVER = os.getenv("HA_REMOTE_SERVER", "ws://yourserver/ha-remote/ws/tunnel/test1")
HA_HOST = os.getenv("HA_REMOTE_HA_HOST", "homeassistant")
HA_PORT = int(os.getenv("HA_REMOTE_HA_PORT", "8123"))
RETRY = 5


async def read_http_response_from_sock(sock):
    """Blocking read of HTTP response."""
    sock.settimeout(10)
    data = b""
    while b"\r\n\r\n" not in data:
        chunk = sock.recv(4096)
        if not chunk:
            break
        data += chunk
    header_part, sep, rest = data.partition(b"\r\n\r\n")
    header_lines = header_part.decode(errors="replace").split("\r\n")
    status = 200
    if header_lines:
        parts = header_lines[0].split(" ")
        if len(parts) > 1 and parts[1].isdigit():
            status = int(parts[1])
    headers = {}
    content_len = None
    for h in header_lines[1:]:
        if ":" in h:
            k, v = h.split(":", 1)
            headers[k.strip()] = v.strip()
            if k.lower().strip() == "content-length":
                try:
                    content_len = int(v.strip())
                except:
                    content_len = None
    body = rest
    if content_len is not None:
        while len(body) < content_len:
            chunk = sock.recv(8192)
            if not chunk:
                break
            body += chunk
    else:
        sock.settimeout(1)
        try:
            while True:
                chunk = sock.recv(8192)
                if not chunk:
                    break
                body += chunk
        except socket.timeout:
            pass
    return status, headers, body


async def handle_ws():
    while True:
        try:
            print("[relay] connecting to", SERVER)
            async with websockets.connect(
                SERVER, max_size=None, ping_interval=None, ping_timeout=None
            ) as ws:
                print("[relay] connected, waiting for frames...")
                async for msg in ws:
                    if isinstance(msg, bytes):
                        print("[relay] ignoring binary frame of", len(msg))
                        continue
                    print("[relay] got raw frame len", len(msg))
                    try:
                        obj = json.loads(msg)
                    except Exception as e:
                        print("[relay] bad JSON:", e)
                        continue

                    if obj.get("type") != "req" or "body" not in obj:
                        continue

                    rid = obj["id"]
                    req_raw = base64.b64decode(obj["body"])
                    print("[relay] forwarding to HA", HA_HOST, HA_PORT, "id=", rid)

                    try:
                        s = socket.create_connection((HA_HOST, HA_PORT), timeout=5)
                        s.sendall(req_raw)
                        # read full response synchronously
                        status, headers, body = await asyncio.to_thread(
                            read_http_response_from_sock, s
                        )
                        s.close()

                        res = {
                            "id": rid,
                            "type": "res",
                            "status": status,
                            "headers": headers,
                            "body": base64.b64encode(body).decode(),
                        }
                        await ws.send(json.dumps(res))
                        print("[relay] sent response id=", rid, "status=", status)
                    except Exception as e:
                        print("[relay] error contacting HA:", e)
                        res = {
