"""Load a field declaration from YAML."""

from pathlib import Path
from typing import get_args

import yaml
from pydantic import BaseModel, ValidationError

from incognito_sql.core.config.model import Declaration


def load_declaration(path: Path) -> Declaration:
    """Read and validate a declaration file; raise pydantic.ValidationError if invalid."""
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return Declaration.model_validate(raw)


def config_problem(exc: Exception) -> str:
    """Return one line saying what is wrong with a config: a schema error names its place.

    Nothing the operator typed is repeated: a place names only the schema's own fields and
    list positions, any other key reads ``<key>``; a validator's message, which may quote
    a value, reads "invalid value"; a YAML error is named by its line and column, never by
    its tag or alias; any other error by its type only (a typed tag such as ``!!int``
    fails with the value in its message).
    """
    if isinstance(exc, ValidationError):
        first = exc.errors()[0]
        if first["type"] == "extra_forbidden":
            return f"{_place(first['loc'][:-1]) or 'top level'}: unknown key"
        where = _place(first["loc"])
        what = "invalid value" if first["type"] in _QUOTING else first["msg"]
        return f"{where}: {what}" if where else str(what)
    if isinstance(exc, yaml.YAMLError):
        mark = getattr(exc, "problem_mark", None)
        at = f" at line {mark.line + 1}, column {mark.column + 1}" if mark is not None else ""
        return f"invalid YAML{at}"
    return type(exc).__name__


_QUOTING = frozenset({"value_error", "assertion_error"})  # our validators' own messages
_INDEX = 1000  # a list's position is a small number; a larger one is a key the operator typed


def _fields(model: type[BaseModel]) -> set[str]:
    """Return the field names of ``model`` and of every model its fields hold."""
    names, todo, seen = set(), [model], set()
    while todo:
        current = todo.pop()
        if current in seen:
            continue
        seen.add(current)
        for name, field in current.model_fields.items():
            names.add(name)
            todo.extend(_models(field.annotation))
    return names


def _models(annotation: object) -> list[type[BaseModel]]:
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return [annotation]
    return [m for arg in get_args(annotation) for m in _models(arg)]


_FIELDS = frozenset(_fields(Declaration))


def _place(loc: tuple[int | str, ...]) -> str:
    """Join an error's place: the schema's fields and list positions; other keys ``<key>``."""
    return ".".join(
        str(part)
        if (isinstance(part, int) and not isinstance(part, bool) and 0 <= part < _INDEX)
        or part in _FIELDS
        else "<key>"
        for part in loc
    )
