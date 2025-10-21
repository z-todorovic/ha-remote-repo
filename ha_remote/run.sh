#!/bin/sh
set -e

echo "[INFO] Starting HA Remote Relay"

echo "[DEBUG] Current working directory: $(pwd)"
echo "[DEBUG] Contents of /data:"
ls -al /data || echo "[DEBUG] /data missing!"
echo "[DEBUG] Contents of /:"
ls -al / || echo "[DEBUG] / missing!"

# Configuration (simple defaults for now)
SERVER=${SERVER:-"ws://yourdomain/ha-cloud/ws/tunnel/test1"}
HA_HOST=${HA_HOST:-"127.0.0.1"}
HA_PORT=${HA_PORT:-"8123"}

echo "[INFO] Using configuration:"
echo "       SERVER=$SERVER"
echo "       HA_HOST=$HA_HOST"
echo "       HA_PORT=$HA_PORT"

# Debug path check
if [ -f "/data/ha_remote_relay.py" ]; then
    echo "[DEBUG] File /data/ha_remote_relay.py FOUND"
else
    echo "[DEBUG] File /data/ha_remote_relay.py NOT FOUND!"
fi

if [ -f "ha_remote_relay.py" ]; then
    echo "[DEBUG] File ha_remote_relay.py FOUND in current directory"
else
    echo "[DEBUG] File ha_remote_relay.py NOT FOUND in current directory"
fi

echo "[INFO] Launching relay script..."
python3 ha_remote_relay.py "$SERVER" "$HA_HOST" "$HA_PORT"
