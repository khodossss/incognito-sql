# Threat model

incognito-sql is an MVP and has not been audited. Found a way for a hidden value to reach
the model? Report it privately: see [SECURITY.md](../SECURITY.md).

The server is one layer; the database login and the OS account it runs as are the others.
For other people's data, run it in the *closed* installation profile
([docs/deployment.md](deployment.md)), and read what it does not protect against
before you rely on it.

## What it does not protect against

1. **Pseudonymization, not anonymization.** Quasi columns are shown as they are. City,
   birth date and postcode together can single out one person; the server does not
   coarsen them. Declare such a column hidden or identifier if the combination matters.
2. **A model with a shell, in the convenient profile.** An agent that runs commands as the
   server's OS user can read the client's MCP settings or the environment, find the DSN
   and connect to the database directly, or read a SQLite file whole. The closed profile
   ([docs/deployment.md](deployment.md)) runs the server as another OS user that
   alone holds the secrets; `incognito-sql check` shows which profile you have. Docker
   is no boundary for an agent whose account controls Docker.
3. **"Does this person exist?"** A literal a human typed is allowed in `WHERE`
   (`full_name = 'Ivan Petrov'`), so a model can test whether a value exists. The literal
   budget limits how many distinct values it can test; within the budget, single questions
   remain possible. Lower `limits.literal_budget` if that matters.
4. **People in open columns.** Notes, addresses, external ids can hold personal data.
   The declaration is yours; `init` lists the contradictions it sees and the output mask
   catches values that look personal, later too, but a name inside a note looks like any
   text.
5. **An agent in your browser.** An agent that drives your own browser (computer use, a
   browser extension) carries your session cookie and sees the cards exactly as you do;
   an agent running as your OS user can also copy the cookie from the browser's files and
   read cards without you until the session ends (8 hours by default, `session_ttl_s`). A
   password would not help: the agent sees what you type, or replaces the file that holds
   it. Do not let an agent drive the browser you open cards in, and run the agent under
   another OS account (a separate user, WSL, a dev container) so it cannot read that
   browser's files.
6. **Scan order.** With an index on an identifier column, a result that depends on the
   order rows are read in can reveal the rank of a hidden value, about one bit per query:
   equal values printed differently under `MAX` / `MIN`, `GROUP BY`, `DISTINCT` or
   `UNION`, a runtime error inside `EXISTS`, float rounding in `SUM` / `AVG` of a column.
7. **Timing.** A token compared with a column of another type, none of whose stored forms
   fit that type, becomes a constant false condition that the database answers quickly.
   On a large table the difference in latency tells whether the hidden value fits the type.
8. **Parsing is the boundary.** Any difference between how sqlglot reads a query and how
   the DBMS runs it is a potential leak. The attack corpus and the five-DBMS test matrix
   measure this; they do not prove there is none.
9. **Per-DBMS gaps.** SQLite and DuckDB have no statement timeout of their own; the server
   cuts a statement at `statement_timeout_ms` (a progress check on SQLite, an interrupt on
   DuckDB). SQL Server has no read-only session. SQLite, DuckDB and
   SQL Server give no SQLSTATE, so their errors arrive as a bare `db_error`. On these
   systems the database login and file permissions carry the weight.
10. **A secret typed where a file, a name or a URL belongs.** The command line never
    repeats a value typed into a wrong argument in its error messages. But the path of a
    file it is about to write (`connect --file`, your home folder, `demo`'s folder,
    `init --out`) is printed as typed, in the question before writing, in the line that
    reports it written and in the next steps; only that path, never the DSN or a value
    from the database. A path built from `CODEX_HOME` is not printed: it is "the Codex
    config (from CODEX_HOME)". What makes up the client's entry is printed and written as
    typed: the server's name (`--name`, any letters, digits, `-` and `_` up to 64; it is
    the entry's key in the client's settings), the path of `--config` (also in the advice
    to run `check`) and the service's URL (`--url`; `connect` refuses a login, a query or a
    fragment in it, but not a token in its path or host). A secret pasted there shows on
    your terminal and, except for the paths printed before writing, in the client's
    settings.

