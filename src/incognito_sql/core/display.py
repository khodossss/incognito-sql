"""Entity keys behind an identifier value, for labels mode."""

from datetime import datetime

from sqlalchemy import Engine, text
from sqlglot import exp

from incognito_sql.core.config import ColumnClass, Declaration, column_class
from incognito_sql.core.errors import Rejection
from incognito_sql.core.exec.run import Rows
from incognito_sql.core.sql.bind_type import bind_cast, bind_domain
from incognito_sql.core.sql.binder import MAX_FORMS
from incognito_sql.core.sql.catalog import Catalog
from incognito_sql.core.sql.rewrite import render
from incognito_sql.core.sql.row_mask import mask_rows
from incognito_sql.core.tokens.store import TokenStore

MAX_IDS = 20


class DisplayIds:
    """Find, per entity table, the primary keys of rows whose identifier columns hold a value.

    Only key values are returned, never the identifier or display values, and
    only for entities whose key column is declared `open` (a surrogate key).
    Keys of different entities are kept apart.
    """

    def __init__(
        self,
        decl: Declaration,
        catalog: Catalog,
        store: TokenStore,
        engine: Engine,
        *,
        for_model: bool = True,
    ) -> None:
        """Plan one lookup per identifier column of each declared entity table.

        ``for_model`` reads tables through their row rules; a signed-in human's card does not.
        """
        self._store = store
        self._engine = engine
        self._dialect = decl.dialect
        self._decl, self._catalog, self._for_model = decl, catalog, for_model
        self._lookups: list[tuple[str, str, str, str]] = []  # table, key, column, its type
        for table, key in entity_keys(decl, catalog):
            types = catalog.columns[table]
            for column in types:
                if column_class(decl, table, column) is ColumnClass.IDENTIFIER:
                    self._lookups.append((table, key, column, types[column]))

    def __call__(self, value: object) -> dict[str, list[object]]:
        """Return up to MAX_IDS distinct keys per entity table; any error gives `{}`."""
        try:
            return self.find(value)
        except Exception:  # noqa: BLE001 -- a label without keys is still a label
            return {}

    def find(self, value: object) -> dict[str, list[object]]:
        """Return the same keys as a call, but let a database error out."""
        raws = self._store.variants_for_literal(value)
        found: dict[str, dict[object, None]] = {}
        for table, key, column, col_type in self._lookups:
            keys = found.setdefault(table, {})
            if len(keys) >= MAX_IDS:
                continue
            try:  # stored forms: only those the column's exact type holds, cast to it
                domain = bind_domain(col_type, self._dialect)
                target = bind_cast(col_type, self._dialect)
            except Rejection:
                continue
            checked = (v for v in map(domain.check, raws) if v is not None)
            values = list(dict.fromkeys(checked))[:MAX_FORMS]
            if not values:  # the value cannot be in a column of this type
                continue
            binds = {f"p{i}": v for i, v in enumerate(values)}
            holders: list[exp.Expr] = [exp.Placeholder(this=name) for name in binds]
            if target is not None:
                holders = [exp.Cast(this=h, to=target.copy()) for h in holders]
            # A row rule hides keys from the model the way it hides cells: no key of a
            # hidden row or cell.
            tree: exp.Expr = _lookup(table, key, column, holders)
            if self._for_model:
                tree = mask_rows(tree, self._decl, self._catalog)
            sql = render(tree, self._dialect)
            with self._engine.connect() as conn:
                for (pk,) in conn.execute(text(sql), binds).fetchmany(MAX_IDS):
                    if pk is not None:  # a key a row rule hides is no key
                        keys[pk] = None
        return {table: list(keys)[:MAX_IDS] for table, keys in found.items() if keys}


def entity_keys(decl: Declaration, catalog: Catalog) -> list[tuple[str, str]]:
    """Return (table, key column) in catalog names for each entity whose key is open."""
    found: list[tuple[str, str]] = []
    for entity in decl.entities:
        table = catalog.table(entity.table)
        key = None if table is None else catalog.column(table, entity.pk)
        if key is not None and column_class(decl, entity.table, key) is ColumnClass.OPEN:
            found.append((str(table), key))
    return found


def remember_forms(
    rows: Rows, classes: list[ColumnClass | None], store: TokenStore, now: datetime
) -> None:
    """Tokenize every identifier cell first, so a lookup knows all spellings in the answer."""
    for row in rows.rows:
        for cls, value in zip(classes, row, strict=True):
            if cls is ColumnClass.IDENTIFIER and value is not None:
                store.tokenize(value, now)


def _lookup(table: str, key: str, column: str, holders: list[exp.Expr]) -> exp.Select:
    # Every name quoted: a reserved word or a mixed-case name is still that name.
    return (
        exp.select(exp.column(_quoted(key)))
        .from_(exp.Table(this=_quoted(table)))
        .where(exp.column(_quoted(column)).isin(*holders))
    )


def _quoted(name: str) -> exp.Identifier:
    return exp.to_identifier(name, quoted=True)
