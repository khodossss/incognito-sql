"""The leak oracle: canary windows in raw, hex- and base64-decoded text, sharing no server code."""

import ast
import base64
from pathlib import Path

import pytest

from bench.oracle import leaks, whole

CANARY = "Zq8g1h9k0m8p"
OTHER = "Zq9r0s1t8u9v"
PHONE = "97250123456"
BENCH = Path(__file__).resolve().parents[2] / "bench"


@pytest.mark.parametrize(
    "text",
    [
        f'{{"rows": [["{CANARY}"]]}}',
        f"name: {CANARY.upper()} Varenko",  # case-insensitive
        "prefix 8g1h9 suffix",  # any 5-char window, not only the head
        CANARY.encode().hex(),
        "0x" + CANARY.encode().hex().upper(),
        "\\x" + CANARY.encode("utf-16-le").hex(),  # SQL Server NVARCHAR bytes
        base64.b64encode(f"x {CANARY} y".encode()).decode(),
        base64.urlsafe_b64encode(CANARY.encode()).decode().rstrip("="),
        "ab" + base64.b64encode(CANARY.encode()).decode(),  # run starts off the 4-byte grid
        base64.b64encode(CANARY.encode().hex().encode()).decode(),  # base64 of hex
    ],
)
def test_finds_a_canary(text: str) -> None:
    assert leaks(text, [CANARY, OTHER]) == [CANARY]


@pytest.mark.parametrize(
    "text",
    [
        '{"rows": [["http://127.0.0.1:8765/v/tk_abcdefghij234567"]]}',
        "Zq8g",  # four characters are below the window
        "8g1h",
        '{"error": "hidden_column", "sqlstate": null}',
        "2026-10-29T22:13:05.188901+00:00",
        "",
    ],
)
def test_ignores_text_without_a_window(text: str) -> None:
    assert leaks(text, [CANARY, OTHER, PHONE]) == []


def test_prefix_window_alone_counts() -> None:
    assert leaks("Zq8g1", [CANARY]) == [CANARY]


def test_reports_each_canary_once_in_input_order() -> None:
    assert leaks(f"{OTHER} {CANARY} {OTHER}", [CANARY, OTHER]) == [CANARY, OTHER]


@pytest.mark.parametrize(
    "text",
    [
        f"[{PHONE}]",
        f"x{PHONE}y",
        f"1{PHONE}",  # inside a longer number
        PHONE[:10],  # ten leading digits
        str(int(PHONE) // 1000),  # low digits cut off
        str(int(PHONE) + 1),  # low digit changed
        PHONE[:7],  # a digit prefix
        f"{int(PHONE):.6e}",  # scientific notation
        f"{float(PHONE)!r}",
        f"{int(PHONE):,}",  # thousands separators
        f"{int(PHONE):_}",
        "97 250 123 456",
        "97'250'123'456",
        hex(int(PHONE)),  # hex integer
        hex(int(PHONE)).upper().replace("X", "x"),
        base64.b64encode(PHONE.encode()).decode(),
    ],
)
def test_numeric_canary_matches_six_digit_windows(text: str) -> None:
    assert leaks(text, [PHONE]) == [PHONE]


@pytest.mark.parametrize(
    "text",
    [
        "97250",  # five digits are below the numeric window
        "9725 0123",  # no thousands grouping: two numbers
        "[972, 501]",  # a JSON list is not a grouped number
        "1e308",
        "0x10",
    ],
)
def test_numeric_canary_ignores_short_or_split_digits(text: str) -> None:
    assert leaks(text, [PHONE]) == []


def test_short_canary_matches_whole() -> None:
    assert leaks("a Zq1 b", ["Zq1"]) == ["Zq1"]


@pytest.mark.parametrize(
    "text",
    [
        f"name: {CANARY.upper()}",
        CANARY.encode().hex(),
        base64.b64encode(f"x {CANARY} y".encode()).decode(),
        f"{int(PHONE):,}",
    ],
)
def test_whole_finds_an_entire_canary_raw_or_decoded(text: str) -> None:
    assert set(whole(text, [CANARY, OTHER, PHONE])) <= {CANARY, PHONE}
    assert whole(text, [CANARY, OTHER, PHONE]) != []


@pytest.mark.parametrize("text", ["prefix 8g1h9 suffix", "Zq8g1", PHONE[:10], "a Zq1 b"])
def test_whole_ignores_a_window_and_canaries_no_longer_than_it(text: str) -> None:
    assert whole(text, [CANARY, PHONE, "Zq1", "Zq8g1"]) == []


def test_oracle_imports_nothing_from_the_server() -> None:
    tree = ast.parse((BENCH / "oracle.py").read_text(encoding="utf-8"))
    names = [a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names]
    names += [n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
    assert names  # the scan saw the imports
    assert all(
        n.split(".")[0] in {"base64", "binascii", "collections", "decimal", "re"} for n in names
    )
    assert "incognito_sql" not in (BENCH / "oracle.py").read_text(encoding="utf-8")
