"""Field declaration model: which column is what, and the query limits."""

from enum import StrEnum
from typing import Self

from pydantic import (
    BaseModel,
    ConfigDict,
    NonNegativeInt,
    PositiveInt,
    field_validator,
    model_validator,
)

from incognito_sql.core.config.protection import (
    DEFAULT,
    CustomProfile,
    Operation,
    check_names,
    resolve,
)
from incognito_sql.core.config.row_rules import RowRule, rule_problem, rules_problem


class ColumnClass(StrEnum):
    """Disclosure class of a column."""

    IDENTIFIER = "identifier"
    QUASI = "quasi"
    FREE_TEXT = "free_text"
    SECRET = "secret"  # noqa: S105
    OPEN = "open"


_EXPOSED = frozenset({ColumnClass.OPEN, ColumnClass.QUASI})


UNLIMITED = "unlimited"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Entity(_Strict):
    """A table whose rows are people-like entities, and its key column."""

    table: str
    pk: str

    @field_validator("table", "pk")
    @classmethod
    def _lower(cls, value: str) -> str:
        return value.lower()


class Limits(_Strict):
    """Bounds on a single query and on literal probing."""

    max_sql_chars: PositiveInt = 20000
    max_ast_nodes: PositiveInt = 2000
    max_joins: PositiveInt = 8
    max_in_items: PositiveInt = 50
    max_rows: PositiveInt = 500
    statement_timeout_ms: PositiveInt = 10000
    # A budget is a number, 0 (turned off) or `unlimited`, held as None.
    literal_budget: NonNegativeInt | None = 20
    literal_window_s: PositiveInt = 3600
    probe_budget: NonNegativeInt | None = 100
    query_rate: PositiveInt = 600
    query_window_s: PositiveInt = 60

    @field_validator("literal_budget", "probe_budget", mode="before")
    @classmethod
    def _unlimited(cls, value: object) -> object:
        if value is None:
            msg = "write unlimited for no budget"
            raise ValueError(msg)
        if isinstance(value, bool):  # YAML reads `off` and `no` as false: say a number
            msg = "write a number, 0 or unlimited"
            raise ValueError(msg)  # noqa: TRY004 -- pydantic reports a ValueError as invalid
        return None if value == UNLIMITED else value


class Declaration(_Strict):
    """The full field declaration. A column absent from `columns` is hidden."""

    dsn_env: str
    dialect: str
    columns: dict[str, dict[str, ColumnClass]]
    entities: list[Entity]
    verified_open: dict[str, list[str]] = {}
    verified_relations: list[str] = []
    token_ttl_s: PositiveInt | None = 86400
    web_port: PositiveInt = 8765
    web_enabled: bool = True
    session_ttl_s: PositiveInt = 8 * 3600
    mcp_port: PositiveInt = 8766
    limits: Limits = Limits()
    protection: str = DEFAULT
    protections: dict[str, CustomProfile] = {}
    column_protection: dict[str, dict[str, str]] = {}
    row_rules: list[RowRule] = []

    @field_validator("columns", mode="before")
    @classmethod
    def _null_tables(cls, value: object) -> object:
        if isinstance(value, dict):
            return {table: {} if cols is None else cols for table, cols in value.items()}
        return value

    @field_validator("columns")
    @classmethod
    def _lower_columns(
        cls, value: dict[str, dict[str, ColumnClass]]
    ) -> dict[str, dict[str, ColumnClass]]:
        tables: dict[str, dict[str, ColumnClass]] = {}
        for table, cols in value.items():
            key = table.lower()
            if key in tables:
                msg = f"tables differ only in case: {key}"
                raise ValueError(msg)
            lowered: dict[str, ColumnClass] = {}
            for column, kind in cols.items():
                if column.lower() in lowered:
                    msg = f"columns differ only in case in {key}: {column.lower()}"
                    raise ValueError(msg)
                lowered[column.lower()] = kind
            tables[key] = lowered
        return tables

    @field_validator("verified_open")
    @classmethod
    def _lower_verified(cls, value: dict[str, list[str]]) -> dict[str, list[str]]:
        return {table.lower(): [c.lower() for c in cols] for table, cols in value.items()}

    @field_validator("verified_relations")
    @classmethod
    def _lower_relations(cls, value: list[str]) -> list[str]:
        return [name.lower() for name in value]

    @model_validator(mode="after")
    def _verified_relations_are_declared(self) -> Self:
        for name in self.verified_relations:
            if name not in self.columns:
                msg = f"verified_relations {name} is not a declared table"
                raise ValueError(msg)
        return self

    @model_validator(mode="after")
    def _verified_are_exposed(self) -> Self:
        for table, cols in self.verified_open.items():
            for column in cols:
                if column_class(self, table, column) not in _EXPOSED:
                    msg = f"verified_open {table}.{column} is not an open or quasi column"
                    raise ValueError(msg)
        return self

    @field_validator("column_protection")
    @classmethod
    def _lower_protected(cls, value: dict[str, dict[str, str]]) -> dict[str, dict[str, str]]:
        lowered = {t.lower(): {c.lower(): p for c, p in cols.items()} for t, cols in value.items()}
        if len(lowered) != len(value) or any(
            len(lowered[t.lower()]) != len(cols) for t, cols in value.items()
        ):
            msg = "column_protection names differ only in case"
            raise ValueError(msg)
        return lowered

    @model_validator(mode="after")
    def _known_profiles(self) -> Self:
        check_names(self.protections)
        resolve(self.protection, self.protections)
        for table, cols in self.column_protection.items():
            for column, name in cols.items():
                if column_class(self, table, column) is not ColumnClass.IDENTIFIER:
                    msg = f"column_protection {table}.{column} is not an identifier column"
                    raise ValueError(msg)
                resolve(name, self.protections)
        return self

    @model_validator(mode="after")
    def _row_rules(self) -> Self:
        problems = [rule_problem(rule, self.columns, self.dialect) for rule in self.row_rules]
        problems.append(None if any(problems) else rules_problem(self.row_rules, self.dialect))
        for problem in problems:
            if problem is not None:
                raise ValueError(problem)
        return self

    @model_validator(mode="after")
    def _declared_entities(self) -> Self:
        seen: set[str] = set()
        for entity in self.entities:
            if entity.table in seen:
                msg = f"entity table {entity.table} is listed twice"
                raise ValueError(msg)
            seen.add(entity.table)
            if entity.pk not in self.columns.get(entity.table, {}):
                msg = f"entity {entity.table}.{entity.pk} is not a declared column"
                raise ValueError(msg)
        return self


def column_class(decl: Declaration, table: str, column: str) -> ColumnClass | None:
    """Return the class of a column, or None if unmarked (treated as hidden)."""
    return decl.columns.get(table.lower(), {}).get(column.lower())


def verified_columns(decl: Declaration) -> frozenset[str]:
    """Return ``table.column`` of every column a human marked open and checked."""
    return frozenset(f"{t}.{c}" for t, cols in decl.verified_open.items() for c in cols)


def column_profile(decl: Declaration, table: str, column: str) -> str:
    """Return the name of the protection profile of an identifier column."""
    return decl.column_protection.get(table.lower(), {}).get(column.lower(), decl.protection)


def column_operations(decl: Declaration, table: str, column: str) -> frozenset[Operation]:
    """Return the operations the protection profile of an identifier column admits."""
    return resolve(column_profile(decl, table, column), decl.protections)
