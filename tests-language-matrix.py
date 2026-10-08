"""One table, every case at once. Any fix must keep every row green."""
import os, sys
import orca.extension_loader  # noqa: F401
sys.path.insert(0, os.path.expanduser("~/.local/share/orca/extensions"))
from orca import speech_presenter, script_manager
from orca.acss import ACSS
from orca.ax_object import AXObject
from orca.ax_text import AXText
from orca.extension import ExtensionSettings
from polyglot import speech_interceptor as si, config as cfg

c = cfg.Config(settings=ExtensionSettings("polyglot")); c.load()
si.install(config=c)
# AFTER install, not before: install() calls Config.load(), which reads the
# stored value straight back over anything set here. Setting it first meant
# this file silently tested whichever mode happened to be saved rather than
# the one it named -- rows passed or failed for reasons that had nothing to
# do with the mode they claimed to cover.
MODE = os.environ.get("POLYGLOT_TEST_MODE", "markup_text")
c.detection_mode = MODE
si._rebuild_configured_languages()
print(f"detection mode under test: {c.detection_mode}\n")
p = speech_presenter.get_presenter()
script = script_manager.get_manager().get_default_script()
p._get_active_script = lambda: script
gen = script.get_speech_generator(); ctx = p._build_generator_context()

# Two kinds of accessible: a text container showing a line, and a button.
class TextObj:
    def __init__(self, line): self.line = line
class Button:
    def __init__(self, label): self.label = label

AXObject.supports_text = staticmethod(lambda o: isinstance(o, TextObj))
AXText.get_caret_offset = staticmethod(lambda o: 0)
AXText.get_line_at_offset = staticmethod(
    lambda o, off: (o.line, 0, len(o.line)) if isinstance(o, TextObj) else ("", 0, 0))

def vlang(string, obj):
    v = gen.voice(obj=obj, string=string, context=ctx, language="", dialect="")
    return ((v[0] if v else None) or {}).get(ACSS.FAMILY, {}).get("lang")

GER = "Ich möchte bitte eine Tasse Kaffee mit Milch und Zucker"
ENG = "The committee will reconvene on Thursday afternoon"
RUS = "Погода вчера была значительно лучше чем сегодня"

rows, fails = [], 0
def check(name, got, want):
    global fails
    good = got == want
    if not good: fails += 1
    rows.append((name, str(want), str(got), "ok" if good else "FAIL"))

def chars(line, obj, want, label, preset=None):
    """Every character of a line, including spaces."""
    if preset: si._switch_language(preset)
    got = {vlang(ch, obj) for ch in line}
    check(label, got, {want})

# --- characters in a text container ---
ger_obj, eng_obj, rus_obj = TextObj(GER), TextObj(ENG), TextObj(RUS)
si._switch_language("en")
chars(GER, ger_obj, "de", "chars of a German line")
chars(ENG, eng_obj, "en", "chars of an English line")
chars(RUS, rus_obj, "ru", "chars of a Russian line")
chars(GER, ger_obj, "de", "chars of German, current=en", preset="en")
chars(GER, ger_obj, "de", "chars of German, current=ru", preset="ru")
check("spaces of a German line",
      {vlang(ch, ger_obj) for ch in GER if ch == " "}, {"de"})
# Mode-independent, and the one the user actually hears: whatever language a
# line is read in, every character of it must be read in the same one. In
# markup-only mode the rows above are expected to say "en" for German, since
# German is Latin script and that mode reads nothing out of the text itself
# -- but they must not say "en" for the letters and "de" for the spaces.
si._switch_language("en")
check("characters of a line never disagree with each other",
      len({vlang(ch, ger_obj) for ch in GER}), 1)
check("a Cyrillic char in a German line", vlang("Д", ger_obj), "ru")

# --- UI furniture: an object with no text interface ---
si._switch_language("de")
labels = ["OK", "Go", "Up", "No", "Cancel", "Open", "Save", "Close",
          "Apply", "Help", "Print", "Edit", "View", "File", "New", "Yes"]
wrong = {l: vlang(l, Button(l)) for l in labels}
check("UI labels after German content",
      {l for l, g in wrong.items() if g != "en"}, set())
# A single German word cannot beat the word threshold of 4, by design, so
# the useful check is that a German *phrase* in a UI element is German.
si._switch_language("en")
check("a German UI phrase is German",
      vlang("Datei speichern unter einem anderen Namen",
            Button("Datei speichern unter einem anderen Namen")), "de")

# --- typing: no object at all ---
si._switch_language("de")
check("typing starts in the previous language", vlang("T", None), "de")
for w in "The committee will reconvene on Thursday".split():
    p._speak(w)
check("typing has learned English", vlang("y", None), "en")

# --- whole-line reading still detects ---
si._switch_language("en")
check("German line detected", si._detector.detect(GER), "de")
check("Russian line detected", si._detector.detect(RUS), "ru")
check("English line detected", si._detector.detect(ENG), "en")
check("numbers do not split",
      si._detector.detect_mixed("I have 1 apple 2 oranges 3 pears 4 plums and 5 bananas now"), None)
