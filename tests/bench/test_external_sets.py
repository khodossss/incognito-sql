"""Reading the sets' question files, on invented samples in their formats."""

import json
from pathlib import Path

import pytest

from bench.external.sets import bird, read, securesql, spider


def test_spider_and_bird_questions() -> None:
    (s,) = spider([{"db_id": "shop", "query": "SELECT 1", "question": "?"}])
    assert (s.id, s.source, s.db, s.sql) == ("spider-0", "spider", "shop", "SELECT 1")
    (b,) = bird([{"question_id": 7, "db_id": "shop", "SQL": "SELECT 2", "evidence": ""}])
    assert (b.id, b.source, b.sql) == ("bird-7", "bird", "SELECT 2")


def test_securesql_samples() -> None:
    raw = [
        {
            "id": 1,
            "db_id": "shop",
            "security_condition": "c",
            "queries": ["q1", "q2"],
            "label": "DI",
        },
        {"id": 2, "db_id": "shop", "security_condition": "c", "queries": ["q3"], "label": "SU"},
    ]
    attack, safe = securesql(raw)
    assert attack.attack
    assert attack.queries == ("q1", "q2")
    assert not safe.attack
    assert safe.id == "securesql-2"


@pytest.mark.parametrize(
    "raw",
    [
        {"id": 1, "db_id": "shop", "security_condition": "c", "queries": ["q"], "label": "XX"},
        {"id": 1, "db_id": "shop", "security_condition": "c", "queries": "q", "label": "DI"},
    ],
)
def test_a_bad_sample_is_refused(raw: dict[str, object]) -> None:
    with pytest.raises(ValueError, match="bad sample"):
        securesql([raw])


def test_a_missing_field_is_refused() -> None:
    with pytest.raises(TypeError, match="query"):
        spider([{"db_id": "shop"}])


def test_read_wants_a_list_of_objects(tmp_path: Path) -> None:
    good, bad = tmp_path / "good.json", tmp_path / "bad.json"
    good.write_text(json.dumps([{"a": 1}]), encoding="utf-8")
    bad.write_text(json.dumps({"a": 1}), encoding="utf-8")
    assert read(good) == [{"a": 1}]
    with pytest.raises(ValueError, match=r"bad\.json"):
        read(bad)
