from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import ValidationError

from incognito_sql.core.config import ColumnClass, column_class, config_problem, load_declaration

Writer = Callable[..., Path]


def test_unmarked_column_is_hidden(write_yaml: Writer) -> None:
    decl = load_declaration(write_yaml(columns={"people": {"full_name": "identifier"}}))
    assert column_class(decl, "people", "full_name") is ColumnClass.IDENTIFIER
    assert column_class(decl, "people", "notes") is None


def test_ttl_null_means_forever(write_yaml: Writer) -> None:
    assert load_declaration(write_yaml(token_ttl_s=None)).token_ttl_s is None


def test_defaults(write_yaml: Writer) -> None:
    decl = load_declaration(write_yaml())
    assert decl.token_ttl_s == 86400
    assert decl.web_port == 8765
    assert decl.web_enabled is True
    assert decl.limits.max_rows == 500


def test_unknown_class_rejected(write_yaml: Writer) -> None:
    with pytest.raises(ValidationError):
        load_declaration(write_yaml(columns={"t": {"c": "pii"}}))


def test_unknown_key_rejected(write_yaml: Writer) -> None:
    with pytest.raises(ValidationError):
        load_declaration(write_yaml(bogus=1))


def test_names_lowercased_and_lookup_case_insensitive(write_yaml: Writer) -> None:
    decl = load_declaration(
        write_yaml(
            columns={"People": {"Full_Name": "identifier", "Id": "open"}},
            entities=[{"table": "People", "pk": "ID"}],
        )
    )
    assert "people" in decl.columns
    assert (decl.entities[0].table, decl.entities[0].pk) == ("people", "id")
    assert column_class(decl, "PEOPLE", "FULL_NAME") is ColumnClass.IDENTIFIER


def test_non_mapping_yaml_rejected(tmp_path: Path) -> None:
    path = tmp_path / "bad.yaml"
    path.write_text("- a\n- b\n", encoding="utf-8")
    with pytest.raises(ValidationError):
        load_declaration(path)


def test_limits_override(write_yaml: Writer) -> None:
    limits: dict[str, Any] = {"max_rows": 10}
    assert load_declaration(write_yaml(limits=limits)).limits.max_rows == 10


@pytest.mark.parametrize("key", ["literal_budget", "probe_budget"])
def test_a_budget_is_a_number_zero_or_unlimited(write_yaml: Writer, key: str) -> None:
    assert getattr(load_declaration(write_yaml(limits={key: 0})).limits, key) == 0
    assert getattr(load_declaration(write_yaml(limits={key: "unlimited"})).limits, key) is None
    for wrong in (None, -1, "lots", False, True):
        with pytest.raises(ValidationError):
            load_declaration(write_yaml(limits={key: wrong}))


def test_case_colliding_tables_rejected(write_yaml: Writer) -> None:
    cols = {"People": {"full_name": "identifier"}, "people": {"full_name": "open"}}
    with pytest.raises(ValidationError):
        load_declaration(write_yaml(columns=cols))


def test_case_colliding_columns_rejected(write_yaml: Writer) -> None:
    cols = {"people": {"Full_Name": "identifier", "full_name": "open"}}
    with pytest.raises(ValidationError):
        load_declaration(write_yaml(columns=cols))


@pytest.mark.parametrize(
    ("override", "where"),
    [
        ({"entities": [{"table": "people", "pk": "id", "display": "id"}]}, "display"),
        ({"foreign_keys": [["orders.person_id", "people.id"]]}, "foreign_keys"),
        ({"entities": [{"table": "ghosts", "pk": "id"}]}, "ghosts"),
        ({"entities": [{"table": "people", "pk": "nope"}]}, "nope"),
        ({"entities": [{"table": "people", "pk": "id"}, {"table": "PEOPLE", "pk": "id"}]}, "twice"),
    ],
)
def test_bad_entities_and_removed_keys_rejected(
    write_yaml: Writer, override: dict[str, Any], where: str
) -> None:
    with pytest.raises(ValidationError, match=where):
        load_declaration(write_yaml(**override))


