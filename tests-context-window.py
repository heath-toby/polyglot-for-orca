#!/usr/bin/env python3
"""Deciding a short line by the sentences around it, and the embedded floor.

Two ideas taken from Dialingo, an NVDA add-on by Rashad Naqeeb
(github.com/rashadnaqeeb/nvda-dialingo, GPL-2.0). The code here is our own
-- Lingua is not fastText and the mechanics differ -- but the reasoning is
theirs and worth the credit.

``sentence_window`` plus ``slice_runs``
    A forty-cell braille line is a handful of words, and ``detect_mixed``
    declines anything under eight. The sentences either side of it are
    evidence, so detect the window and cut the answer back down to the
    line. The invariant that matters: the runs handed back must still
    reconstruct exactly the span asked about, because the braille maps are
    built from their lengths.

``EMBEDDED_FLOOR``
    A foreign fragment surrounded by default-language text is making a
    surprising claim, so it is held to a much higher confidence than an
    ordinary switch. Judged between the candidate and the default alone,
    which is what ``two_way_confidence`` renormalises for.

The detection rows are real Lingua. Nothing here needs braille or BRLTTY.

Usage: python3 tests-context-window.py
"""

from __future__ import annotations

import os
import sys

# The repo first, the installed copy only as a fallback. Both exist on a
# development machine and the installed one is usually the older: testing it
# by accident is how a green run once hid a change that had not been
# installed yet.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.append(os.path.expanduser("~/.local/share/orca/extensions"))

# Lingua lives in Polyglot's own venv, outside the package, and it is
# speech_interceptor._add_venv_to_path that normally puts it on the path at
# runtime. Importing that module here would drag in Orca, so the venv goes
# on the path the same way it does there.
import glob

for _site in glob.glob(os.path.expanduser(
        "~/.local/share/orca/polyglot/.venv/lib/*/site-packages")):
    sys.path.append(_site)

from polyglot.language_detector import (
    CONTEXT_CHARACTERS,
    EMBEDDED_FLOOR,
    LanguageDetector,
    is_lingua_available,
    sentence_window,
    slice_runs,
)

rows, fails = [], 0


def check(name, got, want):
    global fails
    ok = got == want
    if not ok:
        fails += 1
    rows.append((name, repr(want), repr(got), "ok" if ok else "FAIL"))


# --- sentence_window ---------------------------------------------------------

T = "One sentence here. The line is in this one. A third sentence follows."
start, end = T.index("The line"), T.index("The line") + len("The line")

check("a span widens to its own sentence",
      T[slice(*sentence_window(T, start, end))],
      "The line is in this one.")
check("a span already covering whole sentences is left alone",
      sentence_window("Alpha. Beta.", 0, 12), (0, 12))
T2 = "Paragraph one.\nSecond para starts here and runs on"
check("a newline is a left boundary, so the paragraph before is not read",
      sentence_window(T2, T2.index("runs"), len(T2))[0],
      T2.index("Second"))
check("a newline is a right boundary",
      sentence_window("First para here\nsecond para", 0, 5)[1], 15)
long_before = "word " * 100
LONG = long_before + "The target line. " + "after " * 100
ls, le = LONG.index("The target"), LONG.index("The target") + len("The target line.")
low, high = sentence_window(LONG, ls, le)
check("widening is capped at CONTEXT_CHARACTERS each way",
      (ls - low <= CONTEXT_CHARACTERS, high - le <= CONTEXT_CHARACTERS),
      (True, True))
check("a capped left edge lands on a space, not mid-word",
      LONG[low - 1] if low > 0 else " ", " ")
check("the window always contains the span",
      (low <= ls, high >= le), (True, True))

# A span ending in its own full stop needs no widening rightwards: that is
# the braille case, where the line ends the sentence.
w = sentence_window("Alpha beta. Gamma delta.", 0, 11)
check("a span ending at a full stop does not widen right", w[1], 11)
check("a span ending mid-sentence widens right",
      sentence_window("Alpha beta gamma delta. Next.", 0, 10)[1], 23)

# Degenerate inputs must not raise or invent.
check("an empty text gives an empty window", sentence_window("", 0, 0), (0, 0))
check("a one-character text is its own window",
      sentence_window("a", 0, 1), (0, 1))


# --- slice_runs --------------------------------------------------------------

RUNS = [("hello ", "en"), ("привет ", "ru"), ("world", "en")]

check("slicing the whole text gives every run back",
      slice_runs(RUNS, 0, 18), RUNS)
check("slicing one run gives that run",
      slice_runs(RUNS, 6, 13), [("привет ", "ru")])
check("a slice crossing a boundary keeps both parts",
      slice_runs(RUNS, 3, 9), [("lo ", "en"), ("при", "ru")])
check("a slice outside the runs is empty", slice_runs(RUNS, 99, 120), [])
check("an empty slice is empty", slice_runs(RUNS, 5, 5), [])

