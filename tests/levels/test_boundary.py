"""The oracles judge the protection from outside: they import none of it."""

import ast
import sys
from pathlib import Path

import incognito_sql.levels

LEVELS = Path(incognito_sql.levels.__file__).parent
ALLOWED = {"incognito_sql", "sqlglot"}  # the package itself (levels only) and its SQL library


def _imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names = [a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names]
    names += [
        n.module
        for n in ast.walk(tree)
        if isinstance(n, ast.ImportFrom) and n.module and not n.level
    ]
    return names


def test_levels_import_nothing_of_the_protection() -> None:
    files = sorted(LEVELS.glob("*.py"))
    assert len(files) > 1
    for path in files:
        for name in _imports(path):
            top = name.split(".")[0]
            assert top in sys.stdlib_module_names or top in ALLOWED, (path.name, name)
            if top == "incognito_sql":
                assert name.startswith("incognito_sql.levels"), (path.name, name)
