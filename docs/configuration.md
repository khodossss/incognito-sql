# Configuration

## How it works

1. **Declaration.** A YAML file gives each column a class, named by who sees the value:

   | Class | The model | You, on a card |
   |---|---|---|
   | `identifier` | a token | the value |
   | `open` | the value | the value |
   | `open_quasi` (city, birth date, postcode) | the value; it may identify in combination | the value |
   | `closed` (free text, health and other special data) | nothing | the value |
   | `closed_hidden` (passwords, keys) | nothing | nothing |

   A column the file does not list is hidden like `closed_hidden`. The names before
   0.1.2 (`quasi`, `free_text`, `secret`) are still read.
2. **Checked AST.** The query is parsed with sqlglot and checked against an allowlist of
   syntax nodes. A hidden column anywhere in the query is a refusal. An identifier column
   may only be selected, grouped, counted with `COUNT(DISTINCT ...)`, compared with `=` /
   `IN` to a token, to a literal a human typed, or to another identifier column, and only
   as far as its [protection profile](#protection-profiles) admits; the default
   `permissive` also lets it be sorted, measured, matched with `LIKE` and compared with
   `<` `>` `<>`. Other functions on it, and on `MIN` / `MAX` of it, are refused under every
   profile, as are system catalogs, `EXPLAIN` and more than one statement.
3. **Regenerated SQL.** Only SQL generated anew from the checked tree runs, never the
   model's text. Literals and tokens travel as bind parameters. The connection is read-only
   where the driver allows it (see [the database login](threat-model.md#the-database-login-is-the-real-guard)).
4. **Shaped output.** Rows are shuffled unless the outer query has an `ORDER BY`; then
   they follow its keys (never an identifier), ties in random order. Identifier cells
   become pseudonyms; any other cell that looks like personal data (e-mail, phone, card
   number, IBAN, key) is masked: with cards on, the mask is a link `/m/<token>` that shows
   the value to you, never to the model, and the audit log names the column (see
   [People in open columns](threat-model.md#what-it-does-not-protect-against)). A refusal is
   `{"error": <reason>, "sqlstate": ..., "retry": ..., "hint": ...}` with a reason from a
   fixed list and no database text, except a short syntax or name message that holds no
   bound value; `retry` and `hint` tell the agent what to do next
   ([Refusal codes](#refusal-codes)).

**Tokens.** Each distinct identifier value gets a random token `tk_` + 16 base32
characters, shared by its spelling variants (case, spaces) across columns, living 24 hours
by default. The model passes it back (`WHERE full_name = 'tk_...'`) to follow up.

**Two output modes.** With the web on (default), an identifier cell is a link
`http://127.0.0.1:<port>/v/<token>`. With `web_enabled: false` (labels mode), it is a
label local to one answer (`name_1`), with the primary keys of the entity rows that hold
it; the model follows up by key.

**Cards for the human.** A small web on `127.0.0.1` shows a value card (the value and the
entity rows holding it) and a person card. It answers 401 without a session, 400 to a
foreign `Host` header, and sends no telemetry. `incognito-sql login` opens a one-time link
(valid 5 minutes) that sets a session cookie for 8 hours.

The MCP surface is two read-only tools, `query` and `describe` (the DBMS, so the model
writes its dialect, the visible tables and columns, and the `person_key` of each table of
people). The server instructions ask the model to show a row that holds that key as one
link to the person card, labelled in the user's language. No tool reveals a value,
and no tool argument changes the rules: only the config does.

The lines are chained: each carries its number `n` and `prev`, a digest of the line
before keyed with the service's key and written in the letters a to p, so it never reads
as a number a value could be, and the number and digest of the last line are kept
in the token store too. `incognito-sql audit verify --config field.yaml` checks the chain
as the service's user and names the first break: a line edited, lines missing or
inserted, a tail cut. Lines written before the chain began are counted, not judged.
Several server processes may append at once, under a lock beside the log; keep the log
on a local disk, where that lock holds. Whoever holds the key and both files can still
rewrite everything: the chain shows tampering by anyone without them.

## Protection profiles

A profile names the operations an identifier column admits. Whatever the profile, the
server never shows an identifier value whole, never names a hidden column, never decodes
a token, keeps system catalogs, other databases and placeholders closed, and runs only SQL
regenerated from the checked tree.

| Operation | What it is | What the model can learn |
|---|---|---|
| `output` | select the column; the value leaves as a token or label | nothing beyond equal tokens |
| `eq_token` | `=` / `IN` with a token | nothing beyond equal tokens |
| `eq_literal` | `=` / `IN` with a literal a human typed | whether that value exists (L3) |
| `join_ident` | `JOIN` / `=` between two identifier columns | nothing beyond equal tokens |
| `group` | `GROUP BY` the column | nothing beyond equal tokens |
| `count_distinct` | `COUNT(DISTINCT column)` | nothing beyond equal tokens |
| `is_null` | `IS [NOT] NULL` in a condition | nothing a selected column does not show (a NULL comes back as `null`) |
| `length` | `length(column)` anywhere a number may stand | its length (L3) |
| `order` | `ORDER BY` the column, also in a window (without a `RANGE` offset), `MIN` / `MAX` (a token), `<` `>` `<=` `>=` `BETWEEN` with a literal or another identifier | where it sorts (L3) |
| `prefix` | `LIKE 'abc%'` (and `NOT LIKE`, `ILIKE` where the DBMS has it) | how it begins (L3) |
| `contains` | any other `LIKE` pattern | what it contains (L3) |
| `ne` | `<>` with a literal a human typed or another identifier | whether that value exists (L3) |

`strict` admits the first six, exactly what earlier releases did. `balanced` adds what opens
no new channel: today `is_null`. `permissive`, the default, admits every operation in the
table and will add part of a value in the output in a later release. Every literal an L3
test compares with the value (`<`, `LIKE`, `<>`) spends the literal budget, each spelling
on its own, and is written to the audit log as `?`. A window frame of a distance from an
identifier sort key (`RANGE` with an offset) is refused: it would measure values apart.
No answer shows an identifier value whole, but a series of such tests can rebuild one,
as far as the budgets allow: each literal spends the literal budget, and each probe, with
a literal or without one (identifier against identifier, a sort key, `length()`), spends
`limits.probe_budget`.
**The default trades protection for usefulness**, more with each such release. When the
profile in use follows `permissive` or admits more than `balanced`, `serve` and `service`
say so on stderr when they start and `check` prints it, together with the budgets: they
are the only brake on a series of tests, and have no total cap. Set `protection: balanced`
for a fixed, narrower set. The model reads the operations it may use in `describe`.

`strict` alone also closes what is left of the scan order, where an index on an identifier
column can make the DBMS meet rows in the order of its values. It refuses `SUM` / `AVG`
over columns declared as floats (`REAL`, `FLOAT`, `DOUBLE`): a float sum rounds by the
order of addition (`float_aggregate`). It refuses arithmetic, `CAST` and other
expressions that can fail on some rows (on SQL Server and DuckDB also a text column met
with a number, which they convert row by row) inside `EXISTS`, `IN (SELECT ...)`, a scalar
subquery or a `WITH` query, unless all that encloses them up to such a boundary aggregates
everything it reads: such a query may stop at its first matching row
(`fallible_subquery`). On MySQL and SQL Server, whose default collations compare
spellings such as `Abc` and `ABC` equal, it refuses `GROUP BY`, `DISTINCT`, `MIN` / `MAX`
and `UNION` over open text columns, even under `lower()`: which spelling an answer shows
depends on the scan, and keys, indexes and joins can lead it in an identifier's order
(`equal_spellings`). And it prints a number one
way whatever its type: `1.0` as `1`, `1.50` as `1.5`.

### Which profile to choose

Ask what it costs if the model learns something about a person short of the whole value:
the first letters of a name, its length, where it sorts, or that such a person is in the
database.

| Situation | Profile | Why |
|---|---|---|
| Health, finance, government data; strict regulation or audit | `strict` | The model learns no prefix, length or order. Some honest queries are refused |
| An ordinary company: CRM, orders, support, internal analytics | `balanced` | Nearly the protection of `strict`, fewer needless refusals |
| Your own or test data, a prototype, the most useful answers | `permissive` | Search by part of a name, sorting, length: the model can piece much together, though the server never shows the whole value |
| Some columns matter more than others (passport, phone) | your own | `balanced` or `permissive` for the database, `strict` for those columns in `column_protection` |

If learning that a person exists or how their surname begins is already harm, choose
`strict`. If only the whole value must stay hidden, `permissive` will do. The default is
`permissive` for convenience; for a production database with real customers choose
`balanced` or `strict` on purpose.

```yaml
protection: balanced
protections:
  reports: {extends: balanced, deny: [eq_literal]}
column_protection:
  people: {phone: reports}
```

An unknown profile name, a preset's name taken by your own profile, an `extends` that is not a
preset, an unknown operation and a `column_protection` entry on a column that is not an
identifier are load errors.

### Query forms

Some query forms carry no channel and are accepted under every profile: `INTERSECT` and
`EXCEPT` (an identifier position takes only identifiers, and needs `join_ident`), a table
alias repeated across their branches, a column outside `GROUP BY` when the whole primary
key of its table is grouped and cannot hold NULL (SQLite, Postgres and MySQL; DuckDB and
SQL Server refuse it themselves), `SUM` / `AVG` over a `CASE` of small non-negative
integers, SQLite's double-quoted strings (`"x"` naming no column is the string `'x'`),
SQLite's date functions and `instr` over open columns, and catalog names with spaces,
parentheses or hyphens.

Others only under `permissive`, because their result can depend on the order the scan
meets the rows: window functions (`ROW_NUMBER`, `RANK`, `DENSE_RANK`, aggregates over a
window with a fixed frame; never over an identifier), `SUM` / `AVG` over any other
expression (it can overflow at a point that depends on that order), and grouping by a
primary key that can hold NULL (a SQLite key that is neither `NOT NULL` nor a rowid
alias). Recursive `WITH` stays refused everywhere.

### Row rules

Some values are private only in some rows: one person's date of birth, the ballots of every
state but one. A row rule hides them under every profile:

```yaml
row_rules:
  - {table: people, hide: [dob], where: "name = 'Lewis'"}
  - {table: ballots, hide: [vote], where: "NOT (state = 'California')"}
  - {table: schedule, hide: "*", where: "air_date > '2009-01-15'"}
```

Where the condition holds, or is unknown (NULL), the `hide` columns of the row are NULL;
`"*"` leaves the row out. The server reads such a table through a masked copy of it, so the
hidden cells are NULL to every condition, join and aggregate of the query, not just in the
answer. A DBMS may evaluate an expression before the copy drops its rows, so a query that
reads a table with a `"*"` rule refuses any expression that can fail on some rows
(arithmetic, a cast), wherever it stands and whichever table it reads (`hidden_rows`);
`SUM` / `AVG` of a plain column still answer. The condition is one comparison over the
table's own `open` and `open_quasi` columns (`=`, `<>`, `<`, `>`, `IN`, `BETWEEN`, `LIKE`,
`IS NULL`, `AND`, `OR`, `NOT`): which rows it names shows in the pattern of NULLs, so it
may read nothing the model may not see. `describe` names the columns hidden in some rows,
not the condition. A query is masked by the rules of the table it names. A database view
reads its tables as they are, and the server does not work out which: a rule of the view's
own masks the view, not its tables. Partitions, child and parent tables (Postgres) show
each other's rows: give every table of such a family the same rules. While row rules are
declared, `serve` and `service` do not start with an open view, with a rule of its own or
not, or with an open table of a family that lacks a rule another table of the family has;
list one under `verified_relations` once you have checked it shows no ruled row. Facts only the caller may see ("only their
own"), counts and facts across tables are not row rules.

## Configuration keys

| Key | Default | Meaning |
|---|---|---|
| `dsn_env` | required | environment variable holding the DSN |
| `dialect` | required | `postgres`, `sqlite`, `mysql`, `duckdb` or `tsql` |
| `columns` | required | `table: {column: class}`; unlisted columns are hidden |
| `entities` | required | list of `{table, pk}`: tables whose rows are people, and their key |
| `verified_open` | `{}` | `table: [columns]`: open or open_quasi columns you checked; their values are not masked when selected as they are (an expression over them still is) |
| `token_ttl_s` | `86400` | token lifetime in seconds; `null` = tokens never expire |
| `web_port` | `8765` | port of the cards on `127.0.0.1` |
| `web_enabled` | `true` | `false` = labels mode, no cards |
| `session_ttl_s` | `28800` | how long a sign-in to the cards lasts, in seconds (8 hours) |
| `mcp_port` | `8766` | port of `incognito-sql service` on `127.0.0.1` |
| `limits.max_sql_chars` | `20000` | longest SQL accepted |
| `limits.max_ast_nodes` | `2000` | largest parsed query |
| `limits.max_joins` | `8` | joins per query |
| `limits.max_in_items` | `50` | items in one `IN` as written; a token is one item |
| `limits.max_rows` | `500` | rows returned; the answer says `truncated` |
| `limits.statement_timeout_ms` | `10000` | per query; on SQLite and DuckDB the server cuts it |
| `limits.literal_budget` | `20` | distinct human literals per `serve` process for its life, and per window of the installation; the service counts by the window only. A query refused before it reaches the database (a limit, a stored form that cannot be bound) spends nothing; one the database refuses has spent its literals and probes. `0` turns such literals off (`literals_off`, tokens and open columns still work); `unlimited` removes the cap, and `serve`, `service` and `check` warn of it |
| `limits.literal_window_s` | `3600` | sliding window of the installation-wide literal budget |
| `limits.probe_budget` | `100` | probes of identifier values per window of the installation: each `<` `>` `BETWEEN` `<>` `LIKE`, sort key, `MIN` / `MAX` and `length()` over one is one probe, counted before the query runs and never by its answer (`probe_budget`). `0` turns probes off (`probes_off`); `unlimited` removes the cap, with the same warning |
| `limits.query_rate` | `600` | queries the installation answers per window, refused ones included; it slows a search down, it does not replace the literal budget |
| `limits.query_window_s` | `60` | sliding window of `query_rate` |
| `protection` | `permissive` | protection profile of every identifier column: `strict`, `balanced`, `permissive` or a name from `protections` |
| `protections` | `{}` | `name: {extends: preset, allow: [operations], deny: [operations]}`: your own profiles |
| `column_protection` | `{}` | `table: {column: profile}`: a profile for one identifier column |
| `row_rules` | `[]` | `{table, hide: [columns] or "*", where: "<condition>"}`: cells the model never sees in the rows the condition names ([Row rules](#row-rules)) |
| `verified_relations` | `[]` | views, partitions, child and parent tables you checked show no row of a table with row rules ([Row rules](#row-rules)) |

Unknown keys are an error, and so are the `display` and `foreign_keys` of earlier drafts.
An entity's table and key must be declared columns, each table listed once.
Two configs on one machine need different `web_port` values.

**Reviewing a change.** `incognito-sql diff old.yaml new.yaml` lists what the new
declaration lets the model see or link more (`WIDENED`), less (`NARROWED`) or differently
with no effect on the model (`CHANGED`). It compares a column's class by what the model
sees (nothing, a token, the value, an open entity key that names a person's rows),
`verified_open`, `verified_relations`, the operations of each identifier column's profile
(an operation that opens nothing, such as `is_null`, is `CHANGED`), the profile's query
forms, `web_enabled`, `token_ttl_s`, the literal budget and its window, the probe budget,
the query rate and its window, `max_rows`, the rules on rows, and the database it
applies to. A budget turned on from 0 or lifted to `unlimited` is `WIDENED`; so is a
rule on rows that is gone, hides fewer columns, or has another condition (whether that
condition covers more rows is not worked out). It reads only the two files. With `--ci`
it exits 1 on any `WIDENED`, so a pipeline stops such a change until someone chooses it:

```sh
incognito-sql diff deploy/shop.yaml shop.yaml --ci
```

## Refused by design

These cost usability, not security; all but the first and last are refusals.

- **Row order.** Without an outer `ORDER BY` the rows are shuffled; with one they follow
  its keys, and rows that tie on every key come in random order.
- **Paging.** `LIMIT`, `OFFSET` and `TOP` take non-negative integer literals only, not
  expressions or subqueries. Postgres `LIMIT ALL` and `FETCH FIRST`, SQL Server
  `OFFSET … FETCH` (use `TOP`, or `OFFSET` alone), and `OFFSET` without `LIMIT` on SQLite
  and MySQL (including SQLite `LIMIT -1 OFFSET n`) are refused.
- **Identifier against identifier** of different types: allowed only within signed
  integers up to 64 bits, or within character types; any other type only with the
  identical type (a `DECIMAL` with the same precision and scale).
- **Human literals** go only to text or numeric identifier columns. Date, timestamp, UUID,
  money and boolean identifier columns take tokens only: a date literal on a `DATE`
  identifier is refused on all five DBMS, a number on a SQL Server `MONEY` identifier too.
- **No literal or token at all** against MySQL unsigned integers narrower than `BIGINT`,
  MySQL `TIMESTAMP`, `ENUM`, `SET` or `DOMAIN` types, arrays, structs and maps. In labels
  mode such columns get labels without entity keys.
- **`COLLATE`** anywhere in a query; any function on an identifier (string and date
  functions included; on open columns they work). Window functions only under
  `permissive` (see [Query forms](#query-forms)).
- **`SUM` / `AVG`** over a stored column or over a `CASE` whose every result is a small
  non-negative integer or NULL (`SUM(CASE WHEN … THEN 1 ELSE 0 END)`); any other
  expression only under `permissive`: `SUM(total * 2)` is refused elsewhere,
  `SUM(total) * 2` works.
- **Large numbers.** A number in an open cell whose integer part has 10 or more digits
  (a phone number, but also a sum in the billions) is masked as personal-looking. Computed
  floats are rounded to 12 significant digits, so `SUM` and `AVG` print the same whatever
  order the rows were added in. That is lost utility, not a leak.

## Trying a query

`incognito-sql try --config shop.yaml "<sql>"` tells you what the server would do with a
query, without running it: it reads the database's schema only, and writes no audit line,
token or budget. It prints the verdict (answered, or the refusal code with its `retry` and
hint), the base columns the query reads with their classes, and which output columns
would come back as pseudonyms. It runs the server's checks up to execution, the rewrite
included; what only the running server or the database can tell is not checked: whether
a token in the query is live (the verdict then says so), the literal budget, and the
database's own errors. The exit code is 0 for an answer, 1 for a refusal and 2 when
nothing could be tried (a bad config, an unset DSN variable, an unreadable schema, a
failed probe). The tokens the rewrite needs live in memory only: nothing of the query
reaches a file.

## Refusal codes

A refusal is `{"error": <reason>, "sqlstate": ..., "retry": ..., "hint": ...}`. `sqlstate`
is the database's code on Postgres and MySQL and `null` otherwise; `internal_error` has
none. `retry` tells the agent what to do next: `rewrite` (fix the query itself, once),
`ask_user` (only a human can lift it: a literal budget, a protection profile) or `stop` (final for this
question). The hint is fixed per reason: it never names a value, a column or database text.

| Reason | `retry` | Hint |
|---|---|---|
| `parse_error` | `rewrite` | The SQL could not be parsed. Write it in the dialect `describe` names. |
| `multiple_statements` | `rewrite` | Send one statement per call. |
| `limit_exceeded` | `rewrite` | The query is too large: too long, too many nodes, joins or IN items, or more values than the database takes as parameters. Simplify or split it. |
| `node_not_allowed` | `rewrite` | Only one read-only SELECT, WITH ... SELECT, UNION, INTERSECT or EXCEPT runs, and some syntax inside it is not accepted (LIMIT and OFFSET take integer literals only; a `*` reads base tables only). Rewrite it with plainer SQL. |
| `unknown_column` | `rewrite` | A table or column name is not known, or a `*` cannot be expanded there (in a branch of UNION, INTERSECT or EXCEPT, or with no table). Take the names from `describe` and list them. |
| `ambiguous_column` | `rewrite` | A column name does not resolve to exactly one usable column, or an alias repeats the name of a column of a table in the query. Qualify the column with its table or alias, or rename the alias, and take the names from `describe`. |
| `hidden_column` | `rewrite` | The query names a column that `describe` does not list: it is hidden and cannot be queried in any form. Answer without it; only the operator can open it. |
| `pii_operation` | `rewrite` | An identifier column is used in a way its protection profile does not allow. Use only the operations `describe` lists; if the question needs more, tell the user. Rewording the same question to get the value in another shape is not a fix. |
| `pii_join_with_open` | `rewrite` | An identifier column is compared with a column that is not an identifier. Compare it only with a token, a literal the user gave you, or another identifier column. |
| `literal_type_mismatch` | `rewrite` | A literal or column compared with an identifier does not have its type. Use a token, or a literal of the column's type. |
| `invalid_token` | `rewrite` | A token is unknown, expired or cut short. Take a fresh one from a recent answer. |
| `literal_budget` | `ask_user` | The limit of distinct literals compared with identifiers is reached: per session it does not refill, for the whole installation it frees up within the hour. Tokens from earlier answers still work; for a new literal, tell the user. |
| `literals_off` | `rewrite` | Literals compared with personal columns are turned off by the operator. Find the row through open columns and use its token. |
| `probe_budget` | `ask_user` | Too many probes of identifier columns this hour across the installation: each <, >, BETWEEN, <>, LIKE, ORDER BY, MIN/MAX or length() over one counts. Sort or filter by an open column instead, or wait; if the question needs the probes, tell the user. |
| `probes_off` | `rewrite` | Comparing or sorting by personal columns is turned off by the operator: <, >, BETWEEN, <>, LIKE, ORDER BY, MIN/MAX and length() over them. Sort or filter by an open column instead; = and IN with a token still work. |
| `rate_limit` | `ask_user` | Too many queries for now: the installation answers a fixed number per minute. Wait a minute, or ask the user whether this many queries are needed. |
| `system_catalog` | `rewrite` | System catalogs and system schemas are closed. Use `describe` for the schema. |
| `float_aggregate` | `rewrite` | SUM or AVG over a column declared floating-point can depend on the order rows are added. Sum or average an integer or DECIMAL column; a wider profile is the operator's choice. |
| `fallible_subquery` | `rewrite` | A computation that can fail on some values (arithmetic, CAST, abs, round, substr, a date function) runs inside EXISTS, IN (SELECT ...), a scalar subquery or WITH. Move it to the outer query, or into an aggregate without GROUP BY. |
| `equal_spellings` | `ask_user` | On MySQL and SQL Server, the strict profile does not group, deduplicate or take MIN/MAX of open text: the database may pick among equal spellings in an order that follows an identifier. Ask the operator for another profile. |
| `hidden_rows` | `rewrite` | An expression that can fail, anywhere in a query over a table with hidden rows. Aggregate the plain column instead. |
| `db_error` | `rewrite` | The database refused or did not finish the statement; `sqlstate` (Postgres and MySQL only) and `detail`, when present, say why. Fix or simplify the SQL for this DBMS once; if it fails again, tell the user. |
| `internal_error` | `stop` | The server failed on this query. Tell the user; the operator can read the server log. |
