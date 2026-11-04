"""A person's terminal: the null device and a pipe are none, on Windows too."""

import io
import subprocess
import sys

from incognito_sql.setup.console import interactive

PROBE = "from incognito_sql.setup.console import interactive; print(interactive())"


def test_the_null_device_is_no_terminal() -> None:
    done = subprocess.run(  # noqa: S603 -- this interpreter, a fixed probe
        [sys.executable, "-c", PROBE], stdin=subprocess.DEVNULL, capture_output=True, check=True
    )
    assert done.stdout.strip() == b"False"


def test_a_pipe_is_no_terminal() -> None:
    done = subprocess.run(  # noqa: S603 -- this interpreter, a fixed probe
        [sys.executable, "-c", PROBE], input=b"", capture_output=True, check=True
    )
    assert done.stdout.strip() == b"False"


class _Broken(io.StringIO):
    def isatty(self) -> bool:
        return True

    def fileno(self) -> int:
        raise io.UnsupportedOperation


def test_input_that_is_no_file_or_no_tty_is_no_terminal() -> None:
    assert not interactive(io.StringIO())
    assert not interactive(_Broken())
