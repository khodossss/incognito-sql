"""Where `secret` and `env` keep a variable: for the OS user, or in a KEY=VALUE file."""

import os
from collections.abc import Callable
from pathlib import Path

ForUser = Callable[[str, str], None]
NO_USER_VARIABLE = "this system has no variable kept for the user: name an --env-file"
_FILE_MODE = 0o600


def keep(name: str, value: str, env_file: Path | None, for_user: ForUser | None) -> str:
    """Keep ``name`` and set it in this process too; return where, in words.

    Raise OSError when it cannot be kept; with neither a file nor a user variable, the
    caller has refused already (``NO_USER_VARIABLE``).
    """
    if env_file is not None:
        keep_in_file(env_file, name, value)
        where = "the --env-file"
    elif for_user is not None:
        for_user(name, value)
        where = "your user; restart the client"
    else:
        raise OSError(NO_USER_VARIABLE)
    os.environ[name] = value  # the steps that follow in this process read it
    return where


def keep_in_file(path: Path, name: str, value: str) -> None:
    """Set ``name`` in a KEY=VALUE file, replacing its line, the file readable by its owner."""
    if "\n" in value or "\r" in value:
        msg = "a value on more than one line"
        raise OSError(msg)
    lines = path.read_text(encoding="utf-8-sig").splitlines() if path.exists() else []
    kept = [ln for ln in lines if ln.partition("=")[0].strip() != name]
    kept.append(f'{name}="{value}"')  # the reader takes one pair of quotes off
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, _FILE_MODE)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write("\n".join(kept) + "\n")
    path.chmod(_FILE_MODE)  # a file that was there keeps its mode otherwise
