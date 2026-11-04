"""Keep the machine from sleeping while a benchmark runs.

A run that sleeps through the night comes back with broken database connections and
latencies measured across the gap. On Windows the running thread asks the system to stay
awake (the display may still turn off); elsewhere this does nothing.
"""

import ctypes
import sys
from collections.abc import Iterator
from contextlib import contextmanager

_CONTINUOUS = 0x80000000
_SYSTEM_REQUIRED = 0x00000001


@contextmanager
def awake() -> Iterator[None]:
    """Hold the system awake for the block; release it after, however the block ends."""
    if sys.platform != "win32":  # mypy then reads windll only where it exists
        yield
        return
    state = ctypes.windll.kernel32.SetThreadExecutionState
    state(_CONTINUOUS | _SYSTEM_REQUIRED)
    try:
        yield
    finally:
        state(_CONTINUOUS)