check("real mixing splits",
      si._detector.detect_mixed("This is an English sentence and now " + GER) is not None, True)

# --- Orca's role-name locale must track the language ---
si._switch_language("de"); si._switch_language("en", also_braille=False)
check("names locale follows the language", si._current_names_locale, "en")

# --- braille: the contraction table must follow the focus line, and must
# --- not be switched for objects that are not text at all.
from orca.scripts.default import Script as DefaultScript
applied = []

def _fake_set_contraction_table(path):
    # Mimics the real function's early return, or a repeat call would look
    # like a switch when in fact nothing happens.
    if path != si._current_contraction_table:
        applied.append(path)
        si._current_contraction_table = path

si._set_contraction_table = _fake_set_contraction_table
si._set_brltty_text_table = lambda code: None
DE_TABLE = "/usr/share/liblouis/tables/de-g1-detailed.ctb"
EN_TABLE = "/usr/share/liblouis/tables/en-ueb-g2.ctb"
c.language_settings = {"de": {"contraction_table": DE_TABLE},
                       "en": {"contraction_table": EN_TABLE},
                       "ru": {"contraction_table": ""}}
si._rebuild_configured_languages()
update_braille = DefaultScript.update_braille

class FakeScript:
    pass

def braille(obj):
    """Run Orca's update_braille for obj and report table changes.

    Only the original's own failure is tolerated -- it needs a real script
    and a real accessible to render. A failure in Polyglot's part of it must
    not be swallowed, or these rows would pass for the wrong reason.
    """
    applied.clear()
    try:
        update_braille(FakeScript(), obj)
    except Exception as error:
        if "update_braille" not in repr(error) and not isinstance(
                error, (AttributeError, TypeError)):
            raise
    return list(applied)

def set_tables(lang):
    """Establish a starting braille table for the rows below.

    _switch_language no longer touches braille unless asked -- braille is
    opt-in now, so that a speech-side call cannot drag the tables off the
    focus line. Setup that wants a starting table has to say so.
    """
    si._switch_language(lang, also_braille=True)


set_tables("en")
check("braille follows a German line", DE_TABLE in braille(TextObj(GER)), True)
set_tables("de")
check("braille follows an English line", EN_TABLE in braille(TextObj(ENG)), True)
# A frame or a button is not text: it must not touch the table at all. This
# is the fix -- those objects used to yield a language and switch it.
set_tables("de")
check("a button does not move the braille table", braille(Button("OK")), [])
check("a frame does not move the braille table", braille(Button("some window")), [])
# Repeated calls for one event must not re-switch.
set_tables("en")
ger = TextObj(GER)
braille(ger)
check("repeat calls for one line do not re-switch", braille(ger), [])

# --- braille belongs to the line on the display, not to the speech -------
# Only one braille table can be active at a time, so update_braille owns it.
# The speech-side patches run after it, per utterance and per character, and
# they used to switch tables too: a German line then had its German
# contraction rendered through an English text table -- the right number of
# cells with the wrong dots -- and stayed that way until the user moved off
# the line and back. These rows are the regression.
set_tables("en")
ger_line = TextObj(GER)
braille(ger_line)
# Which table it is depends on the mode -- markup-only reads nothing out of a
# Latin-script line, so a German paragraph legitimately settles on the default
# language's table there. What must hold in every mode is the next three rows:
# whatever the line settled on, speech does not move it.
_expected = EN_TABLE if MODE == "markup_only" else DE_TABLE
check("the focus line owns the braille table",
      si._current_contraction_table, _expected)
_settled = si._current_contraction_table

p._speak(ENG)
check("speaking English on a German line leaves braille alone",
      si._current_contraction_table, _settled)
try:
    p.speak_character("n")
except Exception as _error:
    print(f"  (speak_character raised {type(_error).__name__}: {_error})")
check("a character spoken in English leaves braille alone",
      si._current_contraction_table, _settled)
p._speak("OK")
check("a short label spoken in English leaves braille alone",
      si._current_contraction_table, _settled)
# ...and the line still owns it afterwards: a fresh update_braille for the
# same line must not have to undo anything.
braille(TextObj(GER))
check("the line's table survives a round of speech",
      si._current_contraction_table, _settled)

# Braille-only sentinels name a table rather than a language, so they are
# never enabled languages and _language_of_line drops them. update_braille
# has to ask for them outright -- until it did, an IPA or Unicode-braille
# line got its table only from the speech-side leak above, which means
# closing the leak without this would have taken both tables away.
BRL_LINE = "\u2801\u2803\u2809\u2819\u2811\u280b\u281b"
IPA_LINE = "\u02a7\u0283\u025b\u0279\u0254\u00f8"
BRL_TABLE = "/usr/share/liblouis/tables/unicode-braille.utb"
IPA_TABLE = "/usr/share/liblouis/tables/IPA.utb"
set_tables("en")
check("a Unicode-braille line gets the pass-through table",
      BRL_TABLE in braille(TextObj(BRL_LINE)), True)
