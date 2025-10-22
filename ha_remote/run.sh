#!/bin/sh
CONFIG_PATH=/data/options.json

echo "[HA Remote] Starting container..."
echo "Checking /data/options.json:"
cat $CONFIG_PATH || echo "No options.json found!"

HA_REMOTE_SERVER=$(jq -r '.server' $CONFIG_PATH)
HA_REMOTE_HA_HOST=$(jq -r '.ha_host' $CONFIG_PATH)
HA_REMOTE_HA_PORT=$(jq -r '.ha_port' $CONFIG_PATH | tr -cd '0-9')

# *** THIS PART WAS MISSING ***
export HA_REMOTE_SERVER
export HA_REMOTE_HA_HOST
export HA_REMOTE_HA_PORT
# *****************************

echo "SERVER=$HA_REMOTE_SERVER"
echo "HA_HOST=$HA_REMOTE_HA_HOST"
echo "HA_PORT=$HA_REMOTE_HA_PORT"

echo "[HA Remote] Launching Python..."
python3 -u /ha_remote_relay.py || echo "Python exited with code $?"

echo "[HA Remote] Script ended."
sleep 999999
