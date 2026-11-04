"""The model's outer ORDER BY decides the order of the answer; ties come out in random order."""

from incognito_sql.core.pipeline import Gateway

SQL = "SELECT p.city, p.id, o.id FROM people AS p CROSS JOIN orders AS o"


def test_rows_follow_the_outer_order_by(gateway: Gateway) -> None:
    for direction, cities in (("", ["Eilat"] * 3 + ["Haifa"] * 6), (" DESC", None)):
        out = gateway.query(f"{SQL} ORDER BY p.city{direction}, o.id", "c1")
        rows = out["rows"]
        assert isinstance(rows, list), out
        got = [r[0] for r in rows]
        assert got == (cities or ["Haifa"] * 6 + ["Eilat"] * 3)
        ids = [r[2] for r in rows if r[0] == "Haifa"]
        assert ids == sorted(ids)


def test_tied_rows_vary(gateway: Gateway) -> None:
    seen = set()
    for _ in range(30):
        out = gateway.query(f"{SQL} ORDER BY p.city", "c1")
        rows = out["rows"]
        assert isinstance(rows, list), out
        seen.add(tuple((r[1], r[2]) for r in rows if r[0] == "Haifa"))
    assert len(seen) > 1


def test_no_order_by_is_shuffled(gateway: Gateway) -> None:
    seen = {
        tuple(map(tuple, gateway.query(SQL, "c1")["rows"]))  # type: ignore[call-overload]
        for _ in range(30)
    }
    assert len(seen) > 1
