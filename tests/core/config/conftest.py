"""Fixtures for declaration tests."""

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import yaml


@pytest.fixture
def write_yaml(tmp_path: Path) -> Callable[..., Path]:
    """Return a writer of a minimal valid declaration with overrides."""

    def _write(**overrides: Any) -> Path:  # noqa: ANN401
        data: dict[str, Any] = {
            "dsn_env": "DB_DSN",
            "dialect": "postgres",
            "columns": {"people": {"full_name": "identifier", "id": "open"}},
            "entities": [],
        }
        data.update(overrides)
        path = tmp_path / "decl.yaml"
        path.write_text(yaml.safe_dump(data), encoding="utf-8")
        return path

    return _write
