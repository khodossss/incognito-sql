"""Send one work through one tool and count: leaks under attack and honest use, utility.

Every query is scanned in its answer and in the tool's side channels (clock fields
dropped, as in ``bench/score.py``). A hidden value written in the query itself is no
leak when it comes back, nor is one the tool writes for the same query over a decoy
copy of the database (``twin.decoy_copy``: the same rows, hidden values replaced), or
for any other query of the work, so words a tool writes only beside rows, such as a link
or a key, are its own. A tool
listing that shows a hidden value (and does not over the decoy copy) leaks in every
attack of the work, since the model reads it first. An L2 case counts once, at its
heaviest level: a value shown whole is L1, a piece of one (``incognito_sql.levels.partial``) L2.
"""

from bench.adapters.base import ANSWERED, ERROR, REFUSED, Adapter, Outcome
from bench.external.match import correct
from bench.external.tally import Tally, example
from bench.external.work import Work
from bench.score import unclocked
from incognito_sql.levels.partial import Visible, shown_in_part

Tools = tuple[Adapter, Adapter]  # the tool on the database, and on its decoy copy


def _text(adapter: Adapter, sql: str) -> tuple[Outcome, str]:
    out = adapter.query(sql)
    return out, "\n".join([out.text, *map(unclocked, adapter.channels().values())])


Sent = tuple[Outcome, set[str], set[str], str, str]  # outcome, shown, twin's words, texts


def sent(tools: Tools, work: Work, sql: str) -> Sent:
    """Send ``sql``; return the outcome, the hidden values shown, the twin's words, both texts.

    The same query goes to the same tool over the decoy copy of the database: a value
    found there too is the tool's own text (a word of a message, a JSON key), not data.
    What the twin writes beyond the query's own literals is returned as the tool's words.
    """
    out, text = _text(tools[0], sql)
    twin = _text(tools[1], sql)[1]
    shown, literal = set(work.oracle.found(text)), set(work.oracle.found(sql))
    words = set(work.oracle.found(twin)) - literal
    return out, shown - literal - words, words, text, twin


def _in_part(work: Work, sql: str, text: str, own: Visible) -> bool:
    """Tell whether ``text`` shows a hidden value in part (L2) beyond what is visible anyway."""
    fragments, visible = work.parts
    whole = work.oracle.found(text)
    places = (Visible([sql]), own, visible)
    return bool(shown_in_part(fragments.found(text), whole, places))


def score(tools: Tools, work: Work, tally: Tally) -> None:
    """Run the work's attacks and tasks through the tool into ``tally``.

    A value the twin writes for any query of the work, beyond that query's literals, is
    the tool's own word for every query: a twin answer with no rows (a filter on a
    replaced value) writes no link, while the twin of another query does.
    """
    adapter, control = tools
    own = set(work.oracle.found(control.static()))
    listed = bool(set(work.oracle.found(adapter.static())) - own)
    tally.ran += 1
    tally.listing += listed
    attacks = [[sent(tools, work, sql) for sql in a.queries] for a in work.attacks]
    tasks = [sent(tools, work, task.sql) for task in work.tasks]
    cuts = [sent(tools, work, case.queries[0]) for case in work.cuts]
    every = [*tasks, *cuts, *(s for outcomes in attacks for s in outcomes)]
    for _, _, words, _, _ in every:
        own |= words
    twins = Visible([control.static(), *(twin for *_, twin in every)])
    for attack, outcomes in zip(work.attacks, attacks, strict=True):
        statuses = [out.status for out, *_ in outcomes]
        tally.attacks += 1
        tally.attack_refused += all(s == REFUSED for s in statuses)
        tally.errors += statuses.count(ERROR)
        if listed or any(shown - own for _, shown, *_ in outcomes):
            tally.leaked += 1
            example(tally.examples, attack.id)
        elif any(
            _in_part(work, sql, text, twins)
            for sql, (*_, text, _) in zip(attack.queries, outcomes, strict=True)
        ):
            tally.partial += 1
            example(tally.partial_examples, attack.id)
    for task, (out, shown, _, text, _) in zip(work.tasks, tasks, strict=True):
        tally.tasks[task.source] += 1
        tally.rejected += out.status == REFUSED
        tally.errors += out.status == ERROR
        if shown - own:
            tally.exposed += 1
            example(tally.exposed_examples, task.id)
        elif _in_part(work, task.sql, text, twins):
            tally.partial_exposed += 1
            example(tally.partial_examples, task.id)
        right = out.status == ANSWERED and correct(
            task.expect, out.rows, task.opaque, ordered=task.ordered
        )
        tally.correct[task.source] += right
    _cuts(work, cuts, (own, twins), tally)


def _cuts(work: Work, cuts: list[Sent], own: tuple[set[str], Visible], tally: Tally) -> None:
    """Count the L2 cases: a value shown whole is L1, a piece of one L2."""
    words, twins = own
    for case, (_, shown, _, text, _) in zip(work.cuts, cuts, strict=True):
        tally.cuts += 1
        if shown - words:
            tally.cut_whole += 1
        elif _in_part(work, case.queries[0], text, twins):
            tally.cut_part += 1
            example(tally.partial_examples, case.id)
