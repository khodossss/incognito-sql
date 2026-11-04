"""`incognito-sql audit verify`: check the audit log's chain with the service's key."""

import argparse
import os
import sys
from pathlib import Path

from incognito_sql.core.audit_chain import Anchor
from incognito_sql.core.audit_verify import verify
from incognito_sql.core.tokens.crypto import Cipher, load_key
from incognito_sql.envfile import EnvFileError, load_env_file
from incognito_sql.wiring import audit_path, store_path

EXIT_BROKEN, EXIT_UNREADABLE = 1, 2


def add_audit_parser(commands: "argparse._SubParsersAction[argparse.ArgumentParser]") -> None:
    """Add `audit verify` to the command line."""
    audit = commands.add_parser("audit", help="the audit log")
    actions = audit.add_subparsers(dest="audit_command", required=True)
    check = actions.add_parser("verify", help="check that no line was edited, removed or added")
    check.add_argument("--config", type=Path, required=True, help="the service's declaration")
    check.add_argument("--env-file", type=Path, help="KEY=VALUE secrets for unset variables")


def run_audit(args: argparse.Namespace) -> int:
    """Check the chain; print what was checked and the first break; return the exit code."""
    log, store = audit_path(args.config), store_path(args.config)
    try:
        if args.env_file is not None:
            load_env_file(args.env_file, os.environ)
        cipher = Cipher(load_key())
        anchor = Anchor(store) if store.exists() else None
        try:
            verdict = verify(log, cipher, anchor.get() if anchor else None)
        finally:
            if anchor is not None:
                anchor.close()
    except (OSError, EnvFileError, RuntimeError, ValueError) as exc:
        sys.stderr.write(f"incognito-sql: audit verify: {type(exc).__name__}\n")
        return EXIT_UNREADABLE
    sys.stdout.write(
        f"lines: {verdict.lines}; before the chain: {verdict.before_chain}; "
        f"checked: {verdict.checked}; anchor: {verdict.anchor}\n"
    )
    if verdict.holds:
        sys.stdout.write("the chain holds\n")
        return 0
    sys.stdout.write(f"broken: {verdict.broken}\n")
    return EXIT_BROKEN
