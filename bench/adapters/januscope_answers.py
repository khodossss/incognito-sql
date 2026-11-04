"""How JanuScope's answers read: each bundled lens's upstream prints rows its own way.

Postgres MCP Pro prints a Python list of row dicts (``Decimal('1.50')``,
``datetime.date(...)``); the MySQL server prints a JSON list of row objects followed by a
timing line; mcp-sqlite prints an HTML table. JanuScope's sqlGuard refuses with a JSON-RPC
error (read as a refusal by ``bench/adapters/calls.py``); upstream SQL errors are text
beginning with ``Error``, or an error result.
"""

import ast
import json
from html.parser import HTMLParser

from bench.adapters.base import ANSWERED, REFUSED, Rows, dict_rows

_TIMING = "\nQuery execution time"


def parse(text: str, is_error: bool) -> tuple[str, Rows | None]:  # noqa: FBT001 -- MCP flag
    """Read an answer of any of the three upstreams; an error is a refusal."""
    body = text.strip()
    if is_error or body.startswith("Error"):
        return REFUSED, None
    if body.startswith("<table>"):
        return ANSWERED, table_rows(body)
    head = body.split(_TIMING, 1)[0]
    try:
        records = json.loads(head)
    except json.JSONDecodeError:
        try:
            tree = ast.parse(head, mode="eval")
        except SyntaxError as exc:  # prose: an answer without rows
            raise ValueError(head[:40]) from exc
        records = python_value(tree.body)
    return ANSWERED, dict_rows(records)


def python_value(node: ast.expr) -> object:
    """Evaluate a printed Python literal; a constructor call becomes its argument's text."""
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, (ast.List, ast.Tuple)):
        return [python_value(e) for e in node.elts]
    if isinstance(node, ast.Dict):
        return {
            python_value(k): python_value(v)
            for k, v in zip(node.keys, node.values, strict=True)
            if k
        }
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        return f"-{python_value(node.operand)}"
    if isinstance(node, ast.Call):  # Decimal('1.5'), datetime.date(2001, 2, 3), UUID('...')
        args = [str(python_value(a)) for a in node.args]
        return args[0] if len(args) == 1 else ast.unparse(node)
    msg = f"not a printed literal: {ast.unparse(node)[:40]}"
    raise ValueError(msg)


class _Table(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.rows: list[list[str]] = []
        self._cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: object) -> None:  # noqa: ARG002 -- HTMLParser
        if tag == "tr":
            self.rows.append([])
        elif tag in {"td", "th"}:
            self._cell = []

    def handle_endtag(self, tag: str) -> None:
        if tag in {"td", "th"} and self._cell is not None and self.rows:
            self.rows[-1].append("".join(self._cell))
            self._cell = None

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)


def table_rows(html: str) -> Rows:
    """Return the body rows of an HTML table; a ``None`` cell is SQL NULL."""
    table = _Table()
    table.feed(html)
    return [[None if c == "None" else c for c in row] for row in table.rows[1:]]
