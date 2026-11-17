"""Each language on a braille line shown in its own table.

Orca contracts every braille region with one call, ``louis.translate``, which
returns the output plus two maps: the text offset of every cell
(``in_position``) and the cell of every text offset (``out_position``).
Routing keys, the cursor, attribute underlining and panning all read those
maps. This module wraps that one call, exactly as the NVDA add-on
BrailleLanguageSwitcher wraps ``louisHelper.translate``: the line is split
into language runs, each run is translated with its own table, and the cells
and both maps are joined again with their offsets corrected.

**Why BRLTTY is not in the way.** It looked as though it had to be, since
Orca sends text and BRLTTY turns text into dots. But BRLAPI says plainly that
its text path is a one-to-one character table and that a client wanting
contraction should "perform it itself (e.g. thanks to liblouis) and send the
resulting dot patterns ... exactly the same problem as font rendering on a
graphical display". Orca already does precisely that for contracted braille.

So the trick is to make liblouis emit dots rather than letters. Prefixing
``unicode.dis`` to the table list returns the line as U+2800-block
characters, whose low byte *is* the dot pattern, and BRLTTY renders those
verbatim whatever its own table says -- ``Programs/ttb_translate.c`` in
BRLTTY 6.9.1:

    if (row == UNICODE_BRAILLE_ROW) {
      return character & UNICODE_CELL_MASK;
    }

That check sits after the text-table lookup, and none of the 90 text tables
shipped on this machine defines the braille row, so it always applies.

**Two things follow.** Mixed tables become possible at all, because each run
is translated separately into dots that no later stage reinterprets. And the
BRLTTY text table stops mattering, so Polyglot no longer has to set it --
which removes the ``brlapi.setParameter`` round trip that once stopped Orca
for 49 seconds, and leaves the display's input table alone, since that is the
same table Polyglot used to be changing underneath it.

Every run goes through ``unicode.dis``, including a line that turns out to be
in one language. A line must not change appearance according to whether
detection found a second language in it, and one code path is one path to
test.
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict

#: Prefixed to every table list so liblouis returns dot patterns.
UNICODE_DIS = "unicode.dis"

#: Offset of the Unicode braille block. cell = ord(char) - BRAILLE_ROW.
BRAILLE_ROW = 0x2800

#: Lines whose segmentation is remembered, and for how long. Braille is
#: re-rendered on every caret movement, so the same line is translated over
#: and over; detecting it once per keystroke would be wasteful, and detecting
#: it differently on two keystrokes would make the line flicker between
#: tables.
_CACHE_SIZE = 256
_CACHE_SECONDS = 60.0

#: Longer than this and the line is shown in one table without detection. A
#: braille line is at most a couple of hundred characters; anything far
#: larger is a whole document handed over as one region, where per-run
#: translation would cost more than it is worth.
MAX_DETECT_LENGTH = 2000


def cells_of(text: str) -> list[int]:
    """Returns the dot bytes of a Unicode-braille string.

    BRLAPI codes a cell as ISO/TR 11548-1 -- bit 0 is dot 1, bit 7 is dot 8 --
    which is the low byte of the U+2800 block, so this is a subtraction. Used
    by the tests and the tools to say what reached the display.
    """

    return [ord(char) - BRAILLE_ROW for char in text]


def is_braille(text: str) -> bool:
    """Returns whether every character is in the Unicode braille block."""

    return bool(text) and all(BRAILLE_ROW <= ord(c) <= BRAILLE_ROW + 0xFF for c in text)


def script_runs(text, script_to_language, get_script):
    """Splits `text` into runs by Unicode script.

    Returns ``[(start, end, language or None)]`` covering all of `text` with
    no gaps, where None means "the table Orca asked for".

    Script is used rather than statistical detection because the evidence is
    certain and length-independent. That matters here in a way it does not
    for speech: a braille line is short -- a Mantis shows forty cells -- and
    Polyglot's mixed-language detector declines anything under eight words,
    so on a braille line it would almost always decline. One Cyrillic word in
    an English sentence is unambiguously Cyrillic whether or not there are
    eight words around it.

    Characters with no script of their own -- spaces, punctuation, digits --
    join the run they follow, so the space between two languages belongs to
    the first and cannot produce a run of its own. Leading ones join the
    first run that has a script.
    """

    runs: list[list] = []
    pending_start = None

    for index, char in enumerate(text):
        script = get_script(char)
        if script is None:
            if runs:
                # Belongs to the run before it.
                runs[-1][1] = index + 1
            elif pending_start is None:
                pending_start = index
            continue

        language = script_to_language.get(script)
        start = index if pending_start is None else pending_start
        pending_start = None
        if runs and runs[-1][2] == language:
            runs[-1][1] = index + 1
        else:
            runs.append([start, index + 1, language])

    if not runs:
        # No scripted character anywhere: digits, punctuation, or empty.
        return [(0, len(text), None)] if text else []

    # Trailing unscripted characters, and a line that began with them.
    runs[-1][1] = len(text)
    runs[0][0] = 0
    return [(start, end, language) for start, end, language in runs]


def merge_runs(segments):
    """Joins neighbouring segments that share a language."""

    merged: list[list] = []
    for start, end, language in segments:
        if merged and merged[-1][2] == language:
            merged[-1][1] = end
        else:
            merged.append([start, end, language])
    return [(start, end, language) for start, end, language in merged]


def segment_at(segments, position):
    """Returns the segment holding `position`, or the last one past the end."""

    for segment in segments:
        if segment[0] <= position < segment[1]:
            return segment
    return segments[-1] if segments else None


def translate_segments(
    translate,
    tabled,
    inbuf,
    typeform,
    cursor_pos,
    mode,
    comp_flag,
    extra_tables=(),
):
    """Translates each ``(start, end, table)`` of `inbuf` with its own table.

    Returns what ``louis.translate`` returns for the whole line:
    ``(output, in_position, out_position, cursor_position)``.

    The two maps are the whole job. ``in_position`` holds a text offset per
    cell, so each segment's values shift by where that segment starts in the
    text; ``out_position`` holds a cell per text offset, so its values shift
    by how many cells came before. Get either wrong and the line still looks
    right while routing keys land on the wrong character -- which is why the
    tests check the maps rather than the output.
    """

    output: list[str] = []
    in_position: list[int] = []
    out_position: list[int] = []
    cursor_position = None

    # No cursor asked for means no segment holds it, so every segment is
    # translated with the flag cleared and None is reported back.
    cursor_segment = None
    if cursor_pos is not None:
        for index, (start, end, _table) in enumerate(tabled):
            if start <= cursor_pos < end:
                cursor_segment = index
                break
        else:
            cursor_segment = len(tabled) - 1

    for index, (start, end, table) in enumerate(tabled):
        part = inbuf[start:end]
        part_typeform = typeform[start:end] if typeform is not None else None
        has_cursor = index == cursor_segment
        # compbrlAtCursor left set on a segment that does not hold the cursor
        # would be read as a cursor at offset 0, showing that segment's first
        # word in computer braille. The NVDA add-on documents the same trap.
        part_mode = mode if has_cursor else (mode & ~comp_flag)

        # liblouis types cursorPos as an int and will not take None, unlike
        # NVDA's wrapper. Zero is the right stand-in: with compbrlAtCursor
        # cleared it changes neither the output nor the maps (measured), and
        # with it set it would expand that segment's first word to computer
        # braille -- "the" going from one cell to three.
        part_out, part_in, part_rev, part_cursor = translate(
            [UNICODE_DIS, table, *extra_tables],
            part,
            typeform=part_typeform,
            cursorPos=(cursor_pos - start) if has_cursor else 0,
            mode=part_mode,
        )

        cells_before = len(output)
        if has_cursor and part_cursor is not None:
            cursor_position = part_cursor + cells_before
        output.extend(part_out)
        in_position.extend(position + start for position in part_in)
        out_position.extend(position + cells_before for position in part_rev)

    return "".join(output), in_position, out_position, cursor_position


class _LouisProxy:
    """Stands in for the ``louis`` module, intercepting only ``translate``.

    Orca works out the typeform, the cursor offset and the mode itself and
    then makes one call. Replacing the module rather than reimplementing
    ``Region._contract_line`` leaves all of that logic where Orca's authors
    put it, and keeps this add-on to the one thing it has an opinion about:
    which table each run of the line is translated with.
    """

    def __init__(self, real, translate):
        self._real = real
        self.translate = translate

    def __getattr__(self, name):
        # Everything else -- compbrlAtCursor, getTypeformForEmphClass,
        # charToDots -- is the real module's.
        return getattr(self._real, name)


class MixedBraille:
    """Shows each language run of a braille line in its own table."""

    def __init__(
        self,
        table_for,
        script_map,
        get_script,
        log=None,
        statistical=None,
        line_language=None,
        default_language=None,
    ):
        """
        Args:
            table_for: language code -> contraction table path, or None to
                keep the table Orca asked for.
            script_map: callable returning the script -> language mapping.
            get_script: callable returning a character's script, or None.
            log: optional callable for diagnostics.
            statistical: optional callable ``text -> [(text, lang)] | None``
                for languages that share a script, used only when the line is
                long enough for it to mean anything.
            line_language: callable ``text -> lang | None`` giving the
                language of a line that script could not place at all. This
                is what a wholly German line needs: there is no German script,
                so without it the line would fall back to the default table,
                which is the one thing Polyglot used to get right by setting
                the table per line.
            default_language: callable giving the configured default language,
                used for the parts of a *mixed* line that script left
                undecided. The line's own detected language is wrong here: on
                a line where Russian dominates it would put the English words
                in a Russian table.
        """

        self._table_for = table_for
        self._script_map = script_map
        self._get_script = get_script
        self._log = log or (lambda _message: None)
        self._statistical = statistical
        self._line_language = line_language or (lambda _text: None)
        self._default_language = default_language or (lambda: None)
        self._installed = False
        self._real_louis = None
        self._original_translate = None
        self._braille = None
        self._lock = threading.Lock()
        self._cache: OrderedDict = OrderedDict()
        self._reported: set = set()
        #: The last line logged, so a region re-rendered on every caret
        #: movement does not fill the log with the same line.
        self._last_logged = None
        self.translations = 0
        self.mixed_lines = 0

    # --- installation ----------------------------------------------------

    def install(self) -> bool:
        """Replaces Orca's liblouis module with the proxy. Returns success."""

        if self._installed:
            return True
        try:
            from orca import braille
        except ImportError:
            self._log("mixed braille: orca.braille unavailable")
            return False
        if getattr(braille, "LOUIS", None) is None:
            # Orca has no liblouis, so it is not contracting anything and
            # there is no call to wrap.
            self._log("mixed braille: Orca has no liblouis; nothing to wrap")
            return False
        if isinstance(braille.LOUIS, _LouisProxy):
            self._log("mixed braille: already wrapped")
            self._installed = True
            return True

        self._braille = braille
        self._real_louis = braille.LOUIS
        self._original_translate = braille.LOUIS.translate
        braille.LOUIS = _LouisProxy(self._real_louis, self._translate)
        self._installed = True

        # Worth saying out loud, because the symptom is nothing happening at
        # all: Orca only translates a region when contracted braille is on,
        # so with it off there is no call to wrap and this does nothing
        # whatever. The wrapper stays in place rather than refusing to
        # install, so turning the setting on starts working without a
        # restart.
        if not getattr(braille._STATE, "enable_contracted_braille", True):
            self._log(
                "mixed braille: on, but Orca's contracted braille is off, so "
                "nothing is being translated and no table can be chosen. Turn "
                "it on in Orca Preferences -> Braille."
            )
        else:
            self._log("mixed braille: on")
        return True

    def uninstall(self) -> None:
        """Puts Orca's liblouis module back."""

        if not self._installed:
            return
        self._installed = False
        braille = self._braille
        if braille is not None and isinstance(getattr(braille, "LOUIS", None), _LouisProxy):
            braille.LOUIS = self._real_louis
        self._real_louis = None
        self._original_translate = None
        self._braille = None
        self.clear_cache()
        self._log("mixed braille: off")

    @property
    def installed(self) -> bool:
        """Returns whether the proxy is in place."""

        return self._installed

    def clear_cache(self) -> None:
        """Forgets remembered segmentations, after a settings change."""

        with self._lock:
            self._cache.clear()

    # --- segmentation ----------------------------------------------------

    def segments(self, text: str):
        """Returns the language segments of `text`, remembered for a while."""

        if not text:
            return []
        if len(text) > MAX_DETECT_LENGTH:
            return [(0, len(text), None)]

        script_map = self._script_map() or {}
        key = (text, tuple(sorted(script_map.items())))
        now = time.monotonic()
        with self._lock:
            cached = self._cache.get(key)
            if cached is not None and now - cached[0] < _CACHE_SECONDS:
                self._cache.move_to_end(key)
                return cached[1]

        found = merge_runs(script_runs(text, script_map, self._get_script))
        found = self._refine(text, found)

        with self._lock:
            self._cache[key] = (now, found)
            self._cache.move_to_end(key)
            while len(self._cache) > _CACHE_SIZE:
                self._cache.popitem(last=False)
        return found

    def _refine(self, text, found):
        """Splits same-script runs further, where there is enough text to try.

        Script alone cannot separate English from German. The statistical
        detector can, but only with enough words to be worth believing, so it
        is asked only about runs that script left undecided and only when it
        offers an answer. Its segments are consecutive slices of what it was
        given, which is what makes them placeable.
        """

        if self._statistical is None:
            return found

        refined = []
        for start, end, language in found:
            if language is not None:
                refined.append((start, end, language))
                continue
            part = text[start:end]
            try:
                runs = self._statistical(part)
            except Exception:  # pylint: disable=broad-exception-caught
                runs = None
            if not runs:
                refined.append((start, end, language))
                continue
            offset = start
            for run_text, run_language in runs:
                length = len(run_text)
                if length <= 0:
                    continue
                refined.append((offset, offset + length, run_language))
                offset += length
            if offset != end:
                # The slices did not reconstruct the run; trust script only.
                return found
        return merge_runs(refined)

    def tables_for(self, text, default_table):
        """Returns ``[(start, end, table)]`` for `text`, merged by table.

        A run script could not place takes a language from one of two
        places, and which one depends on whether script placed anything at
        all. If it placed nothing, the line has no script signal in it and
        the line's own detected language is the best answer -- a German line
        is German. If it placed something, the line is mixed and the parts it
        left are the other language's, so the configured default is the right
        answer and the line's dominant language is not.
        """

        found = self.segments(text)
        fallback = None
        if found:
            if all(language is None for _s, _e, language in found):
                fallback = self._line_language(text)
            elif any(language is None for _s, _e, language in found):
                fallback = self._default_language()

        tabled: list[list] = []
        for start, end, language in found:
            chosen = language if language is not None else fallback
            table = (self._table_for(chosen) if chosen is not None else None) or default_table
            if tabled and tabled[-1][2] == table:
                tabled[-1][1] = end
            else:
                tabled.append([start, end, table])
        return [(start, end, table) for start, end, table in tabled]

    # --- the wrapped call ------------------------------------------------

    def _translate(self, table_list, inbuf, typeform=None, cursorPos=0, mode=0):
        """Orca's one translation call, done per language run.

        The signature mirrors ``louis.translate`` exactly, defaults included,
        because this stands in for it. In particular ``cursorPos`` is an int
        and defaults to 0: liblouis has no "no cursor" value, and Orca always
        passes an offset. Whether the cursor is *shown* is carried by
        ``compbrlAtCursor`` in `mode`, not by the offset.
        """

        original = self._original_translate
        if original is None:
            original = self._real_louis.translate

        if not self._installed or not inbuf or not table_list or "\0" in inbuf:
            return original(table_list, inbuf, typeform=typeform, cursorPos=cursorPos, mode=mode)

        tabled = []
        try:
            default_table = table_list[0]
            tabled = self.tables_for(inbuf, default_table)
            if not tabled:
                return original(
                    table_list, inbuf, typeform=typeform, cursorPos=cursorPos, mode=mode
                )

            comp_flag = getattr(self._real_louis, "compbrlAtCursor", 0)
            result = translate_segments(
                original,
                tabled,
                inbuf,
                typeform,
                cursorPos,
                mode,
                comp_flag,
                extra_tables=list(table_list[1:]),
            )
            self.translations += 1
            distinct = {table for _s, _e, table in tabled}
            if len(distinct) == 1 and tabled[0][2] != default_table:
                # One table, but not the one Orca asked for: a line with no
                # script signal placed by its own language, which is what a
                # wholly German line looks like. Logged because it is the
                # case the old per-line table switching used to handle, and
                # the only way to see that it still does.
                entry = (
                    f"braille table: {tabled[0][2].rsplit('/', 1)[-1]}"
                    f" for {inbuf[:40]!r} => {result[0][:40]}"
                )
                if entry != self._last_logged:
                    self._last_logged = entry
                    self._log(entry)
            if len(distinct) > 1:
                self.mixed_lines += 1
                entry = (
                    "mixed braille: "
                    + " | ".join(
                        f"{inbuf[s:e]!r}->{table.rsplit('/', 1)[-1]}"
                        for s, e, table in tabled
                    )
                    + f" => {result[0]}"
                )
                if entry != self._last_logged:
                    self._last_logged = entry
                    self._log(entry)
            return result
        except Exception as error:  # pylint: disable=broad-exception-caught
            # A missing or broken table would fail on every line, so it is
            # reported once per set of tables and then the line is shown in
            # one table. Braille that is in the wrong table is a nuisance;
            # braille that raises would take out the display.
            key = tuple(table for _s, _e, table in tabled)
            if key not in self._reported:
                self._reported.add(key)
                self._log(f"mixed braille: FAILED {error!r}; using one table for {key}")
            return original(table_list, inbuf, typeform=typeform, cursorPos=cursorPos, mode=mode)
