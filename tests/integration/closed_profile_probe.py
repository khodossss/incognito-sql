"""Inside the container: POST an MCP initialize to the service; print the HTTP status."""

import json
import sys
import urllib.error
import urllib.request

INIT = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "probe", "version": "0"},
    },
}

headers = {"content-type": "application/json", "accept": "application/json, text/event-stream"}
if sys.argv[1]:
    headers["authorization"] = f"Bearer {sys.argv[1]}"
request = urllib.request.Request(
    "http://127.0.0.1:8776/mcp", data=json.dumps(INIT).encode(), headers=headers
)
try:
    with urllib.request.urlopen(request, timeout=10) as response:  # noqa: S310
        sys.stdout.write(str(response.status))
except urllib.error.HTTPError as exc:
    sys.stdout.write(str(exc.code))
