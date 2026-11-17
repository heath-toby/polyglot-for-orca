#!/usr/bin/env python3
"""Show what mixed-table braille actually put on the display.

    ./tools/braille-trace.py            # the last 20 lines translated
    ./tools/braille-trace.py -n 50      # more of them
    ./tools/braille-trace.py -f         # follow, as lines are read
    ./tools/braille-trace.py --check    # re-translate each line and compare

Polyglot writes a line to its debug log every time a braille line needed more
than one table, naming each run, the table it chose and the cells that came
out. This reads those back.

**--check is the point of the tool.** It takes the runs out of the log,
translates them again here with liblouis, and compares the result with what
was logged. Agreement means the cells on the display are the cells the tables
say they should be -- which is the one thing that cannot be seen by reading
the display, since a wrong cell still feels like a cell.

Needs Polyglot's debug logging on:
    Orca Preferences -> User Extensions -> Polyglot, or
    dconf write /org/gnome/orca/default/extensions/polyglot/... (see README)
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import time

sys.path.insert(0, os.path.expanduser("~/.local/share/orca/extensions"))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

LOG = os.path.join(
    os.environ.get("XDG_DATA_HOME", os.path.expanduser("~/.local/share")),
    "orca", "polyglot", "debug.log",
)

#: A logged mixed line: "<stamp> mixed braille: 'a'->t1 | 'b'->t2 => <cells>"
_LINE = re.compile(r"^(?P<stamp>[\d-]+ [\d:]+) mixed braille: (?P<body>.*?) => (?P<cells>.*)$")
_RUN = re.compile(r"^(?P<text>'.*'|\".*\")->(?P<table>\S+)$")

TABLES = "/usr/share/liblouis/tables"


def parse(line):
    """Returns (stamp, [(text, table)], cells) or None."""

    match = _LINE.match(line.rstrip("\n"))
    if match is None:
        return None
    runs = []
    for piece in match.group("body").split(" | "):
        run = _RUN.match(piece.strip())
        if run is None:
            return None
        try:
            text = eval(run.group("text"), {"__builtins__": {}}, {})  # noqa: S307
        except Exception:  # pylint: disable=broad-exception-caught
            return None
        if not isinstance(text, str):
            return None
        runs.append((text, run.group("table")))
    return match.group("stamp"), runs, match.group("cells")


def entries(path, limit=None):
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            lines = handle.readlines()
    except OSError as error:
        print(f"  cannot read {path}: {error}", file=sys.stderr)
        return []
    found = [parsed for parsed in (parse(line) for line in lines) if parsed]
    return found[-limit:] if limit else found


def recheck(runs, logged_cells):
    """Re-translate the runs and compare with what was logged."""

    import louis

    from polyglot.mixed_braille import UNICODE_DIS

    rebuilt = []
    for text, table in runs:
        path = table if "/" in table else f"{TABLES}/{table}"
        try:
            rebuilt.append(louis.translate([UNICODE_DIS, path], text)[0])
        except Exception as error:  # pylint: disable=broad-exception-caught
            return None, f"{table}: {error}"
    joined = "".join(rebuilt)
    return joined, None if joined == logged_cells else "differs"


def show(parsed, check):
    stamp, runs, cells = parsed
    print(f"  {stamp}")
    for text, table in runs:
        print(f"    {text!r:40} {table.rsplit('/', 1)[-1]}")
    print(f"    {'cells on the display':40} {cells}")
    if check:
        rebuilt, problem = recheck(runs, cells)
        if problem is None:
            print(f"    {'re-translated here':40} matches")
        elif rebuilt is None:
            print(f"    {'re-translated here':40} could not ({problem})")
        else:
            print(f"    {'re-translated here':40} {rebuilt}")
            print(f"    {'':40} DIFFERS from the display")
    print()


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("-n", type=int, default=20, help="how many to show")
    parser.add_argument("-f", "--follow", action="store_true", help="keep watching")
    parser.add_argument("--check", action="store_true",
                        help="re-translate each line and compare")
    parser.add_argument("--log", default=LOG, help="log file to read")
    args = parser.parse_args(argv[1:])

    if not os.path.exists(args.log):
        print(f"\n  No log at {args.log}.")
        print("  Polyglot's debug logging is off, or no mixed line has been read yet.\n")
        return 1

    found = entries(args.log, args.n)
    print()
    if not found:
        print("  No mixed-table lines logged yet. Read a line with two languages in it.\n")
    for parsed in found:
        show(parsed, args.check)

    if not args.follow:
        checked = sum(1 for _ in found)
        if args.check and checked:
            print(f"  {checked} line(s) re-translated.\n")
        return 0

    seen = len(entries(args.log))
    print("  Following. Ctrl+C to stop.\n")
    try:
        while True:
            time.sleep(1.0)
            current = entries(args.log)
            for parsed in current[seen:]:
                show(parsed, args.check)
            seen = len(current)
    except KeyboardInterrupt:
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
