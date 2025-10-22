#!/usr/bin/env python3
import os, socket, struct, time, threading, websocket

SERVER = os.getenv("HA_REMOTE_SERVER", "wss://cometgps.com/ha-remote/ws/tunnel/test1")
HA_HOST = os.getenv("HA_REMOTE_HA_HOST", "127.0.0.1")
HA_PORT = int(os.getenv("HA_REMOTE_HA_PORT", "8123"))

# Frame format: [type(1)][chan(4)][len(4)][payload...]
# type: 1=data, 2=end

def send_frame(ws, type_, chan, payload=b""):
    ws.send_binary(struct.pack("!BII", type_, chan, len(payload)) + payload)

def handle_ha_to_tunnel(ws, chan, sock):
    """Read from HA TCP socket and forward to Tomcat."""
    try:
        while True:
            data = sock.recv(8192)
            if not data:
                break
            send_frame(ws, 1, chan, data)
    except Exception:
        pass
    finally:
        try:
            send_frame(ws, 2, chan)
        except Exception:
            pass
        sock.close()

def connect_loop():
    while True:
        try:
            print(f"[HA Relay] Connecting to {SERVER} ...")
            ws = websocket.create_connection(SERVER, timeout=10)
            print("[HA Relay] Connected to Tomcat tunnel.")
            while True:
                # Each frame = header + payload
                header = ws.recv_frame().data
                if not header or len(header) < 9:
                    continue
                type_, chan, length = struct.unpack("!BII", header[:9])
                payload = b""
                if length > 0:
                    payload = ws.recv() if isinstance(ws.recv, bytes) else ws.recv_frame().data
                if type_ == 1:  # data -> send to HA
                    s = socket.socket()
                    s.connect((HA_HOST, HA_PORT))
                    t = threading.Thread(target=handle_ha_to_tunnel, args=(ws, chan, s), daemon=True)
                    t.start()
                    s.sendall(payload)
                elif type_ == 2:
                    pass  # end of stream
        except Exception as e:
            print(f"[HA Relay] Disconnected ({e}), retrying in 5 s ...")
            time.sleep(5)

if __name__ == "__main__":
    connect_loop()
