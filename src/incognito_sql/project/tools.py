"""The project server's tools over one project's setup, without the MCP SDK.

Every answer is safe for the model: what is set up and where, names of variables, tables
and columns, counts, the next step; never a DSN, a key, a sign-in code or a value.
"""

import json
import webbrowser
from collections.abc import Callable

from incognito_sql.core.config import ColumnClass
from incognito_sql.mcp.refusals import explained
from incognito_sql.project import actions
from incognito_sql.project.live import Live, NotReady
from incognito_sql.project.place import Place
from incognito_sql.project.words import FIX, OFFER, READY, REVIEW, secret_step, start
from incognito_sql.web.run import HOST


def _json(data: object) -> str:
    return json.dumps(data, ensure_ascii=False)


def _not_ready(problem: str) -> str:
    return _json(
        {
            "error": "not_set_up",
            "retry": "ask_user",
            "hint": f"{problem}; call setup_status for the next step",
        }
    )


# What the human sees on a card and the model does not.
_HUMAN_ONLY = frozenset({ColumnClass.IDENTIFIER, ColumnClass.FREE_TEXT})


class Tools:
    """The tools over one project's setup."""

    def __init__(
        self,
        place: Place,
        live: Live,
        release: str | None,
        *,
        open_browser: Callable[[str], bool] = webbrowser.open,
    ) -> None:
        """Hold the project, its open parts and the installed release for printed commands."""
        self._place, self._live, self._open = place, live, open_browser
        self._run = f'uvx "incognito-sql=={release}"' if release else "incognito-sql"

    def status(self) -> str:
        """Say what is set up in the project and what comes next."""
        setup = self._live.setup()
        info: dict[str, object] = {
            "project": str(self._place.root),
            "declaration": str(self._place.config) if self._place.config.exists() else None,
            "dsn_env": setup.decl.dsn_env if setup.decl is not None else None,
            "dsn_found_in": setup.found.source if setup.found is not None else None,
            "protection": setup.decl.protection if setup.decl is not None else None,
        }
        if setup.decl is None and setup.problem is None:
            return _json(info | {"ready": False, "next": start(self._run)})
        if setup.problem is not None:
            return _json(info | {"ready": False, "problem": setup.problem, "next": FIX})
        if setup.found is None and setup.decl is not None:
            nxt = secret_step(self._run, setup.decl.dsn_env)
            return _json(info | {"ready": False, "next": nxt})
        try:
            self._live.gateway()
        except NotReady as exc:
            return _json(info | {"ready": False, "problem": str(exc), "next": FIX})
        port = self._live.port()
        columns = setup.decl.columns if setup.decl is not None else {}
        kinds = {k for cols in columns.values() for k in cols.values()}
        more = bool(kinds & _HUMAN_ONLY) and port is not None
        return _json(
            info
            | {
                "ready": True,
                "cards": f"http://{HOST}:{port}/"
                if port is not None
                else "not served here: its port is held by another program",
                "human_sees_more": more,
                "next": READY + OFFER if more else READY,
            }
        )

    def create_demo(self) -> str:
        """Write the invented shop into the project and set it up."""
        try:
            config = actions.create_demo(self._place, actions.free_port(self._place))
        except actions.ActionError as exc:
            return _json({"error": str(exc)})
        return _json(
            {
                "declaration": str(config),
                "next": "Call setup_status, then describe and query: ask who spent the most.",
            }
        )

    def draft(
        self,
        dialect: str,
        dsn_env: str | None = None,
        database_file: str | None = None,
        *,
        sample: bool = True,
    ) -> str:
        """Write the declaration draft from the database's schema, or list contradictions."""
        try:
            done = actions.draft_declaration(
                self._place,
                actions.free_port(self._place),
                dialect,
                dsn_env=dsn_env,
                # A relative path is the project's: the server's own folder is the plugin's.
                database_file=self._place.root / database_file if database_file else None,
                find=self._live.find,
                sample=sample,
            )
        except actions.ActionError as exc:
            return _json({"error": str(exc)})
        if not done.written:
            return _json(
                {
                    "declaration": str(done.path),
                    "written": False,
                    "contradictions": done.found,
                    "next": "Resolve each contradiction with the human in the declaration.",
                }
            )
        return _json(
            {
                "declaration": str(done.path),
                "written": True,
                "draft": done.text,
                "candidates": done.found,
                "next": REVIEW,
            }
        )

    def open_cards(self) -> str:
        """Open the card page in the human's browser, signed in; the link is not returned."""
        try:
            parts = self._live.cards()
        except NotReady as exc:
            return _not_ready(str(exc))
        port = self._live.port()
        url = f"http://{HOST}:{port}/login/{parts.sessions.issue_code()}"
        opened = self._open(url)
        return _json(
            {
                "opened": bool(opened),
                "next": "The human sees real values on the page; you never do."
                if opened
                else f"No browser opened: the human runs `{self._run} login --config "
                f"{self._place.config}` in their own terminal.",
            }
        )

    def query(self, sql: str, connection_id: str) -> str:
        """Run one read-only query through the gateway of the setup as it is now."""
        try:
            gateway = self._live.gateway()
        except NotReady as exc:
            return _not_ready(str(exc))
        return _json(explained(gateway.query(sql, connection_id)))

    def describe(self) -> str:
        """Describe what may be queried."""
        try:
            gateway = self._live.gateway()
        except NotReady as exc:
            return _not_ready(str(exc))
        return _json(gateway.describe())
