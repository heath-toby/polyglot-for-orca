"""User-editable speech dictionary: how words and patterns are pronounced.

Orca has a pronunciation dictionary of its own, but it is a flat word list:
``re.split(r"(\\W+)", text)`` followed by an exact, case-insensitive lookup
of each word. That means it can replace "ACME" with "acky", and nothing
else. It cannot match a phrase, cannot tell "US" from "us" (keys are
lowercased on save, and Orca's own source carries a TODO about it), and has
no patterns at all -- so "#5" cannot become "number 5", because the number
is not known in advance.

This module adds what is missing:

``text``
    A literal replacement, optionally case-sensitive and optionally
    restricted to whole words. The common case, and the one Orca already
    half-covers.
``regex``
    A Python regular expression with backreferences in the replacement, so
    ``#(\\d+)`` -> ``number \\1`` turns "#5" into "number 5" while
    ``#([A-Za-z]\\w*)`` -> ``hash tag \\1`` turns "#LINUX" into
    "hash tag LINUX".
Each entry can be limited to one language, which is the thing Polyglot can
do and Orca cannot: a rule for German text need not fire in English.

Rules live outside the extension package, in
``$XDG_DATA_HOME/orca/polyglot/speech_dictionary.json``, because Orca
approves an extension by hashing every file in its directory and a rule
saved after install would un-approve the add-on.
"""

import json
import logging
import os
import re
import subprocess
import sys
import time

log = logging.getLogger("polyglot")

RULE_TEXT = "text"
RULE_REGEX = "regex"
RULE_TYPES = (RULE_TEXT, RULE_REGEX)

DATA_DIR = os.path.join(
    os.environ.get("XDG_DATA_HOME", os.path.expanduser("~/.local/share")),
    "orca", "polyglot",
)
DICTIONARY_FILE = os.path.join(DATA_DIR, "speech_dictionary.json")

FILE_VERSION = 1

# A rule that takes longer than this is dropped for the rest of the session
# with a warning. Speech has to keep up with a keypress; a rule that cannot
# is not usable anyway. This catches slow-but-finite rules. The genuinely
# dangerous case -- a pattern that effectively never finishes -- cannot be
# caught here, because the measurement only happens once the substitution
# has returned. That one is stopped at the door instead; see _stress_test.
_SLOW_RULE_SECONDS = 0.05

# A quantifier applied to a group that itself contains one: (a+)+, (x*)*,
# ([a-z]+)* and so on. Against input that nearly matches, these backtrack
# exponentially -- "(a+)+b" against forty a's does not finish in any useful
# time, and Python's re has no timeout to interrupt it with. Matched before
# anything is run, so the message can say what is wrong.
_NESTED_QUANTIFIER = re.compile(r"\([^()]*[*+][^()]*\)\s*[*+{]")

# Inputs a pattern is tried against before it may be saved. Each is the
# shape that turns a careless pattern into a hang: a long run of one
# character, then one that nearly matches but fails at the very end.
_STRESS_INPUTS = ("a" * 64, "a" * 64 + "!", "ab" * 32, "ab" * 32 + "!",
                  "0" * 64, " " * 64, "x" * 64 + "y")

# How long the stress test is given. It runs in a separate process, so a
# pattern that never finishes is killed rather than taking Orca with it.
_STRESS_TIMEOUT_SECONDS = 2.0

# Regex rules are skipped on text longer than this. Nothing Orca speaks in
# one utterance is this long, so the only thing it rules out is a
# pathological case.
_MAX_REGEX_TEXT = 10000

_entries: list = []
_file_mtime: float | None = None
# (type, pattern, case_sensitive, whole_word) -> compiled pattern or None
_compiled: dict = {}
# Patterns disabled for this session after misbehaving, so the warning is
# logged once rather than on every utterance.
_disabled_patterns: set = set()
# Set while preview() has substituted a set of unsaved rules. load() must
# not run then: it would see the file on disk unchanged, decide the rules in
# memory are stale and read the saved ones back over the ones being
# previewed. The editor's Test field then showed "No change" for every rule
# as soon as a dictionary had been saved once.
_frozen = False


