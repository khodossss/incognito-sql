"""Turn executed rows into the JSON the model receives, without personal values."""

import random
from collections.abc import Callable
from datetime import datetime

from incognito_sql.core.config import ColumnClass, Declaration
from incognito_sql.core.config.forms import Form, forms
from incognito_sql.core.exec.run import Rows
from incognito_sql.core.output.detect import looks_personal
from incognito_sql.core.output.mask import Masker, plain, rounded, spelled_once
from incognito_sql.core.tokens.store import TokenStore


def _keys(found: dict[str, list[object]]) -> dict[str, list[object]]:
    kept = {t: [plain(k) for k in keys if not looks_personal(k)] for t, keys in found.items()}
    return {table: keys for table, keys in kept.items() if keys}


def shape(  # noqa: PLR0913, PLR0917
    rows: Rows,
    classes: list[ColumnClass | None],
    store: TokenStore,
    decl: Declaration,
    now: datetime,
    rng: random.Random,
    *,
    hidden_count: int = 0,
    display_ids: Callable[[object], dict[str, list[object]]] | None = None,
    keep_order: bool = False,
    masker: Masker | None = None,
) -> dict[str, object]:
    """Build the model-facing result.

    Rows are shuffled first, so order and label numbers carry nothing about the
    values, unless ``keep_order`` says the query sorted them by keys the policy
    allowed (never an identifier). An identifier cell becomes a link (web mode) or a label such as
    ``name_1`` (label mode); equal values, including spelling variants, share one.
    A NULL stays null. Under a profile that closes the scan order a number prints one way
    whatever its type. Any other cell goes through ``masker``, which masks what
    looks like personal data (plain-text masks by default).
    In label mode ``labels`` maps each label to ``{entity table: [keys]}`` from
    ``display_ids``; a key that looks like personal data is dropped, and so is
    an entity left without keys.
    """
    masker = masker or Masker()
    shuffled = list(rows.rows)
    # Shuffled unless sorted by allowed keys.
    if not keep_order:
        rng.shuffle(shuffled)
    labels: dict[str, dict[str, list[object]]] = {}
    label_of: dict[str, str] = {}

    def identifier(value: object) -> str:
        token = store.tokenize(value, now)
        if decl.web_enabled:
            return f"http://127.0.0.1:{decl.web_port}/v/{token}"
        if token not in label_of:
            name = f"name_{len(label_of) + 1}"
            label_of[token] = name
            labels[name] = _keys(display_ids(value)) if display_ids else {}
        return label_of[token]

    # Equal numbers of different types print alike, so no spelling tells which row the
    # scan met first.
    once = Form.SPELLING_CHOICE not in forms(decl.protection, decl.protections)
    out_rows: list[list[object]] = []
    for row in shuffled:
        cells: list[object] = []
        for i, (cls, value) in enumerate(zip(classes, row, strict=True)):
            if cls is ColumnClass.IDENTIFIER:
                cells.append(None if value is None else identifier(value))
            else:
                cells.append(masker.cell(i, spelled_once(rounded(value)) if once else value))
        out_rows.append(cells)
    result: dict[str, object] = {
        "columns": list(rows.columns),
        "rows": out_rows,
        "hidden_columns": hidden_count,
        "truncated": rows.truncated,
    }
    if not decl.web_enabled:
        result["labels"] = labels
    return result
