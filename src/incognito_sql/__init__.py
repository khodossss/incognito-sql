"""Pseudonymizing MCP server for LLM access to databases with personal data."""

import logging

__version__ = "0.0.0"

# sqlglot logs unparsable SQL verbatim (with its literals); keep it off stderr.
_sqlglot_log = logging.getLogger("sqlglot")
_sqlglot_log.addHandler(logging.NullHandler())
_sqlglot_log.propagate = False
