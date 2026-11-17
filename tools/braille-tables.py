#!/usr/bin/env python3
"""Show a line of text translated three ways, cell by cell.

    ./tools/braille-tables.py "the word is привет here"
    ./tools/braille-tables.py            # a built-in set of examples

Three renderings, so the difference mixed tables make is visible rather than
asserted:

1. **one table** -- the default table for the whole line, which is what Orca
   does unaided. Text the table cannot represent degrades to liblouis hex
   escapes, eight cells per character.
2. **dominant** -- one table chosen for the line's main language, which is
   what Polyglot did before. Correct for the majority and wrong for the rest.
3. **per run** -- a table per language run, which is what it does now.

Each is shown as braille characters, as dot numbers per cell, and as the byte
BRLAPI would receive, so a cell can be checked by hand against a table chart.
Nothing here touches BRLTTY or the display.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.expanduser("~/.local/share/orca/extensions"))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import louis  # noqa: E402

from polyglot.language_detector import _get_script  # noqa: E402
from polyglot.mixed_braille import (  # noqa: E402
    UNICODE_DIS,
    MixedBraille,
    cells_of,
)

TABLES = "/usr/share/liblouis/tables"
DEFAULT_TABLE = f"{TABLES}/en-ueb-g2.ctb"
LANG_TABLES = {
    "ru": f"{TABLES}/ru-litbrl-detailed.utb",
    "de": f"{TABLES}/de-g1.ctb",
    "en": f"{TABLES}/en-ueb-g2.ctb",
    "ipa": f"{TABLES}/IPA.utb",
    "unicode_braille": f"{TABLES}/unicode-braille.utb",
}
SCRIPT_MAP = {"CYRILLIC": "ru", "IPA": "ipa", "BRAILLE": "unicode_braille"}

EXAMPLES = [
    "the word is привет here",
    "привет, this is mixed",
    "читать a book",
    "no other language at all",
]


def dot_numbers(cell: int) -> str:
    """Returns a cell as its dot numbers, e.g. 19 -> '125'."""

    if cell == 0:
        return "-"
    return "".join(str(dot) for dot in range(1, 9) if cell & (1 << (dot - 1)))


def show(label: str, braille: str, indent: str = "    ") -> None:
    cells = cells_of(braille)
    print(f"{indent}{label:>10}: {braille}")
    print(f"{indent}{'':>10}  {len(cells)} cells")
    print(f"{indent}{'':>10}  dots:  {' '.join(dot_numbers(c) for c in cells)}")
    print(f"{indent}{'':>10}  bytes: {' '.join(str(c) for c in cells)}")


def dominant_language(text: str) -> str | None:
    """The language of most of the line's scripted characters."""

    counts: dict = {}
    for char in text:
        script = _get_script(char)
        if script is None:
            continue
        language = SCRIPT_MAP.get(script)
        counts[language] = counts.get(language, 0) + 1
    if not counts:
        return None
    return max(counts, key=counts.get)


def report(text: str) -> None:
    mixer = MixedBraille(
        table_for=LANG_TABLES.get,
        script_map=lambda: SCRIPT_MAP,
        get_script=_get_script,
    )
    tabled = mixer.tables_for(text, DEFAULT_TABLE)

    print(f"  {text!r}")
    print(f"    runs: " + " | ".join(
        f"{text[s:e]!r} -> {t.rsplit('/', 1)[-1]}" for s, e, t in tabled
    ))
    print()

    one = louis.translate([UNICODE_DIS, DEFAULT_TABLE], text)[0]
    show("one table", one)

    language = dominant_language(text)
    table = LANG_TABLES.get(language) or DEFAULT_TABLE
    best = louis.translate([UNICODE_DIS, table], text)[0]
    show(f"dominant", best)
    print(f"{'':14}  (chose {table.rsplit('/', 1)[-1]}, the table for "
          f"{language or 'the line default'}, which most of the line is in)")

    from polyglot.mixed_braille import translate_segments

    mixed = translate_segments(
        louis.translate, tabled, text, None, 0, 0,
        getattr(louis, "compbrlAtCursor", 0),
    )[0]
    show("per run", mixed)

    if len(tabled) > 1:
        print(f"{'':14}  one table needed {len(one)} cells for this line;"
              f" per run needs {len(mixed)}")
    print()


def main(argv: list[str]) -> int:
    lines = argv[1:] or EXAMPLES
    print()
    for text in lines:
        report(text)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
