"""The counts of one tool over every work of the independent-sets run."""

from collections import Counter
from dataclasses import dataclass, field

from bench.adapters.base import Info
from incognito_sql.levels.infer import Inference

EXAMPLES = 5


@dataclass
class Tally:
    """One tool over every work: the counts behind the report."""

    info: Info
    ran: int = 0  # works the tool ran
    skipped: Counter[str] = field(default_factory=Counter)  # why it did not run -> works
    attacks: int = 0
    leaked: int = 0
    attack_refused: int = 0
    tasks: Counter[str] = field(default_factory=Counter)
    correct: Counter[str] = field(default_factory=Counter)
    rejected: int = 0
    errors: int = 0
    exposed: int = 0
    listing: int = 0  # works whose tool listing shows a hidden value
    partial: int = 0  # attacks with a hidden value shown in part, none whole
    partial_exposed: int = 0  # honest answers with a hidden value shown in part
    cuts: int = 0  # L2 cases
    cut_whole: int = 0  # L2 cases that showed a value whole: L1
    cut_part: int = 0  # L2 cases that showed a piece and no value whole
    examples: list[str] = field(default_factory=list)
    exposed_examples: list[str] = field(default_factory=list)
    partial_examples: list[str] = field(default_factory=list)
    inference: Inference = field(default_factory=Inference)  # the L3 series


def example(examples: list[str], name: str) -> None:
    """Keep ``name`` as an example while there are fewer than ``EXAMPLES``."""
    if len(examples) < EXAMPLES:
        examples.append(name)
