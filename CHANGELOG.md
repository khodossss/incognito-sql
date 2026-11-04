# Changelog

All notable changes to incognito-sql are listed here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

0.0.1 and 0.0.2 were stages of development and were never released as packages; their dates
are when the stage was finished. Numbers from the benchmark are in
[docs/benchmark.md](docs/benchmark.md), not here.

## [0.1.0] - 2026-11-04

The first release. It holds everything since 0.0.3, which was never published: 0.0.4 and
0.0.5 did not come out on their own, and 0.0.5a1 was a test build.

### Added

- **Setup in two ways, one sequence of steps**: `incognito-sql guide` prints the steps for
  an agent in a harness, `incognito-sql setup` walks the same steps in the terminal with
  arrow keys (numbers where the console cannot draw them), and `incognito-sql secret`
  takes a password typed outside the chat.
- **`incognito-sql skill <client>`** gives the agent of Claude Code, Codex or OpenCode a
  skill that says how to start the setup: run `guide` of this exact version and walk the
  human through it, never asking for a secret in the chat. Asked to connect a database
  through incognito-sql, the agent then knows where to begin. It is written after a yes,
  or with `--yes`; a skill already there with other text is replaced only after that yes.
- **The incognito-sql plugin for Claude Code and Codex**: the same skill, installed once
  from the marketplace `khodossss/incognito-sql` (`claude plugin install incognito-sql@incognito-sql`,
  `codex plugin add incognito-sql@incognito-sql`). It carries no server: the agent sets
  up the server per project through `guide`.
- **Refusals tell the agent what to do next.** A refusal carries `retry` (`rewrite`,
  `ask_user` or `stop`) and a fixed `hint` per reason; neither names a value, a column or
  database text.
- **Row rules** in the declaration (`row_rules`): hide rows or cells by a condition on
  open columns, under every profile. A query that could fail on a hidden row is refused
  (`hidden_rows`).
- **`incognito-sql try --config <file> "<sql>"`**: the verdict on a query, the base
  columns it reads and its output columns, without running it.
- **`incognito-sql assess`**: judges what the model can learn about each column on your own
  database and protection profile, and how long the literal budget makes a series of
  probes wait.
- **`incognito-sql report`**: a per-column report for a data protection officer: what the
  model may learn of each column and what it asked.
- **`incognito-sql diff <old> <new>`**: what a new declaration lets the model see or link
  more (`WIDENED`) or less (`NARROWED`); with `--ci` it exits 1 on any widening.
