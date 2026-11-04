"""A stand-in competitor for the stdio adapter test: one SQL tool, a line on stderr.

``echo(sql)`` answers ``{"rows": [[sql]]}``; SQL starting with ``bad`` is a tool error,
SQL starting with ``slow`` hangs for a while.
Every call writes the SQL to stderr, the way a tool's log would.
"""

import json
import sys
import time

from mcp.server.mcpserver import MCPServer

server: MCPServer = MCPServer(name="stand-in", log_level="ERROR")


def echo(sql: str) -> str:
    """Answer with the SQL as the only cell."""
    sys.stderr.write(f"log: {sql}\n")
    sys.stderr.flush()
    if sql.startswith("slow"):
        time.sleep(10)
    if sql.startswith("bad"):
        msg = "rejected"
        raise ValueError(msg)
    return json.dumps({"rows": [[sql]]})


server.add_tool(echo, name="echo", description="Echo SQL.", structured_output=False)

if __name__ == "__main__":
    server.run("stdio")
