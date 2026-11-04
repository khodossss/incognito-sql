# incognito-sql

[![CI](https://github.com/khodossss/incognito-sql/actions/workflows/ci.yml/badge.svg)](https://github.com/khodossss/incognito-sql/actions/workflows/ci.yml)
[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-blue)](LICENSE)
![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue)
![DBMS](https://img.shields.io/badge/DBMS-Postgres%20%7C%20MySQL%20%7C%20SQL%20Server%20%7C%20SQLite%20%7C%20DuckDB-lightgrey)
![Status: MVP](https://img.shields.io/badge/status-MVP%2C%20not%20audited-orange)

**Let an LLM agent answer questions about a database of personal data without ever
receiving the personal values.**

incognito-sql is an MCP server. The agent writes SQL; the server parses and checks it
before anything runs, executes a regenerated read-only form, and returns rows in which
every name, phone number, e-mail or document number you declared is a token. The agent
can still compare, group, count and join on those tokens. A human who needs the real
value opens the token's link to a local card after signing in; the model never can.

[Quick start](#quick-start) · [Protection profiles](#protection-profiles) ·
[Benchmark](docs/benchmark.md) ·
[Threat model](#what-it-does-not-protect-against) · [Security](SECURITY.md) ·
[Changelog](CHANGELOG.md)

## See it

Three customers and their orders (invented). The agent asks who spent the most:

```sql
SELECT c.full_name, c.city, SUM(o.total) AS spent
FROM customers c JOIN orders o ON o.customer_id = c.id
GROUP BY c.full_name, c.city ORDER BY spent DESC
```

| | full_name | city | spent |
|---|---|---|---|
| **in the database** | Mira Quellbrandt | Tellport | 320.5 |
| **what the model gets** | `http://127.0.0.1:8765/v/tk_xpdi6slbwnqe42nn` | Tellport | 320.5 |

The answer is right and the name never left the database: `full_name` is declared an
identifier, so it comes back as a token the model can pass on, filter by
(`WHERE full_name = 'tk_xpdi…'`) and show to you as a link. `city` is declared
`open_quasi` (identifying in combination) and is shown; `total` is open. Opening the link shows you, signed in on
your own machine, the real name and the customer's rows.

Asking for the value in another shape is refused before the query runs, not filtered
afterwards:

```sql
SELECT upper(full_name) FROM customers                     -- {"error": "pii_operation"}
SELECT full_name FROM customers WHERE email LIKE 'mira%'   -- {"error": "pii_operation"}
```

(Captured from the server on the example database of the [quick start](#quick-start);
token strings differ per installation.)

## Why incognito-sql

Most tools that guard an agent's SQL look at the answer and mask what looks personal, or
look at the query's keywords. Both miss a value the query has reshaped on the way out:
upper-cased, cut into pieces, hex-encoded, concatenated, renamed by an alias.
incognito-sql decides from the query itself.

- **It decides before the query runs.** Every output and every comparison is traced to
  its base columns; an operation that could carry an identifier's value out (a function
  over it, arithmetic) is refused; sorting, `LIKE` and ranges pass only as far as the
  protection profile admits them. Only SQL regenerated from the checked tree runs, never
  the model's text.
- **Identifiers stay usable.** The same value is the same token in every answer, so the
  model can still join, group, count distinct and follow up. Tools that hash or drop a
  column, or give a new pseudonym per query, lose that.
- **Any type is protected.** A hidden number, date or binary value is tokenised or
  refused like text; several tools protect strings only.
- **The human sees the value, the model never does.** No tool turns a token back into a
  value for the agent; a person opens local cards behind a sign-in.
- **A second layer on open columns.** An open cell that looks personal (e-mail, phone,
  card, IBAN, key) is masked anyway, and you are told which column.
- **You choose the trade-off.** Three [protection profiles](#protection-profiles), from
  `strict` to `permissive`, set per database or per column.
- **Five DBMS, one set of rules**, held by the same attack corpus on each.

The [benchmark](docs/benchmark.md) runs one attack corpus and a set of honest tasks
through incognito-sql, a plain read-only connection and 15 other open
tools of its kind, each with its recommended configuration, on every DBMS it supports,
judged by an oracle that shares no code with the server:

| | Attacks that showed a hidden value | Honest tasks answered |
|---|---|---|
| incognito-sql (`strict`) | 0.0% (0/2894) | 91.1% (164/180): 100% on Postgres, SQLite and DuckDB; on MySQL and SQL Server `strict` refuses grouping open text |
| incognito-sql (`permissive`) | 0.0% (0/2894) | 100.0% (180/180) |
| best other tool: sanitized-db-mcp (Postgres only) | 0.0% (0/581) | 75.0% (27/36) |
| plain read-only SQL | 17.5% (508/2909) | 100.0% (180/180) |

"Best other tool": the fewest attacks that showed a hidden value on the DBMS it runs on,
then the most honest tasks answered.

Each tool is also held to its own promise: what its README says it keeps from the model,
tested with single queries and with series of queries that try to infer a hidden value:

| Tool | What it promises | Kept? |
|---|---|---|
| incognito-sql (`strict`) | no hidden value, whole or in part, and nothing inferred about one, except whether a typed value exists (within the literal budget) | yes |
| incognito-sql (`balanced`) | the same as `strict` | yes |
| incognito-sql (`permissive`) | no hidden value, whole or in part; of what can be inferred, only whether a value exists, its order, length, beginning and what it contains (within the literal budget) | yes |
| datacharter | no hidden value whole | yes |
| db-mcp-server | nothing stated (held to: no hidden value whole) | no: shown whole by 1/60 attacks and 149 cuts; rebuilt by a series 48/66 |
| dbmcp | nothing stated (held to: no hidden value whole) | no: shown whole by 19/60 attacks and 90 cuts; rebuilt by a series 48/66 |
| dbridge-mcp | no hidden value whole | no: shown whole by 1/60 attacks and 174 cuts; rebuilt by a series 0/66 |
| gate | no hidden value whole | no: shown whole by 4/60 attacks and 76 cuts; rebuilt by a series 46/66 |
| januscope | nothing stated (held to: no hidden value whole) | no: shown whole by 23/60 attacks and 137 cuts; rebuilt by a series 46/66 |
| mcp-server-conceal | nothing stated (held to: no hidden value whole) | no: shown whole by 20/60 attacks and 164 cuts; rebuilt by a series 48/66 |
| safedb-mcp | no hidden value whole | no: shown whole by 0/60 attacks and 174 cuts; rebuilt by a series 48/66 |
| veil | no hidden value whole | no: shown whole by 4/60 attacks and 21 cuts; rebuilt by a series 45/63 |

Every tool's promise, quoted from its README, and the verdict:
[docs/benchmark.md](docs/benchmark.md#on-independent-sets-spider-bird-mini-dev-securesql).

Numbers from the run of 3 November 2026: the first table on every DBMS each tool supports,
the promises on SQLite with Spider, BIRD Mini-Dev and SecureSQL.
The price of deciding from the query is refusing what the checker does not yet understand; the benchmark counts those refusals
too, on our tasks and on sets we did not write (Spider, BIRD Mini-Dev, SecureSQL).

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
### What your profile holds on your data: `assess`

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

### For your DPO: `report`

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

## Quick start

### Try it on an invented shop

`demo` writes a SQLite database of made-up customers and its declaration, and prints the
two commands that follow: the DSN variable to set and `connect` for your client.

```sh
uvx incognito-sql==<version> demo ./demo
```

Then ask your agent who spent the most: the names come back as links. On Windows it prints
PowerShell lines, and the one that sets the variable for your user: a client started
from the Start menu does not see a `$env:` variable set in a terminal window.

### Let your agent set it up

In Claude Code and Codex, install the plugin once per client; restart the client
afterwards. It brings the server itself and a skill that tells the agent how to set it
up, in every project:

```sh
claude plugin marketplace add khodossss/incognito-sql
claude plugin install incognito-sql@incognito-sql
codex plugin marketplace add khodossss/incognito-sql
codex plugin add incognito-sql@incognito-sql
```

Then, in a project, ask the agent: "connect my database through incognito-sql", or "show
me incognito-sql on the demo". It sets the project up through the server's tools
(`setup_status`, `create_demo`, `draft_declaration`, `open_cards`), goes through the
columns with you, and queries with `describe` and `query`; nothing needs a restart. The
setup lives in the project's `.incognito-sql/` folder. A password is the one step that
is yours: the agent prints the `secret` command and you run it in your own terminal.

OpenCode takes the skill alone: `uvx incognito-sql==<version> skill opencode`
(`skill claude-code` and `skill codex` do the same without a plugin), and the setup
below.

Without the plugin (OpenCode, other people's data, or a client you set up by hand), ask
the agent to set up incognito-sql. It runs `incognito-sql guide`, which prints the setup's
steps for this version:
the demo, your own database (`own`), other people's data (`closed`), several projects, or
a change to a declaration in use. It asks you what each step needs and runs the commands
that are its own; `--case <name>` prints one case, `--from <step>` goes on after a restart.
Without an agent, `incognito-sql setup` walks you through the same steps in your terminal:
you choose with the arrow keys, or by number where the terminal has no arrow keys.

The agent never asks for a password in the chat. That step is yours, in your own terminal:

```sh
incognito-sql secret SHOP_DSN --template 'postgresql+psycopg://reader:{password}@db:5432/shop'
```

`secret` reads the password with hidden input, encodes it for the URL, and keeps the DSN
for your user (Windows; restart the client afterwards) or in `--env-file`, a `KEY=VALUE`
file only you can read (elsewhere). It prints only the variable's name, and refuses to run
when its input is no console: a pipe or the null device, which is what an agent's shell
gives a command (observed in Claude Code on Windows). A harness that gives its commands a
real terminal could run it, so keep this step your own. `--generate key` and
`--generate token` make the service's value key and token into its `--env-file`; the token
is shown once, for you to type into your own client's `secret`. `incognito-sql env` keeps a
variable that is no secret (a database file's DSN: `env SHOP_DSN --file shop.db`), and
`incognito-sql set shop.yaml protection balanced` changes one setting of a declaration.

### Install

Python 3.12 or newer, from PyPI:

```sh
pip install "incognito-sql[mcp,postgres]"
```

Extras: `mcp` (the MCP SDK; only `serve` needs it), and one driver per DBMS: `postgres`
(psycopg), `mysql` (PyMySQL), `mssql` (pymssql), `duckdb`. SQLite needs none.

For your own database, the example below uses SQLite. Other DSNs: `postgresql+psycopg://…`,
`mysql+pymysql://…`, `mssql+pymssql://…`, `duckdb:///path/file.duckdb`; `--dialect` is one
of `postgres`, `sqlite`, `mysql`, `duckdb`, `tsql`. The config names the DSN's variable, never the DSN.

**1. Write a scaffold.** `init` reads the schema and writes a declaration with every
column hidden (commented out). Candidates carry a `PII?` hint found by name or by a local
sample of values; sampled values are never printed, and `--no-sample` skips sampling.

```sh
export SHOP_DSN="sqlite:////srv/data/shop.db"
incognito-sql init --dsn-env SHOP_DSN --dialect sqlite --out shop.yaml
```

**2. Decide every column**, and name the tables whose rows are people:

```yaml
dsn_env: SHOP_DSN
dialect: sqlite
columns:
  customers:
    id: open
    full_name: identifier
    email: identifier
    city: open_quasi
    notes: closed
    password_hash: closed_hidden
  orders:
    id: open
    customer_id: open
    total: open
entities:
  - table: customers
    pk: id        # declare it open: labels and person cards use it
```

Run `init` again: an existing file is left as is, and `init` lists contradictions (open
columns whose name or sampled values look personal, open_quasi columns whose values do). Settle
each one: remove the column (hidden), or, if its values only look personal (order numbers,
a shared support address), list it under `verified_open`.

**3. The key.** The token store is encrypted with a 32-byte key, generated on first start
and kept in the OS keyring. Losing it loses the tokens and cards already issued. Without
a usable keyring, set `INCOGNITO_SQL_KEY` to base64 of 32 random bytes:

```sh
python -c "import base64, secrets; print(base64.b64encode(secrets.token_bytes(32)).decode())"
```

**4. Connect the client.** The client starts `incognito-sql serve` over stdio. `connect`
prints the entry in your client's own format: `claude-code`, `codex`, `cursor` or
`opencode`. The entry names the DSN's variable in the client's substitution syntax and
never holds its value, so set the variable where the client starts:

```sh
incognito-sql connect claude-code --config /srv/incognito/shop.yaml
# claude mcp add --scope project shop -e 'SHOP_DSN=${SHOP_DSN}' -- uvx --from 'incognito-sql[mcp]==<version>' incognito-sql serve --config /srv/incognito/shop.yaml
```

For Claude Code it prints the `claude mcp add` command, which writes Claude Code's own
settings; on Windows the command is quoted for PowerShell. For Codex, Cursor and
OpenCode, `--write` adds the entry to their settings file (`$CODEX_HOME` or
`~/.codex/config.toml`, `.cursor/mcp.json`, `opencode.json`; `--file` names another)
after asking on a terminal; with no terminal it refuses, unless `--yes` says to write
without asking (for a script or an agent that sets the client up). It prints only the
entry it adds, never the rest of the file, and leaves every other server there as it is.
With `--env-file F` the entry runs `serve --env-file F` and passes no variable: the server
reads its DSN from the file. The command pins the installed release and carries the
database's driver as an extra (`[mcp,postgres]`, `[mcp,mysql]`, `[mcp,mssql]`, `[mcp,duckdb]`; SQLite needs none); an installation that
is no published release (a checkout) is run by its own interpreter instead. The entries
follow each client's documentation; Claude Code's and OpenCode's were also tried with those
clients, Codex's and Cursor's were not.

This is the *convenient* profile: the client starts the server as the agent's own OS user,
so an agent with a shell can read the DSN and go around the server. For other people's
personal data use the *closed* profile: `incognito-sql service` runs as its own OS user,
holds the secrets, and the client connects to `http://127.0.0.1:8766/mcp` with a token
(`incognito-sql connect <client> --url http://127.0.0.1:8766/mcp` prints that entry, the
token read from `INCOGNITO_SQL_MCP_TOKEN` or the variable `--token-env` names).
[docs/deployment.md](docs/deployment.md) sets it up for each place the database can live,
and `incognito-sql check`, run as the agent's account, tells which profile you have.

**5. Sign in to the cards.** `serve` starts the cards when their port is free. With the
DSN variable set, `incognito-sql login --config shop.yaml` signs you in through the browser
(and serves the cards if nothing does); `incognito-sql web --config shop.yaml` serves them
alone, so links work after the client exits. In the closed profile only the service's
account or an administrator can sign in: `login --print` writes the link instead of
opening a browser. Next to the config live `<name>.tokens.db` (tokens, sessions, literal
budget) and `<name>.audit.jsonl`. `serve`, `service`, `web`, `login` and `init` also take
`--env-file`, a file of `KEY=VALUE` lines for variables the environment does not set
(`check` only probes it). The card session is a browser cookie: an agent running as your
browser's OS account can take it over; see [docs/deployment.md](docs/deployment.md).

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
   where the driver allows it (see [the database login](#the-database-login-is-the-real-guard)).
4. **Shaped output.** Rows are shuffled unless the outer query has an `ORDER BY`; then
   they follow its keys (never an identifier), ties in random order. Identifier cells
   become pseudonyms; any other cell that looks like personal data (e-mail, phone, card
   number, IBAN, key) is masked: with cards on, the mask is a link `/m/<token>` that shows
   the value to you, never to the model, and the audit log names the column (see
   [People in open columns](#what-it-does-not-protect-against)). A refusal is
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

## Benchmark

[docs/benchmark.md](docs/benchmark.md) runs one attack corpus and a set of honest tasks
against this server, a plain read-only connection and the other tools of its kind on the five
DBMS (each where it runs), with an oracle that shares no code with the server. It states
its method, numbers and known limits. A second section runs the same tools on sets we did
not write (Spider, BIRD Mini-Dev and SecureSQL, on SQLite), downloaded at run time.

| On sets we did not write (SQLite) | incognito-sql (`strict`) | incognito-sql (`permissive`) | datacharter | plain SQL |
|---|---|---|---|---|
| Spider and BIRD questions answered | 81.4% (822/1010) | 88.7% (896/1010) | 45.2% (457/1010) | 100.0% (1010/1010) |
| SecureSQL attacks that showed a hidden value | 0.0% (0/75) | 0.0% (0/75) | 0.0% (0/60) | 46.7% (35/75) |
| SecureSQL safe questions answered | 44.9% (31/69) | 69.6% (48/69) | 9.3% (5/54) | 88.4% (61/69) |

## Security

incognito-sql is an MVP and has not been audited. Found a way for a hidden value to reach
the model? Report it privately: see [SECURITY.md](SECURITY.md).

The server is one layer; the database login and the OS account it runs as are the others.
For other people's data, run it in the *closed* installation profile
([docs/deployment.md](docs/deployment.md)), and read what it does not protect against
before you rely on it.

### What it does not protect against

1. **Pseudonymization, not anonymization.** Quasi columns are shown as they are. City,
   birth date and postcode together can single out one person; the server does not
   coarsen them. Declare such a column hidden or identifier if the combination matters.
2. **A model with a shell, in the convenient profile.** An agent that runs commands as the
   server's OS user can read the client's MCP settings or the environment, find the DSN
   and connect to the database directly, or read a SQLite file whole. The closed profile
   ([docs/deployment.md](docs/deployment.md)) runs the server as another OS user that
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

### The database login is the real guard

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

### Audit log

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

## Reference

### Configuration

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

### Refused by design

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

### Trying a query

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

### Refusal codes

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
| `ambiguous_column` | `rewrite` | A column name does not resolve to exactly one usable column. Qualify it with its table or alias, and take the names from `describe`. |
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

## License

Apache License 2.0: see [LICENSE](LICENSE). Attribution of the bench corpora is in
[NOTICE](NOTICE).
