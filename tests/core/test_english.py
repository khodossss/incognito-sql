"""Everything the package ships is English: no Cyrillic in code, templates or instructions."""

from pathlib import Path

import incognito_sql
from incognito_sql.core.output.mask import MASK

PACKAGE = Path(incognito_sql.__file__).parent
CYRILLIC = range(0x0400, 0x0530)


def test_no_cyrillic_in_the_package() -> None:
    found = [
        str(path.relative_to(PACKAGE))
        for path in PACKAGE.rglob("*")
        if path.is_file()
        and path.suffix in {".py", ".html", ".md", ".sql"}
        and any(ord(ch) in CYRILLIC for ch in path.read_text("utf-8"))
    ]
    assert found == []


def test_the_mask_is_named_in_the_instructions() -> None:
    instructions = (PACKAGE / "mcp" / "instructions.md").read_text("utf-8")
    assert MASK in instructions
