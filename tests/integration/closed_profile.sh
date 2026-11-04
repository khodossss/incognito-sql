#!/bin/sh
# Closed profile on a real OS: the service runs as `incognito`, the agent as `agent`.
# MODE=open leaves the service's folder readable: the falsifier the closed run must differ from.
# Prints one `name=value` line per observation; the test reads them.
set -u
pip install -q --no-cache-dir "$(ls /dist/*.whl)[mcp]" >/dev/null 2>&1 || { echo "install=failed"; exit 1; }
useradd -m incognito && useradd -m agent
mkdir -p /srv/incognito && cp /fixture/* /srv/incognito/
chown -R incognito /srv/incognito
if [ "${MODE:-closed}" = "open" ]; then
  chmod 755 /srv/incognito && chmod 644 /srv/incognito/*
else
  chmod 700 /srv/incognito && chmod 600 /srv/incognito/*
fi
su incognito -s /bin/sh -c \
  "cd /srv/incognito && incognito-sql service --config shop.yaml --env-file secrets.env" \
  2>/tmp/service.err &
for _ in $(seq 1 50); do
  python -c "import socket; socket.create_connection(('127.0.0.1', 8776), 1)" 2>/dev/null && break
  sleep 0.2
done
as_agent() { su agent -s /bin/sh -c "$1" >/dev/null 2>&1; echo $?; }
echo "agent_is=$(su agent -s /bin/sh -c whoami)"
echo "agent_has_cli=$(as_agent 'command -v incognito-sql')"
echo "check=$(as_agent 'cd /tmp && incognito-sql check --config /srv/incognito/shop.yaml --env-file /srv/incognito/secrets.env --database /srv/incognito/shop.db')"
echo "read_secrets=$(as_agent 'cat /srv/incognito/secrets.env')"
echo "read_db=$(as_agent 'cat /srv/incognito/shop.db')"
echo "read_tokens=$(as_agent 'cat /srv/incognito/shop.tokens.db')"
echo "login=$(as_agent 'cd /tmp && incognito-sql login --config /srv/incognito/shop.yaml --env-file /srv/incognito/secrets.env --print')"
TOKEN=$(grep INCOGNITO_SQL_MCP_TOKEN /fixture/secrets.env | cut -d= -f2)
echo "mcp_without_token=$(su agent -s /bin/sh -c "python /fixture/probe.py ''")"
echo "mcp_with_token=$(su agent -s /bin/sh -c "python /fixture/probe.py '$TOKEN'")"
echo "login_as_service=$(su incognito -s /bin/sh -c 'cd /srv/incognito && incognito-sql login --config shop.yaml --env-file secrets.env --print' | grep -c '/login/')"
