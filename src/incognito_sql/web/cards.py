"""What a card shows: the value behind a token, and entity rows by their key."""

from dataclasses import dataclass

from sqlalchemy import Engine, text
from sqlglot import exp

from incognito_sql.core.config import ColumnClass, Declaration, column_class
from incognito_sql.core.display import DisplayIds, entity_keys
from incognito_sql.core.errors import Rejection
from incognito_sql.core.sql.bind_values import coerce_raws
from incognito_sql.core.sql.catalog import Catalog
from incognito_sql.core.sql.rewrite import render
from incognito_sql.core.tokens.store import InvalidToken, TokenStore

# Secret and undeclared columns are never shown, not even to the human.
SHOWN = frozenset(
    {ColumnClass.IDENTIFIER, ColumnClass.QUASI, ColumnClass.OPEN, ColumnClass.FREE_TEXT}
)


@dataclass(frozen=True)
class Row:
    """One entity row: its table, its key and the shown columns in table order."""

    entity: str
    pk: object
    fields: list[tuple[str, object]]


@dataclass(frozen=True)
class _Plan:
    sql: str
    pk_type: str
    columns: list[str]


class Cards:
    """Reads card contents with SQL built from the declaration, never from URL text."""

    def __init__(
        self, decl: Declaration, store: TokenStore, engine: Engine, catalog: Catalog
    ) -> None:
        """Plan one row lookup per entity whose key column is open and present."""
        self._store = store
        self._masks = store.masks()
        self._engine = engine
        self._ids = DisplayIds(decl, catalog, store, engine, for_model=False)
        self._plans: dict[str, _Plan] = {}
        for table, key in entity_keys(decl, catalog):
            types = catalog.columns[table]
            shown = [c for c in types if column_class(decl, table, c) in SHOWN]
            sql = _row_sql(table, key, shown, decl.dialect)
            self._plans[table] = _Plan(sql, types[key], shown)

    def value(self, token: str) -> tuple[str, list[Row]] | None:
        """Return the value behind a token (however old) and the rows holding it now.

        A database error is raised, never shown as "no rows".
        """
        try:
            value = self._store.reveal(token)
        except InvalidToken:
            return None
        rows = [
            row
            for table, keys in self._ids.find(value).items()
            for key in keys
            if (row := self.row(table, str(key))) is not None
        ]
        return value, rows

    def masked(self, token: str) -> str | None:
        """Return the value behind a mask token (however old), or None."""
        try:
            return self._masks.reveal(token)
        except InvalidToken:
            return None

    def row(self, entity: str, key: str) -> Row | None:
        """Return the entity row with this key, or None if unknown or gone."""
        plan = self._plans.get(entity)
        if plan is None:
            return None
        try:
            [pk] = coerce_raws([key], plan.pk_type)
        except Rejection:  # the key cannot be a value of the key column
            return None
        with self._engine.connect() as conn:
            found = conn.execute(text(plan.sql), {"pk": pk}).fetchone()
        if found is None:
            return None
        return Row(entity, pk, list(zip(plan.columns, found, strict=True)))


def _row_sql(table: str, key: str, columns: list[str], dialect: str) -> str:
    tree = (
        exp.select(*(exp.column(_quoted(c)) for c in columns))
        .from_(exp.Table(this=_quoted(table)))
        .where(exp.column(_quoted(key)).eq(exp.Placeholder(this="pk")))
    )
    return render(tree, dialect)


def _quoted(name: str) -> exp.Identifier:
    return exp.to_identifier(name, quoted=True)
