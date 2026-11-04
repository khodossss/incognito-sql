# ruff: noqa: RUF001
import time
from collections.abc import Callable
from decimal import Decimal

import pytest

from incognito_sql.core.output.detect import looks_personal

POSITIVE = [
    "ivan@example.com",
    "write to ivan.p@mail.example.org please",
    "+972 50 123 4567",
    "050-123-4567",
    "(050) 123 4567",
    "0501234567",
    "4111 1111 1111 1111",
    "4111-1111-1111-1111",
    "4111111111111111",
    "GB82 WEST 1234 5698 7654 32",
    "DE89370400440532013000",
    "-----BEGIN PRIVATE KEY-----",
    "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.abcdEFGHijklMNOPqrst",
    "d41d8cd98f00b204e9800998ecf8427ed41d8cd98f00b204e9800998ecf8427e",
    "sk-abcdefghijklmnop1234",
    "ghp_abcdefghijklmnop1234",
    "AKIAIOSFODNN7EXAMPLE",
    "aB3dE5gH7jK9mN1pQ3sT5vW7yZ9bD1fH3jL5nP7r",
    1234567890,
    -1234567890,
    "see 4111 1111 1111 1111 for payment",
    "iban GB82 WEST 1234 5698 7654 32 here",
    "call +972 50 123 4567 now",
    " +972 50 123 4567",
    "＋972 50 123 4567",
    "ivan＠example.com",
    "05\u200b0-123-4567",
    "050/123/4567",
    "050–123–4567",
    {"contact": "ivan@example.com"},
    ["ok", ("x", "+972 50 123 4567")],
]

NEGATIVE = [
    "Haifa",
    "2026-01-15",
    "2026-01-15 10:30:00",
    "2020-2025",
    "1234.56",
    "1234567.89",
    "123456789",
    123456789,
    42,
    3.14,
    "ORD-2026-0042",
    "6f1c3a52-8e0b-4b7e-9a4d-2f1c8d7e5a10",
    "GB82 WEST 1234 5698 7654 33",
    "sk-1",
    "a.b@c",
    "the quick brown fox jumps over the lazy dog today again",
    "very-long-subdomain.example.company.com.example.org",
    "",
    None,
    True,
    -1234567,
    -12345.67,
    -73.9857123,
    Decimal("-12345.67"),
    Decimal("12345.67"),
    "-1234567",
    "-73.9857123",
    "15/01/2026",
    "2026/01/15",
    "call me maybe, +1 soon",
    {"a": 1, "b": ["x", 2.5]},
    b"4111111111111111",
]


@pytest.mark.parametrize("value", POSITIVE)
def test_personal_looking_values_match(value: object) -> None:
    assert looks_personal(value)


@pytest.mark.parametrize("value", NEGATIVE)
def test_ordinary_values_do_not_match(value: object) -> None:
    assert not looks_personal(value)


BIG = 100_000
SHAPES: list[Callable[[int], str]] = [
    lambda n: "a" * n,
    lambda n: "1" * n,
    lambda n: "1 " * (n // 2),
    lambda n: "aB3-" * (n // 4),
    lambda n: "a" * n + "@" + "b" * n,
    lambda n: "a" * (n // 25) + "@" + "b" * (n // 25),
    lambda n: "@" * n,
    lambda n: "a@" * (n // 2),
    lambda n: "+" * n,
    lambda n: "+1" + " " * n,
    lambda n: "ab12" + "c" * n,
    lambda n: "ab12 " * (n // 5),
    lambda n: "eyJ" + "a" * n,
]


def _best_of_five(cell: str) -> float:
    times = []
    for _ in range(5):
        started = time.perf_counter()
        looks_personal(cell)
        times.append(time.perf_counter() - started)
    return min(times)


@pytest.mark.parametrize("shape", SHAPES)
def test_detection_is_linear(shape: Callable[[int], str]) -> None:
    # Growth, not wall time: 8x the input may cost at most 24x (quadratic would be 64x).
    small, big = _best_of_five(shape(BIG // 8)), _best_of_five(shape(BIG))
    assert big < 24 * max(small, 1e-4)
    assert big < 2.0
