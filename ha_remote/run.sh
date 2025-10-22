#!/bin/sh
# Read add-on options directly from the Supervisor JSON
CONFIG_PATH=/data/options.json

HA_REMOTE_SERVER=$(jq -r '.server' $CONFIG_PATH)
HA_REMOTE_HA_HOST=$(jq -r '.ha_host' $CONFIG_PATH)
HA_REMOTE_HA_PORT=$(jq -r '.ha_port' $CONFIG_PATH)

export HA_REMOTE_SERVER
export HA_REMOTE_HA_HOST
export HA_REMOTE_HA_PORT

exec python3 /ha_remote_relay.py