def _default_entry() -> dict:
    return {
        "type": RULE_TEXT,
        "pattern": "",
        "replacement": "",
        "language": "",      # "" means every language
        "case_sensitive": False,
        "whole_word": True,
        "enabled": True,
        "comment": "",
    }


def _coerce_entry(raw) -> dict | None:
    """Return a well-formed entry from whatever was in the file, or None."""
    if not isinstance(raw, dict):
        return None
    pattern = raw.get("pattern", "")
    if not isinstance(pattern, str) or not pattern:
        return None
    rule_type = raw.get("type", RULE_TEXT)
    if rule_type not in RULE_TYPES:
        # Dropped rather than treated as a text rule. A rule of a kind this
        # version cannot apply must do nothing at all -- applying its
        # replacement literally would be worse than ignoring it. This is
        # what becomes of the phoneme rules 2.7.0 stored but never applied.
        log.info(f"Polyglot: ignoring speech rule {pattern!r} of unknown kind "
                 f"{rule_type!r}")
        return None
    entry = _default_entry()
    entry["pattern"] = pattern
    entry["type"] = rule_type
    for key in ("replacement", "language", "comment"):
        value = raw.get(key, "")
        entry[key] = value if isinstance(value, str) else ""
    for key in ("case_sensitive", "whole_word", "enabled"):
        if key in raw:
            entry[key] = bool(raw[key])
    return entry


def load(force: bool = False) -> list:
    """Read the rules, re-reading only when the file has changed."""
    global _entries, _file_mtime

    if _frozen:
        return _entries

    try:
        mtime = os.path.getmtime(DICTIONARY_FILE)
    except OSError:
        if _file_mtime is not None:
            # The file has been removed; forget what it used to say.
            _entries = []
            _file_mtime = None
            _compiled.clear()
        return _entries

    if mtime == _file_mtime and not force:
        return _entries

    try:
        with open(DICTIONARY_FILE, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError) as error:
        log.warning(f"Polyglot: could not read the speech dictionary: {error}")
        return _entries

    raw_entries = data.get("entries") if isinstance(data, dict) else data
    entries = []
    for raw in raw_entries or []:
        entry = _coerce_entry(raw)
        if entry is not None:
            entries.append(entry)

    _entries = entries
    _file_mtime = mtime
    _compiled.clear()
    _disabled_patterns.clear()
    log.info(f"Polyglot: loaded {len(_entries)} speech dictionary rules")
    return _entries


def save(entries: list) -> bool:
    """Write the rules, replacing whatever was there. Returns True on success."""
    global _entries, _file_mtime

    cleaned = []
    for raw in entries or []:
        entry = _coerce_entry(raw)
        if entry is not None:
            cleaned.append(entry)

    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        # Written to a sibling and moved into place, so an interrupted save
        # cannot leave a half-written file that then fails to parse.
        temp_path = DICTIONARY_FILE + ".new"
        with open(temp_path, "w", encoding="utf-8") as handle:
            json.dump({"version": FILE_VERSION, "entries": cleaned},
                      handle, indent=2, ensure_ascii=False)
        os.replace(temp_path, DICTIONARY_FILE)
    except OSError as error:
        log.error(f"Polyglot: could not save the speech dictionary: {error}")
        return False

    _entries = cleaned
    try:
        _file_mtime = os.path.getmtime(DICTIONARY_FILE)
    except OSError:
        _file_mtime = None
    _compiled.clear()
    _disabled_patterns.clear()
    log.info(f"Polyglot: saved {len(cleaned)} speech dictionary rules")
    return True


def get_entries() -> list:
    """Return a copy of the rules, in the order they are applied."""
    load()
    return [dict(entry) for entry in _entries]


