#!/usr/bin/env python3
"""Each language on a braille line in its own table.

Orca contracts a braille region with one ``louis.translate`` call that returns
the output and two maps: a text offset per cell, and a cell per text offset.
Routing keys, the cursor, attribute underlining and panning all read those
maps. Translating a line in several tables means calling translate once per
run and joining three things, and **the maps are the whole risk**: get them
wrong and the display still looks right while routing lands on the wrong
character. So most of these rows check the maps, not the output.

The translation itself is real liblouis against Toby's own tables. Nothing
here needs BRLTTY or a display.

Usage: python3 tests-mixed-braille.py
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.expanduser("~/.local/share/orca/extensions"))

import louis  # noqa: E402

from polyglot.mixed_braille import (  # noqa: E402
    BRAILLE_ROW,
    MAX_DETECT_LENGTH,
    UNICODE_DIS,
    MixedBraille,
    _LouisProxy,
    cells_of,
    is_braille,
    merge_runs,
    script_runs,
    segment_at,
    translate_segments,
)
from polyglot.language_detector import _get_script  # noqa: E402

TABLES = "/usr/share/liblouis/tables"
EN = f"{TABLES}/en-ueb-g2.ctb"
RU = f"{TABLES}/ru-litbrl-detailed.utb"
DE = f"{TABLES}/de-g1.ctb"
SCRIPT_MAP = {"CYRILLIC": "ru", "BRAILLE": "unicode_braille", "IPA": "ipa"}
LANG_TABLES = {"ru": RU, "de": DE, "en": EN}

rows, fails = [], 0


def check(name, got, want):
    global fails
    ok = got == want
    if not ok:
        fails += 1
    # Record what was compared, not a reference to it: a live list appended to
    # later would print its final state beside a verdict reached earlier.
    rows.append((name, repr(want), repr(got), "ok" if ok else "FAIL"))


def runs(text):
    return script_runs(text, SCRIPT_MAP, _get_script)


# --- Splitting a line by script ----------------------------------------------
# Script rather than statistics, because a braille line is short: a Mantis
# shows forty cells, and Polyglot's mixed detector declines anything under
# eight words. One Cyrillic word is Cyrillic however few words surround it.

check("an English line is one run", runs("the word is here"), [(0, 16, None)])
check("a Russian line is one run", runs("привет мир"), [(0, 10, "ru")])
check("English then Russian splits",
      runs("hello привет"), [(0, 6, None), (6, 12, "ru")])
check("Russian then English splits",
      runs("привет hello"), [(0, 7, "ru"), (7, 12, None)])
check("English, Russian, English",
      runs("say привет now"), [(0, 4, None), (4, 11, "ru"), (11, 14, None)])

# The space between two languages belongs to the first, so it can never
# become a run of its own and split a line into three where there are two.
text = "hello привет"
segments = runs(text)
check("the space goes with the run before it",
      text[segments[0][0]:segments[0][1]], "hello ")

check("leading punctuation joins the first scripted run",
      runs('"привет" said'), [(0, 9, "ru"), (9, 13, None)])
check("trailing punctuation joins the last run",
      runs("привет!!!"), [(0, 9, "ru")])
check("a line of digits alone is one undecided run",
      runs("123 456"), [(0, 7, None)])
check("punctuation alone is one undecided run", runs("--- ..."), [(0, 7, None)])
check("an empty line has no runs", runs(""), [])
check("one Cyrillic character is still Cyrillic", runs("д"), [(0, 1, "ru")])
check("a single Cyrillic word inside English splits",
      runs("the да word"), [(0, 4, None), (4, 7, "ru"), (7, 11, None)])
check("braille input maps through the script map",
      runs("⠮⠀⠘⠺"), [(0, 4, "unicode_braille")])
check("an unmapped script is left undecided",
      script_runs("привет", {}, _get_script), [(0, 6, None)])

# --- The invariant everything else depends on --------------------------------
# Segments must cover the line exactly: a gap would drop characters from the
# display and an overlap would double them.

SAMPLES = [
    "", "a", "д", "the word is here", "привет мир", "hello привет",
    "привет hello", "say привет now", '"привет" said', "привет!!!",
    "123 456", "--- ...", "  leading space", "trailing space  ",
    "ТЕКСТ and TEXT", "a д a д a", "⠮⠀⠘⠺", "mixed ⠮ braille привет",
    "ёлка", "наш IPA ɑ here", "\t\ttabs\t\t", "число 42 und wort",
]
bad_coverage = []
for sample in SAMPLES:
    found = runs(sample)
    if not sample:
        if found:
            bad_coverage.append((sample, "expected none"))
        continue
    if not found or found[0][0] != 0 or found[-1][1] != len(sample):
        bad_coverage.append((sample, found))
        continue
    if any(found[i][1] != found[i + 1][0] for i in range(len(found) - 1)):
        bad_coverage.append((sample, found))
check("every sample is covered exactly once, start to end", bad_coverage, [])

check("merging joins neighbours with the same language",
      merge_runs([(0, 3, None), (3, 6, None), (6, 9, "ru")]),
      [(0, 6, None), (6, 9, "ru")])
check("merging leaves alternating languages alone",
      merge_runs([(0, 3, "ru"), (3, 6, None), (6, 9, "ru")]),
      [(0, 3, "ru"), (3, 6, None), (6, 9, "ru")])

check("segment_at finds the holding segment",
      segment_at([(0, 5, None), (5, 10, "ru")], 7), (5, 10, "ru"))
check("segment_at past the end gives the last",
      segment_at([(0, 5, None), (5, 10, "ru")], 99), (5, 10, "ru"))
check("segment_at of nothing is None", segment_at([], 0), None)

# --- Dots rather than letters ------------------------------------------------
# BRLTTY renders the U+2800 block verbatim whatever its text table says, which
# is what makes a line of mixed tables render as translated rather than being
# mapped a second time.

plain = louis.translate([EN], "the word")[0]
dotted = louis.translate([UNICODE_DIS, EN], "the word")[0]
check("without unicode.dis liblouis returns letters", is_braille(plain), False)
check("with unicode.dis it returns braille patterns", is_braille(dotted), True)
check("the two agree on length", len(plain) == len(dotted), True)
check("a cell is the low byte of its character",
      cells_of("⠠⠓"), [0x20, 0x13])
check("every cell fits in a byte",
      all(0 <= c <= 255 for c in cells_of(dotted)), True)
check("the dot bits match BRLAPI's coding",
      cells_of("⠁⠂⠄⠈⠐⠠⡀⢀"), [1, 2, 4, 8, 16, 32, 64, 128])
check("is_braille rejects an empty string", is_braille(""), False)
check("is_braille rejects mixed content", is_braille("⠠a"), False)


# --- Joining the translations, and the maps ----------------------------------


def joined(text, tabled, cursor=None, mode=0):
    return translate_segments(
        louis.translate, tabled, text, None, cursor, mode,
        getattr(louis, "compbrlAtCursor", 0),
    )


# One segment must come out exactly as a single call would, or the add-on
# changes lines it has no opinion about.
text = "the word is here"
one = louis.translate([UNICODE_DIS, EN], text, cursorPos=5)
via = joined(text, [(0, len(text), EN)], cursor=5)
check("a single segment matches a single translate call", via[0], one[0])
check("a single segment matches its cell map", via[1], one[1])
check("a single segment matches its text map", via[2], one[2])
check("a single segment matches its cursor", via[3], one[3])

MIXED = "the word is привет here"
split = [(0, 12, EN), (12, 19, RU), (19, 23, EN)]
output, in_position, out_position, cursor = joined(MIXED, split)

check("the joined output is all braille", is_braille(output), True)
check("one map entry per cell", len(in_position), len(output))
check("one map entry per character", len(out_position), len(MIXED))

# Each cell must point at a character inside the segment that produced it.
wrong_segment = []
produced = []
for start, end, table in split:
    part = louis.translate([UNICODE_DIS, table], MIXED[start:end])[0]
    produced.extend([(start, end)] * len(part))
check("the segments produce as many cells as were joined",
      len(produced), len(output))
for cell, (start, end) in enumerate(produced):
    if cell >= len(in_position):
        break
    if not start <= in_position[cell] < end:
        wrong_segment.append((cell, in_position[cell], start, end))
check("every cell maps into the segment that produced it", wrong_segment, [])

# The round trip Orca actually performs: a routing key on cell N asks
# in_position for a character offset. That offset must name the character the
# reader is pressing on, which for a Cyrillic cell means a Cyrillic character.
misrouted = []
for cell, char in enumerate(output):
    offset = in_position[cell]
    if not 0 <= offset < len(MIXED):
        misrouted.append((cell, offset, "out of range"))
        continue
    script = _get_script(MIXED[offset])
    expected = "CYRILLIC" if 12 <= offset < 19 else None
    if script is not None and expected == "CYRILLIC" and script != "CYRILLIC":
        misrouted.append((cell, offset, MIXED[offset]))
check("routing a Cyrillic cell lands on a Cyrillic character", misrouted, [])

# out_position is the other direction, and must not run past the cells.
check("no text offset points past the last cell",
      [p for p in out_position if p > len(output)], [])
check("text offsets never go backwards",
      all(b >= a for a, b in zip(out_position, out_position[1:])), True)
check("the first character maps to the first cell", out_position[0], 0)

# The Russian really is in the Russian table: with one English table the
# Cyrillic degrades to liblouis hex escapes, which is what this replaces.
english_only = louis.translate([UNICODE_DIS, EN], MIXED)[0]
check("one table makes the line longer than per-segment",
      len(english_only) > len(output), True)
russian_part = louis.translate([UNICODE_DIS, RU], MIXED[12:19])[0]
check("the Russian cells appear verbatim in the joined line",
      russian_part in output, True)

# --- The cursor --------------------------------------------------------------

for offset, expected_segment in ((3, 0), (14, 1), (21, 2)):
    _o, _i, _r, cell = joined(MIXED, split, cursor=offset)
    start, end, table = split[expected_segment]
    before = sum(
        len(louis.translate([UNICODE_DIS, t], MIXED[s:e])[0])
        for s, e, t in split[:expected_segment]
    )
    after = before + len(louis.translate([UNICODE_DIS, table], MIXED[start:end])[0])
    check(f"a cursor at text {offset} lands in segment {expected_segment}",
          cell is not None and before <= cell <= after, True)

_o, _i, _r, no_cursor = joined(MIXED, split, cursor=None)
check("no cursor asked for, none reported", no_cursor, None)

# compbrlAtCursor must reach only the segment holding the cursor; left set on
# the others, each would show its first word in computer braille.
comp = getattr(louis, "compbrlAtCursor", 0)
seen_modes = []


def recording_translate(tables, text, typeform=None, cursorPos=None, mode=0):
    seen_modes.append((text, mode & comp != 0, cursorPos))
    return louis.translate(tables, text, typeform=typeform, cursorPos=cursorPos, mode=mode)


translate_segments(recording_translate, split, MIXED, None, 14, comp, comp)
check("exactly one segment is given the cursor flag",
      sum(1 for _t, flagged, _c in seen_modes if flagged), 1)
check("the flagged segment is the one holding the cursor",
      [t for t, flagged, _c in seen_modes if flagged], [MIXED[12:19]])
# Every segment is handed an offset, because liblouis has no "no cursor"
# value; what must hold is that the segments without the cursor are handed a
# plain 0 with the flag cleared, which is inert, and that the one holding it
# is handed the offset relative to its own start.
check("the segments without the cursor are handed an inert zero",
      [cursor_pos for text, flagged, cursor_pos in seen_modes if not flagged],
      [0, 0])
check("the cursor segment is handed its own relative offset",
      [cursor_pos for _t, flagged, cursor_pos in seen_modes if flagged],
      [14 - 12])


# --- The proxy ---------------------------------------------------------------


class FakeLouis:
    compbrlAtCursor = 0x100
    dotsIO = 4

    def translate(self, *args, **kwargs):
        return ("original", [], [], None)

    def charToDots(self, tables, text):
        return "dots"


fake = FakeLouis()
proxy = _LouisProxy(fake, lambda *a, **k: ("wrapped", [], [], None))
check("the proxy intercepts translate", proxy.translate()[0], "wrapped")
check("the proxy passes compbrlAtCursor through", proxy.compbrlAtCursor, 0x100)
check("the proxy passes other functions through",
      proxy.charToDots([], ""), "dots")
check("the proxy is truthy, as Orca's checks require", bool(proxy), True)


# --- Choosing tables, and failing safely -------------------------------------

mixer = MixedBraille(
    table_for=LANG_TABLES.get,
    script_map=lambda: SCRIPT_MAP,
    get_script=_get_script,
)

check("an English line gets the table Orca asked for",
      mixer.tables_for("the word", EN), [(0, 8, EN)])
check("a mixed line gets a table each",
      mixer.tables_for("the привет word", EN),
      [(0, 4, EN), (4, 11, RU), (11, 15, EN)])
check("a language with no table of its own keeps Orca's",
      MixedBraille(lambda _l: None, lambda: SCRIPT_MAP, _get_script)
      .tables_for("the привет word", EN), [(0, 15, EN)])
check("neighbouring runs on the same table are merged",
      MixedBraille(lambda _l: EN, lambda: SCRIPT_MAP, _get_script)
      .tables_for("the привет word", EN), [(0, 15, EN)])

check("a very long line is not segmented",
      mixer.tables_for("привет " * (MAX_DETECT_LENGTH // 4), EN)[0][2], EN)
check("a very long line is one segment",
      len(mixer.tables_for("привет " * (MAX_DETECT_LENGTH // 4), EN)), 1)

# The same line twice must give the same answer, or it would flicker between
# tables as the caret moves along it.
first = mixer.tables_for("the привет word", EN)
second = mixer.tables_for("the привет word", EN)
check("the same line segments identically on a second pass", second, first)

# A broken table must not take the display out: a line in the wrong table is
# a nuisance, a line that raises is a screen reader with no braille.
logged = []
broken = MixedBraille(
    table_for=lambda _lang: "/nonexistent/table.ctb",
    script_map=lambda: SCRIPT_MAP,
    get_script=_get_script,
    log=logged.append,
)
broken._installed = True
broken._real_louis = louis
broken._original_translate = louis.translate
result = broken._translate([EN], "the привет word")
check("a broken table falls back instead of raising",
      is_braille(result[0]) or isinstance(result[0], str), True)
check("the fallback is reported once", len(logged), 1)
broken._translate([EN], "the привет word")
check("the same broken table is not reported twice", len(logged), 1)

# Input that cannot be segmented must go straight through.
passthrough = MixedBraille(LANG_TABLES.get, lambda: SCRIPT_MAP, _get_script)
passthrough._installed = True
passthrough._real_louis = louis
passthrough._original_translate = louis.translate
check("an empty line goes to the original call",
      passthrough._translate([EN], "")[0], louis.translate([EN], "")[0])
check("a line with a NUL goes to the original call",
      passthrough._translate([EN], "a\0b")[0], louis.translate([EN], "a\0b")[0])


def raises(call):
    try:
        call()
    except Exception as error:  # pylint: disable=broad-exception-caught
        return type(error).__name__
    return None


# An empty table list raises in liblouis itself. The wrapper must neither
# swallow that nor change it: Orca should fail exactly as it would unwrapped.
check("an empty table list raises the same way wrapped as unwrapped",
      raises(lambda: passthrough._translate([], "abc")),
      raises(lambda: louis.translate([], "abc")))
check("and that is a RuntimeError, not something the wrapper invented",
      raises(lambda: passthrough._translate([], "abc")), "RuntimeError")

# --- Refining a same-script run with the statistical detector ----------------
# Script cannot separate English from German, so a detector may be consulted
# for runs script left undecided. It is the less trustworthy source, and these
# rows are about containing it.


def refiner(runs):
    """A MixedBraille whose statistical detector returns `runs` verbatim."""

    return MixedBraille(
        table_for=LANG_TABLES.get,
        script_map=lambda: SCRIPT_MAP,
        get_script=_get_script,
        statistical=lambda _text: runs,
    )


text = "das ist ein deutscher Satz"
check("a run the detector claims is German gets the German table",
      refiner([(text, "de")]).tables_for(text, EN), [(0, len(text), DE)])

# A run marked with no language keeps the default, which is how the caller
# vetoes a claim it cannot justify -- a file path called German, say.
check("a run the detector declines to name keeps the default table",
      refiner([(text, None)]).tables_for(text, EN), [(0, len(text), EN)])

half = "hello there das ist"
check("the detector can split an undecided run in two",
      refiner([("hello there ", None), ("das ist", "de")]).tables_for(half, EN),
      [(0, 12, EN), (12, 19, DE)])

# If the runs do not reconstruct the text, their offsets cannot be trusted,
# and a wrong offset means a wrong table for the rest of the line. Script
# alone is the safe answer.
check("runs that do not reconstruct the text are discarded",
      refiner([("hello", "de")]).tables_for(half, EN), [(0, len(half), EN)])
check("a detector that returns nothing leaves script's answer alone",
      refiner(None).tables_for(half, EN), [(0, len(half), EN)])
check("a detector that raises leaves script's answer alone",
      MixedBraille(LANG_TABLES.get, lambda: SCRIPT_MAP, _get_script,
                   statistical=lambda _t: (_ for _ in ()).throw(ValueError("boom"))
                   ).tables_for(half, EN),
      [(0, len(half), EN)])

# Script evidence is never overridden by the detector: a Cyrillic run stays
# Cyrillic whatever a statistical guess says about the line around it.
mixed_text = "hello привет there"
check("the detector is not asked about a run script already decided",
      refiner([(mixed_text, "de")]).tables_for(mixed_text, EN),
      [(0, 6, EN), (6, 13, RU), (13, 18, EN)])

# --- Where an undecided run gets its language --------------------------------
# There is no German script, so a wholly German line is invisible to script
# detection. Before mixed braille, Polyglot set the table per line and got
# this right; it has to keep getting it right.

GERMAN = "das ist ein deutscher Satz"


def placer(line_language=None, default_language=None):
    return MixedBraille(
        table_for=LANG_TABLES.get,
        script_map=lambda: SCRIPT_MAP,
        get_script=_get_script,
        line_language=(lambda _t: line_language),
        default_language=(lambda: default_language),
    )


check("a line script cannot place at all takes the line's language",
      placer(line_language="de").tables_for(GERMAN, EN), [(0, len(GERMAN), DE)])
check("with no line language it keeps the table Orca asked for",
      placer().tables_for(GERMAN, EN), [(0, len(GERMAN), EN)])
check("a line language with no table of its own keeps Orca's",
      placer(line_language="xx").tables_for(GERMAN, EN), [(0, len(GERMAN), EN)])

# On a mixed line the undecided parts are the *other* language's, so the
# configured default is right and the line's dominant language is not: a line
# where Russian dominates must not put its English words in a Russian table.
RU_HEAVY = "привет мир здравствуй hello"
check("a mixed line's undecided run takes the configured default",
      placer(line_language="ru", default_language="en").tables_for(RU_HEAVY, DE),
      [(0, 22, RU), (22, 27, EN)])
check("and not the line's dominant language",
      [t for _s, _e, t in
       placer(line_language="ru", default_language="en").tables_for(RU_HEAVY, DE)
       if t == RU],
      [RU])
check("with no default language the undecided run keeps Orca's table",
      placer(line_language="ru").tables_for(RU_HEAVY, DE),
      [(0, 22, RU), (22, 27, DE)])

# The line language is asked about the whole line, not about a run, so the
# one-entry cache it keeps stays keyed on the text speech also uses.
asked = []
MixedBraille(
    table_for=LANG_TABLES.get,
    script_map=lambda: SCRIPT_MAP,
    get_script=_get_script,
    line_language=lambda text: asked.append(text) or "de",
).tables_for(GERMAN, EN)
check("the line language is asked once, about the whole line", asked, [GERMAN])

asked.clear()
MixedBraille(
    table_for=LANG_TABLES.get,
    script_map=lambda: SCRIPT_MAP,
    get_script=_get_script,
    line_language=lambda text: asked.append(text) or "de",
).tables_for("hello привет", EN)
check("it is not asked at all about a line script could place", asked, [])

# --- Formatting marks --------------------------------------------------------
# Orca shows formatting two ways, and both have to survive being split across
# tables. Emphasis classes the table knows (bold, italic, underline) become a
# liblouis typeform; everything else the user asked for (size, paragraph
# style, selection) becomes dots 7 and 8 in the attribute mask.

BOLD, ITALIC, UNDERLINE = 4, 1, 2

# **The assumption that makes this work at all.** Orca computes the typeform
# once, with the region's own table, and hands the same numbers to every run.
# That is only safe because the bit for an emphasis class is a liblouis
# constant rather than something a table chooses: the table either has the
# class, and gets the standard bit, or lacks it and gets 0. Asserted across a
# spread of tables so that if liblouis ever stops being true, this fails
# instead of the braille going quietly wrong.
SPREAD = [
    EN, RU, DE,
    f"{TABLES}/en-gb-g1.utb", f"{TABLES}/en-us-g2.ctb",
    f"{TABLES}/fr-bfu-g2.ctb", f"{TABLES}/nl-NL-g0.utb",
    f"{TABLES}/ru-comp8.utb", f"{TABLES}/IPA.utb",
    f"{TABLES}/unicode-braille.utb", f"{TABLES}/en-ueb-g1.ctb",
]
odd = []
for table in SPREAD:
    if not os.path.exists(table):
        continue
    for emphasis_class, standard in (("bold", BOLD), ("italic", ITALIC),
                                     ("underline", UNDERLINE)):
        try:
            value = louis.getTypeformForEmphClass([table], emphasis_class)
        except Exception:  # pylint: disable=broad-exception-caught
            continue
        if value not in (0, standard):
            odd.append((os.path.basename(table), emphasis_class, value))
check("an emphasis class gets the standard bit or none, in every table", odd, [])

# Each run marks emphasis in its own script's convention, which is the part
# that could not happen at all with one table for the line.
typeform = [0] * len(MIXED)
for index in range(12, 19):          # the Russian run
    typeform[index] = BOLD
russian_bold = joined(MIXED, split)[0], translate_segments(
    louis.translate, split, MIXED, typeform, 0, 0,
    getattr(louis, "compbrlAtCursor", 0))[0]
check("bold on the Russian run changes the line", russian_bold[0] != russian_bold[1], True)
check("and marks it with the Russian table's own emphasis sign",
      louis.translate([UNICODE_DIS, RU], MIXED[12:19],
                      typeform=[BOLD] * 7)[0] in russian_bold[1], True)

typeform = [0] * len(MIXED)
for index in range(0, 11):           # the English run
    typeform[index] = BOLD
english_bold = translate_segments(
    louis.translate, split, MIXED, typeform, 0, 0,
    getattr(louis, "compbrlAtCursor", 0))[0]
check("bold on the English run marks it in UEB instead",
      english_bold != russian_bold[1], True)
check("an unemphasised line is unchanged by an all-zero typeform",
      translate_segments(louis.translate, split, MIXED, [0] * len(MIXED), 0, 0,
                         getattr(louis, "compbrlAtCursor", 0))[0],
      joined(MIXED, split)[0])

# A run whose table has no emphasis class must ignore the typeform rather than
# fail or produce something else: the line still has to render.
ipa_split = [(0, 12, EN), (12, 19, f"{TABLES}/IPA.utb"), (19, 23, EN)]
if os.path.exists(f"{TABLES}/IPA.utb"):
    # Bold on the IPA run only, so the English runs are not what is being
    # compared: they would quite rightly change.
    bold_ipa = [0] * len(MIXED)
    for index in range(12, 19):
        bold_ipa[index] = BOLD
    check("a table without emphasis classes ignores the typeform",
          translate_segments(louis.translate, ipa_split, MIXED, bold_ipa, 0, 0,
                             getattr(louis, "compbrlAtCursor", 0))[0],
          translate_segments(louis.translate, ipa_split, MIXED, None, 0, 0,
                             getattr(louis, "compbrlAtCursor", 0))[0])

# --- Joining an emphasis passage across a change of table ---------------------
# A bold passage running from English into Russian should open once, in the
# table it starts in, and close once, in the table it ends in. Translated run
# by run, liblouis closes it at the end of one and opens it again at the start
# of the next, because each call is a line to itself.

from polyglot.mixed_braille import (  # noqa: E402
    EMPHASIS_BITS,
    continuing_emphasis,
    join_across_boundaries,
    remove_cells,
    wrapping_indicators,
)


def bolded(text, first, last):
    typeform = [0] * len(text)
    for index in range(first, last):
        typeform[index] = BOLD
    return typeform


def run_with(text, split, typeform, join=True):
    return translate_segments(
        louis.translate, split, text, list(typeform), 0, 0,
        getattr(louis, "compbrlAtCursor", 0), join_emphasis=join,
    )


# The indicators are found by asking the table, not by knowing anything.
check("UEB wraps a bold passage", wrapping_indicators(louis.translate, EN, BOLD),
      ("\u2818\u2836", "\u2818\u2804"))
check("the Russian table wraps with the same mark either side",
      wrapping_indicators(louis.translate, RU, BOLD)[0],
      wrapping_indicators(louis.translate, RU, BOLD)[1])
check("a table with no such class has no pair",
      wrapping_indicators(louis.translate, f"{TABLES}/unicode-braille.utb", BOLD),
      None)
check("the answer is remembered rather than probed again",
      wrapping_indicators(louis.translate, EN, BOLD)
      is wrapping_indicators(louis.translate, EN, BOLD), True)

check("an emphasis set either side of a boundary is continuing",
      continuing_emphasis([BOLD, BOLD, BOLD], 1), (BOLD,))
check("an emphasis ending at the boundary is not",
      continuing_emphasis([BOLD, 0, 0], 1), ())
check("an emphasis starting at the boundary is not",
      continuing_emphasis([0, BOLD, BOLD], 1), ())
check("two emphases can continue at once",
      sorted(continuing_emphasis([BOLD | ITALIC] * 3, 1)), sorted((ITALIC, BOLD)))
check("no typeform means nothing continues", continuing_emphasis(None, 1), ())
check("a boundary at the start continues nothing",
      continuing_emphasis([BOLD, BOLD], 0), ())

# Three bold words in UEB is a passage, and the join then applies.
PASSAGE = "the word is really привет here"
PSPLIT = [(0, 19, EN), (19, 26, RU), (26, 30, EN)]
typeform = bolded(PASSAGE, 0, 25)
separate = run_with(PASSAGE, PSPLIT, typeform, join=False)[0]
joined_out, joined_in, joined_rev, _cursor = run_with(PASSAGE, PSPLIT, typeform)

opener_en, terminator_en = wrapping_indicators(louis.translate, EN, BOLD)
opener_ru, terminator_ru = wrapping_indicators(louis.translate, RU, BOLD)

# Left alone, the English run closes the passage and the Russian run opens
# one of its own. In the Russian table the opening and closing mark are the
# same character, so it appears twice there before joining and once after.
check("left alone, the English run closes the passage",
      terminator_en in separate, True)
check("left alone, the Russian run opens and closes its own",
      separate.count(opener_ru), 2)
check("joined, it opens in the English table", joined_out.startswith(opener_en), True)
check("joined, the English terminator is gone",
      terminator_en in joined_out, False)
check("joined, the Russian opener is gone too",
      joined_out.count(opener_ru), 1)
check("joined, it closes in the Russian table",
      joined_out.index(terminator_ru) > joined_out.index(opener_en), True)
check("joining makes the line shorter, not longer",
      len(joined_out) < len(separate), True)

# The maps must survive cells being taken out: this is where a wrong index
# would show up as routing landing on the wrong character.
check("one map entry per cell after joining", len(joined_in), len(joined_out))
check("one map entry per character after joining", len(joined_rev), len(PASSAGE))
check("every in_position is inside the text after joining",
      [p for p in joined_in if not 0 <= p < len(PASSAGE)], [])
check("out_position never steps backwards after joining",
      all(b >= a for a, b in zip(joined_rev, joined_rev[1:])), True)
check("out_position stays within the cells after joining",
      [p for p in joined_rev if not 0 <= p <= len(joined_out)], [])
wrong = []
for cell in range(len(joined_out)):
    offset = joined_in[cell]
    for start, end, _table in PSPLIT:
        if start <= offset < end:
            break
    else:
        wrong.append((cell, offset))
check("every cell still maps into one of the runs after joining", wrong, [])

# Two bold words in UEB is the word regime: there is no passage to carry, and
# striking the Russian opener would leave a terminator closing nothing.
WORDS = "the word is привет here"
WSPLIT = [(0, 12, EN), (12, 19, RU), (19, 23, EN)]
word_typeform = bolded(WORDS, 4, 18)
check("the word regime is left exactly as it was",
      run_with(WORDS, WSPLIT, word_typeform)[0],
      run_with(WORDS, WSPLIT, word_typeform, join=False)[0])

# Emphasis that stops at the boundary is not continuing, so nothing is joined.
stops = bolded(PASSAGE, 0, 19)
check("an emphasis that ends at the boundary is untouched",
      run_with(PASSAGE, PSPLIT, stops)[0],
      run_with(PASSAGE, PSPLIT, stops, join=False)[0])

# An unemphasised line must be identical either way.
check("a line with no emphasis is identical with the join on or off",
      run_with(PASSAGE, PSPLIT, [0] * len(PASSAGE))[0],
      run_with(PASSAGE, PSPLIT, [0] * len(PASSAGE), join=False)[0])

# Italic and underline go the same way as bold.
for label, bit in (("italic", ITALIC), ("underline", UNDERLINE)):
    tf = [0] * len(PASSAGE)
    for index in range(0, 25):
        tf[index] = bit
    with_join = run_with(PASSAGE, PSPLIT, tf)[0]
    without = run_with(PASSAGE, PSPLIT, tf, join=False)[0]
    pair_en = wrapping_indicators(louis.translate, EN, bit)
    if pair_en and pair_en[1]:
        check(f"a {label} passage is joined too", len(with_join) < len(without), True)

# remove_cells on its own.
check("removing cells shortens the output",
      remove_cells("abcdef", [0, 1, 2, 3, 4, 5], [0, 1, 2, 3, 4, 5], 2, 2)[0], "abef")
check("removing cells drops their map entries",
      remove_cells("abcdef", [0, 1, 2, 3, 4, 5], [0, 1, 2, 3, 4, 5], 2, 2)[1],
      [0, 1, 4, 5])
check("removing cells moves later text offsets back",
      remove_cells("abcdef", [0, 1, 2, 3, 4, 5], [0, 1, 2, 3, 4, 5], 2, 2)[2],
      [0, 1, 2, 2, 2, 3])
check("removing nothing changes nothing",
      remove_cells("abc", [0, 1, 2], [0, 1, 2], 1, 0), ("abc", [0, 1, 2], [0, 1, 2]))
check("a removal past the end is refused",
      remove_cells("abc", [0, 1, 2], [0, 1, 2], 2, 5), ("abc", [0, 1, 2], [0, 1, 2]))


# --- Dots 7 and 8, spread through out_position --------------------------------
# For attributes with no emphasis class, Orca builds a mask per character and
# spreads it across the cells that character produced, using out_position. The
# loop below is Orca's own (braille.py, get_attribute_mask); running it against
# the joined maps is what proves the mask still lands on the right cells when
# the line changed table part-way along.

_output, _in_pos, out_pos, _c = joined(MIXED, split)


def spread(region_mask, out_position, cell_count):
    """Orca's own spreading loop, so the maps are tested against the real one."""

    mask = [0] * cell_count
    out_len = len(out_position)
    for index, value in enumerate(region_mask):
        if not value or index >= out_len:
            continue
        start = max(out_position[index], 0)
        end = out_position[index + 1] if index + 1 < out_len else cell_count
        for cell in range(start, min(end, cell_count)):
            mask[cell] |= value
    return mask


