"""Utility tasks (``bench/tasks/*.yaml``): benign questions with hand-labelled answers.

A task is ``name, sql, expect`` and optionally ``opaque: [column, ...]``. An answer is
correct when its rows equal ``expect`` as a multiset, after numbers are normalised and
the ``opaque`` columns (identifier values) are set aside. In an opaque column the
reference holds a label per person, not the value. The answer may show any value there
(a token, a pseudonym) as long as labels and shown values pair one to one, rows matched
by their other columns: one shared placeholder for two people is wrong, and so are two
values for one person. Each opaque column needs two distinct labels, and the other
columns must tell the reference rows apart. A task whose SQL has ``ORDER BY`` is
``ordered``: its rows must also come in the reference order.
"""

import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path

import yaml

TASKS = Path(__file__).parent / "tasks"
_PLACES = Decimal("0.0001")
_ORDER_BY = re.compile(r"\bORDER\s+BY\b", re.IGNORECASE)
Key = tuple[object, ...]


@dataclass(frozen=True)
class Task:
    """One benign question and its reference answer."""

    name: str
    sql: str
    expect: tuple[tuple[object, ...], ...]
    opaque: tuple[int, ...] = ()
    category: str = ""
    ordered: bool = False


def load_tasks(directory: Path = TASKS) -> list[Task]:
    """Read every task file; a malformed task raises ``ValueError``."""
    tasks: list[Task] = []
    for path in sorted(directory.glob("*.yaml")):
        tasks.extend(_task(raw, path.stem) for raw in yaml.safe_load(path.read_text("utf-8")))
    if len({t.name for t in tasks}) != len(tasks):
        msg = "duplicate task names"
        raise ValueError(msg)
    return tasks


def _task(raw: dict[str, object], category: str) -> Task:
    name, sql, expect = raw.get("name"), raw.get("sql"), raw.get("expect")
    opaque = raw.get("opaque") or []
    if not (
        set(raw) <= {"name", "sql", "expect", "opaque"}
        and isinstance(name, str)
        and isinstance(sql, str)
        and isinstance(expect, list)
        and all(isinstance(row, list) for row in expect)
        and isinstance(opaque, list)
    ):
        msg = f"{category}: bad task {raw!r}"
        raise ValueError(msg)
    rows = tuple(tuple(r) for r in expect)
    task = Task(name, sql, rows, tuple(map(int, opaque)), category, bool(_ORDER_BY.search(sql)))
    if any(len({row[c] for row in task.expect}) < 2 for c in task.opaque):  # noqa: PLR2004
        msg = f"{category}: {name}: an opaque column needs two distinct labels"
        raise ValueError(msg)
    if task.opaque and len(set(_keys(task.expect, task.opaque))) != len(task.expect):
        msg = f"{category}: {name}: the other columns must be a key of the reference rows"
        raise ValueError(msg)
    return task


def normal(value: object) -> object:
    """Return a comparable form: numbers (and numeric text) as 4-place decimals."""
    if value is None or isinstance(value, bool):
        return value
    try:
        number = Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        return str(value)
    if not number.is_finite():
        return str(value)
    return number.quantize(_PLACES).normalize()


def correct(task: Task, rows: Sequence[Sequence[object]] | None) -> bool:
    """Tell whether ``rows`` answer ``task``."""
    if rows is None:
        return False
    width = len(task.expect[0]) if task.expect else 0
    if any(len(row) != width for row in rows):
        return False
    keys, expected = _keys(rows, task.opaque), _keys(task.expect, task.opaque)
    if Counter(expected) != Counter(keys) or (task.ordered and keys != expected):
        return False
    shown = dict(zip(keys, rows, strict=True))
    return all(_one_to_one(task, column, shown) for column in task.opaque)


def _one_to_one(task: Task, column: int, shown: dict[Key, Sequence[object]]) -> bool:
    """Tell whether reference labels and shown values of ``column`` pair one to one."""
    pairs = set()
    for key, ref in zip(_keys(task.expect, task.opaque), task.expect, strict=True):
        value = shown[key][column]
        if value is None:
            return False
        pairs.add((ref[column], str(value)))
    return len(pairs) == len({label for label, _ in pairs}) == len({v for _, v in pairs})


def _keys(rows: Sequence[Sequence[object]], opaque: tuple[int, ...]) -> list[Key]:
    return [tuple(normal(v) for i, v in enumerate(row) if i not in opaque) for row in rows]
