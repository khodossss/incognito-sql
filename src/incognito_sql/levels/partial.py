"""L2 on one work: a hidden value shown in part, unless that part is visible anyway.

A run of ``incognito_sql.levels.fragment`` counts when one of its windows is in none of the
places the caller names: the query itself, what the tool's twin wrote over the decoy
copy, the shown columns and names of the same database. A value also shown whole in the
same text is L1 and not counted here, nor is a piece of it another value shares. Short
texts are searched as they are (``Visible``); the shown text of a database, hundreds of
megabytes, once for the hidden values' pieces (``Pieces``).
"""

from collections.abc import Container, Iterable

from incognito_sql.levels.fragment import Fragments, Run
from incognito_sql.levels.textforms import plain, variants

_APART = "\n|\n"  # no window spans two texts


class Visible:
    """Texts a window may be found in: membership is substring search over all of them."""

    def __init__(self, texts: Iterable[str]) -> None:
        """Join the texts in their compared forms."""
        self._blob = _APART.join(form for text in texts for form in variants(text))

    def __contains__(self, piece: object) -> bool:
        """Tell whether ``piece`` is in one of the texts."""
        return isinstance(piece, str) and piece in self._blob


class Pieces:
    """The windows of hidden values found in texts, read in one pass and not kept.

    A window of a value is in a text exactly when ``Fragments.found`` there returns a run
    of that value holding it: every window holds an indexed gram, and a run is extended
    as far as the text and the value agree. So the windows of the runs found answer for
    every window the same fragments find elsewhere.
    """

    def __init__(self, fragments: Fragments, texts: Iterable[str]) -> None:
        """Collect the windows of every run of ``fragments`` in ``texts``."""
        self._windows: set[str] = set()
        for text in texts:
            for run in fragments.found(text):
                self._windows.update(run.windows())

    def __contains__(self, piece: object) -> bool:
        """Tell whether ``piece`` is a window found in one of the texts."""
        return piece in self._windows


def shown_in_part(
    runs: Iterable[Run], whole: Iterable[str], places: Iterable[Container[str]]
) -> set[str]:
    """Return the values of ``runs`` shown in part: a window found nowhere in ``places``.

    A window inside a value shown whole in the same text is that value's, not a part of
    another: two emails share their domain.
    """
    full = {plain(w) for w in whole}
    where = [Visible(full), *places]
    out: set[str] = set()
    for run in runs:
        if run.value in full or run.value in out:
            continue
        if any(not any(w in place for place in where) for w in run.windows()):
            out.add(run.value)
    return out
