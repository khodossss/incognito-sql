"""Fixed catalog of rejection reasons; a rejection never carries free text."""

from enum import StrEnum


class Reason(StrEnum):
    """Why a query was rejected. The value is the only text a rejection exposes."""

    PARSE_ERROR = "parse_error"
    MULTIPLE_STATEMENTS = "multiple_statements"
    LIMIT_EXCEEDED = "limit_exceeded"
    NODE_NOT_ALLOWED = "node_not_allowed"
    UNKNOWN_COLUMN = "unknown_column"
    AMBIGUOUS_COLUMN = "ambiguous_column"
    HIDDEN_COLUMN = "hidden_column"
    PII_OPERATION = "pii_operation"
    PII_JOIN_WITH_OPEN = "pii_join_with_open"
    LITERAL_TYPE_MISMATCH = "literal_type_mismatch"
    INVALID_TOKEN = "invalid_token"  # noqa: S105
    LITERAL_BUDGET = "literal_budget"
    PROBE_BUDGET = "probe_budget"
    LITERALS_OFF = "literals_off"
    PROBES_OFF = "probes_off"
    RATE_LIMIT = "rate_limit"
    SYSTEM_CATALOG = "system_catalog"
    EQUAL_SPELLINGS = "equal_spellings"
    FALLIBLE_SUBQUERY = "fallible_subquery"
    FLOAT_AGGREGATE = "float_aggregate"
    HIDDEN_ROWS = "hidden_rows"
    DB_ERROR = "db_error"
    INTERNAL_ERROR = "internal_error"


class Rejection(Exception):  # noqa: N818
    """A query was refused. `str()` is the reason value only: no SQL text, no values."""

    def __init__(
        self, reason: Reason, sqlstate: str | None = None, detail: str | None = None
    ) -> None:
        """Hold the reason and, for database errors, the SQLSTATE and a scrubbed message."""
        super().__init__(reason.value)
        self.reason = reason
        self.sqlstate = sqlstate
        self.detail = detail
