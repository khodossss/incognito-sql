"""A variable kept for the OS user: on Windows, what `SetEnvironmentVariable(..., 'User')` does.

Elsewhere there is none (a shell profile is the user's own file): `secret` then asks for
an --env-file.
"""

import sys
from collections.abc import Callable

_BROADCAST = 0xFFFF  # HWND_BROADCAST
_SETTING_CHANGE = 0x001A  # WM_SETTINGCHANGE
_ABORT_IF_HUNG = 0x0002


def user_variable() -> Callable[[str, str], None] | None:
    """Return the function that keeps a variable for the user, or None on this system."""
    return _windows if sys.platform == "win32" else None


def _windows(name: str, value: str) -> None:
    """Set ``name`` in the user's Environment key and tell running programs to read it."""
    if sys.platform != "win32":  # for the type checker: only `user_variable` hands it out
        raise OSError(name)
    import ctypes  # noqa: PLC0415 -- Windows only
    import winreg  # noqa: PLC0415 -- Windows only

    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_SET_VALUE) as key:
        winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)
    result = ctypes.c_ulong()
    ctypes.windll.user32.SendMessageTimeoutW(
        _BROADCAST, _SETTING_CHANGE, 0, "Environment", _ABORT_IF_HUNG, 5000, ctypes.byref(result)
    )
