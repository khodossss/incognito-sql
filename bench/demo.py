"""Write a demo SQLite database of invented people and its declaration.

Run from a checkout: ``uv run python -m bench.demo <directory>``. The directory gets
``demo.db`` and ``demo.yaml`` (the benchmark world: users, purchases, ledger, tickets and
two tables the declaration leaves hidden). Every value is generated; none is real.
"""

import sqlite3
import sys
from contextlib import closing
from pathlib import Path

from bench.world import generate_world

SEED = 15


def main(argv: list[str]) -> int:
    """Create ``demo.db`` and ``demo.yaml`` in the directory given."""
    out = Path(argv[0] if argv else "demo").resolve()
    out.mkdir(parents=True, exist_ok=True)
    world, db = generate_world(SEED), out / "demo.db"
    db.unlink(missing_ok=True)
    with closing(sqlite3.connect(db)) as conn, conn:
        for statement in world.statements("sqlite"):
            conn.execute(statement)
    config = world.declaration("sqlite", web=True).replace("BENCH_DSN", "DEMO_DSN")
    (out / "demo.yaml").write_text(config, encoding="utf-8")
    sys.stdout.write(f"DEMO_DSN=sqlite:///{db.as_posix()}\nconfig: {out / 'demo.yaml'}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
