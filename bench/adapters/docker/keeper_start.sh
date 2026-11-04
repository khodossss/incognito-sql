#!/bin/sh
# keeper beside the bench Postgres: its README's "Set up a connection" (connection add with
# the read DSN and our catalog), then its MCP server on this process's stdio.
# Keys and paths as keeper's own end-to-end test sets them (KEEPER_MASTER_KEY, KEEPER_HOME,
# KEEPER_SOCKET, no UI port). Setup output goes to stderr; the connection id, which every
# query names, is written to /work/connection_id for the bench client.
set -e
export KEEPER_HOME=/tmp/keeper/home KEEPER_SOCKET=/tmp/keeper/keeper.sock KEEPER_UI_PORT=0
mkdir -p /tmp/keeper
cp /config/keeper/catalog.yaml /tmp/keeper/catalog.yaml
keeper connection add --name world --dsn "$KEEPER_DSN" --catalog /tmp/keeper/catalog.yaml \
  --json </dev/null >/tmp/keeper/connection.json
sed -n 's/.*"id": *"\([^"]*\)".*/\1/p' /tmp/keeper/connection.json | head -n 1 >/work/connection_id
exec keeper mcp
