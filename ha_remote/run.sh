#!/bin/sh
set -e

echo "[INFO] Starting HA Remote Relay"

# Read config values directly from environment variables provided by HA
SERVER=$(bashio::config 'server' 2>/dev/null || echo "")
HA_HOST=$(bashio::config 'ha_host' 2>/dev/null || echo "")
HA_PORT=$(bashio::config 'ha_port' 2>/dev/null || echo "")

# Fallbacks if bashio isn't available (for Alpine-based image)
if [ -z "$SERVER" ]; then SERVER=${SERVER:-"ws://yourdomain/ha-cloud/ws/tunnel/test1"}; fi
if [ -z "$HA_HOST" ]; then HA_HOST=${HA_HOST:-"127.0.0.1"}; fi
if [ -z "$HA_PORT" ]; then HA_PORT=${HA_PORT:-"8123"}; fi

echo "[INFO] Using configuration:"
echo "       SERVER=$SERVER"
echo "       HA_HOST=$HA_HOST"
echo "       HA_PORT=$HA_PORT"

# Run the relay
python3 /data/ha_remote_relay.py "$SERVER" "$HA_HOST" "$HA_PORT"
