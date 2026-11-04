"""The audit log's chain: each line links the one before; verify finds the first break."""

import json
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

from incognito_sql.core import audit_chain
from incognito_sql.core.audit import AuditLog
from incognito_sql.core.audit_chain import Anchor, Chain, last_line
from incognito_sql.core.audit_verify import verify
from incognito_sql.core.tokens.crypto import Cipher

KEY = bytes(range(32))
CHILD = """
import sys
from pathlib import Path
from incognito_sql.core.audit import AuditLog
from incognito_sql.core.audit_chain import Anchor, Chain
from incognito_sql.core.tokens.crypto import Cipher
log, store, count = Path(sys.argv[1]), Path(sys.argv[2]), int(sys.argv[3])
anchor = Anchor(store)
audit = AuditLog(log, Chain(Cipher(bytes(range(32))), anchor))
for _ in range(count):
    audit.record(
        outcome="ok", reason=None, tables=["people"], row_count=1, ms=1, sql_tokenized=None
    )
anchor.close()
"""


def _write(audit: AuditLog, count: int) -> None:
    for i in range(count):
        audit.record(
            outcome="ok", reason=None, tables=["people"], row_count=i, ms=1, sql_tokenized=None
        )


@pytest.fixture
def chained(tmp_path: Path) -> Iterator[tuple[Path, Anchor]]:
    log, anchor = tmp_path / "f.audit.jsonl", Anchor(tmp_path / "f.tokens.db")
    _write(AuditLog(log), 2)  # written before the chain began
    _write(AuditLog(log, Chain(Cipher(KEY), anchor)), 4)
    yield log, anchor
    anchor.close()


def _lines(log: Path) -> list[str]:
    return log.read_text(encoding="utf-8").splitlines()


def _put(log: Path, lines: list[str]) -> None:
    log.write_text("".join(f"{line}\n" for line in lines), encoding="utf-8")


def test_a_whole_chain_holds_from_the_lines_before_it_to_its_anchor(
    chained: tuple[Path, Anchor],
) -> None:
    log, anchor = chained
    lines = _lines(log)
    assert [json.loads(line).get("n") for line in lines] == [None, None, 0, 1, 2, 3]
    verdict = verify(log, Cipher(KEY), anchor.get())
    assert verdict.holds, verdict.broken
    assert (verdict.lines, verdict.before_chain, verdict.checked) == (6, 2, 4)
    assert verdict.anchor == "number 3, matches"
    assert last_line(log) == lines[-1]
    links = [json.loads(line)["prev"] for line in lines[2:]]
    assert all(len(x) == 64 and x.isalpha() for x in links)  # never a number


@pytest.mark.parametrize(
    ("change", "found"),
    [
        (
            lambda ls: [*ls[:3], ls[3].replace('"row_count": 1', '"row_count": 9'), *ls[4:]],
            "line 4 or 5: edited",
        ),
        (lambda ls: ls[:3] + ls[4:], "line 4: numbers 1 to 1 are missing"),
        (lambda ls: [*ls[:4], ls[3], *ls[4:]], "line 5: number 1 inserted or repeated after 1"),
        (lambda ls: ls[:-1], "the log ends at number 2, the anchor at 3: its tail is cut"),
        (lambda ls: [*ls, ls[-1]], "line 7: number 3 inserted or repeated after 3"),
        (lambda ls: ls[:1] + ls[2:], "line 1 or 2: edited"),  # a line before the chain, removed
    ],
)
def test_verify_names_the_first_break(
    chained: tuple[Path, Anchor], change: object, found: str
) -> None:
    log, anchor = chained
    _put(log, change(_lines(log)))  # type: ignore[operator]
    verdict = verify(log, Cipher(KEY), anchor.get())
    assert verdict.broken == found


def test_another_key_cannot_write_a_chain_that_holds(chained: tuple[Path, Anchor]) -> None:
    log, anchor = chained
    assert verify(log, Cipher(bytes(32)), anchor.get()).broken == "line 2 or 3: edited"
    assert verify(log, Cipher(KEY), None).anchor == "none kept: a cut tail is not seen"


def test_processes_appending_at_once_keep_one_chain(tmp_path: Path) -> None:
    log, store = tmp_path / "f.audit.jsonl", tmp_path / "f.tokens.db"
    Anchor(store).close()
    children = [
        subprocess.Popen([sys.executable, "-c", CHILD, str(log), str(store), "25"])  # noqa: S603
        for _ in range(3)
    ]
    assert [child.wait(timeout=120) for child in children] == [0, 0, 0]
    anchor = Anchor(store)
    verdict = verify(log, Cipher(KEY), anchor.get())
    anchor.close()
    assert verdict.holds, verdict.broken
    assert verdict.checked == 75


@pytest.mark.parametrize(
    ("content", "last"),
    [
        (b"", None),
        (b"\n\n", None),
        (b"one", "one"),
        (b"one\ntwo-is-longer\n", "two-is-longer"),
        (b"one\r\ntwo-is-longer\r\n", "two-is-longer"),
        (b"one\ntwo-is-longer\r\n\n\n", "two-is-longer"),
        (b"one-is-long\nab\n", "ab"),
    ],
)
def test_the_last_line_is_found_across_read_steps(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, content: bytes, last: str | None
) -> None:
    monkeypatch.setattr(audit_chain, "_STEP", 3)  # every line spans several steps
    log = tmp_path / "a.jsonl"
    log.write_bytes(content)
    assert last_line(log) == last