# The invariant the braille maps depend on.
whole = "".join(text for text, _lang in RUNS)
for a, b in ((0, 18), (1, 17), (6, 13), (0, 7), (11, 18)):
    check(f"runs sliced to [{a},{b}) reconstruct that span exactly",
          "".join(text for text, _lang in slice_runs(RUNS, a, b)),
          whole[a:b])


# --- the embedded floor, against real Lingua ---------------------------------

if not is_lingua_available():
    check("lingua is installed", False, True)
else:
    det = LanguageDetector(
        enabled_languages=["en", "de", "fr", "es", "ru"],
        word_threshold=3,
        script_to_language={"CYRILLIC": "ru"},
        default_language="en",
    )
    # Build the high-accuracy detector the mixed path uses.
    det.detect_mixed("This is a sentence long enough to build the detector now")

    def two_way(text, lang):
        return round(det.two_way_confidence(text, lang), 3)

    # The live bug: a path at the end of an English notification, marked
    # German by Lingua and then shown in a German table on the Mantis.
    check("the /usr/bin/gh path is nowhere near the floor",
          two_way("/usr/bin/gh", "de") < EMBEDDED_FLOOR, True)
    # Dialingo's own example of the asymmetry.
    check("'slash enfr' is nowhere near the floor",
          two_way("slash enfr", "es") < EMBEDDED_FLOOR, True)
    check("a lone short word is below the floor",
          two_way("ein", "de") < EMBEDDED_FLOOR, True)
    check("a real German clause clears the floor",
          two_way("Das ist ein deutscher Satz", "de") >= EMBEDDED_FLOOR, True)
    check("a longer German clause clears it comfortably",
          two_way("Dies ist wirklich ein sehr deutscher Satz", "de") >= 0.99,
          True)

    check("the default language scores zero against itself",
          det.two_way_confidence("anything at all here", "en"), 0.0)
    check("empty text scores zero", det.two_way_confidence("   ", "de"), 0.0)

    # The floor only applies to a fragment the default surrounds.
    surrounded = [("English words here ", "en"), ("/usr/bin/gh", "de"),
                  (" and more English", "en")]
    checked, rejected = det._survives_embedded_floor(surrounded)
    check("a surrounded path is relabelled to the default",
          [lang for _t, lang in checked], ["en", "en", "en"])
    check("and the rejection is reported with its score",
          (rejected[0][0], rejected[0][1], rejected[0][2] < EMBEDDED_FLOOR),
          ("/usr/bin/gh", "de", True))

    at_end = [("English words here ", "en"), ("/usr/bin/gh", "de")]
    check("a path at the end of the line is still caught",
          [lang for _t, lang in det._survives_embedded_floor(at_end)[0]],
          ["en", "en"])

    real = [("This is English. ", "en"), ("Das ist ein deutscher Satz", "de"),
            (" Back to English", "en")]
    check("a real German clause survives being surrounded",
          [lang for _t, lang in det._survives_embedded_floor(real)[0]],
          ["en", "de", "en"])

    no_default = [("привет мир", "ru"), ("more Russian здесь", "ru")]
    check("a line with no default-language neighbour is left alone",
          [lang for _t, lang in det._survives_embedded_floor(no_default)[0]],
          ["ru", "ru"])

    check("a single segment is never embedded",
          det._survives_embedded_floor([("/usr/bin/gh", "de")])[0],
          [("/usr/bin/gh", "de")])

    # The floor must not fire when there is no default language to compare
    # against -- there is then no "surprising" direction.
    plain = LanguageDetector(
        enabled_languages=["en", "de"], word_threshold=3,
        script_to_language={}, default_language=None,
    )
    check("no default language means no embedded floor",
          plain._survives_embedded_floor(
              [("a", "en"), ("/usr/bin/gh", "de"), ("b", "en")])[0],
          [("a", "en"), ("/usr/bin/gh", "de"), ("b", "en")])

    # --- detect_mixed_in_context ---
    # The braille case: a line of a few words, in a paragraph that has
    # plenty. Two regimes, because detect_mixed answers None for a window
    # with only one language in it.

    # 1. A window with only German in it.
    para = ("Ich schreibe diesen Satz auf Deutsch und er ist lang genug "
            "dafuer, damit die Erkennung etwas zu arbeiten hat.")
    line = "er ist lang"
    at = para.index(line)
    check("a three-word German line is undecidable on its own",
          det.detect_mixed(line), None)
    got = det.detect_mixed_in_context(para, at, at + len(line))
    check("but its paragraph decides it",
          [lang for _t, lang in got] if got else None, ["de"])
    check("and the span comes back exactly, not approximated",
          "".join(t for t, _l in got) if got else None, line)

    # 2. A window with a language change inside it.
    mixed = ("This sentence is in plain English throughout. "
             "Dieser Satz ist durchgehend auf Deutsch geschrieben.")
    span = "Dieser Satz ist"
    at2 = mixed.index(span)
    got2 = det.detect_mixed_in_context(mixed, at2, at2 + len(span))
    check("a line inside a mixed window is sliced out of the runs",
          "".join(t for t, _l in got2) if got2 else None, span)

    # The guard that keeps this off the voice: scoring, not detecting.
    before = det.current_language
    det.detect_mixed_in_context(para, at, at + len(line))
    check("deciding a braille line never moves the current language",
          det.current_language, before)

    check("a bad span is refused rather than raising",
          det.detect_mixed_in_context(para, 50, 10), None)
    check("a span past the end is refused",
          det.detect_mixed_in_context(para, 0, len(para) + 5), None)
    check("an empty text is refused", det.detect_mixed_in_context("", 0, 1), None)