def validate(entry: dict, deep: bool = True) -> tuple[bool, str]:
    """Check a rule before it is saved. Returns (ok, message for the user).

    ``deep`` runs the subprocess stress test as well. That costs a process
    launch, so the editor validates cheaply on every keystroke and only
    runs the deep check once typing has settled.
    """
    pattern = entry.get("pattern", "")
    if not pattern:
        return False, "Enter the text or pattern to look for."

    rule_type = entry.get("type", RULE_TEXT)
    if rule_type not in RULE_TYPES:
        return False, f"Unknown rule type: {rule_type}"

    if rule_type == RULE_REGEX:
        try:
            compiled = re.compile(pattern)
        except re.error as error:
            return False, f"Not a valid regular expression: {error}"
        # A replacement referring to a group that does not exist fails only
        # when it runs, which would be mid-speech. Find out now.
        try:
            compiled.sub(entry.get("replacement", ""), "")
        except re.error as error:
            return False, f"The replacement does not fit the pattern: {error}"
        if compiled.match(""):
            return False, ("This pattern matches empty text, which would "
                           "insert the replacement between every character.")
        if _NESTED_QUANTIFIER.search(pattern):
            return False, (
                "This pattern repeats a bracketed part that already repeats, "
                "such as (a+)+. On text that nearly matches, that can take "
                "effectively forever and would freeze speech. Repeat the "
                "inner part only, as in a+."
            )
        if deep:
            safe, message = _stress_test(pattern, entry.get("replacement", ""))
            if not safe:
                return False, message

    return True, ""


def _stress_test(pattern: str, replacement: str) -> tuple[bool, str]:
    """Run a pattern against inputs built to provoke runaway backtracking.

    In a subprocess, because the failure being tested for is one that cannot
    be interrupted: Python's re has no timeout, and a pattern like "(a+)+b"
    against a run of a's will not return. On the speech path that would
    freeze Orca outright -- no speech, no keyboard, nothing to do but kill
    it -- which for a screen reader is the worst outcome there is. So the
    pattern is proven safe before it can ever be saved.
    """
    program = (
        "import re,sys,json\n"
        "pattern,replacement,inputs = json.load(sys.stdin)\n"
        "compiled = re.compile(pattern)\n"
        "for text in inputs:\n"
        "    compiled.sub(replacement, text)\n"
    )
    payload = json.dumps([pattern, replacement, list(_STRESS_INPUTS)])
    try:
        completed = subprocess.run(
            [sys.executable, "-c", program],
            input=payload, capture_output=True, text=True,
            timeout=_STRESS_TIMEOUT_SECONDS, check=False,
        )
    except subprocess.TimeoutExpired:
        return False, (
            "This pattern takes too long on some input to be safe to use. "
            "It would freeze speech. Nested repetition such as (a+)+ is the "
            "usual cause: repeat the inner part only, as in a+."
        )
    except Exception as error:  # pylint: disable=broad-exception-caught
        # Could not run the check; let the pattern through rather than
        # refusing a rule for a reason that has nothing to do with it.
        log.debug(f"Polyglot: could not stress-test {pattern!r}: {error}")
        return True, ""
    if completed.returncode != 0:
        detail = (completed.stderr or "").strip().splitlines()
        return False, detail[-1] if detail else "The pattern could not be used."
    return True, ""


def _pattern_for(entry: dict):
    """Compiled pattern for an entry, or None if it cannot be used.

    Text rules are compiled too, rather than handled with str.replace, so
    that both kinds take the same path and whole-word matching is honest
    about word boundaries.
    """
    rule_type = entry.get("type", RULE_TEXT)
    pattern = entry.get("pattern", "")
    case_sensitive = bool(entry.get("case_sensitive"))
    whole_word = bool(entry.get("whole_word"))
    key = (rule_type, pattern, case_sensitive, whole_word)
    if key in _compiled:
        return _compiled[key]

    flags = 0 if case_sensitive else re.IGNORECASE
    try:
        if rule_type == RULE_TEXT:
            source = re.escape(pattern)
            if whole_word:
                # \b is wrong against a pattern that starts or ends with a
                # non-word character -- "#5" would never match, because
                # there is no boundary between a space and a "#". Use a
                # boundary only on the sides where it can mean something.
                if pattern[:1].isalnum() or pattern[:1] == "_":
                    source = r"\b" + source
                if pattern[-1:].isalnum() or pattern[-1:] == "_":
                    source = source + r"\b"
            compiled = re.compile(source, flags)
        elif rule_type == RULE_REGEX:
            if _NESTED_QUANTIFIER.search(pattern):
                # The editor refuses these, but the file can be written by
                # hand, and this is the one class of rule that would not
                # merely misbehave -- it would hang Orca with no way back.
                log.warning(
                    f"Polyglot: refusing speech rule {pattern!r}: it repeats a "
                    "bracketed part that already repeats, which can freeze speech."
                )
                compiled = None
            else:
                compiled = re.compile(pattern, flags)
        else:
            compiled = None
    except re.error as error:
        log.warning(f"Polyglot: ignoring speech rule {pattern!r}: {error}")
        compiled = None

    _compiled[key] = compiled
    return compiled


