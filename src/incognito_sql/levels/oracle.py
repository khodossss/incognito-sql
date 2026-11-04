"""The oracle on real data: a hidden value found whole in the text a tool produced.

Real databases carry no canaries, so the oracle looks for the values of the hidden
columns themselves, in the forms of ``incognito_sql.levels.textforms``. A value is found only
whole: not as part of a longer word or number. Values the caller says are visible
anyway are dropped (``drop``). The oracle shares no code with the server under test.
"""

import re
from collections import defaultdict
from collections.abc import Iterable

from incognito_sql.levels.textforms import MIN_LENGTH, forms, number, plain, variants

__all__ = ["MIN_LENGTH", "Oracle", "forms", "number", "plain", "variants"]
_HEAD = 200  # characters of a value searched for the word that indexes it
_TAIL = 24  # characters past that word that file a value under it
# word -> its offset in a form -> how many first characters -> those characters -> forms
Index = dict[str, dict[int, dict[int, dict[str, list[str]]]]]
_WORD = re.compile(r"\w+")


class Oracle:
    """Find hidden values whole in text; built once per database and marking."""

    def __init__(self, hidden: Iterable[object]) -> None:
        """Index the forms of every hidden value by the longest word of their head.

        The longest word is the rarest in practice: free text starting with ``<p>``
        would otherwise put every post under the word ``p``. Only the head of a long
        text is read for it, without a word the cut splits. Under its word a form is
        filed by the word's offset in it and by its first characters up to ``_TAIL``
        past the word, so a word many values share costs a few dictionary lookups per
        occurrence, not one comparison per value.
        """
        self._index: Index = defaultdict(dict)
        self._forms: set[str] = set()
        for value in hidden:
            for form in forms(value) - self._forms:
                head = form[:_HEAD]
                words = [w for w in _WORD.finditer(head) if w.end() < len(head) or head == form]
                if words:  # no letter or digit: nothing whole to find
                    anchor = max(words, key=lambda w: len(w.group(0)))
                    by_offset = self._index[anchor.group(0)].setdefault(anchor.start(), {})
                    cut = min(len(form), anchor.end() + _TAIL)
                    by_offset.setdefault(cut, {}).setdefault(form[:cut], []).append(form)
                    self._forms.add(form)

    @property
    def size(self) -> int:
        """Return how many forms are looked for."""
        return len(self._forms)

    def drop(self, texts: Iterable[str]) -> int:
        """Stop looking for the values found in ``texts``; return how many were dropped."""
        gone = {form for text in texts for form in self.found(text)}
        for by_offset in self._index.values():
            for by_cut in by_offset.values():
                for heads in by_cut.values():
                    for head, kept in heads.items():
                        if not gone.isdisjoint(kept):
                            heads[head] = [f for f in kept if f not in gone]
        self._forms -= gone
        return len(gone)

    def found(self, text: str) -> list[str]:
        """Return the hidden values found whole in ``text``, each once."""
        hits: dict[str, None] = {}
        for variant in variants(text):
            for word in _WORD.finditer(variant):  # one pass: each whole word once
                by_offset = self._index.get(word.group(0))
                if by_offset is None:
                    continue
                for offset, by_cut in by_offset.items():
                    start = word.start() - offset
                    if start < 0:
                        continue
                    for cut, heads in by_cut.items():
                        for form in heads.get(variant[start : start + cut], ()):
                            if _whole(variant, start, form):
                                hits[form] = None
        return list(hits)


def _whole(text: str, start: int, form: str) -> bool:
    end = start + len(form)
    if not text.startswith(form, start):
        return False
    before = text[start - 1] if start else " "
    after = text[end] if end < len(text) else " "
    if (form[0].isalnum() or form[0] == "_") and (before.isalnum() or before == "_"):
        return False
    if (form[-1].isalnum() or form[-1] == "_") and (after.isalnum() or after == "_"):
        return False
    # a number is not part of a longer one: 1234 is not in 1234.5 or 12.1234
    if form[-1].isdigit() and after == "." and text[end + 1 : end + 2].isdigit():
        return False
    return not (form[0].isdigit() and before == "." and text[start - 2 : start - 1].isdigit())
