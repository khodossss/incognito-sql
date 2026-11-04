"""`incognito-sql project`: the project server over stdio, as a client plugin starts it."""

import os
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import uuid4

from incognito_sql.connect.release import release
from incognito_sql.core.tokens.crypto import load_key
from incognito_sql.project import dsn
from incognito_sql.project.live import Live
from incognito_sql.project.place import Place
from incognito_sql.project.tools import Tools

if TYPE_CHECKING:
    import argparse


def add_project_parser(commands: "argparse._SubParsersAction[argparse.ArgumentParser]") -> None:
    """Register the `project` subcommand."""
    commands.add_parser(
        "project",
        help="run the project server over stdio: setup tools, query and describe (for plugins)",
    )


def run_project() -> int:
    """Serve the project the client names, until the client closes stdin."""
    place = Place.of(os.environ, Path.cwd())
    live = Live(place, lambda name, env: dsn.find(name, env, os.environ, dsn.user_value), load_key)
    # The MCP SDK is the optional extra `[mcp]`: only the servers need it.
    from incognito_sql.mcp.project import build_server  # noqa: PLC0415

    try:
        build_server(Tools(place, live, release()), uuid4().hex).run("stdio")
    finally:
        live.close()
    return 0
