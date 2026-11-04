"""Our marking files: classes, conditions, and the checked-in markings themselves."""

from pathlib import Path

import pytest
from external_world import CONDITION, build

from bench.external.marking import CLASSES, SHOWN, load, load_all


def test_unlisted_columns_are_open(tmp_path: Path) -> None:
    _, marking = build(tmp_path)
    assert marking.cls("People", "Full_Name") == "identifier"
    assert marking.cls("people", "id") == "open"
    assert marking.entities == (("people", "id"),)
    assert marking.condition is None


def test_a_condition_marks_its_columns_identifier(tmp_path: Path) -> None:
    _, marking = build(tmp_path)
    (condition,) = marking.conditions
    under = marking.under(condition)
    assert condition.text == CONDITION
    assert under.cls("orders", "total") == "identifier"
    assert marking.cls("orders", "total") == "open"
    assert under.condition is condition
    assert ("orders", "total") in marking.listed()


@pytest.mark.parametrize(
    "text",
    [
        "db: x\nset: elsewhere\n",
        "db: x\nset: spider\ncolumns: {t: {c: personal}}\n",
        "db: x\nset: spider\nunknown: 1\n",
        "db: x\nset: spider\ncolumns: {t: {c: identifier}}\nverified_open: {t: [c]}\n",
        "- not a mapping\n",
    ],
)
def test_a_bad_marking_is_refused(tmp_path: Path, text: str) -> None:
    path = tmp_path / "bad.yaml"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(ValueError, match=r"bad\.yaml"):
        load(path)


def test_a_database_marked_twice_is_refused(tmp_path: Path) -> None:
    for name in ("a", "b"):
        (tmp_path / f"{name}.yaml").write_text("db: same\nset: bird\n", encoding="utf-8")
    with pytest.raises(ValueError, match="twice"):
        load_all(tmp_path)


def test_the_checked_in_markings() -> None:
    markings = load_all()
    assert {m.source for m in markings} == {"spider", "bird"}
    for m in markings:
        classes = {k for cols in m.columns.values() for k in cols.values()}
        assert classes <= CLASSES
        assert "identifier" in classes, m.db  # every database taken holds people
        for condition in m.conditions:
            under = m.under(condition)
            assert all(under.cls(t, c) not in SHOWN for t, c in condition.columns)
        texts = [c.text for c in m.conditions] + list(m.rows_only)
        assert len(texts) == len(set(texts)), m.db
        assert all(c.columns or c.rows for c in m.conditions), m.db
