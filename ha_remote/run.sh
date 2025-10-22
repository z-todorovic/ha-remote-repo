#!/bin/sh
export HA_REMOTE_SERVER=$(bashio::config 'server')
export HA_REMOTE_HA_HOST=$(bashio::config 'ha_host')
export HA_REMOTE_HA_PORT=$(bashio::config 'ha_port')
exec python3 /ha_remote_relay.py
