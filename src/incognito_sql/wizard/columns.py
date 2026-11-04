"""The columns screen: init's suggestion per table, accepted or changed, then written."""

from collections.abc import Sequence
from pathlib import Path

from incognito_sql.core.config import ColumnClass
from incognito_sql.setup.columns import HIDDEN, Proposal, apply_classes, proposals
from incognito_sql.wizard.prompts import Prompter

CLASSES = (*(c.value for c in ColumnClass), HIDDEN)


class NotWritten(Exception):  # noqa: N818 -- the human chose not to try again
    """The classes were not written; the config is as it was."""


def decide(config: Path, prompter: Prompter) -> list[str]:
    """Ask the class of every column and the tables of people; write them into ``config``.

    Returns ``table.column: class`` lines. Raises ``NotWritten`` when the declaration the
    human decided does not load and they do not try again.
    """
    by_table: dict[str, list[Proposal]] = {}
    for proposal in proposals(config):
        by_table.setdefault(proposal.table, []).append(proposal)
    while True:
        classes = {
            (p.table, p.column): cls
            for table, found in by_table.items()
            for p, cls in zip(found, _table(table, found, prompter), strict=True)
        }
        entities = _entities(by_table, classes, prompter)
        problem = apply_classes(config, classes, entities)
        if problem is None:
            return [f"{t}.{c}: {cls}" for (t, c), cls in classes.items()]
        prompter.tell(f"The declaration does not load: {problem}")
        if not prompter.yesno("Decide the columns again?", default=True):
            raise NotWritten


def _table(table: str, found: Sequence[Proposal], prompter: Prompter) -> list[str]:
    prompter.tell(f"\nTable {table}:")
    for number, p in enumerate(found, 1):
        why = f"  (PII? {p.reason})" if p.reason else ""
        prompter.tell(f"  {number}. {p.column}: {p.suggested}{why}")
    classes = [p.suggested for p in found]
    if prompter.yesno("Take these classes?", default=True):
        return classes
    names = [p.column for p in found]
    for column in prompter.many("Columns to change", names, []):
        at = names.index(column)
        classes[at] = prompter.one(f"Class of {column}?", CLASSES, classes[at])
    return classes


def _entities(
    by_table: dict[str, list[Proposal]], classes: dict[tuple[str, str], str], prompter: Prompter
) -> list[tuple[str, str]]:
    open_ = {
        t: [p.column for p in found if classes[t, p.column] == ColumnClass.OPEN.value]
        for t, found in by_table.items()
    }
    tables = [t for t, columns in open_.items() if columns]  # a key must be an open column
    personal = [
        t
        for t in tables
        if any(classes[t, p.column] == ColumnClass.IDENTIFIER.value for p in by_table[t])
    ]
    chosen = prompter.many("Tables whose rows are people", tables, personal)
    return [
        (t, prompter.one(f"Key column of {t}?", open_[t], "id" if "id" in open_[t] else None))
        for t in chosen
    ]
