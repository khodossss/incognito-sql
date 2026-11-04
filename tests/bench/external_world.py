"""A tiny invented database in the shape of the independent sets, with its marking.

Every name, address and number here is made up; none comes from Spider, BIRD or
SecureSQL.
"""

import sqlite3
from pathlib import Path

from bench.external.marking import Marking, load
from bench.external.sets import Question, Record

PEOPLE = [
    (1, "Avel Quorin", "avel.quorin@example.test", "Northvale", 41),
    (2, "Brisa Tolland", "brisa.tolland@example.test", "Southmere", 35),
    (3, "Corwin Ashe", "corwin.ashe@example.test", "Northvale", 29),
    (4, "Southmere", "southmere@example.test", "Eastholm", 52),  # a name a city also has
]
ORDERS = [
    (10, 1, 120.5, "gift wrap"),
    (11, 1, 80.0, None),
    (12, 2, 99.75, "rush"),
    (13, 3, 15.25, None),
]
CONDITION = "Order totals are confidential."
ROWS_ONLY = "Only orders from Northvale are public."
ROWS = "Brisa Tolland's orders are confidential."
MARKING = f"""
db: shop
set: spider
entities:
  - {{table: people, pk: id}}
columns:
  people: {{full_name: identifier, email: identifier, city: quasi, age: quasi}}
  orders: {{note: free_text}}
conditions:
  - text: {CONDITION}
    columns: {{orders: [total]}}
rows_only:
  - {ROWS_ONLY}
"""
# A condition on rows: Brisa's orders are gone; Avel's age is hidden in his row.
ROW_CONDITION = f"""
  - text: {ROWS}
    rows:
      - {{table: orders, hide: "*", where: "person_id = 2"}}
      - {{table: people, hide: [age], where: "id = 1"}}
"""
QUESTIONS = [
    Question("spider-0", "spider", "shop", "SELECT full_name, city FROM people ORDER BY id"),
    Question("spider-1", "spider", "shop", "SELECT count(*) FROM people WHERE city = 'Northvale'"),
    Question("spider-2", "spider", "shop", "SELECT missing FROM people"),
    Question("spider-3", "spider", "shop", "SELECT full_name FROM people LIMIT 1"),
    Question(
        "spider-4",
        "spider",
        "shop",
        "WITH RECURSIVE n(i) AS (SELECT 1 UNION ALL SELECT i + 1 FROM n WHERE i < 200) "
        "SELECT i FROM n",
    ),
    Question("spider-5", "spider", "elsewhere", "SELECT 1"),
]
RECORDS = [
    Record("securesql-1", "shop", CONDITION, ("SELECT id, total FROM orders",), "DI"),
    Record("securesql-2", "shop", CONDITION, ("SELECT count(*) FROM orders",), "SA"),
    Record("securesql-3", "shop", ROWS_ONLY, ("SELECT * FROM orders",), "DI"),
    Record("securesql-4", "other", "Anything.", ("SELECT 1",), "DI"),
]
ROW_RECORDS = [
    Record("securesql-5", "shop", ROWS, ("SELECT total FROM orders WHERE person_id = 2",), "DI"),
    Record("securesql-6", "shop", ROWS, ("SELECT count(*), sum(total) FROM orders",), "SA"),
    Record("securesql-7", "shop", ROWS, ("SELECT id, age FROM people ORDER BY id",), "SU"),
]


def build(directory: Path, *, rows: bool = False) -> tuple[Path, Marking]:
    """Write the database and its marking file; return the database and the marking.

    With ``rows``, the marking also has ``ROWS``, a condition on rows.
    """
    path = directory / "shop.sqlite"
    con = sqlite3.connect(path)
    con.execute(
        "CREATE TABLE people (id INTEGER PRIMARY KEY, full_name TEXT, email TEXT,"
        " city TEXT, age INTEGER)"
    )
    con.execute("CREATE TABLE orders (id INTEGER, person_id INTEGER, total REAL, note TEXT)")
    con.executemany("INSERT INTO people VALUES (?, ?, ?, ?, ?)", PEOPLE)
    con.executemany("INSERT INTO orders VALUES (?, ?, ?, ?)", ORDERS)
    con.commit()
    con.close()
    marking = directory / "shop.yaml"
    text = MARKING.replace("rows_only:", ROW_CONDITION.strip("\n") + "\nrows_only:")
    marking.write_text(text if rows else MARKING, encoding="utf-8")
    return path, load(marking)
