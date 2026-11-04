"""Whether a person can type into this process: what `secret` and `setup` ask before they run.

`isatty()` alone is not enough on Windows: the null device is a character device, so an
agent's shell that gives a command `NUL` for its input reads as a terminal. There the
input must also be a console, which `GetConsoleMode` accepts and the null device does not.
A pipe is no terminal on any system.
"""

import sys
from typing import TextIO


def interactive(stream: TextIO | None = None) -> bool:
    """Say whether ``stream`` (standard input by default) is a terminal a person types into."""
    stream = sys.stdin if stream is None else stream
    try:
        if not stream.isatty():
            return False
        fd = stream.fileno()
    except (AttributeError, OSError, ValueError):  # closed, detached or replaced input
        return False
    if sys.platform != "win32":
        return True
    import ctypes  # noqa: PLC0415 -- Windows only
    import msvcrt  # noqa: PLC0415 -- Windows only

    mode = ctypes.c_uint32()
    handle = msvcrt.get_osfhandle(fd)
    return bool(ctypes.windll.kernel32.GetConsoleMode(handle, ctypes.byref(mode)))
