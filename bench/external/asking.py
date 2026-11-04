"""A tool under test as the inference series asks it: one SQL query, one reply."""

from bench.adapters.base import ANSWERED, SKIPPED, Adapter
from incognito_sql.levels.asker import Ask, Reply


def ask_of(adapter: Adapter) -> Ask:
    """Return the tool's answer to a query as a ``Reply``; side channels go to its oracle."""

    def ask(sql: str) -> Reply:
        out = adapter.query(sql)
        adapter.channels()  # side channels are the L1 oracle's, not the attacker's
        skipped = out.status == SKIPPED
        return Reply(out.status == ANSWERED, out.rows, out.text, skipped=skipped, spend=out.spend)

    return ask
