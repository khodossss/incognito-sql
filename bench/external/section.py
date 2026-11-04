"""The independent-sets section of ``docs/benchmark.md``, between two markers.

Its text is in ``bench/benchmark.md.in`` like the rest of the document. The full run
renders the whole document and keeps the section of the previous document; this run
fills the section and puts it in place of the previous one.
"""

BEGIN, END = "<!-- external:begin -->", "<!-- external:end -->"
NOT_RUN = "_Not run yet: `uv run poe bench-external --markdown`._"
_BEFORE = "\n## Tools\n"


def block(text: str) -> str | None:
    """Return the section of ``text``, markers included, or None."""
    start, end = text.find(BEGIN), text.find(END)
    if start < 0 or end < start:
        return None
    return text[start : end + len(END)]


def fill(section: str, fills: dict[str, str]) -> str:
    """Fill the ``{{key}}`` placeholders of the section."""
    for key, value in fills.items():
        section = section.replace("{{" + key + "}}", value)
    return section


def carried(document: str, previous: str) -> str:
    """Fill the document's section from ``previous``, or mark it not run yet."""
    old, own = block(previous), block(document)
    if own is None:
        return document
    if old is not None:
        return splice(document, old)
    return splice(document, fill(own, {**dict.fromkeys(KEYS, "-"), "ext_table": NOT_RUN}))


KEYS = (
    "ext_date",
    "ext_sources",
    "ext_sets",
    "ext_table",
    "ext_levels",
    "ext_prices",
    "ext_capacity",
)


def splice(document: str, section: str) -> str:
    """Put ``section`` in place of the document's own, or before its Tools section."""
    old = block(document)
    if old is not None:
        return document.replace(old, section)
    at = document.find(_BEFORE)
    if at < 0:
        return document.rstrip("\n") + "\n\n" + section + "\n"
    return document[:at] + "\n" + section + "\n" + document[at:]
