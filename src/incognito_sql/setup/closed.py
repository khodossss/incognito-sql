"""Other people's data: a service under its own OS account holds every secret.

The administrator's steps outside this CLI (an account, a folder, a service) are said, not
run: they differ by OS and are in docs/deployment.md.
"""

from incognito_sql.connect.clients import TOKEN_ENV
from incognito_sql.core.tokens.crypto import ENV_KEY
from incognito_sql.setup.common import CLIENT, DIALECT, RESTART, VARIABLE, connect
from incognito_sql.setup.model import FILE_DIALECTS, Case, Kind, Question, Step, Who

_SECRETS = "{folder}/secrets.env"
_URL = "http://127.0.0.1:{port}/mcp"

CLOSED = Case(
    "closed",
    "other people's personal data: the service holds the secrets, the agent cannot reach them",
    (
        CLIENT,
        DIALECT,
        Step(
            "account",
            Who.ADMIN,
            "As an administrator: an OS account for the service, and a folder only it and "
            "administrators can read (docs/deployment.md, by OS).",
            ask=Question("folder", "The service's folder?", Kind.PATH),
            writes=("the account", "{folder}"),
        ),
        Step(
            "name",
            Who.AGENT,
            "A short name: the config's file and the server's name in the client.",
            ask=Question("name", "Short name for this database?", Kind.TEXT, default="shop"),
        ),
        VARIABLE,
        Step(
            "host",
            Who.AGENT,
            "Where the database server is. Its password is never asked for here: the "
            "administrator types it in step `password`.",
            ask=Question("host", "Host, port and database, e.g. db:5432/shop?", Kind.TEXT),
            when=lambda a: a.get("dialect") not in FILE_DIALECTS,
            only="for a database server",
        ),
        Step(
            "user",
            Who.AGENT,
            "The database login the service uses: a read-only one.",
            ask=Question("user", "Database login (read-only)?", Kind.TEXT),
            when=lambda a: a.get("dialect") not in FILE_DIALECTS,
            only="for a database server",
        ),
        Step(
            "password",
            Who.ADMIN,
            "As an administrator, in their own terminal: the password is typed there, into "
            "the service's secrets file, and nowhere else.",
            run=(
                "secret",
                "{var}",
                "--env-file",
                _SECRETS,
                "--template",
                "{scheme}://{user}:{{password}}@{host}",
            ),
            writes=(_SECRETS,),
            when=lambda a: a.get("dialect") not in FILE_DIALECTS,
            only="for a database server",
        ),
        Step(
            "dbfile",
            Who.ADMIN,
            "As an administrator: move the database file into {folder}, then type "
            "{dialect}:///<its path in the folder> as the variable's value.",
            run=("secret", "{var}", "--env-file", _SECRETS),
            writes=(_SECRETS, "{folder}"),
            when=lambda a: a.get("dialect") in FILE_DIALECTS,
            only="for a database file (sqlite, duckdb)",
        ),
        Step(
            "key",
            Who.ADMIN,
            "As an administrator: the value key, generated into the secrets file and shown "
            "to nobody.",
            run=("secret", ENV_KEY, "--env-file", _SECRETS, "--generate", "key"),
            writes=(_SECRETS,),
        ),
        Step(
            "token",
            Who.ADMIN,
            "As an administrator: the service's token, generated into the secrets file and "
            "shown once in this terminal, for the human's own client in step `client-token`.",
            run=("secret", TOKEN_ENV, "--env-file", _SECRETS, "--generate", "token"),
            writes=(_SECRETS,),
        ),
        Step(
            "init",
            Who.ADMIN,
            "As an administrator: the scaffold, every column hidden; it holds names only.",
            run=(
                "init",
                "--env-file",
                _SECRETS,
                "--dsn-env",
                "{var}",
                "--dialect",
                "{dialect}",
                "--out",
                "{folder}/{name}.yaml",
            ),
            writes=("{folder}/{name}.yaml",),
        ),
        Step(
            "columns",
            Who.AGENT,
            "The administrator copies the scaffold where the agent can read it (it holds "
            "names only). For each column propose a class and the tables whose rows are "
            "people; the human confirms or changes each; the administrator copies it back.",
            ask=Question(
                "columns",
                "Class of each column?",
                Kind.COLUMNS,
                hint="the scaffold's columns, with the class init suggests",
            ),
            writes=("{folder}/{name}.yaml",),
        ),
        Step(
            "service",
            Who.ADMIN,
            "As an administrator: install and start the service for the account "
            "(docs/deployment.md: systemd on Linux, a scheduled task on Windows).",
            ask=Question("port", "The service's MCP port?", Kind.TEXT, default="8766"),
        ),
        Step(
            "client-token",
            Who.HUMAN,
            "The human, as themselves, in their own terminal: type the token the "
            "administrator's terminal showed. Only its variable reaches the client's entry.",
            run=("secret", TOKEN_ENV),
            writes=(f"the variable {TOKEN_ENV}",),
        ),
        *connect("--url", _URL, "--name", "{name}"),
        RESTART,
        Step(
            "check",
            Who.AGENT,
            "Run as the agent's own account: every probe must be refused.",
            run=("check", "--config", "{folder}/{name}.yaml", "--env-file", _SECRETS),
            done="profile: closed",
        ),
        Step(
            "cards",
            Who.ADMIN,
            "Optional: as an administrator, `incognito-sql login --config {folder}/{name}.yaml "
            f"--env-file {_SECRETS} --print`, and open the link in the human's own browser.",
        ),
    ),
)
