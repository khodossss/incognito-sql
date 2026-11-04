"""Every case of the setup, in the order a human meets them."""

from incognito_sql.setup.closed import CLOSED
from incognito_sql.setup.local import DEMO, OWN
from incognito_sql.setup.model import Case
from incognito_sql.setup.projects import CHANGE, PROJECTS

CASES: tuple[Case, ...] = (DEMO, OWN, CLOSED, PROJECTS, CHANGE)


def case(name: str) -> Case:
    """Return the case of this name; raise KeyError for another."""
    for found in CASES:
        if found.name == name:
            return found
    raise KeyError(name)
