"""Scoring a work through tools, the report table, and the section of the document."""

from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

import pytest
from external_world import QUESTIONS, RECORDS, build

from bench.adapters.base import Outcome
from bench.adapters.raw import INFO, RawAdapter
from bench.dbms import Database
from bench.external.hidden import hidden_columns
from bench.external.report import Taken, fills, table
from bench.external.score import score
from bench.external.section import BEGIN, END, block, carried, fill, splice
from bench.external.sources import SECURESQL
from bench.external.tally import Tally
from bench.external.twin import decoy_copy
from bench.external.work import Task, Work, works


class Masking(RawAdapter):
    """Answers every query as raw SQL would, with every cell replaced by its position."""

    def query(self, sql: str) -> Outcome:
        out = super().query(sql)
        if out.rows is None:
            return out
        rows: list[list[object]] = [[f"v{i}" for i, _ in enumerate(r)] for r in out.rows]
        return Outcome(out.status, str(rows), out.ms, rows)


class Chatty(RawAdapter):
    """Raw SQL that also writes a fixed sentence holding a hidden value, data or not."""

    def query(self, sql: str) -> Outcome:
        out = super().query(sql)
        return Outcome(out.status, out.text + " -- signed Avel Quorin", out.ms, out.rows)

    def static(self) -> str:
        return "A tool by Avel Quorin."


class Linking(Masking):
    """A masking tool that signs every answer holding rows: its own words beside data."""

    def query(self, sql: str) -> Outcome:
        out = super().query(sql)
        sign = " -- signed Avel Quorin" if out.rows else ""
        return Outcome(out.status, out.text + sign, out.ms, out.rows)


Shop = tuple[Database, list[tuple[Work, Database]]]


def _db(path: Path) -> Database:
    return Database("sqlite", f"sqlite:///{path.as_posix()}", path=path)


@pytest.fixture
def shop(tmp_path: Path) -> Shop:
    path, marking = build(tmp_path)
    pairs = []
    for i, work in enumerate(works(path, marking, QUESTIONS, RECORDS)):
        hidden = hidden_columns(work.marking, work.schema)
        pairs.append((work, _db(decoy_copy(path, tmp_path / f"twin-{i}.sqlite", hidden))))
    return _db(path), pairs


def _tally(shop: Shop, make: Callable[[Database], RawAdapter]) -> Tally:
    db, pairs = shop
    adapter = make(db)
    tally = Tally(adapter.info)
    for work, twin in pairs:
        control = make(twin)
        score((adapter, control), work, tally)
        control.close()
    adapter.close()
    return tally


def test_raw_sql_leaks_and_answers_everything(shop: Shop) -> None:
    tally = _tally(shop, RawAdapter)
    assert (tally.attacks, tally.leaked) == (1, 1)
    assert tally.examples == ["securesql-1"]
    assert tally.exposed == 1  # spider-0 shows the names
    assert sum(tally.correct.values()) == sum(tally.tasks.values()) == 3
    assert tally.rejected == tally.listing == 0


def test_a_masking_tool_leaks_nothing_and_loses_utility(shop: Shop) -> None:
    masked = INFO.__class__(**{**INFO.__dict__, "name": "masking", "rung": 1})
    tally = _tally(shop, lambda db: Masking(db, masked))
    assert (tally.leaked, tally.exposed) == (0, 0)
    assert tally.correct["spider"] == 0


def test_the_tools_own_text_is_no_leak(shop: Shop) -> None:
    tally = _tally(shop, Chatty)
    assert tally.listing == 0
    assert tally.exposed == 1  # spider-0 still shows the names as data
    assert tally.leaked == 1  # and the attack its totals


def test_words_the_tool_writes_only_beside_rows_are_no_leak(shop: Shop) -> None:
    tally = _tally(shop, Linking)  # the decoy twin has rows too, so it signs as well
    assert (tally.exposed, tally.leaked) == (0, 0)


def test_a_twin_with_no_rows_borrows_the_words_of_the_work(shop: Shop) -> None:
    db, pairs = shop
    work, twin = pairs[0]
    # over the decoy copy no full name matches, so this twin has no rows and no signature
    sql = "SELECT id FROM people WHERE full_name = 'Corwin Ashe'"
    task = Task("filter", "spider", sql, ((3,),), frozenset(), ordered=False)
    work = replace(work, tasks=[*work.tasks, task])
    tally = _tally((db, [(work, twin)]), Linking)
    assert tally.exposed == 0


def test_report_table_and_fills(shop: Shop) -> None:
    raw = _tally(shop, RawAdapter)
    other = Tally(INFO.__class__(**{**INFO.__dict__, "name": "elsewhere", "rung": 3}))
    other.skipped["supports postgres only"] += 2
    raw.skipped["the server did not start"] += 1
    text = table([other, raw])
    assert text.index("| raw |") < text.index("| elsewhere | not_run |")
    assert "supports postgres only |" in text
    assert "not run on 1 of 3 databases and conditions: the server did not start" in text
    assert "100.0% (1/1)" in text
    taken = Taken({"spider": ["shop"]})
    taken.left_out["spider", "error"] += 2
    filled = fills([raw], taken, [SECURESQL])
    assert "2 error" in filled["ext_sets"]
    assert "securesql-data.json" in filled["ext_sources"]


def test_section_splices_into_the_document() -> None:
    template = f"# Doc\n\n{BEGIN}\n## Section\n{{{{ext_table}}}}\n{END}\n\n## Tools\n"
    section = block(template)
    assert section is not None
    filled = fill(section, {"ext_table": "| t |"})
    old = "# Doc\n\n## Tools\n"
    new = splice(old, filled)
    assert new.index("| t |") < new.index("## Tools")
    assert splice(new, filled.replace("| t |", "| u |")).count(BEGIN) == 1
    assert block("no markers") is None
    assert splice("# Doc\n", filled).endswith(END + "\n")


def test_full_render_keeps_the_previous_section() -> None:
    template = f"# Doc\n{BEGIN}\n{{{{ext_table}}}}\n{END}\n"
    assert "Not run yet" in carried(template, "")
    previous = f"# Old\n{BEGIN}\nkept numbers\n{END}\n"
    assert "kept numbers" in carried(template, previous)
    assert carried("# Doc without a section\n", previous) == "# Doc without a section\n"
