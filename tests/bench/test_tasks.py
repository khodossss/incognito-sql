"""Utility tasks: every hand-labelled answer holds on the seeded world; the comparison."""

from collections.abc import Iterator
from pathlib import Path

import pytest

from bench.adapters.raw import RawAdapter
from bench.dbms import Database
from bench.tasks import Task, correct, load_tasks, normal

TASKS = load_tasks()


@pytest.fixture(scope="module")
def raw(world_db: Path) -> Iterator[RawAdapter]:
    adapter = RawAdapter(Database("sqlite", f"sqlite:///{world_db.as_posix()}", path=world_db))
    yield adapter
    adapter.close()


@pytest.mark.parametrize("task", [pytest.param(t, id=t.name) for t in TASKS])
def test_label_matches_the_seeded_world(task: Task, raw: RawAdapter) -> None:
    out = raw.query(task.sql)
    assert correct(task, out.rows), out.text


def test_there_are_twenty_to_forty_tasks_with_identifier_columns_among_them() -> None:
    assert 20 <= len(TASKS) <= 40
    assert any(t.opaque for t in TASKS)


def test_numbers_compare_by_value() -> None:
    task = Task("t", "", ((12, 9206.91),))
    assert correct(task, [["12", 9206.910000001]])
    assert not correct(task, [[12, 9206.92]])
    assert normal("Zq0t9u8v8u1p") == "Zq0t9u8v8u1p"
    assert normal(None) is None


def test_order_counts_where_the_question_asks_for_it() -> None:
    rows = ((2, 9.5), (1, 3.0))
    ordered = Task("t", "SELECT id, x FROM t ORDER BY x DESC", rows, ordered=True)
    assert correct(ordered, [[2, 9.5], [1, 3]])
    assert not correct(ordered, [[1, 3], [2, 9.5]])
    assert correct(Task("t", "SELECT id, x FROM t", rows), [[1, 3], [2, 9.5]])
    [task] = [t for t in TASKS if t.name == "purchases over 500, largest first"]
    assert task.ordered
    assert not any(t.ordered for t in TASKS if "ORDER BY" not in t.sql.upper())


def test_opaque_column_needs_a_bijection_with_the_reference() -> None:
    task = Task("t", "", ((1, "u1"), (2, "u2"), (3, "u1")), (1,))
    assert correct(task, [[2, "tk_b"], [1, "tk_a"], [3, "tk_a"]])
    assert not correct(task, [[1, "[REDACTED]"], [2, "[REDACTED]"], [3, "[REDACTED]"]])
    assert not correct(task, [[1, "tk_a"], [2, "tk_b"], [3, "tk_c"]])  # one person, two names
    assert not correct(task, [[1, None], [2, "x"], [3, None]])
    assert not correct(task, [[1, "a", "extra"], [2, "b", "extra"], [3, "a", "extra"]])
    assert not correct(task, [[1, "a"], [2, "b"], [4, "a"]])
    assert not correct(task, None)


def test_a_constant_placeholder_never_answers_an_identifier_task() -> None:
    for task in (t for t in TASKS if t.opaque):
        rows = [[*row] for row in task.expect]
        for row in rows:
            for column in task.opaque:
                row[column] = "[REDACTED]"
        assert not correct(task, rows), task.name


def test_every_identifier_task_has_two_people_and_a_key(tmp_path: Path) -> None:
    for task in (t for t in TASKS if t.opaque):
        for column in task.opaque:
            assert len({row[column] for row in task.expect}) >= 2, task.name
    one = "- {name: x, sql: s, expect: [[1, a], [2, a]], opaque: [1]}\n"
    (tmp_path / "a.yaml").write_text(one, encoding="utf-8")
    with pytest.raises(ValueError, match="two distinct"):
        load_tasks(tmp_path)
    keyless = "- {name: x, sql: s, expect: [[1, a], [1, b]], opaque: [1]}\n"
    (tmp_path / "a.yaml").write_text(keyless, encoding="utf-8")
    with pytest.raises(ValueError, match="key"):
        load_tasks(tmp_path)


def test_bad_task_files_are_refused(tmp_path: Path) -> None:
    (tmp_path / "a.yaml").write_text("- {name: x, sql: 1, expect: [[1]]}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="bad task"):
        load_tasks(tmp_path)
    (tmp_path / "a.yaml").write_text(
        "- {name: x, sql: s, expect: [[1]]}\n- {name: x, sql: s, expect: [[1]]}\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="duplicate"):
        load_tasks(tmp_path)
