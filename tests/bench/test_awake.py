"""A benchmark run holds the machine awake, and lets it sleep again after."""

import ctypes
import sys

import pytest

from bench.awake import awake


def test_windows_is_held_awake_for_the_run_and_released_after_a_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if sys.platform != "win32":
        pytest.skip("the wake request is Windows only")
    asked: list[int] = []
    monkeypatch.setattr(ctypes.windll.kernel32, "SetThreadExecutionState", asked.append)
    with pytest.raises(RuntimeError), awake():
        _fail_while(asked)
    assert asked == [0x80000001, 0x80000000]


def _fail_while(asked: list[int]) -> None:
    assert asked == [0x80000001]  # held while the run runs
    raise RuntimeError


def test_elsewhere_it_does_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    with awake():
        pass