def _literal(replacement: str):
    """Wrap a replacement so re.sub treats it as plain text."""
    return lambda _match: replacement


def _applies_to(entry: dict, language) -> bool:
    """Whether a rule is in force for the language being spoken."""
    if not entry.get("enabled", True):
        return False
    wanted = entry.get("language", "")
    return not wanted or wanted == language


def apply(text: str, language=None, trace: list | None = None) -> str:
    """Apply the rules to text, in order. Returns the rewritten text.

    ``language`` is the language the text is about to be spoken in; rules
    bound to a different one are skipped. ``trace``, if given, collects
    (pattern, before, after) for each rule that changed anything, which is
    what the editor's preview reports.
    """
    if not text or not isinstance(text, str):
        return text

    load()
    if not _entries:
        return text

    result = text
    for entry in _entries:
        if not _applies_to(entry, language):
            continue
        pattern = entry.get("pattern", "")
        if pattern in _disabled_patterns:
            continue
        compiled = _pattern_for(entry)
        if compiled is None:
            continue
        if entry.get("type") == RULE_REGEX and len(result) > _MAX_REGEX_TEXT:
            continue

        replacement = entry.get("replacement", "")
        if entry.get("type") == RULE_TEXT:
            # Literal both ways. A text rule's replacement is text, so a
            # backslash in it is a backslash -- not a group reference, which
            # for a pattern with no groups raises at substitution time and
            # cost the rule its whole session with only a line in the log to
            # show for it.
            replacement = _literal(replacement)

        started = time.perf_counter()
        try:
            rewritten = compiled.sub(replacement, result)
        except (re.error, IndexError) as error:
            # IndexError: a backreference to a group the pattern does not
            # have. Both are the user's rule, not a bug here, so disable
            # the rule rather than lose the utterance.
            log.warning(f"Polyglot: disabling speech rule {pattern!r}: {error}")
            _disabled_patterns.add(pattern)
            continue
        elapsed = time.perf_counter() - started

        if elapsed > _SLOW_RULE_SECONDS:
            log.warning(
                f"Polyglot: speech rule {pattern!r} took {elapsed * 1000:.0f} ms "
                "and has been disabled for this session. Simplify it, or avoid "
                "nested repetition such as (a+)+."
            )
            _disabled_patterns.add(pattern)
            continue

        if rewritten != result:
            if trace is not None:
                trace.append((pattern, result, rewritten))
            result = rewritten

    return result


def preview(text: str, entries: list, language=None) -> tuple[str, list]:
    """Apply ``entries`` to ``text`` without saving them.

    Returns (result, [(pattern, before, after)]). This is what makes a
    regular expression usable without being able to see it fail: the editor
    shows what a rule does to a sample before it is kept.
    """
    global _entries, _file_mtime, _frozen
    saved_entries, saved_mtime = _entries, _file_mtime
    saved_compiled = dict(_compiled)
    saved_disabled = set(_disabled_patterns)
    try:
        _entries = [e for e in (_coerce_entry(r) for r in entries or []) if e]
        _frozen = True
        trace: list = []
        result = apply(text, language, trace)
        return result, trace
    finally:
        _frozen = False
        _entries = saved_entries
        _compiled.clear()
        _compiled.update(saved_compiled)
        _disabled_patterns.clear()
        _disabled_patterns.update(saved_disabled)
        _file_mtime = saved_mtime

