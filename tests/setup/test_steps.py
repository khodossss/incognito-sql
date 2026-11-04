"""The setup's steps as data: who may do what, and that every command parses."""

import pytest

from incognito_sql.cli import _parser
from incognito_sql.setup.cases import CASES
from incognito_sql.setup.model import Answers, Case, Step, Who, render

STEPS = [(c.name, s) for c in CASES for s in c.steps]
IDS = [f"{name}.{step.id}" for name, step in STEPS]
ANSWERS: Answers = {
    "client": "opencode",
    "dialect": "postgres",
    "folder": "proj",
    "name": "shop",
    "var": "SHOP_DSN",
    "file": "shop.db",
    "host": "db:5432/shop",
    "user": "reader",
    "port": "8766",
    "config": "proj/shop.yaml",
    "protection": "balanced",
}


def _secret(step: Step) -> bool:
    return step.run is not None and step.run[0] == "secret"


@pytest.mark.parametrize(("case", "step"), STEPS, ids=IDS)
def test_a_secret_is_never_the_agent_s(case: str, step: Step) -> None:
    assert not (step.who is Who.AGENT and _secret(step)), case


@pytest.mark.parametrize(("case", "step"), STEPS, ids=IDS)
def test_what_the_agent_asks_names_no_secret(case: str, step: Step) -> None:
    if step.who is Who.AGENT and step.ask is not None:
        words = step.ask.text.lower()
        assert not any(w in words for w in ("password", "token", "key", "secret")), case


@pytest.mark.parametrize(("case", "step"), STEPS, ids=IDS)
def test_a_condition_is_said_in_words(case: str, step: Step) -> None:
    assert (step.when is None) == (not step.only), case


@pytest.mark.parametrize("case", CASES, ids=[c.name for c in CASES])
def test_step_ids_are_unique_in_a_case(case: Case) -> None:
    ids = [s.id for s in case.steps]
    assert len(ids) == len(set(ids))


@pytest.mark.parametrize(("case", "step"), STEPS, ids=IDS)
def test_every_command_parses(case: str, step: Step) -> None:
    answers = ANSWERS if step.applies(ANSWERS) else {**ANSWERS, "dialect": "sqlite"}
    assert step.applies(answers) or step.id.endswith("claude"), case
    argv = render(step, answers)
    if argv is not None:
        assert "<" not in " ".join(argv), (case, argv)  # every slot answered
        _parser().parse_args(argv)


def test_a_slot_left_unanswered_shows_its_name() -> None:
    step = next(s for _, s in STEPS if s.id == "init")
    assert render(step, {}) == [
        "init", "--dsn-env", "<var>", "--dialect", "<dialect>", "--out", "<config>"
    ]  # fmt: skip
    assert render(step, ANSWERS)[-1] == "proj/shop.yaml"  # type: ignore[index]
