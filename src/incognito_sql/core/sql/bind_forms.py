"""Strict checks of written forms a bind compared with an identifier may carry.

Dates, moments, UUIDs, booleans and text; numbers are in `bind_domain`.
"""

import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
_STAMP = re.compile(r"\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(\.\d{1,6})?(?P<zone>[+-]\d{2}:\d{2})?")
_UUID = re.compile(r"[0-9a-fA-F]{8}(-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}")
_FIRST = datetime(1, 1, 1)  # noqa: DTZ001 -- a wall-clock bound, compared with naive values
_LAST = datetime(9999, 12, 31, 23, 59, 59)  # noqa: DTZ001 -- rounding past it may overflow
_MOST_OFFSET = timedelta(hours=14)


@dataclass(frozen=True)
class Dates:
    """Calendar dates of years 0001 to 9999, written YYYY-MM-DD."""

    def check(self, raw: str) -> str | None:
        """Return the date in ISO form, if valid."""
        if not _DATE.fullmatch(raw):
            return None
        try:
            return date.fromisoformat(raw).isoformat()
        except ValueError:
            return None


@dataclass(frozen=True)
class Stamps:
    """Date and time from `first` to 9999-12-31 23:59:59; an explicit offset iff `zone`."""

    zone: bool
    first: datetime = _FIRST
    millis: bool = False  # whole milliseconds, written with a T (T-SQL DATETIME)

    def check(self, raw: str) -> str | None:
        """Return the moment in ISO form, if valid and in range."""
        found = _STAMP.fullmatch(raw)
        if found is None or (found["zone"] is not None) != self.zone:
            return None
        try:
            moment = datetime.fromisoformat(raw)
            instant = moment.astimezone(UTC).replace(tzinfo=None) if self.zone else moment
        except (ValueError, OverflowError):
            return None
        offset = moment.utcoffset() or timedelta()
        wall = moment.replace(tzinfo=None)
        if abs(offset) > _MOST_OFFSET or not all(self.first <= m <= _LAST for m in (wall, instant)):
            return None
        if self.millis:
            return None if moment.microsecond % 1000 else moment.isoformat(timespec="milliseconds")
        return moment.isoformat(sep=" ")


@dataclass(frozen=True)
class Uuids:
    """UUIDs written 8-4-4-4-12 in hex."""

    def check(self, raw: str) -> str | None:
        """Return the UUID in lower case, if canonical."""
        return raw.lower() if _UUID.fullmatch(raw) else None


@dataclass(frozen=True)
class Booleans:
    """Only `true` and `false`, in any case."""

    def check(self, raw: str) -> bool | None:
        """Return the boolean, if spelled as one."""
        return {"true": True, "false": False}.get(raw.lower())


@dataclass(frozen=True)
class Texts:
    """Any text; `no_nul` refuses a NUL character (PostgreSQL text cannot hold one)."""

    no_nul: bool = False

    def check(self, raw: str) -> str | None:
        """Return the text itself, if storable."""
        return None if self.no_nul and "\0" in raw else raw


@dataclass(frozen=True)
class Nothing:
    """A type no raw form is checked for: nothing is bound."""

    def check(self, raw: str) -> None:  # noqa: ARG002
        """Return None."""
        return
