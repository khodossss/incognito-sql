"""The `demo` command: an invented SQLite shop and its declaration, ready to connect.

Every row is invented; nothing comes from a live system.
"""

import sqlite3
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from incognito_sql import shell

if TYPE_CHECKING:
    import argparse

EXIT_FAILED = 1
DSN_ENV = "DEMO_SHOP_DSN"
_SCHEMA = """
CREATE TABLE customers (id INTEGER PRIMARY KEY, full_name TEXT, email TEXT, city TEXT);
CREATE TABLE orders (id INTEGER PRIMARY KEY, customer_id INTEGER, total REAL);
INSERT INTO customers VALUES
  (1, 'Mira Quellbrandt', 'mira.quellbrandt@example.test', 'Tellport'),
  (2, 'Oskar Vennholm', 'oskar.vennholm@example.test', 'Brindle'),
  (3, 'Ilse Marrowind', 'ilse.marrowind@example.test', 'Tellport'),
  (4, 'Tobin Arcwright', 'tobin.arcwright@example.test', 'Fenmouth');
INSERT INTO orders VALUES
  (10, 1, 240.0), (11, 1, 80.5), (12, 2, 310.0), (13, 3, 45.0), (14, 4, 120.0), (15, 4, 9.9);
"""
_DECLARATION = f"""# The demo shop: names and e-mails reach the model as tokens, cities as they are.
dsn_env: {DSN_ENV}
dialect: sqlite
columns:
  customers:
    id: open
    full_name: identifier
    email: identifier
    city: quasi
  orders:
    id: open
    customer_id: open
    total: open
entities:
  - table: customers
    pk: id
"""


def add_demo_parser(commands: "argparse._SubParsersAction[argparse.ArgumentParser]") -> None:
    """Register the `demo` subcommand."""
    demo = commands.add_parser("demo", help="write an invented SQLite shop and its declaration")
    demo.add_argument("folder", type=Path, help="folder for shop.db and shop.yaml")


def run_demo(folder: Path) -> int:
    """Write ``folder``/shop.db and shop.yaml; print the next steps."""
    database, config = folder / "shop.db", folder / "shop.yaml"
    taken = [p for p in (database, config) if p.exists()]
    if taken:
        sys.stderr.write(f"incognito-sql: the folder has {taken[0].name}; pick an empty one\n")
        return EXIT_FAILED
    try:
        folder.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(database) as con:
            con.executescript(_SCHEMA)
        con.close()
        config.write_text(_DECLARATION, encoding="utf-8")
    except (OSError, sqlite3.Error) as exc:  # their text repeats the path
        sys.stderr.write(f"incognito-sql: cannot write the demo folder: {type(exc).__name__}\n")
        return EXIT_FAILED
    dsn = f"sqlite:///{database.resolve().as_posix()}"
    sys.stdout.write(
        f"Wrote {database} (invented customers and orders) and its declaration {config}.\n"
        "Next: set the DSN where your MCP client starts, then print the client's entry:\n"
        f"{_setting(dsn)}"
        f"  incognito-sql connect claude-code --config {shell.quote(str(config.resolve()))}\n"
        "Then ask your agent who spent the most: names come back as links, not values.\n"
    )
    return 0


def _setting(dsn: str) -> str:
    """Return the lines that set the DSN's variable in the operator's shell."""
    if not shell.WINDOWS:
        return f"  export {DSN_ENV}={shell.quote(dsn)}\n"
    value = shell.powershell(dsn)
    return (
        f"  $env:{DSN_ENV} = {value}\n"
        "  # only this window sees it; for a client started from the Start menu, set it for\n"
        "  # your user and restart the client:\n"
        f"  [Environment]::SetEnvironmentVariable('{DSN_ENV}', {value}, 'User')\n"
    )
