"""The query rate: one sliding window for the whole installation, refused queries count."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from incognito_sql.core.config import Limits
from incognito_sql.core.errors import Reason, Rejection
from incognito_sql.core.rate import QueryRate

NOW = datetime(2026, 11, 2, 12, 0, tzinfo=UTC)


def test_the_window_refuses_past_the_rate_and_frees_up(tmp_path: Path) -> None:
    limits = Limits(query_rate=3, query_window_s=60)
    first, second = QueryRate(tmp_path / "t.db", limits), QueryRate(tmp_path / "t.db", limits)
    try:
        first.hit(NOW)
        second.hit(NOW)  # another process of the installation: the same window
        first.hit(NOW + timedelta(seconds=30))
        with pytest.raises(Rejection) as refused:
            second.hit(NOW + timedelta(seconds=31))
        assert refused.value.reason is Reason.RATE_LIMIT
        second.hit(NOW + timedelta(seconds=61))  # the first two left the window
    finally:
        first.close()
        second.close()
