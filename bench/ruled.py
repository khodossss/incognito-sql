"""The world's tables under rules on rows: patients, and visits that name them.

Patient 4 is gone and patient 3's name and ward are hidden (``ROW_RULES``); neither
key may reach a label (``HIDDEN_KEYS``). The names are plain: what a label gives is a
key. The wards the rules hide carry canaries; the others do not.
"""

from bench.canary import CanaryMint

PATIENT_NAMES = ("Ilan Merovy", "Tova Garnet", "Sela Brandish", "Oren Quillby")
ROW_RULES = (
    "{table: patients, hide: '*', where: 'id = 4'}",
    "{table: patients, hide: [full_name, ward], where: 'id = 3'}",
)
HIDDEN_KEYS = {"patients": frozenset({3, 4})}
Rows = tuple[tuple[object, ...], ...]


def ruled_rows(mint: CanaryMint) -> tuple[Rows, Rows]:
    """Return the rows of PATIENTS and of VISITS."""
    wards = ("Ward North", "Ward South", mint.ruled(), mint.ruled())
    patients = tuple((i + 1, name, wards[i]) for i, name in enumerate(PATIENT_NAMES))
    visits = tuple((11 + i, name, f"Room {i + 1}") for i, name in enumerate(PATIENT_NAMES))
    return patients, visits
