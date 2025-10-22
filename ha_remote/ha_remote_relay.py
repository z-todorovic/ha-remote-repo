#!/usr/bin/env python3
import os, socket, struct, time, threading, websocket

SERVER = os.getenv("HA_REMOTE_SERVER", "wss://cometgps.com/ha-remote/ws/tunnel/test1")
HA_HOST = os.getenv("HA_REMOTE_HA_HOST", "127.0.0.1")
HA_PORT = int(os.getenv("HA_REMOTE_HA_PORT", "8123"))

def handle_channel(ws, chan_id, sock):
    try:
        while True:
            data = sock.recv(8192)
            if not data:
                break
            frame = struct.pack("!BIB", 1, chan_id, 0) + struct.pack("!H", len(data)) + data
            ws.send_binary(frame)
    except Exception:
        pass
    finally:
        sock.close()

def connect_loop():
    while True:
        try:
            print(f"[HA Relay] Connecting to {SERVER} ...")
            ws = websocket.create_connection(SERVER, timeout=10)
            print("[HA Relay] Connected to Tomcat tunnel.")
            while True:
                hdr = ws.recv_frame().data
                if not hdr or len(hdr) < 8:
                    continue
                type_, chan, a, b, c = hdr[0], struct.unpack("!I", hdr[1:5])[0], hdr[5], hdr[6], hdr[7]
                length = (a << 16) | (b << 8) | c
                data = ws.recv() if length > 0 else b""

                if type_ == 1:  # data
                    # open per-channel socket to HA
                    s = socket.socket()
                    s.connect((HA_HOST, HA_PORT))
                    t = threading.Thread(target=handle_channel, args=(ws, chan, s), daemon=True)
                    t.start()
                    s.sendall(data)
                elif type_ == 2:  # end
                    pass
        except Exception as e:
            print(f"[HA Relay] Disconnected ({e}), retrying in 5 s …")
            time.sleep(5)

if __name__ == "__main__":
    connect_loop()
