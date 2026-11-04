"""The corpus loader rejects malformed cases and expands templates; the judge sees every failure."""

from pathlib import Path

import pytest

from bench.cases import Case, load_cases
from bench.judge import Outcome, judge
from bench.templates import expand, spelling_fills, token_fills

OWN = "tk_abcdefghijk23456"


def _write(tmp_path: Path, body: str) -> Path:
    (tmp_path / "x.yaml").write_text(body, encoding="utf-8")
    return tmp_path


@pytest.mark.parametrize(
    "body",
    [
        "- {name: a, sql: s, expect: reject, source: ours}",  # reject without reason
        "- {name: a, sql: s, expect: safe, reason: parse_error, source: ours}",
        "- {name: a, sql: s, expect: maybe, source: ours}",
        "- {name: a, sql: s, expect: safe, source: elsewhere}",
        "- {name: a, sql: s, expect: safe, source: ours, mode: stdout}",
        "- {name: a, sql: s, expect: safe, source: ours, dialects: [oracle]}",
        "- {name: a, sql: s, expect: safe, source: ours, code: X}",
        "- {name: a, sql: s, expect: safe, source: ours, setup: [x]}",
        "- {name: a, expect: safe, source: ours}",
        "- {name: a, sql: s, expect: refuse, reason: parse_error, source: ours}",
        "- {name: a, sql: s, expect: answer, order_sensitive: true, source: ours}",  # no pool
        "- {name: a, sql: s, expect: answer, pool: p, source: ours}",  # pool, not marked
        "- {name: a, sql: s, expect: safe, order_sensitive: true, pool: p, source: ours}",
        "- just text",
        (  # one name twice
            "- {name: a, sql: s, expect: safe, source: ours}\n"
            "- {name: a, sql: t, expect: safe, source: ours}"
        ),
    ],
)
def test_malformed_case_is_refused(tmp_path: Path, body: str) -> None:
    with pytest.raises(ValueError, match="case"):
        load_cases(_write(tmp_path, body))


def test_spellings_share_one_value() -> None:
    assert spelling_fills("Ab C", 3) == {"SPELLINGS_OWN": "'ab c', 'ab C', 'aB c'"}
    assert spelling_fills("O'Ab", 1) == {"SPELLINGS_OWN": "'o''ab'"}


def test_case_scope(tmp_path: Path) -> None:
    body = "- {name: a, sql: s, expect: safe, source: ours, mode: web, dialects: [tsql]}"
    [case] = load_cases(_write(tmp_path, body))
    assert case.id == "x::a"
    assert case.runs_in("web", "tsql")
    assert not case.runs_in("labels", "tsql")
    assert not case.runs_in("web", "sqlite")


@pytest.mark.parametrize(
    ("sql", "expanded"),
    [
        ("{{TOKEN_OWN}}", OWN),
        ("{{TOKEN_BODY}}", OWN[3:]),
        ("{{TOKEN_TRUNCATED}}", OWN[:-8]),
        ("a{{PAD:3}}b", "a   b"),
        ("{{PAD_CHAR:x:4}}", "xxxx"),
        ("{{REPEAT:id, :2}}", "id, id, "),
        ("{{IN_LIST:3}}", "0, 1, 2"),
        ("{{NEST:2}}", "((1))"),
        ("{{JOINS:1}}", " JOIN purchases p0 ON p0.id = u.id"),
    ],
)
def test_templates(sql: str, expanded: str) -> None:
    assert expand(sql, token_fills(OWN)) == expanded


def test_derived_tokens_are_well_formed_and_foreign() -> None:
    fills = token_fills(OWN)
    for name in ("TOKEN_OTHER", "TOKEN_OTHER_KEY_SAME_ALIAS", "TOKEN_FLIPPED"):
        assert fills[name] != OWN
        assert len(fills[name]) == len(OWN)
        assert fills[name].startswith("tk_")
    same = "tk_aaaaaaaaaaaaaaaa"
    assert token_fills(same)["TOKEN_FLIPPED"] != same


def test_order_sensitive_case_carries_its_pool(tmp_path: Path) -> None:
    body = "- {name: a, sql: s, expect: answer, order_sensitive: true, pool: p, source: ours}"
    [case] = load_cases(_write(tmp_path, body))
    assert case.order_sensitive
    assert case.pool == "p"


def _case(expect: str, reason: str | None = None) -> Case:
    return Case("a", "s", expect, reason, frozenset({"sqlite"}), "both", "ours", "x")


CANARY = "Zq8g1h9k0m8p"


def test_judge_reports_leak_and_missing_refusal() -> None:
    case = _case("reject", "hidden_column")
    problems = judge(case, Outcome({"rows": []}, {"answer": CANARY}), [CANARY])
    assert problems == [
        f"leak in answer: ['{CANARY}']",
        "expected refusal hidden_column, got an answer",
    ]
    assert judge(case, Outcome({"error": "hidden_column"}, {"answer": ""}), [CANARY]) == []


@pytest.mark.parametrize("expect", ["safe", "refuse", "answer", "reject"])
def test_internal_error_never_passes(expect: str) -> None:
    case = _case(expect, "internal_error" if expect == "reject" else None)
    problems = judge(case, Outcome({"error": "internal_error"}, {}), [])
    assert "internal_error" in problems


@pytest.mark.parametrize(
    ("expect", "answer", "problem"),
    [
        ("refuse", {"rows": []}, "expected a refusal, got an answer"),
        ("answer", {"error": "db_error"}, "expected an answer, got db_error"),
    ],
)
def test_refuse_and_answer_expectations(
    expect: str, answer: dict[str, object], problem: str
) -> None:
    assert judge(_case(expect), Outcome(answer, {}), []) == [problem]


@pytest.mark.parametrize(
    ("answer", "expect"),
    [({"error": "node_not_allowed"}, "refuse"), ({"error": "db_error"}, "refuse"), ({}, "answer")],
)
def test_expectation_met(answer: dict[str, object], expect: str) -> None:
    assert judge(_case(expect), Outcome(answer, {}), []) == []


def test_warning_and_audit_count_fail() -> None:
    outcome = Outcome({"rows": []}, {}, audit_lines=0, warnings=["UserWarning: x"])
    assert judge(_case("safe"), outcome, []) == [
        "warnings: ['UserWarning: x']",
        "0 audit lines, expected 1",
    ]


def test_a_label_that_gives_a_hidden_key_fails() -> None:
    hidden = {"patients": frozenset({3, 4})}
    labels = {"patient_name_1": {"patients": [1, 3]}, "patient_name_2": {"users": [4]}}
    outcome = Outcome({"rows": [], "labels": labels}, {})
    assert judge(_case("answer"), outcome, [], hidden_keys=hidden) == [
        "label gives a hidden key: patients:3"
    ]
    clean = Outcome({"rows": [], "labels": {"patient_name_1": {"patients": [1]}}}, {})
    assert judge(_case("answer"), clean, [], hidden_keys=hidden) == []
    assert judge(_case("answer"), outcome, []) == []  # no keys named: nothing to judge
