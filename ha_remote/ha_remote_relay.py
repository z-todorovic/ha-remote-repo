#!/usr/bin/env python3
import os
import asyncio
import websockets
import base64
import json
import socket
import traceback

SERVER = os.getenv("HA_REMOTE_SERVER", "ws://yourserver/ha-remote/ws/tunnel/test1")
HA_HOST = os.getenv("HA_REMOTE_HA_HOST", "homeassistant")
HA_PORT = int(os.getenv("HA_REMOTE_HA_PORT", "8123"))
RETRY = 5


def read_http_response_from_sock(sock):
    """Read HTTP response from a socket synchronously."""
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


async def pipe_websocket_to_tcp(ws, sock):
    """Read binary frames from websocket and send to TCP."""
    try:
        async for msg in ws:
            if isinstance(msg, bytes):
                sock.sendall(msg)
    except Exception as e:
        print("[relay] ws->tcp closed:", e)
    finally:
        try:
            sock.shutdown(socket.SHUT_WR)
        except Exception:
            pass


async def pipe_tcp_to_websocket(ws, sock):
    """Read from TCP and send binary frames to websocket."""
    try:
        while True:
            data = sock.recv(4096)
            if not data:
                break
            await ws.send(data)
    except Exception as e:
        print("[relay] tcp->ws closed:", e)
    finally:
        try:
            await ws.close()
        except Exception:
            pass


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
                    print("[relay] frame preview:", msg[:300])
                    try:
                        obj = json.loads(msg)
                    except Exception as e:
                        print("[relay] bad JSON:", e)
                        continue

                    if obj.get("type") != "req" or "body" not in obj:
                        continue

                    rid = obj["id"]
                    req_raw = base64.b64decode(obj["body"])
                    # Detect if this is a websocket upgrade request
                    if b"GET /api/websocket" in req_raw:
                        print("[relay] websocket upgrade requested, bridging...")
                        try:
                            sock = socket.create_connection((HA_HOST, HA_PORT), timeout=5)
                            sock.sendall(req_raw)
                            # Start bidirectional pipe
                            task1 = asyncio.create_task(pipe_websocket_to_tcp(ws, sock))
                            task2 = asyncio.create_task(pipe_tcp_to_websocket(ws, sock))
                            await asyncio.wait([task1, task2], return_when=asyncio.ALL_COMPLETED)
                            sock.close()
                        except Exception as e:
                            print("[relay] websocket bridge failed:", e)
                        continue

                    # Normal HTTP request
                    print("[relay] forwarding to HA", HA_HOST, HA_PORT, "id=", rid)
                    try:
                        s = socket.create_connection((HA_HOST, HA_PORT), timeout=5)
                        s.sendall(req_raw)
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
                            "id": rid,
                            "type": "res",
                            "status": 502,
                            "headers": {},
                            "body": "",
                        }
                        await ws.send(json.dumps(res))

        except Exception as e:
            print("[relay] disconnected:", e)
            traceback.print_exc()
            await asyncio.sleep(RETRY)


if __name__ == "__main__":
    try:
        asyncio.run(handle_ws())
    except KeyboardInterrupt:
        print("exiting")