DOTS78 = 0xC0
per_char = [0] * len(MIXED)
for index in range(12, 18):          # привет, without its trailing space
    per_char[index] = DOTS78
mask = spread(per_char, out_pos, len(_output))

check("the mask is one entry per cell", len(mask), len(_output))
marked = [cell for cell, value in enumerate(mask) if value]
check("marking the Russian word marks some cells", bool(marked), True)
# Every marked cell must map back into the Russian run, and no cell outside it
# may be marked -- a mask landing one cell out is how underlining drifts.
check("every marked cell belongs to the Russian run",
      [cell for cell in marked if not 12 <= _in_pos[cell] < 19], [])
check("no cell of the English runs is marked",
      [cell for cell, value in enumerate(mask)
       if value and not 12 <= _in_pos[cell] < 19], [])
check("the marked cells are contiguous",
      marked == list(range(marked[0], marked[-1] + 1)), True)

# Mark a whole word in each run, which is what a real attribute run covers,
# and check the marks land in both.
per_char = [0] * len(MIXED)
for index in list(range(0, 3)) + list(range(12, 18)) + list(range(19, 23)):
    per_char[index] = DOTS78
mask = spread(per_char, out_pos, len(_output))
runs_marked = {("ru" if 12 <= _in_pos[cell] < 19 else "en")
               for cell, value in enumerate(mask) if value}
