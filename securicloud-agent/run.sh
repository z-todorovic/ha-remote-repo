#!/bin/sh
CONFIG_PATH=/data/options.json

echo "[Securicloud Agent] Starting container..."
echo "Checking /data/options.json:"
cat $CONFIG_PATH || echo "No options.json found!"
echo

SECURICLOUD_AGENT_DEBUG=$(jq -r '.debug' $CONFIG_PATH)

export SECURICLOUD_AGENT_DEBUG

echo "[Securicloud Agent] Launching Python..."
exec python3 -u securicloud_agent.py
code=$?
echo "[Securicloud Agent] Python exited with code $code"
echo "[Securicloud Agent] Script ended."
exit $code
