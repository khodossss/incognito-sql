"""HTML of the cards: file templates filled with escaped text."""

from html import escape
from importlib import resources
from string import Template
from urllib.parse import quote

from incognito_sql.web.cards import Row

NO_ROWS = "no rows hold this value now"
ALARM = (
    '<p class="alarm">Alarm: the model hit the literal or the probe budget, which looks like '
    "guessing values, or many sorts of identifier columns. Details are in the audit log.</p>"
)


def _template(name: str) -> Template:
    source = resources.files("incognito_sql.web").joinpath(f"templates/{name}")
    return Template(source.read_text("utf-8"))


def _page(title: str, body: str, *, alarm: bool) -> str:
    return _template("layout.html").substitute(
        title=escape(title), body=body, alarm=ALARM if alarm else ""
    )


def _cell(value: object) -> str:
    return "" if value is None else escape(str(value))


def _link(row: Row) -> str:
    href = f"/p/{quote(row.entity, safe='')}/{quote(str(row.pk), safe='')}"
    return f'<a href="{escape(href)}">open</a>'


def _tables(rows: list[Row]) -> str:
    if not rows:
        return f'<p class="empty">{NO_ROWS}</p>'
    parts: list[str] = []
    for entity in dict.fromkeys(r.entity for r in rows):
        mine = [r for r in rows if r.entity == entity]
        head = "".join(f"<th>{escape(c)}</th>" for c, _ in mine[0].fields)
        body = "".join(
            f"<tr><td>{_link(r)}</td>{''.join(f'<td>{_cell(v)}</td>' for _, v in r.fields)}</tr>"
            for r in mine
        )
        parts.append(f"<h2>{escape(entity)}</h2><table><tr><th></th>{head}</tr>{body}</table>")
    return "\n".join(parts)


def value_page(value: str, rows: list[Row], *, alarm: bool) -> str:
    """Render the value card: the value and the entity rows that hold it now."""
    body = _template("value.html").substitute(value=escape(value), rows=_tables(rows))
    return _page("Value", body, alarm=alarm)


def masked_page(value: str, *, alarm: bool) -> str:
    """Render a masked cell: an open column's value that looked like personal data."""
    body = _template("masked.html").substitute(value=escape(value))
    return _page("Masked value", body, alarm=alarm)


def person_page(row: Row, *, alarm: bool) -> str:
    """Render the person card: the shown columns of one entity row."""
    fields = "\n".join(f"<tr><th>{escape(c)}</th><td>{_cell(v)}</td></tr>" for c, v in row.fields)
    body = _template("person.html").substitute(
        entity=escape(row.entity), pk=_cell(row.pk), fields=fields
    )
    return _page(row.entity, body, alarm=alarm)


def index_page(*, alarm: bool) -> str:
    """Render the landing page after login."""
    return _page("Signed in", _template("index.html").substitute(), alarm=alarm)
