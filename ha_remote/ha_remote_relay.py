#!/usr/bin/env python3
import os
import socket
import struct
import time
import threading
import websocket
import ssl

SERVER = os.getenv("HA_REMOTE_SERVER", "wss://cometgps.com/ha-remote/ws/tunnel/test1")
HA_HOST = os.getenv("HA_REMOTE_HA_HOST", "127.0.0.1")
HA_PORT = int(os.getenv("HA_REMOTE_HA_PORT", "8123"))

TYPE_DATA = 1
TYPE_END = 2

def send_frame(ws, type_, chan, payload=b""):
    header = struct.pack("!BII", type_, chan, len(payload))
    ws.send_binary(header + payload)

def handle_ha_to_tunnel(ws, chan, sock):
    try:
        while True:
            data = sock.recv(8192)
            if not data:
                break
            send_frame(ws, TYPE_DATA, chan, data)
    except Exception as e:
        print(f"[HA Relay] HA->Tunnel error (chan {chan}): {e}")
    finally:
        try:
            send_frame(ws, TYPE_END, chan, b"")
        except Exception:
            pass
        sock.close()

def connect_loop():
    while True:
        try:
            print(f"[HA Relay] Connecting to {SERVER} ...")
            ws = websocket.create_connection(
                SERVER,
                timeout=10,
                sslopt={"cert_reqs": ssl.CERT_NONE}
            )
            print("[HA Relay] Connected to Tomcat tunnel.")

            # Start keep-alive thread
            def ping_loop():
                try:
                    while True:
                        time.sleep(30)
                        send_frame(ws, TYPE_DATA, 0, b"")
                except Exception as e:
                    print(f"[HA Relay] Ping loop error: {e}")
            threading.Thread(target=ping_loop, daemon=True).start()

            while True:
                frame = ws.recv_frame().data
                if not frame or len(frame) < 9:
                    continue
                type_, chan, length = struct.unpack("!BII", frame[:9])
                payload = b""
                if length > 0:
                    payload = ws.recv()
                if type_ == TYPE_DATA:
                    s = socket.socket()
                    s.connect((HA_HOST, HA_PORT))
                    threading.Thread(
                        target=handle_ha_to_tunnel, args=(ws, chan, s), daemon=True
                    ).start()
                    s.sendall(payload)
                elif type_ == TYPE_END:
                    pass

        except Exception as e:
            print(f"[HA Relay] Disconnected ({e}), retrying in 5 s ...")
            time.sleep(5)

if __name__ == "__main__":
    connect_loop()
