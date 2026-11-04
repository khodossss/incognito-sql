"""What the project server says: tool descriptions and next steps, safe for the model."""

from incognito_sql.setup.model import SCHEMES

FIX = "Tell the human what the problem says; after it is fixed, call setup_status again."
READY = (
    "Use describe, then query. Identifier values come back as links. Once an answer holds "
    "links, offer the human to see the real values: on their yes, call open_cards, which "
    "signs them in on their own browser."
)
CLASSES = (
    "identifier: you get a token, the human sees the value on a card; open: both see the "
    "value; open_quasi: both see it, and it may identify a person in combination (city, "
    "birth date, postcode); closed: you see nothing, the human sees it on a card (free text, "
    "health and other special data); closed_hidden: nobody sees it (passwords, keys). A "
    "column left out is hidden like closed_hidden."
)
REVIEW = (
    "Go through the draft with the human, table by table; candidates are columns that look "
    f"personal. Each column gets one class. {CLASSES} Ask, too, which table holds people "
    "and its key, for `entities` (without it links lead to no person's card), and the "
    "protection profile: strict for health, finance or strict audit; balanced for a CRM, "
    "orders, analytics; permissive (the default) for own or test data. Write the classes, "
    "`entities` and `protection:` into the declaration as the human decides; then call "
    "setup_status. Never ask for or show a value."
)

STATUS_TEXT = (
    "Say what incognito-sql has set up in this project (the declaration, where its DSN "
    "variable is found, whether the database opens) and the next step. Call it first, and "
    "again after each step: nothing needs a client restart."
)
DEMO_TEXT = (
    "Write an invented SQLite shop and its declaration into this project's .incognito-sql "
    "folder, ready to query. Only when the project has no declaration yet."
)
DRAFT_TEXT = (
    "Write a declaration draft from the database's schema into this project's "
    ".incognito-sql folder (if one exists, list its contradictions instead). `dialect` is "
    "sqlite, duckdb, postgres, mysql or tsql. A database file: give `database_file` (its "
    "path; sqlite or duckdb). A server database: give `dsn_env`, the variable the human set "
    "with `secret`. Values are sampled to suggest personal columns, never returned."
)
CARDS_TEXT = (
    "Open the card page in the human's own browser, signed in, so they see the real values "
    "behind the links. The sign-in link is never returned to you."
)


def start(run: str) -> str:
    """Return the first step of a project with nothing set up; ``run`` runs this release."""
    schemes = ", ".join(f"{d}: {s}" for d, s in SCHEMES.items())
    return (
        "Nothing is set up here. Ask the human which case is theirs. The demo: call "
        "create_demo. Their own database in a file (SQLite, DuckDB): call "
        "draft_declaration with dialect and database_file. Their own database on a "
        "server: ask the dialect and a variable name such as SHOP_DSN; the human runs, "
        f"in their own terminal, `{run} secret SHOP_DSN --template "
        "'<scheme>://<user>:{password}@<host>:<port>/<database>'` "
        f"(schemes {schemes}); then call draft_declaration with dialect and dsn_env. "
        "Other people's personal data: that is the closed setup, a service under another "
        "OS user, which this server does not run; tell the human so."
    )


def secret_step(run: str, name: str) -> str:
    """Return the human's step that sets the DSN's variable ``name``."""
    return (
        f"The human sets {name} in their own terminal: `{run} secret {name} "
        "--template '<scheme>://<user>:{password}@<host>:<port>/<database>'`. "
        "Then call setup_status again: no restart is needed."
    )
