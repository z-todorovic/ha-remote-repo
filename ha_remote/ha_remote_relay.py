#!/usr/bin/env python3
import os, asyncio, websockets, base64, json, socket, traceback, time

SERVER = os.getenv("HA_REMOTE_SERVER", "ws://yourserver/ha-remote/ws/tunnel/test1")
HA_HOST = os.getenv("HA_REMOTE_HA_HOST", "homeassistant")
HA_PORT = int(os.getenv("HA_REMOTE_HA_PORT", "8123"))
RETRY = 5

async def read_http_response_from_sock(sock):
    """
    Read HTTP response from connected socket:
     - read headers until \r\n\r\n
     - if Content-Length present, read that many bytes
     - otherwise read until socket closes (fallback)
    Return (status_int, headers_dict, body_bytes)
    """
    sock.settimeout(5)
    data = b""
    while b"\r\n\r\n" not in data:
        chunk = sock.recv(4096)
        if not chunk:
            break
        data += chunk
    header_part, sep, rest = data.partition(b"\r\n\r\n")
    header_lines = header_part.decode(errors='replace').split("\r\n")
    status_line = header_lines[0] if header_lines else "HTTP/1.1 200 OK"
    status_tok = status_line.split(" ", 2)
    status = int(status_tok[1]) if len(status_tok) >= 2 and status_tok[1].isdigit() else 200
    headers = {}
    cl = None
    for h in header_lines[1:]:
        if ":" in h:
            k, v = h.split(":", 1)
            headers[k.strip()] = v.strip()
            if k.lower().strip() == "content-length":
                try:
                    cl = int(v.strip())
                except:
                    cl = None
    body = rest
    if cl is not None:
        need = cl - len(body)
        while need > 0:
            chunk = sock.recv(min(8192, need))
            if not chunk:
                break
            body += chunk
            need -= len(chunk)
    else:
        # read until close (short timeout)
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
            print(f"[relay] connecting to {SERVER}")
            async with websockets.connect(SERVER, max_size=None) as ws:
                print("[relay] connected")
                async for msg in ws:
                    # expect text JSON frames
                    if isinstance(msg, str):
                        try:
                            obj = json.loads(msg)
                            if obj.get("type") == "req" and "body" in obj and "id" in obj:
                                rid = obj["id"]
                                b64 = obj["body"]
                                req_raw = base64.b64decode(b64)
                                # forward to local HA
                                try:
                                    s = socket.create_connection((HA_HOST, HA_PORT), timeout=5)
                                    s.sendall(req_raw)
                                    status, headers, body = await asyncio.get_event_loop().run_in_executor(None, lambda: read_http_response_from_sock(s))
                                    # build response JSON
                                    res = {
                                        "id": rid,
                                        "type": "res",
                                        "status": status,
                                        "headers": headers,
                                        "body": base64.b64encode(body).decode()
                                    }
                                    await ws.send(json.dumps(res))
                                    s.close()
                                except Exception as e:
                                    # send an error response
                                    res = {"id": rid, "type": "res", "status": 502, "headers": {}, "body": base64.b64encode(b"").decode()}
                                    await ws.send(json.dumps(res))
                        except Exception as e:
                            print("bad frame:", e)
                    else:
                        # ignore binary frames for now
                        pass
        except Exception as e:
            print("[relay] disconnected:", e)
            traceback.print_exc()
            await asyncio.sleep(RETRY)

if __name__ == "__main__":
    try:
        asyncio.run(handle_ws())
    except KeyboardInterrupt:
        print("exiting")
