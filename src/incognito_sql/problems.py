"""What the command line says about a config it cannot read: never a path or a value."""

from incognito_sql.core.config import config_problem


def quiet_problem(exc: Exception) -> str:
    """Return one line about a config that did not load, repeating nothing typed.

    The OS's message repeats the path: it becomes the error's type. The rest is
    `config_problem`, which repeats no value of the config.
    """
    if isinstance(exc, OSError | UnicodeDecodeError):
        return type(exc).__name__
    return config_problem(exc)