check("marks in both runs are kept, either side of the boundary",
      sorted(runs_marked), ["en", "ru"])

# **A quirk of Orca's own, recorded so it is not rediscovered as a bug here.**
# The mask for character i is spread from out_position[i] to out_position[i+1],
# which handles one character becoming several cells. It does not handle
# several characters becoming one cell: in a contraction every character but
# the last has an empty span, and the last one owns the lot. "the" is one cell,
# so marking only its 't' marks nothing at all. This is true with or without
# mixed tables -- it is how Orca spreads the mask -- and it does not matter in
# practice because a real attribute run covers whole words.
single = [0] * len(MIXED)
single[0] = DOTS78              # the 't' of a three-character contraction
check("marking one character of a contraction marks no cells",
      any(spread(single, out_pos, len(_output))), False)
last = [0] * len(MIXED)
last[2] = DOTS78                # the 'e', which owns the contraction's cell
check("marking the last character of a contraction marks its cell",
      spread(last, out_pos, len(_output))[0], DOTS78)
# The Russian run is uncontracted, so there each character owns its own cell.
one_russian = [0] * len(MIXED)
one_russian[13] = DOTS78
check("in an uncontracted run one character marks exactly one cell",
      sum(1 for value in spread(one_russian, out_pos, len(_output)) if value), 1)

