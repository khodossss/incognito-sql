"""What lets a long independent-sets run survive a stop: a checkpoint and a watchdog.

The checkpoint keeps the tallies and what was taken after each finished database, under
a key of everything the numbers depend on: the repository's commit and uncommitted
changes (code, markings, tool versions and set digests all live there) and the run's
arguments. A run with the same key starts after the databases it finds there.

The watchdog writes a line every few minutes while one database runs, and stops the run
when a database runs over its limit, so a stall shows within minutes; the databases
finished before it stay in the checkpoint. After each database the tables over the
databases finished so far are written to a progress file, to watch the run as it goes.
"""

import _thread
import copy
import hashlib
import pickle
import shutil
import subprocess
import sys
import threading
import time
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from bench.adapters.launch import CACHE
from bench.external.levels import levels, prices
from bench.external.report import Taken, table
from bench.external.tally import Tally

FILE = CACHE / "external" / "checkpoint.pickle"
PROGRESS = CACHE / "external" / "progress.md"
HEARTBEAT_S = 600.0
Saved = tuple[list[str], dict[str, Tally], Taken]


class OverLimitError(Exception):
    """A database ran over the watchdog's limit."""


def key(args: Sequence[str]) -> str:
    """Return the key of a run: the repository's commit and changes, and ``args``."""
    git = shutil.which("git")
    parts = [*args]
    if git is not None:
        for command in (["rev-parse", "HEAD"], ["diff", "HEAD"]):
            done = subprocess.run([git, *command], capture_output=True, check=False)  # noqa: S603
            parts.append(done.stdout.decode("utf-8", "replace") if done.returncode == 0 else "")
    return hashlib.sha256("\0".join(parts).encode()).hexdigest()


class Checkpoint:
    """The tallies and what was taken after each finished database of one run."""

    def __init__(self, run_key: str, path: Path | None = None, *, fresh: bool = False) -> None:
        """Open the checkpoint of ``run_key``; ``fresh`` starts it over."""
        self.key, self.path = run_key, path or FILE
        self._saved: Saved | None = None if fresh else self._load()

    def _load(self) -> Saved | None:
        try:
            with self.path.open("rb") as file:
                stored_key, saved = pickle.load(file)  # noqa: S301 -- written by save() below
        except (
            OSError,
            EOFError,
            pickle.UnpicklingError,
            ValueError,
            TypeError,
            ImportError,
            AttributeError,
        ):  # an older release wrote it: a module or class is gone
            return None
        return saved if stored_key == self.key else None

    def resumed(self) -> Saved:
        """Return the finished databases, the tallies and what was taken; empty when new."""
        if self._saved is None:
            return [], {}, Taken()
        return self._saved

    def save(self, done: list[str], tallies: dict[str, Tally], taken: Taken) -> None:
        """Store the state after a finished database; the file is replaced whole."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        part = self.path.with_suffix(".part")
        with part.open("wb") as file:
            pickle.dump((self.key, (done, tallies, taken)), file)
        part.replace(self.path)


@contextmanager
def watchdog(name: str, limit_s: float, beat_s: float = HEARTBEAT_S) -> Iterator[None]:
    """Run the block under a limit: a line every ``beat_s``, a stop past ``limit_s``."""
    start, stop, over = time.monotonic(), threading.Event(), threading.Event()

    def watch() -> None:
        while not stop.wait(beat_s):
            minutes = (time.monotonic() - start) / 60
            if time.monotonic() - start > limit_s:
                over.set()
                _thread.interrupt_main()
                return
            sys.stderr.write(f"still on {name}: {minutes:.0f} min\n")

    thread = threading.Thread(target=watch, daemon=True)
    thread.start()
    try:
        yield
    except KeyboardInterrupt:
        if over.is_set():
            msg = f"{name} ran over {limit_s / 60:.0f} min; finished databases are kept"
            raise OverLimitError(msg) from None
        raise
    finally:
        stop.set()


def show(path: Path, done: Sequence[str], total: int, tallies: dict[str, Tally]) -> None:
    """Write the tables over the databases finished so far; the run's tallies stay as is."""
    snapshot = copy.deepcopy(list(tallies.values()))
    for tally in snapshot:
        tally.inference.settle()  # settling clears the pending series: a copy's only
    when = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    head = f"After {len(done)} of {total} databases, {when}: {', '.join(done)}"
    text = "\n\n".join((head, table(snapshot), levels(snapshot), prices(snapshot))) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_suffix(".part")
    part.write_text(text, encoding="utf-8")
    part.replace(path)
