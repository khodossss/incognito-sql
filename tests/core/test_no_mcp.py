"""The core and the command line import without the optional `mcp` SDK installed."""

import subprocess
import sys

# A fresh interpreter where any `import mcp` fails as if the extra were not installed.
_PROBE = """
import importlib, pkgutil, sys

class _NoMcp:
    def find_spec(self, name, path=None, target=None):
        if name == "mcp" or name.startswith("mcp."):
            raise ModuleNotFoundError(f"No module named {name!r}")

sys.meta_path.insert(0, _NoMcp())
import incognito_sql.core
for info in pkgutil.walk_packages(incognito_sql.core.__path__, "incognito_sql.core."):
    importlib.import_module(info.name)
import incognito_sql.cli
import incognito_sql.sdk
assert "mcp" not in sys.modules
"""


def test_core_and_cli_import_without_mcp() -> None:
    done = subprocess.run(  # noqa: S603 -- fixed probe, this interpreter
        [sys.executable, "-c", _PROBE], capture_output=True, text=True, check=False
    )
    assert done.returncode == 0, done.stderr


def test_server_needs_mcp() -> None:
    probe = _PROBE.replace('assert "mcp" not in sys.modules', "import incognito_sql.mcp.server")
    done = subprocess.run(  # noqa: S603 -- fixed probe, this interpreter
        [sys.executable, "-c", probe], capture_output=True, text=True, check=False
    )
    assert "No module named 'mcp" in done.stderr
