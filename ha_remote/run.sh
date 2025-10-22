#!/bin/sh
set -x          # enable shell debug output
CONFIG_PATH=/data/options.json

echo "[HA Remote] Starting container..."
echo "Checking /data/options.json:"
cat $CONFIG_PATH || echo "No options.json found!"

# Read options
if command -v jq >/dev/null 2>&1; then
    HA_REMOTE_SERVER=$(jq -r '.server' $CONFIG_PATH)
    HA_REMOTE_HA_HOST=$(jq -r '.ha_host' $CONFIG_PATH)
    HA_REMOTE_HA_PORT=$(jq -r '.ha_port' $CONFIG_PATH)
else
    echo "jq missing!"
    HA_REMOTE_SERVER=""
    HA_REMOTE_HA_HOST=""
    HA_REMOTE_HA_PORT=""
fi

echo "SERVER=$HA_REMOTE_SERVER"
echo "HA_HOST=$HA_REMOTE_HA_HOST"
echo "HA_PORT=$HA_REMOTE_HA_PORT"
echo "Listing / :"
ls -l /
echo "Listing /data :"
ls -l /data

# Try to run Python
echo "[HA Remote] Launching Python..."
python3 /ha_remote_relay.py || echo "Python exited with code $?"

echo "[HA Remote] Script ended."
sleep 999999