## The database login is the real guard

The server never writes, and it opens read-only sessions where the DBMS has them; the
login is what holds when anything else slips. Give it one that can only read, ideally only
the declared tables:

```sql
-- Postgres (the server also sets default_transaction_read_only and statement_timeout)
CREATE ROLE reader LOGIN PASSWORD '...';
GRANT USAGE ON SCHEMA public TO reader;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO reader;
-- MySQL (the session is also set READ ONLY, with max_execution_time)
CREATE USER 'reader' IDENTIFIED BY '...';
GRANT SELECT ON shop.* TO 'reader';
-- SQL Server: no read-only session exists, the login is the only guard
CREATE LOGIN reader WITH PASSWORD = '...';   -- then, in the database:
CREATE USER reader FOR LOGIN reader;
ALTER ROLE db_datareader ADD MEMBER reader;
```

SQLite and DuckDB files are opened read-only (SQLite `mode=ro` with an authorizer, DuckDB
`read_only` with external access off); let the server's OS user only read the file.

## Audit log

`<name>.audit.jsonl` gets one JSON line per query: time, outcome, refusal reason, tables
touched, row count, duration, and for a query that passed the checks its SQL. Once the
query has spent its budgets, every literal compared with an identifier is replaced by a
token, also when the database refuses it; a query refused before that (an invalid token,
a limit, the budget) logs `'?'` in place of such a literal and issues no token. A query
refused by the checks logs no SQL. Result rows are never logged. `masked`
lists the columns whose cells were masked as looking personal, with the kind seen
(`orders.note: email`); the first time a column is masked, a warning on stderr says so and
how to settle it. `columns` names the base columns the query names (`people.full_name`),
refused or not; the columns behind a `*` once the query passed the checks. `probes`
is what the query spent of the probe budget. Start-up
errors on stderr name the failed step and the exception type, never the DSN or the
driver's message.

## What your profile holds on your data: `assess`

```bash
incognito-sql assess --config field.yaml --env-file secrets.env --fail-on breaks
```

Run as the service's user, with its config and secrets. For every identifier column of an
entity table, `assess` asks the server what the benchmark asks: queries that cut a piece
out of the values (L1 whole, L2 a part), and series of yes-or-no questions that infer a
prefix, a substring, the length, the order or the existence of a value (L3), each in
several forms. The true values are read from the database directly and compared with the
answers. The report holds counts per column and level and a verdict against the column's
profile, never a value. The server is opened on a copy of the config in a temporary
directory, with its own budgets, audit log and tokens, so live agents keep theirs.

`--targets N` values per column (3); `--capacity` also runs the series with the literal
and probe budgets lifted, to show what each channel carries and, as hours, how long the
config's own budgets make the series wait (`-` when nothing was read, `closed` when a
budget the series needs is 0, `unlimited` when none it needs has a cap);
`--json` for CI; `--fail-on breaks` exits 1 when a column breaks its profile's claim. The
series send thousands of queries per column with `--capacity`: run it on a replica.
`assess` is tested on all five DBMS (`tests/integration/test_matrix_assess.py`).

Columns the config does not name are hidden: every cut of them must be refused, and the
report lists each as `hidden: refused N/N`.

## For your DPO: `report`

```bash
incognito-sql assess --config field.yaml --json > assess.json
incognito-sql report --config field.yaml --assess assess.json
```

One row per column: its class and profile, what the model may learn of it by that
claim, what `assess` measured if its report is given, and over the period how many
queries named the column, their outcomes and refusal reasons, and how many answers had
its cells masked and of what kind. A column the config does not name appears as hidden,
with the attempts on it; a query refused before its columns were resolved (its syntax,
the allowlist) names none and is counted in the heading, as are masks of computed
columns, which belong to no base column, and the probes spent (lines written before the
log counted them, apart). `report` only reads files, the config, the `assess` report and the
audit log; it asks nothing of the database. The period is the last 30 days, named in the
report's heading; `--since YYYY-MM-DD` or `--since all`; `--json`. Counts, names,
classes, profiles and reasons only: no value and no query, not even tokenized.