- **`incognito-sql demo`** writes an invented shop database to try the server on, and
  **`incognito-sql connect <client>`** prints the MCP entry for Claude Code, Codex, Cursor
  or OpenCode (`--write` adds it to the client's settings file); the entry names the DSN's
  variable, never its value.
- **`incognito-sql audit verify`**: the audit log is a hash chain, and `verify` names its
  first break.
- Each audit line names the base columns the query read, refused or not.
- `limits.probe_budget` (default 100): probes of identifier values (`<`, `>`, `BETWEEN`,
  `<>`, `LIKE`, sort keys, `MIN` / `MAX`, `length()`) per window of the installation.
- `limits.query_rate` and `limits.query_window_s` (default 600 per 60 s): queries the
  installation answers per window, refused ones included.

### Changed

- A configuration error names the place of a bad value and never repeats the text typed
  there; a secret pasted into a command-line argument is refused and never echoed.

### Known gaps

- On Linux and macOS, `secret` and `env` keep a variable only in `--env-file`, and the
  setup steps of `guide` and `setup` do not pass one yet: there the closed case and the
  password step stop. Run those commands by hand with `--env-file`.

## [0.0.5a1] - 2026-11-03

A test build for hands-on checks in agent harnesses, installed only by its exact version
(`incognito-sql==0.0.5a1`). It holds everything of 0.1.0 except the skill and the plugin.

## [0.0.3] (not published)

### Added

- **Protection profiles** for identifier columns: `strict`, `balanced` and `permissive`,
  your own profiles under `protections`, and a profile per column under
  `column_protection`. A profile names the operations an identifier admits; none of them
  shows a value whole. `describe` tells the model which operations it may use.
- Under `permissive`: `length()` of an identifier, sorting by it, `MIN` / `MAX` of it (as a
  token), `<` `>` `BETWEEN`, `LIKE` and `<>` with a human literal. Each such literal spends
  the literal budget and is written to the audit log as `?`.
- `serve`, `service` and `check` warn when the profile in use admits more than `balanced`.
- Query forms accepted under every profile: `INTERSECT` and `EXCEPT`, a table alias
  repeated across their branches, a column outside `GROUP BY` when the whole non-null
  primary key of its table is grouped, `SUM` / `AVG` over a `CASE` of small non-negative
  integers, SQLite double-quoted strings, SQLite date functions and `instr` over open
  columns, catalog names with spaces, parentheses or hyphens.
- Under `permissive` only: window functions (never over an identifier), `SUM` / `AVG` over
  any expression, grouping by a primary key that can hold NULL.
- A cell of an open column that looks personal is masked as a link that shows the value to
  a signed-in human only; the first time a column is masked, a warning names it and the
  audit line lists it. `verified_open` lists columns checked by a human, whose values are
  not masked.
- `SECURITY.md`: how to report a way for a hidden value to reach the model.
- The package is licensed under Apache-2.0, and a release workflow publishes a tagged
  version to PyPI.
- The benchmark runs on sets we did not write (Spider, BIRD Mini-Dev, SecureSQL), takes
  more tools of the same kind, and judges every tool by levels of disclosure (a value
  whole, a piece of it, a fact about it) against what that tool claims.

### Changed

- **The default protection profile is `permissive`, which admits more than 0.0.2 did.**
  `strict` admits exactly what 0.0.2 admitted; set `protection: strict` or
  `protection: balanced` to keep the narrower behaviour.
- **`strict` now refuses some queries it used to answer**, closing what was left of the
  scan-order channel: `SUM` / `AVG` over float columns (`float_aggregate`); expressions
  that can fail on some rows inside `EXISTS`, `IN (SELECT ...)`, a scalar subquery or a
  `WITH` query (`fallible_subquery`); and, on MySQL and SQL Server, `GROUP BY`,
  `DISTINCT`, `MIN` / `MAX` and `UNION` over open text columns (`equal_spellings`).
  `strict` also prints a number one way whatever its type (`1.0` as `1`).
- The card sign-in lasts 8 hours by default (`session_ttl_s`).
- A query refused after the literal budget (a limit, a database error) has spent its
  literals; the README says so.
- `MIN` / `MAX` of an identifier counts as a place of its value under every profile, and a
  `RANGE` window frame with an offset over an identifier sort key is refused.

### Fixed

- The service (`incognito-sql service`) counted the literal budget of all its clients as
  one connection with no time window, so after `literal_budget` distinct literals it
  refused every new one for good, even after a restart. It now counts by the
  installation window only.
- Honest queries no longer refused: the query forms listed under Added, `CAST` of an open
  column, and a literal left of `IN` against an identifier, which now matches the value's
  spellings.

## [0.0.2] - 2026-10-31 (not published)

The strength of the protection is tested beyond the attack corpus.

### Added

- Differential fuzzing: random queries go through the server on all five DBMS, and any
  disagreement between the parser and the database is recorded.
- Red-team campaigns and honest questions through a real MCP client (Claude Code), run
  locally before a release.
- Mutation testing of the protective modules, weekly in CI.
- A demo database of invented data for those runs.

### Security

- A cell holding more candidate e-mails or card numbers than the detector examines is
  masked instead of passed.

## [0.0.1] - 2026-10-31 (not published)

The first version: safe to run on your own machine.

### Added

- An MCP server with two read-only tools: `query` runs one SQL `SELECT`, `describe` names
  the DBMS and lists the usable tables and columns with their classes, the number of
  hidden columns, and each table of people's `person_key`.
- A YAML declaration of every column: `identifier`, `quasi`, `free_text`, `secret` or
  `open`; a column it does not list is hidden. `entities` names the tables whose rows are
  people.
- Query checks: parser limits, an allowlist of syntax nodes, column lineage through
  aliases, subqueries and set operations, and a default-deny policy for identifier
  columns; system catalogs, `EXPLAIN` and several statements are refused.
- Only SQL regenerated from the checked tree runs, with literals and tokens as bind
  parameters, on a read-only session where the DBMS has one; a refusal or a database error
  reaches the model as a reason from a fixed list, never with a bound value.
- Tokens: each identifier value becomes a random `tk_...` token shared by its spellings,
  living 24 hours by default, kept in an encrypted store whose key lives in the OS
  keyring or in `INCOGNITO_SQL_KEY`. Labels mode (`web_enabled: false`) gives labels local
  to one answer instead.
- Local web cards that show a value or a person to a signed-in human, with a one-time
  sign-in link (`login`) and `web` to serve them alone.
- Output shaping: rows shuffled unless the query has `ORDER BY`, ties in random order,
  computed floats rounded, and cells of open columns that look personal masked.
- A literal budget: distinct human literals compared with identifiers, per connection and
  per window of the installation.
- An audit log with literals replaced by tokens; result rows are never logged.
- `init` writes a declaration scaffold with every column hidden and lists columns that
  look personal.
- PostgreSQL, MySQL, SQL Server, SQLite and DuckDB, with a statement time limit on each.
- The closed installation profile: `incognito-sql service` runs as its own OS user and
  serves MCP over HTTP on `127.0.0.1` behind a token; `--env-file`; `check` tells which
  profile an agent's account is in. [docs/deployment.md](docs/deployment.md) sets it up.
- A leakage benchmark: an attack corpus, an oracle that shares no code with the server,
  and other tools of the same kind on the same attacks.
