"""The command line's argument parser: its errors never repeat a value."""

import argparse
import re
import sys
from typing import Any, NoReturn

# argparse messages made of argument names only; every other one may quote a value.
_NAME = r"[A-Za-z0-9_][A-Za-z0-9_/-]*|-[A-Za-z0-9_/-]+"
_NAMES = rf"(?:{_NAME})(?:,? (?:{_NAME}))*"
_NAMES_ONLY = re.compile(
    rf"the following arguments are required: {_NAMES}"
    rf"|argument {_NAMES}: (?:expected one argument|expected at least one argument"
    rf"|not allowed with argument {_NAMES})"
    rf"|one of the arguments {_NAMES} is required"
)


class QuietParser(argparse.ArgumentParser):
    """A parser whose errors never repeat an argument: one may be a pasted secret."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:  # noqa: ANN401 -- argparse's own
        """Build the parser; options are never guessed from a prefix."""
        kwargs.setdefault("allow_abbrev", False)  # `--d=<value>` is no guess at an option
        super().__init__(*args, **kwargs)

    def error(self, message: str) -> NoReturn:
        """Print usage and the error, naming the argument but never its value."""
        if not _NAMES_ONLY.fullmatch(message):
            slot = message.split(": ", 1)[0] if message.startswith("argument ") else "arguments"
            message = f"{slot}: not accepted (value not shown)"
        self.print_usage(sys.stderr)
        self.exit(2, f"{self.prog}: error: {message}\n")
