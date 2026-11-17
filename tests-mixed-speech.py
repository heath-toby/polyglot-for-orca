#!/usr/bin/env python3
"""Each language in its own voice on a line read.

``SpeechPresenter._speak`` takes "a string or a list from the speech
generator", and ``speak_line`` passes the list -- so Polyglot's
mixed-language speech, guarded on ``isinstance(text, str)``, never ran for a
line read. Braille split the line correctly while one voice read all of it.

The fix rebuilds the list. Getting that right means getting ``_speak_list``'s
protocol right, and it is not obvious: an ``ACSS`` element claims the text
around it, and only a ``Pause`` reliably flushes a group. So the rows below
do not check the list's shape -- a plausible-looking list can still put the
German voice on the English half. They run the rebuilt list through **Orca's
own ``_speak_list``**, with the one call that reaches the synthesiser stubbed,
and check which text came out in which voice.

Usage: python3 tests-mixed-speech.py
"""

from __future__ import annotations

import glob
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.append(os.path.expanduser("~/.local/share/orca/extensions"))
for _site in glob.glob(os.path.expanduser(
        "~/.local/share/orca/polyglot/.venv/lib/*/site-packages")):
    sys.path.append(_site)

# speech_presenter must be imported before speech_generator: importing
# speech_generator first walks into orca.generator -> braille ->
# script_manager -> braille_generator and back into a half-built
# orca.generator, and ImportError on GeneratorMode. Not an alphabetical
# import block, deliberately.
import orca.speech_presenter  # noqa: F401  (import order, see above)
from orca.acss import ACSS
from orca.speech_generator import Pause
from orca.speech_presenter import SpeechPresenter
from orca.speechserver import VoiceFamily

from polyglot.speech_interceptor import split_utterance_list

rows, fails = [], 0


def check(name, got, want):
    global fails
    ok = got == want
    if not ok:
        fails += 1
    rows.append((name, repr(want), repr(got), "ok" if ok else "FAIL"))


def acss_for(lang):
    """An ACSS naming a voice, as _get_lang_acss builds one."""
    if lang is None:
        return None
    return ACSS({ACSS.FAMILY: {VoiceFamily.LANG: lang,
                               VoiceFamily.NAME: f"voice-{lang}"}})


def voice_name(acss):
    try:
        family = acss.get(ACSS.FAMILY) if acss is not None else None
        return (family.get(VoiceFamily.NAME) if family is not None else None) or "(none)"
    except Exception:
        return "(unreadable)"


class _Recorder:
    """Enough of a SpeechPresenter for _speak_list to run against."""

    def __init__(self):
        self.spoken = []

    def _speak_single(self, text, acss, obj=None):
        self.spoken.append((text.strip(), voice_name(acss)))

    def _speak_list(self, content, acss, obj):
        return SpeechPresenter._speak_list(self, content, acss, obj)

    def _resolved_voice(self, acss):
        # Stands in for Orca's voice-set resolution: the voice name is what
        # decides whether two groups may be merged into one call.
        return voice_name(acss)


def spoken(content, outer=None):
    """What Orca's own _speak_list would send to the synthesiser."""
    recorder = _Recorder()
    recorder._speak_list(content, outer, None)
    return recorder.spoken


# --- the protocol itself, before any of our code ----------------------------
# These rows document why the rebuild has the shape it does. If Orca changes
# _speak_list, these fail first and say so.

check("a bare list is spoken in the outer voice",
      spoken(["hello world"], acss_for("en")),
      [("hello world", "voice-en")])
check("an ACSS after text claims that text too -- the trap",
      spoken(["hello", acss_for("de"), "welt"]),
      [("hello welt", "voice-de")])
check("an ACSS before text does not save it either",
      spoken([acss_for("en"), "hello", acss_for("de"), "welt"]),
      [("hello welt", "voice-de")])
check("a Pause is what flushes a group",
      spoken([acss_for("en"), "hello", Pause(), acss_for("de"), "welt"]),
      [("hello.", "voice-en"), ("welt", "voice-de")])


# --- the rebuild -------------------------------------------------------------

EN_DE = [("The first part of this is in English, ", "en"),
         ("aber der Zweiten auf Deutsch.", "de")]


def rebuild(content, runs_by_text):
    return split_utterance_list(
        content,
        segments_of=lambda text: runs_by_text.get(text),
        acss_of=acss_for,
        pause=Pause,
        acss_type=ACSS,
    )


LINE = "The first part of this is in English, aber der Zweiten auf Deutsch."

check("a single-language list is left alone, not rebuilt",
      rebuild(["just plain English here"], {"just plain English here": None}),
      None)
check("a list whose runs are all one language is left alone",
      rebuild(["all English"], {"all English": [("all English", "en")]}),
      None)

got = rebuild([LINE], {LINE: EN_DE})
check("a mixed line is rebuilt", got is not None, True)

# The row that matters: the right voice on the right half.
check("the English half is read in the English voice and the German in German",
      spoken(got),
      [("The first part of this is in English,", "voice-en"),
       ("aber der Zweiten auf Deutsch.", "voice-de")])

# Toby's actual report, the other way round, and three runs.
RU = [("hello ", "en"), ("привет ", "ru"), ("world", "en")]
got3 = rebuild(["hello привет world"], {"hello привет world": RU})
check("three runs give three voices in order",
      [voice for _text, voice in spoken(got3)],
      ["voice-en", "voice-ru", "voice-en"])
check("and the words stay with their own language",
      [text for text, _voice in spoken(got3)],
      ["hello", "привет", "world"])
# _speak_list appends a full stop at every pause, but only when the run ends
# in an alphanumeric character. A trailing pause would therefore put a stop
# on the end of the line, so the rebuild pauses between runs only.
check("no full stop is invented at the end of the line",
      spoken(rebuild(["alpha beta"],
                     {"alpha beta": [("alpha ", "en"), ("beta", "de")]}))[-1][0],
      "beta")

# Non-string elements must survive untouched: a list carries ACSS, Pause and
# nested lists from the generator, and dropping one changes what Orca says.
mixed_content = ["Role name", Pause(), acss_for("de"), LINE, ["nested"]]
out = rebuild(mixed_content, {LINE: EN_DE, "Role name": None, "nested": None})
check("a Pause already in the list is kept",
      sum(1 for item in out if isinstance(item, Pause)) >= 2, True)
check("an ACSS already in the list is kept",
      any(isinstance(item, ACSS) and voice_name(item) == "voice-de"
          for item in out), True)
check("a nested list is passed through, not flattened away",
      ["nested"] in out, True)
check("text that did not split is still present once",
      sum(1 for item in out if item == "Role name"), 1)

# Degenerate input must not raise or invent.
check("an empty list rebuilds to nothing", rebuild([], {}), None)
check("whitespace-only strings are left alone",
      rebuild(["   "], {"   ": EN_DE}), None)
check("a run of only whitespace is not given a voice of its own",
      [text for text, _v in spoken(rebuild(
          ["a b"], {"a b": [("a ", "en"), ("   ", "de"), ("b", "en")]}) or [])],
      ["a", "b"])

width = max(len(row[0]) for row in rows)
print()
for name, want, got_, status in rows:
    print(f"  {status:4s} {name:<{width}}  want={want}  got={got_}")
print(f"\n{len(rows) - fails}/{len(rows)} rows green")
sys.exit(1 if fails else 0)
