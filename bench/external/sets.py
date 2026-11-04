"""Read the sets' question files: Spider dev, BIRD Mini-Dev (SQLite) and SecureSQL.

SecureSQL labels (Song et al., Findings of EMNLP 2024, Table 1): ``DI`` direct attack,
``PR`` inference from prior knowledge, ``RE`` inference by common sense or numerical
reasoning, ``SA`` safe, ``SU`` suspicious but safe. DI, PR and RE are attacks here; SA
and SU are honest questions, scored for utility.
"""

import json
from dataclasses import dataclass
from pathlib import Path

ATTACKS = frozenset({"DI", "PR", "RE"})
SAFE = frozenset({"SA", "SU"})


@dataclass(frozen=True)
class Question:
    """One question of a set with its reference SQL."""

    id: str
    source: str
    db: str
    sql: str


@dataclass(frozen=True)
class Record:
    """One SecureSQL sample: a security condition and the queries asked under it."""

    id: str
    db: str
    condition: str
    queries: tuple[str, ...]
    label: str

    @property
    def attack(self) -> bool:
        """Tell whether the sample leaks what its condition protects."""
        return self.label in ATTACKS


def read(path: Path) -> list[dict[str, object]]:
    """Read a JSON list of objects."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list) or not all(isinstance(x, dict) for x in data):
        msg = f"{path.name}: not a list of objects"
        raise ValueError(msg)
    return data


def spider(raw: list[dict[str, object]]) -> list[Question]:
    """Spider dev questions; the id is the position in ``dev.json``."""
    return [
        Question(f"spider-{i}", "spider", _text(r, "db_id"), _text(r, "query"))
        for i, r in enumerate(raw)
    ]


def bird(raw: list[dict[str, object]]) -> list[Question]:
    """BIRD Mini-Dev SQLite questions; the id is the set's ``question_id``."""
    return [
        Question(f"bird-{r['question_id']}", "bird", _text(r, "db_id"), _text(r, "SQL"))
        for r in raw
    ]


def securesql(raw: list[dict[str, object]]) -> list[Record]:
    """SecureSQL samples; an unknown label is an error."""
    out = []
    for r in raw:
        label, queries = _text(r, "label"), r.get("queries")
        if label not in ATTACKS | SAFE or not isinstance(queries, list):
            msg = f"securesql {r.get('id')}: bad sample"
            raise ValueError(msg)
        sqls = tuple(str(q) for q in queries)
        out.append(
            Record(
                f"securesql-{r['id']}",
                _text(r, "db_id"),
                _text(r, "security_condition"),
                sqls,
                label,
            )
        )
    return out


def _text(raw: dict[str, object], key: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str):
        msg = f"missing {key}: {raw!r}"[:200]
        raise TypeError(msg)
    return value
