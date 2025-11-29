#!/bin/sh
CONFIG_PATH=/data/options.json

echo "[HA Remote] Starting container..."
echo "Checking /data/options.json:"
cat $CONFIG_PATH || echo "No options.json found!"

HA_REMOTE_TUNNEL_HOST=$(jq -r '.tunnel_host' $CONFIG_PATH)
HA_REMOTE_TUNNEL_PORT=$(jq -r '.tunnel_port' $CONFIG_PATH | tr -cd '0-9')

export HA_REMOTE_TUNNEL_HOST
export HA_REMOTE_TUNNEL_PORT

echo "[HA Remote] Launching Python..."
exec python3 -u /ha_remote_relay.py & 
exec python3 -u /ha_remote_webui.py
code=$?
echo "[HA Remote] Python exited with code $code"
echo "[HA Remote] Script ended."
exit $code