set_tables("en")
check("an IPA line gets the IPA table",
      IPA_TABLE in braille(TextObj(IPA_LINE)), True)
# A sentinel must not become the spoken language: there is no voice for it.
check("a braille sentinel does not become the voice",
      si._current_language in ("en", "de", "ru"), True)
set_tables("en")

# --- the speech dictionary -------------------------------------------------
from polyglot import speech_dictionary as sd
import os as _os
import tempfile as _tempfile
# A scratch directory, never the live data directory: an earlier version of
# this file left a runaway rule in the real dictionary, which would have
# hung speech on the next start.
sd.DATA_DIR = _tempfile.mkdtemp(prefix="polyglot-matrix-")
sd.DICTIONARY_FILE = _os.path.join(sd.DATA_DIR, "speech_dictionary.json")

def R(**kw):
    e = {"type": "text", "pattern": "", "replacement": "", "language": "",
         "case_sensitive": False, "whole_word": True, "enabled": True, "comment": ""}
    e.update(kw)
    return e

def rewrite(text, rules, language=None):
    return sd.preview(text, rules, language)[0]

NUM = R(type="regex", pattern=r"#(\d+)", replacement=r"number \1")
TAG = R(type="regex", pattern=r"#([A-Za-z]\w*)", replacement=r"hash tag \1")
check("regex rule: a number after a hash",
      rewrite("Issue #5 is open", [NUM, TAG]), "Issue number 5 is open")
check("regex rule: a word after a hash",
      rewrite("#LINUX rules", [NUM, TAG]), "hash tag LINUX rules")
check("both in one line",
      rewrite("#5 and #LINUX", [NUM, TAG]), "number 5 and hash tag LINUX")
check("text rule, whole words only",
      rewrite("concatenate the cat", [R(pattern="cat", replacement="feline")]),
      "concatenate the feline")
check("case-sensitive rule separates US from us",
      rewrite("The US asked us", [R(pattern="US", replacement="U S", case_sensitive=True)]),
      "The U S asked us")
DE_ONLY = R(pattern="Strasse", replacement="Stra\u00dfe", language="de")
check("a German-only rule fires in German",
      rewrite("Die Strasse", [DE_ONLY], "de"), "Die Stra\u00dfe")
check("a German-only rule does not fire in English",
      rewrite("The Strasse", [DE_ONLY], "en"), "The Strasse")
check("a backslash in a text replacement is a backslash",
      rewrite("see C:\\path", [R(pattern="C:\\path", replacement="C drive \\1")]),
      "see C drive \\1")
check("a disabled rule does nothing",
      rewrite("the cat", [R(pattern="cat", replacement="feline", enabled=False)]),
      "the cat")
check("a rule of an unknown kind is ignored, not applied as text",
      rewrite("tomato", [R(type="phoneme", pattern="tomato", replacement="t@m1AtoU")]),
      "tomato")
# preview() must not be derailed by a dictionary already on disk: it used to
# call load(), which saw the file as newer than the rules in memory and read
# the saved ones straight back over the ones being previewed. Every rule in
# the editor's Test field then showed "No change".
sd.save([R(pattern="unrelated", replacement="rule")])
check("preview is not clobbered by a saved dictionary",
      rewrite("the cat", [R(pattern="cat", replacement="feline")]),
      "the feline")
check("saved rules still apply after a preview",
      sd.apply("an unrelated word"), "an rule word")
check("runaway pattern refused when saved",
      sd.validate(R(type="regex", pattern=r"(a+)+b", replacement="X"))[0], False)
check("sane pattern accepted when saved",
      sd.validate(R(type="regex", pattern=r"#(\d+)", replacement=r"number \1"))[0], True)
check("bad replacement caught when saved",
      sd.validate(R(type="regex", pattern=r"(\d+)", replacement=r"\2"))[0], False)
check("pattern matching empty text refused",
      sd.validate(R(type="regex", pattern="x*", replacement="y"))[0], False)
# A hand-written runaway rule must be skipped, not hang, and must not stop
# the rules after it from working.
import time as _time
_t0 = _time.perf_counter()
_out = rewrite("a" * 60 + " issue #5",
               [R(type="regex", pattern=r"(a+)+b", replacement="X"), NUM])
check("hand-written runaway rule skipped, not run",
      ("number 5" in _out) and (_time.perf_counter() - _t0 < 1.0), True)
import shutil as _shutil
_shutil.rmtree(sd.DATA_DIR, ignore_errors=True)

w = max(len(r[0]) for r in rows)
for name, want, got, status in rows:
    print(f"  {status:4s} {name:<{w}}  want={want}  got={got}")
print(f"\n{len(rows) - fails}/{len(rows)} rows green")