# --- placing the line in the object's text -----------------------------------
# The braille line has to be found in the focused object's text before it can
# be given context. Pulled out of the AT-SPI shell so it can be tested without
# a display: with the Mantis asleep, the shell itself cannot be exercised, and
# a placement bug here would make the whole feature a quiet no-op.

from polyglot.speech_interceptor import _nearest_occurrence, _statistical_runs

WHOLE = "alpha beta. gamma delta. alpha beta. epsilon."

check("a line that occurs once is found",
      _nearest_occurrence(WHOLE, "gamma delta", 0), 12)
check("of two identical lines, the one at the caret wins",
      _nearest_occurrence(WHOLE, "alpha beta", 25), 25)
check("and with the caret at the start, the first one wins",
      _nearest_occurrence(WHOLE, "alpha beta", 0), 0)
check("nearest, not exact: a caret a few characters off still places it",
      _nearest_occurrence(WHOLE, "alpha beta", 28), 25)
check("a caret between the two copies picks the nearer",
      _nearest_occurrence(WHOLE, "alpha beta", 20), 25)
check("a line not in the text is not placed",
      _nearest_occurrence(WHOLE, "not here at all", 0), None)
check("an empty line is not placed", _nearest_occurrence(WHOLE, "", 0), None)
check("an empty text places nothing", _nearest_occurrence("", "x", 0), None)
check("a caret past the end still places the line",
      _nearest_occurrence(WHOLE, "epsilon", 9999), 37)


# --- the wiring in _statistical_runs -----------------------------------------
# The branch that calls all of the above. Stubbed at _line_in_context, which
# is the AT-SPI boundary, so this tests our own logic and not Orca's.

import polyglot.speech_interceptor as si


class _Config:
    enable_mixed_language = True
    braille_line_context = True
    word_threshold = 1


def with_stubs(detector, config, placed, text):
    saved = (si._detector, si._config, si._line_in_context)
    si._detector, si._config = detector, config
    si._line_in_context = lambda _line: placed
    try:
        return _statistical_runs(text)
    finally:
        si._detector, si._config, si._line_in_context = saved


if is_lingua_available():
    PARA = ("Ich schreibe diesen Satz auf Deutsch und er ist lang genug "
            "dafuer, damit die Erkennung etwas zu arbeiten hat.")
    LINE = "er ist lang"
    AT = PARA.index(LINE)

    check("a short line with no context available stays undecided",
          with_stubs(det, _Config(), None, LINE), None)
    got = with_stubs(det, _Config(), (PARA, AT), LINE)
    check("the same line with its paragraph is decided",
          [lang for _t, lang in got] if got else None, ["de"])
    check("and still reconstructs the line exactly",
          "".join(t for t, _l in got) if got else None, LINE)

    off = _Config()
    off.braille_line_context = False
    check("braille_line_context off skips the context lookup entirely",
          with_stubs(det, off, (PARA, AT), LINE), None)

    no_mixed = _Config()
    no_mixed.enable_mixed_language = False
    check("mixed language off skips it too",
          with_stubs(det, no_mixed, (PARA, AT), LINE), None)
    check("no detector at all is survived",
          with_stubs(None, _Config(), (PARA, AT), LINE), None)

    # The natural-word guard still applies to a run decided in context: a
    # path must not pick up a language just because its paragraph has one.
    strict = _Config()
    strict.word_threshold = 4
    noise = "/usr/bin/gh"
    noisy_para = PARA.replace(LINE, noise)
    runs_got = with_stubs(det, strict, (noisy_para, noisy_para.index(noise)), noise)
    check("a path decided in context is still held to the word threshold",
          [lang for _t, lang in runs_got] if runs_got else None, [None])


width = max(len(row[0]) for row in rows)
print()
for name, want, got, status in rows:
    print(f"  {status:4s} {name:<{width}}  want={want}  got={got}")
print(f"\n{len(rows) - fails}/{len(rows)} rows green")
sys.exit(1 if fails else 0)