@pytest.mark.parametrize(
    "override",
    [{"limits": {"max_rows": 0}}, {"web_port": 0}, {"token_ttl_s": 0}, {"token_ttl_s": -5}],
)
def test_non_positive_numbers_rejected(write_yaml: Writer, override: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        load_declaration(write_yaml(**override))


def test_table_with_null_mapping_is_hidden(tmp_path: Path) -> None:
    path = tmp_path / "decl.yaml"
    path.write_text(
        "dsn_env: X\ndialect: sqlite\nentities: []\ncolumns:\n  people:\n  # nothing yet\n",
        encoding="utf-8",
    )
    assert load_declaration(path).columns == {"people": {}}


def test_config_problem_is_one_line(write_yaml: Writer) -> None:
    twice = [{"table": "people", "pk": "id"}, {"table": "people", "pk": "id"}]
    with pytest.raises(ValidationError) as exc:
        load_declaration(write_yaml(entities=twice))
    assert config_problem(exc.value) == "invalid value"  # its message names the table
    assert config_problem(ValueError()) == "ValueError"


SECRET = "ghp_Zqsecret0123456789abcdef"  # noqa: S105 -- made up, a token in the wrong slot


@pytest.mark.parametrize(
    "text",
    [f"dsn_env: !{SECRET} X\n", f"dsn_env: *{SECRET}\n", f"dsn_env: X\ndialect: *{SECRET}\n"],
)
def test_a_yaml_tag_or_alias_is_not_repeated(tmp_path: Path, text: str) -> None:
    path = tmp_path / "decl.yaml"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(yaml.YAMLError) as exc:
        load_declaration(path)
    assert "Zqsecret" not in config_problem(exc.value)
    assert config_problem(exc.value).startswith("invalid YAML at line ")


@pytest.mark.parametrize(
    ("override", "place"),
    [({SECRET: 1}, "top level"), ({"limits": {SECRET: 1}}, "limits")],
)
def test_an_unknown_key_is_named_by_its_place(
    write_yaml: Writer, override: dict[str, object], place: str
) -> None:
    with pytest.raises(ValidationError) as exc:
        load_declaration(write_yaml(**override))
    assert config_problem(exc.value) == f"{place}: unknown key"


@pytest.mark.parametrize(
    ("text", "error", "shown"),
    [
        (f"x: !!int {SECRET}\n", ValueError, "ValueError"),
        (f"x: !!bool {SECRET}\n", KeyError, "KeyError"),
    ],
)
def test_a_typed_tag_s_value_is_not_repeated(
    tmp_path: Path, text: str, error: type[Exception], shown: str
) -> None:
    path = tmp_path / "decl.yaml"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(error) as exc:
        load_declaration(path)
    assert config_problem(exc.value) == shown


def test_a_key_that_is_no_plain_name_is_not_repeated(write_yaml: Writer) -> None:
    columns = {"people": {f"postgresql://u:{SECRET}@h/x": "bogus", "id": "open"}}
    with pytest.raises(ValidationError) as exc:
        load_declaration(write_yaml(columns=columns))
    problem = config_problem(exc.value)
    assert "Zqsecret" not in problem
    assert problem.startswith("columns.<key>.<key>:")  # only the schema's own names


@pytest.mark.parametrize("key", [SECRET, -4821397, 4821397])
def test_a_place_names_only_the_schema_s_fields_and_list_positions(
    write_yaml: Writer, key: object
) -> None:
    with pytest.raises(ValidationError) as exc:
        load_declaration(write_yaml(columns={"people": {key: "bogus", "id": "open"}}))
    problem = config_problem(exc.value)
    assert problem.startswith("columns.<key>.<key>")
    assert str(key) not in problem
    assert "people" not in problem
    entities = [{"table": "people", "pk": "id"}, {"table": 5}]
    with pytest.raises(ValidationError) as exc:
        load_declaration(write_yaml(entities=entities))
    assert config_problem(exc.value).startswith("entities.1.")
