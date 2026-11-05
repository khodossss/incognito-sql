# Setup

## Try it on an invented shop

`demo` writes a SQLite database of made-up customers and its declaration, and prints the
two commands that follow: the DSN variable to set and `connect` for your client.

```sh
uvx incognito-sql==<version> demo ./demo
```

Then ask your agent who spent the most: the names come back as links. On Windows it prints
PowerShell lines, and the one that sets the variable for your user: a client started
from the Start menu does not see a `$env:` variable set in a terminal window.

## Let your agent set it up

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

## Install

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
[docs/deployment.md](deployment.md) sets it up for each place the database can live,
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
browser's OS account can take it over; see [docs/deployment.md](deployment.md).