# The spreading loop reads out_position[i + 1] as the end of character i's
# cells, so a run boundary must not make it go backwards.
check("out_position never steps backwards across a run boundary",
      all(b >= a for a, b in zip(out_pos, out_pos[1:])), True)
check("the last character's cells reach the end of the line",
      out_pos[-1] <= len(_output), True)


# --- Saying so when it can do nothing ----------------------------------------
# Orca only translates a region when contracted braille is on, so with it off
# this is inert. The symptom is nothing happening, which is the hardest kind
# to diagnose, so install says so.

from orca import braille as _orca_braille  # noqa: E402

_was = _orca_braille._STATE.enable_contracted_braille
_said = []
try:
    _orca_braille._STATE.enable_contracted_braille = False
    _quiet = MixedBraille(LANG_TABLES.get, lambda: SCRIPT_MAP, _get_script,
                          log=_said.append)
    check("it installs even with contracted braille off", _quiet.install(), True)
    check("and says that nothing will be translated",
          any("contracted braille is off" in message for message in _said), True)
    _quiet.uninstall()

    _said.clear()
    _orca_braille._STATE.enable_contracted_braille = True
    _loud = MixedBraille(LANG_TABLES.get, lambda: SCRIPT_MAP, _get_script,
                         log=_said.append)
    _loud.install()
    check("with it on, it just says it is on", _said[0], "mixed braille: on")
    _loud.uninstall()
    check("uninstall puts Orca's liblouis back",
          type(_orca_braille.LOUIS).__name__, "module")
finally:
    _orca_braille._STATE.enable_contracted_braille = _was

width = max(len(row[0]) for row in rows)
print()
for name, want, got, status in rows:
    print(f"  {status:4s} {name:<{width}}  want={want}  got={got}")
print(f"\n{len(rows) - fails}/{len(rows)} rows green")
sys.exit(1 if fails else 0)
