"""Steps more than one case takes: the client, its entry, a restart, a first query, cards."""

from incognito_sql.connect.clients import CLIENTS, valid_variable
from incognito_sql.core.db import DIALECTS
from incognito_sql.setup.model import Answers, Kind, Question, Step, Who

CLIENT = Step(
    "client",
    Who.AGENT,
    "The MCP client that gets the server: one client at a time.",
    ask=Question("client", "Which client should get the server?", Kind.CHOICE, CLIENTS),
)

DIALECT = Step(
    "dialect",
    Who.AGENT,
    "The database system that holds the data.",
    ask=Question("dialect", "Which database system is it?", Kind.CHOICE, DIALECTS),
)

VARIABLE = Step(
    "variable",
    Who.AGENT,
    "The variable that will hold the database's address (the DSN): only its name is "
    "said, never its value.",
    ask=Question(
        "var",
        "Name of the variable for the DSN (upper case, e.g. SHOP_DSN)?",
        Kind.TEXT,
        default="SHOP_DSN",
        valid=valid_variable,
    ),
)


def _claude(answers: Answers) -> bool:
    return answers.get("client") == "claude-code"


def connect(*source: str, steps: str = "connect") -> tuple[Step, Step]:
    """Return the two ways to add the entry: Claude Code runs its own command."""
    common = ("connect", "{client}", *source)
    return (
        Step(
            f"{steps}-claude",
            Who.AGENT,
            "Print the entry, then run the `claude mcp add` command it prints, as it is.",
            run=common,
            writes=(".mcp.json of the project",),
            done="`claude mcp list` names the server",
            when=_claude,
            only="when the client is claude-code",
        ),
        Step(
            steps,
            Who.AGENT,
            "Add the entry to the client's settings without a question.",
            run=(*common, "--write", "--yes"),
            writes=("the client's settings file",),
            done="the command says the server was added",
            when=lambda a: not _claude(a),
            only="for any other client",
        ),
    )


RESTART = Step(
    "restart",
    Who.HUMAN,
    "Restart the client, so it starts the server with the new entry and sees the new variables.",
    ask=Question("restarted", "Restarted the client?", Kind.NONE),
)

PROBE = Step(
    "probe",
    Who.AGENT,
    "In the restarted client, a first question of the data (`describe`, then `query`): "
    "identifier cells come back as links or labels, never as values.",
    done="the answer holds links where names would be",
)

CARDS = Step(
    "cards",
    Who.HUMAN,
    "Optional: to see the real values behind links, run `incognito-sql login --config "
    "{config}` in a window of its own and keep it open. Not the agent's step.",
)
