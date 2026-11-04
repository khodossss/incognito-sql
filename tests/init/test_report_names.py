"""Contradictions find samples of mixed-case names, which the declaration lowers."""

from incognito_sql.core.config import Declaration
from incognito_sql.init.report import contradictions


def test_sample_of_a_mixed_case_column_is_found() -> None:
    decl = Declaration.model_validate(
        {
            "dsn_env": "DSN",
            "dialect": "postgres",
            "entities": [],
            "columns": {"Clients": {"RefCode": "open", "Town": "quasi"}},
        }
    )
    samples: dict[tuple[str, str], list[object]] = {
        ("Clients", "RefCode"): ["+972 50 123 4567"],
        ("Clients", "Town"): ["Haifa"],
    }
    assert contradictions(decl, samples) == ["clients.refcode: sample looks personal"]
