"""Cases where the client starts the server: the demo, an own database, several projects."""

from incognito_sql.core.config.protection import PRESETS
from incognito_sql.setup.common import CARDS, CLIENT, DIALECT, PROBE, RESTART, VARIABLE, connect
from incognito_sql.setup.model import FILE_DIALECTS, Answers, Case, Kind, Question, Step, Who

_DEMO_CONFIG = "{folder}/shop.yaml"


def _file(answers: Answers) -> bool:
    return answers.get("dialect") in FILE_DIALECTS


DEMO = Case(
    "demo",
    "to see it work first, on an invented shop",
    (
        CLIENT,
        Step(
            "folder",
            Who.AGENT,
            "An empty folder for the demo.",
            ask=Question("folder", "Folder for the demo?", Kind.PATH, default="incognito-demo"),
        ),
        Step(
            "demo",
            Who.AGENT,
            "Write the invented shop and its declaration.",
            run=("demo", "{folder}"),
            writes=("{folder}/shop.db", _DEMO_CONFIG),
        ),
        Step(
            "demo-dsn",
            Who.AGENT,
            "Keep DEMO_SHOP_DSN for the user, where the client starts. Its value is "
            "invented, so the agent sets it itself. On Linux and macOS add "
            "`--env-file {folder}/demo.env` here and to `connect`.",
            run=("env", "DEMO_SHOP_DSN", "--file", "{folder}/shop.db"),
            writes=("the variable DEMO_SHOP_DSN",),
        ),
        *connect("--config", _DEMO_CONFIG),
        RESTART,
        PROBE,
        CARDS,
    ),
)

OWN = Case(
    "own",
    "your own database, the client starts the server (the convenient installation)",
    (
        CLIENT,
        DIALECT,
        Step(
            "folder",
            Who.AGENT,
            "The project folder; the config lives there.",
            ask=Question("folder", "Project folder?", Kind.PATH, default="."),
        ),
        Step(
            "name",
            Who.AGENT,
            "A short name: the config's file and the server's name in the client.",
            ask=Question("name", "Short name for this database?", Kind.TEXT, default="shop"),
        ),
        VARIABLE,
        Step(
            "file",
            Who.AGENT,
            "The database file; its DSN is kept in {var}. A file's path is no password, so "
            "this step is the agent's.",
            ask=Question("file", "Path to the database file?", Kind.PATH),
            run=("env", "{var}", "--file", "{file}", "--dialect", "{dialect}"),
            writes=("the variable {var}",),
            when=_file,
            only="for a database file (sqlite, duckdb)",
        ),
        Step(
            "host",
            Who.AGENT,
            "Where the database server is. Its password is never asked for here: it is typed "
            "in step `password`.",
            ask=Question("host", "Host, port and database, e.g. db:5432/shop?", Kind.TEXT),
            when=lambda a: not _file(a),
            only="for a database server",
        ),
        Step(
            "user",
            Who.AGENT,
            "The database login the server uses: a read-only one.",
            ask=Question("user", "Database login (read-only)?", Kind.TEXT),
            when=lambda a: not _file(a),
            only="for a database server",
        ),
        Step(
            "password",
            Who.HUMAN,
            "The human runs this in their own terminal and types the password there; it "
            "never passes through the chat. On Windows, then restart the client and go on "
            "from step `init` (`incognito-sql guide --case own --from init`).",
            run=("secret", "{var}", "--template", "{scheme}://{user}:{{password}}@{host}"),
            writes=("the variable {var}",),
            when=lambda a: not _file(a),
            only="for a database server",
        ),
        Step(
            "init",
            Who.AGENT,
            "Write the scaffold: every column hidden, candidates marked PII? by name or a "
            "local sample. No value is printed.",
            run=("init", "--dsn-env", "{var}", "--dialect", "{dialect}", "--out", "{config}"),
            writes=("{config}",),
        ),
        Step(
            "columns",
            Who.AGENT,
            "For each column of {config}, a class (identifier, open, open_quasi, closed, "
            "closed_hidden), "
            "and the tables whose rows are people: init's suggestion, confirmed or changed "
            "by the human, then written into {config}.",
            ask=Question(
                "columns",
                "Class of each column?",
                Kind.COLUMNS,
                hint="the scaffold's columns, with the class init suggests",
            ),
            writes=("{config}",),
        ),
        Step(
            "protection",
            Who.AGENT,
            "The protection profile. For other people's personal data take the closed case "
            "instead.",
            ask=Question(
                "protection",
                "Protection profile?",
                Kind.CHOICE,
                tuple(PRESETS),
                default="permissive",
            ),
            run=("set", "{config}", "protection", "{protection}"),
            writes=("{config}",),
        ),
        Step(
            "recheck",
            Who.AGENT,
            "Run init again: it lists contradictions. Settle each with the human.",
            run=("init", "--dsn-env", "{var}", "--dialect", "{dialect}", "--out", "{config}"),
            done="contradictions: 0",
        ),
        *connect("--config", "{config}", "--name", "{name}"),
        RESTART,
        Step(
            "check",
            Who.AGENT,
            "The verdict, and what it means: convenient = an agent with a shell can go "
            "around the server.",
            run=("check", "--config", "{config}"),
            done="profile: convenient",
        ),
        PROBE,
        CARDS,
    ),
)
