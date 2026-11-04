"""Send random queries through incognito-sql in both modes; a hidden canary anywhere is a finding.

    uv run python -m bench.fuzz.run --count 2000 --seed 7 --out fuzz-findings.yaml

The same seed and count replay the same queries. Findings are written as YAML (DBMS,
mode, seed, index, SQL, canaries found), ready to become attack-corpus cases.
"""

import argparse
import random
import sys
import tempfile
from collections import Counter
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path

import yaml

from bench import dbms
from bench.adapters.incognito import IncognitoAdapter, open_incognito
from bench.fuzz.grammar import Grammar
from bench.oracle import leaks
from bench.run import SEED
from bench.schema import DIALECTS
from bench.templates import expand
from bench.world import generate_world


@dataclass(frozen=True)
class Finding:
    """A random query after which the oracle found hidden canaries."""

    dialect: str
    mode: str
    seed: int
    index: int
    sql: str
    canaries: list[str]


@dataclass
class Tally:
    """What happened to the queries on one DBMS, per mode."""

    sent: int = 0
    statuses: Counter[str] = field(default_factory=Counter)
    findings: list[Finding] = field(default_factory=list)


def fuzz(
    adapters: Sequence[IncognitoAdapter],
    forbidden: frozenset[str],
    seed: int,
    count: int,
) -> Tally:
    """Send ``count`` queries drawn from ``seed`` through every adapter; scan every channel."""
    tally = Tally()
    dialect = adapters[0].dialect
    grammar = Grammar(random.Random(seed), dialect)  # noqa: S311 -- reproducible, not secret
    for index in range(count):
        sql = grammar.query()
        for adapter in adapters:
            outcome = adapter.query(expand(sql, adapter.tokens))
            tally.sent += 1
            tally.statuses[f"{adapter.mode}:{outcome.status}"] += 1
            text = "\n".join([outcome.text, *adapter.channels().values()])
            found = leaks(text, forbidden)
            if found:
                finding = Finding(dialect, adapter.mode, seed, index, sql, found)
                tally.findings.append(finding)
    return tally


def run_on(dialect: str, seed: int, count: int) -> Tally:
    """Start ``dialect`` with the bench world, fuzz our gateway on it, stop it."""
    world = generate_world(SEED)
    with (
        dbms.opened(dialect, world.statements(dialect), limit=dbms.LIMIT_S) as db,
        tempfile.TemporaryDirectory(prefix="fuzz-", ignore_cleanup_errors=True) as work,
    ):
        adapters = open_incognito(world, db, Path(work))
        try:
            return fuzz(adapters, world.planted(dialect), seed, count)
        finally:
            for adapter in adapters:
                adapter.close()


def main(argv: Sequence[str] | None = None) -> int:
    """Fuzz each DBMS asked for; exit 1 on any finding (written to ``--out``), 2 on a crash.

    Findings are written after every DBMS, so a later DBMS that fails to start does not
    lose them; a crashed DBMS is reported and the others still run.
    """
    parser = argparse.ArgumentParser(prog="bench.fuzz.run", description=__doc__)
    parser.add_argument("--dialects", nargs="*", default=list(DIALECTS))
    parser.add_argument("--count", type=int, default=500, help="queries per DBMS")
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--out", type=Path, default=Path("fuzz-findings.yaml"))
    args = parser.parse_args(argv)
    findings, crashed = list[Finding](), list[str]()
    for dialect in args.dialects:
        try:
            tally = run_on(dialect, args.seed, args.count)
        except Exception as exc:  # noqa: BLE001 -- one DBMS down must not hide the others
            crashed.append(dialect)
            sys.stdout.write(f"{dialect}: crashed: {type(exc).__name__}\n")
            continue
        statuses = ", ".join(f"{k} {v}" for k, v in sorted(tally.statuses.items()))
        sys.stdout.write(
            f"{dialect}: {tally.sent} sent; {statuses}; findings {len(tally.findings)}\n"
        )
        findings += tally.findings
        if findings:
            args.out.write_text(
                yaml.safe_dump([asdict(f) for f in findings], allow_unicode=True),
                encoding="utf-8",
            )
    if findings:
        sys.stdout.write(f"{len(findings)} findings written to {args.out}\n")
        return 1
    return 2 if crashed else 0


if __name__ == "__main__":
    sys.exit(main())
