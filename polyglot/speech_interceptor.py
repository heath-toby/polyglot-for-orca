"""Polyglot for Orca — core speech pipeline patches.

Monkey-patches Orca's speech and braille systems to provide automatic
language switching, emoji/emoticon expansion, and Unicode announcement.
"""

import logging
import os
import sys

log = logging.getLogger("polyglot")

# Polyglot's data directory: the venv, the custom character names, the
# debug log. Deliberately outside the extension package -- Orca approves
# an extension by hashing every file in its directory and refuses to load
# it if anything changed, so nothing written at runtime may live there.
_DATA_DIR = os.path.join(
    os.environ.get("XDG_DATA_HOME", os.path.expanduser("~/.local/share")),
    "orca", "polyglot",
)

# Every monkey-patch we apply, as (owner, attribute, original, was_own).
# Recorded so uninstall() can put Orca back exactly as it found it. This
# matters for more than tidiness: the extension loader re-imports the
# module on reload, so a fresh module would otherwise patch the already
# patched functions and every utterance would be processed twice.
_patched_targets = []


def _patch(owner, attr, replacement):
    """Install replacement on owner.attr, remembering what was there."""
    try:
        was_own = attr in vars(owner)
    except TypeError:
        was_own = True
    _patched_targets.append((owner, attr, getattr(owner, attr), was_own))
    setattr(owner, attr, replacement)


def _unpatch_all():
    """Restore every patched attribute, most recent first."""
    while _patched_targets:
        owner, attr, original, was_own = _patched_targets.pop()
        try:
            if was_own:
                setattr(owner, attr, original)
            else:
                # It was inherited from the class; deleting the instance
                # attribute we added restores the original lookup rather
                # than pinning a bound method onto the instance.
                delattr(owner, attr)
        except Exception as error:  # pylint: disable=broad-exception-caught
            log.warning(f"Polyglot: could not restore {attr}: {error}")


# File-based debug log for diagnosing issues
_debug_log = None
_DEBUG_ENABLED = os.environ.get("ORCA_POLYGLOT_DEBUG", "").lower() in ("1", "true", "yes")


def _debug(msg):
    """Write debug message to file log if ORCA_POLYGLOT_DEBUG is set."""
    global _debug_log
    if not _DEBUG_ENABLED:
        return
    try:
        if _debug_log is None:
            os.makedirs(_DATA_DIR, exist_ok=True)
            log_path = os.path.join(_DATA_DIR, "debug.log")
            _debug_log = open(log_path, "a")
        import time
        _debug_log.write(f"{time.strftime('%H:%M:%S')} {msg}\n")
        _debug_log.flush()
    except Exception:
        pass

# Emoji expansion — imported lazily after venv path is set up
import re as _re
_emoji_mod = None
_emoji_available = False
_emoji_languages = set()


def _normalize_lang_code(lang):
    """Reduce a language tag from any common form to a bare ISO 639-1 code.

    Handles BCP 47 (``de``, ``de-DE``, ``en-Latn-US``), POSIX locales
    (``de_DE``, ``de_DE.UTF-8``, ``de@variant``), and stray uppercase
    casing. Returns the lowercased primary subtag, or ``None`` if the
    input is empty.
    """
    if not lang or not isinstance(lang, str):
        return None
    code = lang.strip()
    if not code:
        return None
    for sep in ("-", "_", ".", "@"):
        if sep in code:
            code = code.split(sep, 1)[0]
    code = code.lower()
    return code or None


def _acss_lang(acss):
    """Read the language tag from an ACSS family, normalised to ISO 639-1.

    Returns ``None`` if there's no usable language signal. Treats this as
    "voice() told us the language explicitly upstream" — the markup-only
    rule is: explicit signal here → use it, otherwise default.
    """
    if acss is None:
        return None
    try:
        from orca.acss import ACSS
        family = acss.get(ACSS.FAMILY)
        if not family:
            return None
        if isinstance(family, dict):
            return _normalize_lang_code(family.get("lang"))
        # VoiceFamily — also dict-like
        return _normalize_lang_code(family.get("lang"))
    except Exception:
        return None


def _init_emoji():
    """Try to import emoji module. Called after _add_venv_to_path()."""
    global _emoji_mod, _emoji_available, _emoji_languages
    if _emoji_available:
        return
    try:
        import emoji
        _emoji_mod = emoji
        _emoji_available = True
        _emoji_languages = set(emoji.LANGUAGES)
        log.info("Polyglot: emoji support loaded")
    except ImportError:
        log.info("Polyglot: emoji package not available")


def _expand_emojis(text, lang_code=None):
    """Replace emojis in text with their spoken names in the given language."""
    if not _emoji_available:
        return text
    elang = lang_code if lang_code in _emoji_languages else "en"
    demojized = _emoji_mod.demojize(text, language=elang)
    if demojized == text:
        return text

    def _replace(m):
        name = m.group(1).replace("_", " ")
        return f" {name} "

    # The character class excludes whitespace as well as colons.
    # Without that, a literal label colon followed by an emoji name
    # — e.g. "Family: :family_man_woman_girl:" — would let the
    # regex greedily match the label colon + space + the emoji's
    # leading colon as a fake ":<space>:" pair, eating the start
    # of the real emoji name and mangling the rest.
    result = _re.sub(r":([^\s:]+):", _replace, demojized)
    result = _re.sub(r"  +", " ", result).strip()
    return result


def _expand_emoji_char(char, lang_code=None):
    """Expand a single emoji character to its spoken name."""
    if not _emoji_available:
        return None
    elang = lang_code if lang_code in _emoji_languages else "en"
    demojized = _emoji_mod.demojize(char, language=elang)
    if demojized == char:
        return None
    name = demojized.strip(":").replace("_", " ")
    return name



# Text emoticon pronunciations
_EMOTICONS = {
    ":-)": "smiley face", ":)": "smiley face",
    ":-(": "sad face", ":(": "sad face",
    ":-D": "grinning face", ":D": "grinning face",
    ":-d": "grinning face", ":d": "grinning face",
    ";-)": "winking face", ";)": "winking face",
    ":-P": "tongue out", ":P": "tongue out",
    ":-p": "tongue out", ":p": "tongue out",
    ":-/": "confused face", ":/": "confused face",
    ":-\\": "confused face", ":\\": "confused face",
    ":-O": "surprised face", ":O": "surprised face",
    ":-o": "surprised face", ":o": "surprised face",
    ":-|": "neutral face", ":|": "neutral face",
    ":-*": "kiss", ":*": "kiss",
    ":'(": "crying face", ":'-(": "crying face",
    ">:(": "angry face", ">:-(": "angry face",
    "<3": "heart", "</3": "broken heart",
    "XD": "laughing", "xD": "laughing",
    "T_T": "crying", "T.T": "crying",
    "O_O": "shocked", "o_o": "shocked", "O.O": "shocked",
    "^_^": "happy", "^-^": "happy", "^^": "happy",
    ">_<": "frustrated", ">.<": "frustrated",
    "-_-": "unamused", "-.-": "unamused",
    "B-)": "cool face", "B)": "cool face",
    "8-)": "cool face", "8)": "cool face",
    "D:": "horrified",
    ">:)": "evil grin", ">:-)": "evil grin",
    "¯\\_(ツ)_/¯": "shrug",
    "(╯°□°)╯︵ ┻━┻": "table flip",
    "ಠ_ಠ": "disapproval",
}
_EMOTICON_PATTERN = None


def _build_emoticon_pattern():
    """Build regex pattern for emoticon detection. Called once."""
    global _EMOTICON_PATTERN
    sorted_emoticons = sorted(_EMOTICONS.keys(), key=len, reverse=True)
    escaped = [_re.escape(e) for e in sorted_emoticons]
    _EMOTICON_PATTERN = _re.compile(
        r'(?<!\w)(' + '|'.join(escaped) + r')(?!\w)'
    )


def _expand_emoticons(text):
    """Replace text emoticons with their spoken descriptions."""
    if _EMOTICON_PATTERN is None:
        _build_emoticon_pattern()

    def _replace(match):
        return f" {_EMOTICONS[match.group(0)]} "

    result = _EMOTICON_PATTERN.sub(_replace, text)
    return _re.sub(r"  +", " ", result).strip()


import unicodedata as _unicodedata

# Characters that TTS engines can pronounce — everything else gets expanded
# via unicodedata.name(). This covers Basic Latin letters, digits, and the
# standard ASCII punctuation that speech engines handle natively.
_PRONOUNCEABLE = set(
    # ASCII letters and digits
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    # Standard ASCII punctuation that TTS engines speak correctly
    " \t\n\r.,:;!?'\"()[]{}/-@#&*+=%<>\\|~`^_$"
    # Smart quotes and typographic punctuation — TTS engines treat these
    # the same as their ASCII equivalents (apostrophe, quotes, dashes, etc.)
    "\u2018\u2019"  # ' ' left/right single quotes (used as apostrophes)
    "\u201C\u201D"  # " " left/right double quotes
    "\u201A\u201E"  # ‚ „ low-9 quotes (German/Eastern European)
    "\u00AB\u00BB"  # « » guillemets
    "\u2039\u203A"  # ‹ › single guillemets
    "\u2013\u2014"  # – — en dash, em dash
    "\u2026"        # … horizontal ellipsis
    "\u00A0"        # non-breaking space
)

# Friendly name overrides for verbose Unicode names.
# Maps full Unicode name to a shorter, more natural spoken form.
_FRIENDLY_NAMES = {
    # Common punctuation and symbols
    "PILCROW SIGN": "pilcrow",
    "SECTION SIGN": "section sign",
    "COPYRIGHT SIGN": "copyright",
    "REGISTERED SIGN": "registered",
    "TRADE MARK SIGN": "trademark",
    "DEGREE SIGN": "degree",
    "MICRO SIGN": "micro",
    "MIDDLE DOT": "middle dot",
    "BROKEN BAR": "broken bar",
    "NOT SIGN": "not sign",
    "PLUS-MINUS SIGN": "plus minus",
    "MULTIPLICATION SIGN": "times",
    "DIVISION SIGN": "divided by",
    "INVERTED EXCLAMATION MARK": "inverted exclamation mark",
    "INVERTED QUESTION MARK": "inverted question mark",
    "INTERROBANG": "interrobang",
    "REVERSED QUESTION MARK": "reversed question mark",
    "NUMERO SIGN": "numero",
    # Dashes and hyphens (not covered by _PRONOUNCEABLE)
    "FIGURE DASH": "figure dash",
    "HORIZONTAL BAR": "horizontal bar",
    "HYPHEN": "hyphen",
    "NON-BREAKING HYPHEN": "non-breaking hyphen",
    "SOFT HYPHEN": "soft hyphen",
    "MINUS SIGN": "minus",
    # Spaces and formatting
    "ZERO WIDTH SPACE": "zero width space",
    "ZERO WIDTH NON-JOINER": "zero width non-joiner",
    "ZERO WIDTH JOINER": "zero width joiner",
    "LEFT-TO-RIGHT MARK": "left to right mark",
    "RIGHT-TO-LEFT MARK": "right to left mark",
    "WORD JOINER": "word joiner",
    "OBJECT REPLACEMENT CHARACTER": "object replacement",
    # Dots and bullets
    "BULLET": "bullet",
    "BULLET OPERATOR": "bullet",
    "TRIANGULAR BULLET": "triangular bullet",
    "HYPHENATION POINT": "hyphenation point",
    "HORIZONTAL ELLIPSIS": "ellipsis",
    # Currency
    "EURO SIGN": "euro",
    "POUND SIGN": "pound",
    "YEN SIGN": "yen",
    "CENT SIGN": "cent",
    "CURRENCY SIGN": "currency",
    "INDIAN RUPEE SIGN": "rupee",
    "RUBLE SIGN": "ruble",
    "TURKISH LIRA SIGN": "lira",
    "BITCOIN SIGN": "bitcoin",
    # Fractions
    "VULGAR FRACTION ONE HALF": "one half",
    "VULGAR FRACTION ONE QUARTER": "one quarter",
    "VULGAR FRACTION THREE QUARTERS": "three quarters",
    "VULGAR FRACTION ONE THIRD": "one third",
    "VULGAR FRACTION TWO THIRDS": "two thirds",
    "VULGAR FRACTION ONE FIFTH": "one fifth",
    "VULGAR FRACTION TWO FIFTHS": "two fifths",
    "VULGAR FRACTION THREE FIFTHS": "three fifths",
    "VULGAR FRACTION FOUR FIFTHS": "four fifths",
    "VULGAR FRACTION ONE SIXTH": "one sixth",
    "VULGAR FRACTION FIVE SIXTHS": "five sixths",
    "VULGAR FRACTION ONE EIGHTH": "one eighth",
    "VULGAR FRACTION THREE EIGHTHS": "three eighths",
    "VULGAR FRACTION FIVE EIGHTHS": "five eighths",
    "VULGAR FRACTION SEVEN EIGHTHS": "seven eighths",
    # Superscripts and subscripts
    "SUPERSCRIPT ONE": "superscript 1",
    "SUPERSCRIPT TWO": "superscript 2",
    "SUPERSCRIPT THREE": "superscript 3",
    "SUPERSCRIPT ZERO": "superscript 0",
    "SUBSCRIPT ZERO": "subscript 0",
    "SUBSCRIPT ONE": "subscript 1",
    "SUBSCRIPT TWO": "subscript 2",
    "SUBSCRIPT THREE": "subscript 3",
    "SUBSCRIPT FOUR": "subscript 4",
    "SUBSCRIPT FIVE": "subscript 5",
    "SUBSCRIPT SIX": "subscript 6",
    "SUBSCRIPT SEVEN": "subscript 7",
    "SUBSCRIPT EIGHT": "subscript 8",
    "SUBSCRIPT NINE": "subscript 9",
    # Music
    "EIGHTH NOTE": "eighth note",
    "BEAMED EIGHTH NOTES": "beamed eighth notes",
    "QUARTER NOTE": "quarter note",
    "MUSIC SHARP SIGN": "sharp",
    "MUSIC FLAT SIGN": "flat",
    "MUSIC NATURAL SIGN": "natural",
    # Card suits
    "BLACK SPADE SUIT": "spade",
    "BLACK HEART SUIT": "heart",
    "BLACK DIAMOND SUIT": "diamond",
    "BLACK CLUB SUIT": "club",
    "WHITE SPADE SUIT": "white spade",
    "WHITE HEART SUIT": "white heart",
    "WHITE DIAMOND SUIT": "white diamond",
    "WHITE CLUB SUIT": "white club",
    # Checkmarks and crosses
    "CHECK MARK": "check mark",
    "HEAVY CHECK MARK": "check mark",
    "BALLOT X": "x mark",
    "HEAVY BALLOT X": "x mark",
    "BALLOT BOX": "ballot box",
    "BALLOT BOX WITH CHECK": "checked ballot box",
    "BALLOT BOX WITH X": "x ballot box",
    # Stars
    "BLACK STAR": "black star",
    "WHITE STAR": "white star",
    "STAR OPERATOR": "star",
    # Arrows (simplified)
    "LEFTWARDS ARROW": "left arrow",
    "UPWARDS ARROW": "up arrow",
    "RIGHTWARDS ARROW": "right arrow",
    "DOWNWARDS ARROW": "down arrow",
    "LEFT RIGHT ARROW": "left right arrow",
    "UP DOWN ARROW": "up down arrow",
    "NORTH WEST ARROW": "northwest arrow",
    "NORTH EAST ARROW": "northeast arrow",
    "SOUTH EAST ARROW": "southeast arrow",
    "SOUTH WEST ARROW": "southwest arrow",
    "RIGHTWARDS DOUBLE ARROW": "right double arrow",
    "LEFTWARDS DOUBLE ARROW": "left double arrow",
    "UPWARDS DOUBLE ARROW": "up double arrow",
    "DOWNWARDS DOUBLE ARROW": "down double arrow",
    "LEFT RIGHT DOUBLE ARROW": "left right double arrow",
    # Mathematical
    "INFINITY": "infinity",
    "ALMOST EQUAL TO": "approximately equal",
    "NOT EQUAL TO": "not equal",
    "LESS-THAN OR EQUAL TO": "less than or equal",
    "GREATER-THAN OR EQUAL TO": "greater than or equal",
    "SQUARE ROOT": "square root",
    "PROPORTIONAL TO": "proportional to",
    "FOR ALL": "for all",
    "THERE EXISTS": "there exists",
    "EMPTY SET": "empty set",
    "ELEMENT OF": "element of",
    "NOT AN ELEMENT OF": "not element of",
    "SUBSET OF": "subset of",
    "SUPERSET OF": "superset of",
    "UNION": "union",
    "INTERSECTION": "intersection",
    "INTEGRAL": "integral",
    "PARTIAL DIFFERENTIAL": "partial differential",
    "NABLA": "nabla",
    "SUMMATION": "summation",
    "N-ARY PRODUCT": "product",
    "IDENTICAL TO": "identical to",
    "LOGICAL AND": "logical and",
    "LOGICAL OR": "logical or",
    "TILDE OPERATOR": "tilde",
    "DEGREE CELSIUS": "degrees celsius",
    "DEGREE FAHRENHEIT": "degrees fahrenheit",
    # Misc symbols
    "REPLACEMENT CHARACTER": "replacement character",
    "BLACK CIRCLE": "black circle",
    "WHITE CIRCLE": "white circle",
    "BLACK SQUARE": "black square",
    "WHITE SQUARE": "white square",
    "BLACK UP-POINTING TRIANGLE": "up triangle",
    "BLACK DOWN-POINTING TRIANGLE": "down triangle",
    "BLACK LEFT-POINTING TRIANGLE": "left triangle",
    "BLACK RIGHT-POINTING TRIANGLE": "right triangle",
    "LOZENGE": "lozenge",
    "WHITE MEDIUM SQUARE": "white square",
    "BLACK MEDIUM SQUARE": "black square",
    "SNOWFLAKE": "snowflake",
    "COMET": "comet",
    "BLACK SUN WITH RAYS": "sun",
    "CLOUD": "cloud",
    "UMBRELLA": "umbrella",
    "HOT SPRINGS": "hot springs",
    "SKULL AND CROSSBONES": "skull and crossbones",
    "RADIOACTIVE SIGN": "radioactive",
    "BIOHAZARD SIGN": "biohazard",
    "PEACE SYMBOL": "peace",
    "YIN YANG": "yin yang",
    "WARNING SIGN": "warning",
    "HIGH VOLTAGE SIGN": "high voltage",
    "ANCHOR": "anchor",
    "HEAVY EXCLAMATION MARK ORNAMENT": "exclamation mark",
    "HEAVY HEART EXCLAMATION MARK ORNAMENT": "heart exclamation",
    "HEAVY BLACK HEART": "red heart",
    "SPARKLES": "sparkles",
    "SNOWMAN": "snowman",
    # Dingbat ornament brackets and quotation marks
    "HEAVY LEFT-POINTING ANGLE QUOTATION MARK ORNAMENT": "left angle quote",
    "HEAVY RIGHT-POINTING ANGLE QUOTATION MARK ORNAMENT": "right angle quote",
    "HEAVY LEFT-POINTING ANGLE BRACKET ORNAMENT": "left angle bracket",
    "HEAVY RIGHT-POINTING ANGLE BRACKET ORNAMENT": "right angle bracket",
    "MEDIUM LEFT-POINTING ANGLE BRACKET ORNAMENT": "left angle bracket",
    "MEDIUM RIGHT-POINTING ANGLE BRACKET ORNAMENT": "right angle bracket",
    "MEDIUM LEFT PARENTHESIS ORNAMENT": "left parenthesis",
    "MEDIUM RIGHT PARENTHESIS ORNAMENT": "right parenthesis",
    "MEDIUM FLATTENED LEFT PARENTHESIS ORNAMENT": "left parenthesis",
    "MEDIUM FLATTENED RIGHT PARENTHESIS ORNAMENT": "right parenthesis",
    "MEDIUM LEFT CURLY BRACKET ORNAMENT": "left curly bracket",
    "MEDIUM RIGHT CURLY BRACKET ORNAMENT": "right curly bracket",
    "LIGHT LEFT TORTOISE SHELL BRACKET ORNAMENT": "left bracket",
    "LIGHT RIGHT TORTOISE SHELL BRACKET ORNAMENT": "right bracket",
    "HEAVY LOW DOUBLE COMMA QUOTATION MARK ORNAMENT": "low double quote",
    "CURVED STEM PARAGRAPH SIGN ORNAMENT": "paragraph sign",
    # Dingbat circled numbers
    "DINGBAT NEGATIVE CIRCLED DIGIT ONE": "circled 1",
    "DINGBAT NEGATIVE CIRCLED DIGIT TWO": "circled 2",
    "DINGBAT NEGATIVE CIRCLED DIGIT THREE": "circled 3",
    "DINGBAT NEGATIVE CIRCLED DIGIT FOUR": "circled 4",
    "DINGBAT NEGATIVE CIRCLED DIGIT FIVE": "circled 5",
    "DINGBAT NEGATIVE CIRCLED DIGIT SIX": "circled 6",
    "DINGBAT NEGATIVE CIRCLED DIGIT SEVEN": "circled 7",
    "DINGBAT NEGATIVE CIRCLED DIGIT EIGHT": "circled 8",
    "DINGBAT NEGATIVE CIRCLED DIGIT NINE": "circled 9",
    "DINGBAT NEGATIVE CIRCLED NUMBER TEN": "circled 10",
    # IPA symbols — common phonetic characters with short, spoken-friendly names
    "LATIN SMALL LETTER SCHWA": "schwa",
    "LATIN SMALL LETTER OPEN E": "open e",
    "LATIN SMALL LETTER OPEN O": "open o",
    "LATIN SMALL LETTER TURNED A": "turned a",
    "LATIN SMALL LETTER ALPHA": "alpha",
    "LATIN SMALL LETTER TURNED ALPHA": "turned alpha",
    "LATIN SMALL LETTER ESH": "esh",
    "LATIN SMALL LETTER EZH": "ezh",
    "LATIN SMALL LETTER ENG": "eng",
    "LATIN SMALL LETTER TURNED R": "turned r",
    "LATIN SMALL LETTER TURNED V": "turned v",
    "LATIN LETTER SMALL CAPITAL I": "small capital i",
    "LATIN SMALL LETTER UPSILON": "upsilon",
    "LATIN SMALL LETTER REVERSED OPEN E": "reversed open e",
    "LATIN LETTER GLOTTAL STOP": "glottal stop",
    "LATIN SMALL LETTER B WITH HOOK": "b hook",
    "LATIN SMALL LETTER C WITH CURL": "c curl",
    "LATIN SMALL LETTER D WITH TAIL": "d tail",
    "LATIN SMALL LETTER D WITH HOOK": "d hook",
    "LATIN SMALL LETTER DOTLESS J WITH STROKE": "barred dotless j",
    "LATIN SMALL LETTER G WITH HOOK": "g hook",
    "LATIN SMALL LETTER TURNED H": "turned h",
    "LATIN SMALL LETTER H WITH HOOK": "h hook",
    "LATIN SMALL LETTER LEZH": "lezh",
    "LATIN SMALL LETTER TURNED M": "turned m",
    "LATIN SMALL LETTER TURNED M WITH LONG LEG": "turned m long leg",
    "LATIN SMALL LETTER N WITH LEFT HOOK": "n left hook",
    "LATIN SMALL LETTER N WITH RETROFLEX HOOK": "n retroflex hook",
    "LATIN LETTER SMALL CAPITAL N": "small capital n",
    "LATIN LETTER SMALL CAPITAL OE": "small capital o e",
    "LATIN SMALL LETTER PHI": "phi",
    "LATIN LETTER SMALL CAPITAL R": "small capital r",
    "LATIN SMALL LETTER R WITH FISHHOOK": "r fishhook",
    "LATIN SMALL LETTER TURNED R WITH HOOK": "turned r hook",
    "LATIN SMALL LETTER S WITH HOOK": "s hook",
    "LATIN SMALL LETTER T WITH RETROFLEX HOOK": "t retroflex",
    "LATIN SMALL LETTER V WITH HOOK": "v hook",
    "LATIN SMALL LETTER TURNED W": "turned w",
    "LATIN SMALL LETTER TURNED Y": "turned y",
    "LATIN SMALL LETTER Z WITH RETROFLEX HOOK": "z retroflex",
    "LATIN SMALL LETTER Z WITH CURL": "z curl",
    "LATIN LETTER PHARYNGEAL VOICED FRICATIVE": "pharyngeal fricative",
    "LATIN LETTER INVERTED GLOTTAL STOP": "inverted glottal stop",
    "LATIN LETTER STRETCHED C": "stretched c",
    "LATIN SMALL LETTER BETA": "beta",
    "LATIN SMALL LETTER GAMMA": "gamma",
    "LATIN LETTER SMALL CAPITAL G": "small capital g",
    "LATIN LETTER SMALL CAPITAL L": "small capital l",
    "LATIN SMALL LETTER RAMS HORN": "rams horn",
    "LATIN SMALL LETTER SQUAT REVERSED ESH": "squat reversed esh",
    # IPA stress and length marks
    "MODIFIER LETTER VERTICAL LINE": "primary stress",
    "MODIFIER LETTER LOW VERTICAL LINE": "secondary stress",
    "MODIFIER LETTER TRIANGULAR COLON": "long",
    "MODIFIER LETTER HALF TRIANGULAR COLON": "half long",
    # IPA diacritics and modifiers
    "MODIFIER LETTER SMALL H": "aspirated",
    "MODIFIER LETTER SMALL W": "labialized",
    "MODIFIER LETTER SMALL J": "palatalized",
    "MODIFIER LETTER SMALL GAMMA": "velarized",
    "MODIFIER LETTER RHOTIC HOOK": "rhoticity",
}

# Prefixes to strip from Unicode names for cleaner speech.
# Applied only when no friendly name override exists.
_NAME_STRIP_PREFIXES = [
    "BOX DRAWINGS ",
    "BLOCK ",
    "BRAILLE PATTERN ",
    "DINGBAT ",
    # IPA / phonetic — longer prefixes first so they match before shorter ones
    "MODIFIER LETTER SMALL ",
    "MODIFIER LETTER ",
    "LATIN SMALL LETTER ",
    "LATIN CAPITAL LETTER ",
    "LATIN LETTER SMALL CAPITAL ",
    "LATIN LETTER ",
]

# Noise words to strip from Unicode names in brief mode.
# These add verbosity without meaning: "HEAVY RIGHT-POINTING ANGLE QUOTATION
# MARK ORNAMENT" → "right-pointing angle quotation mark".
_NAME_STRIP_WORDS_BRIEF = {"HEAVY", "MEDIUM", "LIGHT", "ORNAMENT", "NEGATIVE"}

# Invisible formatting characters to skip in "brief" unicode verbosity.
# These are zero-width or invisible control characters that serve no
# purpose when read aloud — bidirectional isolates, joiners, marks, etc.
_INVISIBLE_FORMATTING = set(
    "\u200B"  # ZERO WIDTH SPACE
    "\u200C"  # ZERO WIDTH NON-JOINER
    "\u200D"  # ZERO WIDTH JOINER
    "\u200E"  # LEFT-TO-RIGHT MARK
    "\u200F"  # RIGHT-TO-LEFT MARK
    "\u2028"  # LINE SEPARATOR
    "\u2029"  # PARAGRAPH SEPARATOR
    "\u202A"  # LEFT-TO-RIGHT EMBEDDING
    "\u202B"  # RIGHT-TO-LEFT EMBEDDING
    "\u202C"  # POP DIRECTIONAL FORMATTING
    "\u202D"  # LEFT-TO-RIGHT OVERRIDE
    "\u202E"  # RIGHT-TO-LEFT OVERRIDE
    "\u2060"  # WORD JOINER
    "\u2061"  # FUNCTION APPLICATION
    "\u2062"  # INVISIBLE TIMES
    "\u2063"  # INVISIBLE SEPARATOR
    "\u2064"  # INVISIBLE PLUS
    "\u2066"  # LEFT-TO-RIGHT ISOLATE
    "\u2067"  # RIGHT-TO-LEFT ISOLATE
    "\u2068"  # FIRST STRONG ISOLATE
    "\u2069"  # POP DIRECTIONAL ISOLATE
    "\u206A"  # INHIBIT SYMMETRIC SWAPPING
    "\u206B"  # ACTIVATE SYMMETRIC SWAPPING
    "\u206C"  # INHIBIT ARABIC FORM SHAPING
    "\u206D"  # ACTIVATE ARABIC FORM SHAPING
    "\u206E"  # NATIONAL DIGIT SHAPES
    "\u206F"  # NOMINAL DIGIT SHAPES
    "\uFEFF"  # ZERO WIDTH NO-BREAK SPACE (BOM)
    "\uFFF9"  # INTERLINEAR ANNOTATION ANCHOR
    "\uFFFA"  # INTERLINEAR ANNOTATION SEPARATOR
    "\uFFFB"  # INTERLINEAR ANNOTATION TERMINATOR
    "\u00AD"  # SOFT HYPHEN
    "\u034F"  # COMBINING GRAPHEME JOINER
    "\u061C"  # ARABIC LETTER MARK
    "\u180E"  # MONGOLIAN VOWEL SEPARATOR
)


def _is_invisible_formatting(char):
    """Check if a character is an invisible formatting character.

    Returns True for codepoints that exist purely as rendering hints
    or modifiers on a neighbouring base, and have no spoken value on
    their own in brief mode. In verbose mode the caller still
    announces them by name — power users may want to know a VS-16 is
    attached to a heart.
    """
    if char in _INVISIBLE_FORMATTING:
        return True
    cp = ord(char)
    # Variation selectors. VS-1..16 (U+FE00..FE0F) toggle text vs
    # emoji rendering or pick script-specific glyph variants. VS-17..
    # 256 (U+E0100..E01EF) pick Han ideograph variants. Both are
    # category Mn, so not caught by the Cf catch-all below.
    if 0xFE00 <= cp <= 0xFE0F or 0xE0100 <= cp <= 0xE01EF:
        return True
    # Regional indicator symbols (U+1F1E6..1F1FF). Pairs of these
    # form flag emojis; the emoji module resolves complete pairs into
    # country names in line reading. Reading each indicator letter
    # individually as "REGIONAL INDICATOR SYMBOL LETTER G" is just
    # noise. Category So, also not caught below.
    if 0x1F1E6 <= cp <= 0x1F1FF:
        return True
    # Catch any remaining Cf (Format) category chars not in the set
    return _unicodedata.category(char) == "Cf"


def _is_pronounceable(char):
    """Check if a character is one that TTS engines can pronounce natively."""
    if char in _PRONOUNCEABLE:
        return True
    # Emoji characters are never pronounceable — they must be expanded to names
    if _emoji_available and _emoji_mod.is_emoji(char):
        return False
    cp = ord(char)
    # IPA Extensions, Spacing Modifier Letters, Phonetic Extensions —
    # TTS engines cannot pronounce these; they need to be announced by name.
    if (0x0250 <= cp <= 0x02FF      # IPA Extensions + Spacing Modifier Letters
            or 0x1D00 <= cp <= 0x1DBF):  # Phonetic Extensions + Supplement
        return False
    # Latin Extended characters (accented letters, etc.) — TTS handles these
    if 0x00C0 <= cp <= 0x024F:
        return True
    # Common Latin-script letters beyond ASCII (e.g. ß, ð, þ, ø)
    if _unicodedata.category(char).startswith("L"):
        # Letter characters in scripts the TTS is likely to handle:
        # Latin, Cyrillic, Greek, Arabic, Hebrew, CJK, Hangul, Devanagari, etc.
        # These are actual language characters, not symbols.
        return True
    # Digit characters from other scripts (Arabic-Indic digits, etc.)
    if _unicodedata.category(char) == "Nd":
        return True
    return False


def _get_char_spoken_name(char, verbosity="verbose"):
    """Get a pronounceable name for a single character, or None.

    Returns None for characters that TTS engines can already pronounce
    (letters, digits, standard ASCII punctuation). For everything else,
    checks if it's an emoji (for modern names like "red heart" instead of
    "HEAVY BLACK HEART"), then falls back to Unicode name with friendly
    name overrides.

    In "brief" mode, invisible formatting characters (bidi isolates,
    zero-width joiners, etc.) are silently skipped (returns "").
    In "verbose" mode, everything is announced.
    """
    if _is_pronounceable(char):
        return None

    # In brief mode, silently swallow invisible formatting characters
    if verbosity == "brief" and _is_invisible_formatting(char):
        return ""

    # Check user-defined custom names first (highest priority)
    try:
        # `from .x import y`, not `from . import x`: the loader never
        # creates the `orca_user_extension` parent package, and the
        # latter form makes Python try to import it.
        from .custom_names import get_name as _custom_names_get_name
        custom = _custom_names_get_name(char, verbosity)
        if custom:
            return custom
    except Exception:
        pass

    # Try emoji name first — gives modern names (e.g. "red heart" not "heavy black heart")
    if _emoji_available and _emoji_mod.is_emoji(char):
        emoji_name = _expand_emoji_char(char, _current_language or "en")
        if emoji_name:
            return emoji_name

    name = _unicodedata.name(char, None)
    if not name:
        return None

    # Check friendly name overrides
    friendly = _FRIENDLY_NAMES.get(name)
    if friendly:
        return friendly

    # Strip verbose prefixes for cleaner speech
    for prefix in _NAME_STRIP_PREFIXES:
        if name.startswith(prefix):
            name = name[len(prefix):]
            break

    # In brief mode, strip noise words like HEAVY, ORNAMENT, etc.
    if verbosity == "brief":
        words = [w for w in name.split() if w not in _NAME_STRIP_WORDS_BRIEF]
        if words:
            name = " ".join(words)

    return name.lower()


def _expand_unpronounceable(text, verbosity="verbose"):
    """Replace unpronounceable Unicode characters with their spoken names.

    Handles repeated characters by collapsing them: "──────" becomes
    "6 light horizontal characters" instead of repeating the name.

    In "brief" mode, invisible formatting chars are silently dropped.

    Runs whole-string emoji expansion FIRST so multi-codepoint
    sequences (regional-indicator flag pairs, heart+VS-16, ZWJ family
    sequences, …) get resolved to their full names while their
    constituent codepoints are still intact. Without this step,
    per-char processing would strip invisible parts of the sequence
    (e.g. the regional indicators in brief mode after v1.1.8),
    leaving nothing for downstream emoji handlers to recognise.
    """
    if not text:
        return text
    # Step 1: whole-string emoji expansion. Idempotent — if called
    # again later (e.g. by _patched_speak), the second call no-ops.
    if (_config and _config.speak_emojis and _emoji_available):
        text = _expand_emojis(text, _current_language)
    # Quick check: if all characters are pronounceable, skip processing
    if all(_is_pronounceable(c) for c in text):
        return text

    result = []
    i = 0
    while i < len(text):
        char = text[i]
        name = _get_char_spoken_name(char, verbosity)
        if name is not None:
            if name == "":
                # Invisible character in brief mode — silently skip
                i += 1
                continue
            # Count consecutive identical characters
            count = 1
            while i + count < len(text) and text[i + count] == char:
                count += 1
            if count > 1:
                result.append(f" {count} {name} characters ")
            else:
                result.append(f" {name} ")
            i += count
        else:
            result.append(char)
            i += 1

    expanded = "".join(result)
    # Clean up extra spaces
    expanded = _re.sub(r"  +", " ", expanded)
    return expanded


# Global state
_installed = False
_detector = None
_config = None
_current_language = None
# The languages Polyglot is configured for. Serves the membership test
# that _lang_acss_cache used to: "is this a language we handle?"
_configured_languages = set()
_in_detection = False  # reentrancy guard


def _add_venv_to_path():
    """Add Polyglot's venv site-packages to sys.path for lingua.

    The venv lives in Polyglot's data directory, not inside the extension
    package. Keeping it out means the package holds only code, and -- more
    importantly -- means the venv survives the package being moved or
    reinstalled, which matters because its scripts bake in an absolute
    path and have to be rebuilt whenever it moves.
    """
    venv_site = os.path.join(_DATA_DIR, ".venv", "lib")
    if not os.path.isdir(venv_site):
        return
    for entry in os.listdir(venv_site):
        sp = os.path.join(venv_site, entry, "site-packages")
        if os.path.isdir(sp) and sp not in sys.path:
            sys.path.insert(0, sp)
            break


def install(config=None):
    """Install the language-switching monkey-patches into Orca's speech system.

    ``config`` is the Config the Extension owns, already bound to Orca's
    per-extension settings store. It is optional only so that the older
    orca-customizations.py entry point keeps working.
    """
    global _installed, _detector, _config, _current_language

    if _installed:
        return

    _add_venv_to_path()
    _init_emoji()

    from .custom_names import load as _custom_names_load
    _custom_names_load()

    from .speech_dictionary import load as _speech_dictionary_load
    _speech_dictionary_load()

    from .config import Config
    from .language_detector import LanguageDetector, is_lingua_available

    _config = config if config is not None else Config()
    first_run = _config.is_first_run
    _config.load()

    # Hand any pre-2.2 per-language voices over to Orca's voice sets before
    # the save below prunes those keys out of the store.
    needs_save = _config.migrate_voice_settings_to_orca()

    if first_run:
        _config.auto_configure()
        _config.save()
        log.info("Polyglot: first run, auto-configured from available voices")
    else:
        # Languages whose voices have gone are no longer worth detecting.
        if _config.prune_unavailable_languages() or needs_save:
            _config.save()
            log.info("Polyglot: updated config for the available voices")

    # Always apply patches — they handle emoji (independent) and language
    # switching (checks _config.enabled and _detector internally).
    _apply_patches()

    if not _config.enabled:
        log.info("Polyglot: language switching disabled (emoji + keybinding still active)")
        _installed = True
        return

    if not _config.enabled_languages:
        log.info("Polyglot: no languages configured")
        _installed = True
        return

    _detector = LanguageDetector(
        enabled_languages=_config.enabled_languages,
        word_threshold=_config.word_threshold,
        script_to_language=_config.script_to_language,
        default_language=_config.default_language,
        switch_confidence=_config.switch_confidence,
        mixed_max_words=_config.mixed_max_words,
        dictionaries=_build_dictionary_detector(),
        detection_order=_config.detection_order,
    )
    _current_language = _config.default_language
    _detector.current_language = _current_language

    _rebuild_configured_languages()
    _installed = True

    lang_count = len(_config.enabled_languages)
    lingua_status = "with Lingua" if is_lingua_available() else "script detection only"
    log.info(
        f"Polyglot: installed ({lang_count} languages, {lingua_status})"
    )
    log.info(
        "Polyglot: detection order is "
        + " then ".join(_detector.detection_order)
    )

    # Word lists are read on first lookup, which would otherwise be the
    # first thing Orca says. Reading them costs about 40 ms for three
    # languages, so spend it on an idle callback instead.
    _schedule_dictionary_warmup()

    if first_run:
        try:
            from gi.repository import GLib
            GLib.idle_add(_speak_first_run_notification, lang_count, lingua_status)
        except Exception:
            pass


def _speak_first_run_notification(lang_count, lingua_status):
    """Speak a notification about the auto-configuration (called from GLib idle)."""
    try:
        from orca import speech_presenter
        speech_presenter.get_presenter().speak_message(
            f"Polyglot configured with {lang_count} languages, {lingua_status}.",
        )
    except Exception:
        pass
    return False


def _rebuild_configured_languages():
    """Refresh the set of languages Polyglot will switch to.

    This used to build a full ACSS per language -- voice name, dialect,
    rate, pitch and volume, read from Polyglot's own settings. Orca 51
    supplies all of that itself from the matching voice set, so the only
    thing worth remembering is which languages are enabled.

    One behaviour change falls out of that, for the better: a language used
    to be skipped unless it had a voice name stored, so an enabled language
    with no voice chosen silently never switched. Now ticking it is enough.
    """
    global _configured_languages, _focus_line_language, _line_language_cache
    global _line_sentinel_cache
    _configured_languages = set(_config.enabled_languages)
    _fallback_families.clear()
    _focus_line_language = None
    _line_language_cache = None
    _line_sentinel_cache = None
    log.info(
        "Polyglot: configured languages: "
        + (", ".join(sorted(_configured_languages)) or "(none)")
    )


def _switch_language(lang_code, also_braille: bool = False):
    """Switch the voice, and the braille tables only if asked.

    ``also_braille`` defaults to False because the safe answer is the common
    one: ``_patched_update_braille`` is the single authority for braille and
    the only caller that passes True. It used to default to True, and the
    four speech-side call sites that simply forgot to pass False were enough
    to drag the tables off the focus line. Opting in makes a new call site
    harmless by default rather than wrong by default.

    Symbol-name locale is speech-side state and switches regardless — it
    follows the active speech.
    """
    global _current_language, _in_detection

    # Only _patched_update_braille passes also_braille=True. Everything on
    # the speech side passes False, because only one braille table can be
    # active at a time and the line on the display owns it. A speech-side
    # switch happens per utterance and per character, after update_braille
    # has already settled the line: letting those move the tables rendered
    # the line's German contraction through an English text table, giving
    # the right number of cells with the wrong dots until the user moved off
    # the line and back.

    # IPA sentinel — switch braille table only, don't change voice or current language
    if lang_code == "ipa":
        if also_braille:
            _set_contraction_table("/usr/share/liblouis/tables/IPA.utb")
        return

    # Unicode braille sentinel — line is made of U+2800–U+28FF dot patterns.
    # Use the liblouis pass-through table so contracted braille shows the
    # actual dot patterns instead of being misinterpreted. Keep voice and
    # current language unchanged so speech still tracks the surrounding text.
    if lang_code == "unicode_braille":
        if also_braille:
            _set_contraction_table("/usr/share/liblouis/tables/unicode-braille.utb")
        return

    if lang_code not in _configured_languages:
        return

    # Before either early return below, because neither of them used to be
    # reached by it and the result was Orca announcing roles in the wrong
    # language indefinitely: "Schaltfläche" instead of "button" long after
    # the voice had gone back to English, which also fed that German
    # straight back into detection. It is idempotent and cached, so calling
    # it on every switch costs a comparison.
    _set_orca_names_locale(lang_code)

    # If the language is already current AND the caller doesn't care
    # about braille, there's nothing to do. But when also_braille=True
    # the braille tables may still be lagging — speech-side calls with
    # also_braille=False set _current_language but skip the table
    # switch, so a follow-up update_braille for the same language
    # needs to fall through to _switch_braille_tables.
    if lang_code == _current_language and not also_braille:
        return

    if _in_detection:
        # Avoid reentrancy — just update the language marker
        _current_language = lang_code
        if _detector is not None:
            _detector.current_language = lang_code
        return

    _in_detection = True
    try:
        _debug(f"_switch_language: {_current_language} -> {lang_code} (also_braille={also_braille})")
        _current_language = lang_code
        # Keep the detector's notion of "current language" in sync. Without
        # this, markup-only mode silently misbehaves: _patched_voice sets
        # this module's _current_language from markup, but the detector
        # still holds the previous value. _patched_speak then calls
        # detect(statistical=False) which falls back to the detector's
        # stale value and overrides the just-resolved ACSS with the wrong
        # language — symptom: German markup reads in English.
        if _detector is not None:
            _detector.current_language = lang_code
        if also_braille:
            lang_settings = _config.language_settings.get(lang_code, {})
            _switch_braille_tables(lang_settings)
        _debug(f"_switch_language: done")
    except Exception as e:
        _debug(f"_switch_language: ERROR {e}")
        raise
    finally:
        _in_detection = False


_current_names_locale = None


# "Languages" that exist only to name a braille table. There is no voice
# for either, so neither is ever an enabled language -- which is why they do
# not survive the _configured_languages filter that _language_of_line
# applies. See _braille_sentinel.
_BRAILLE_ONLY_SENTINELS = ("ipa", "unicode_braille")


def _set_orca_names_locale(lang_code):
    """Switch Orca's character/symbol name modules to ``lang_code``.

    Orca's mathsymbols, keynames, cmdnames etc. read translations through
    gettext. ``orca_i18n.setLocaleForNames`` reloads those modules against
    a different locale, which makes character announcements (space, comma,
    arrows, …) come out in that language. Driving it from our language
    switch means symbol names follow the active language too — useful as
    an audible signal that the language really changed.

    Cached so we only pay the reload cost on actual locale changes. Skip
    for braille-only sentinels.
    """
    global _current_names_locale
    if not lang_code or lang_code in ("ipa", "unicode_braille"):
        return
    if lang_code == _current_names_locale:
        return
    try:
        from orca import orca_i18n
        orca_i18n.setLocaleForNames(lang_code)
        _current_names_locale = lang_code
        _debug(f"setLocaleForNames: {lang_code}")
    except Exception as e:
        _debug(f"setLocaleForNames ERROR: {e}")


_current_contraction_table = None
_brltty_conn = None
_brltty_failed = False
_current_brltty_text_table = None

# Saved state captured when entering a flash message (notifications,
# time announcements, mode strings) and restored when the flash ends.
# We track an explicit _in_flash flag rather than relying on None
# sentinels because the saved values themselves may legitimately be
# None (e.g. before any line has been focused, no contraction table
# is set yet — "saving" None is a legitimate "no-op on restore").
_in_flash = False
# Snapshot of the focus line's tables at the moment a flash starts.
# Used both as the values to restore to AND (compared against the
# current _focus_line_* values) to detect navigation during the flash.
_pre_flash_focus_contraction: str | None = None
_pre_flash_focus_brltty: str | None = None
# What the tables actually became after _switch_to_default_braille_tables.
# Used at restore time to detect whether speech-side switching changed
# the tables during the flash (e.g. user navigated into German content
# while a flash was still showing — _patched_speak switched tables, and
# we must not undo that legitimate change).
_flash_default_contraction: str | None = None
_flash_default_brltty: str | None = None


def _switch_to_default_braille_tables() -> None:
    """Switch contraction + BRLTTY text tables to the default language.

    Used when entering a flash message so that notifications, time
    announcements, and other non-line content are read in the user's
    primary language regardless of what the focus line was set to.
    Records the resulting "flash default" so the restore step can
    distinguish "tables unchanged since flash" from "tables changed
    by speech during flash".
    """
    global _flash_default_contraction, _flash_default_brltty
    if not _config:
        return
    default_lang = _config.default_language
    lang_settings = _config.language_settings.get(default_lang, {})
    contraction = lang_settings.get("contraction_table", "")
    # Switch both tables together, or switch neither: a half-switched
    # state where one table is the default-language and the other is
    # still the focus line's language produces wrong braille (text and
    # contraction tables disagreeing on character → dot mapping).
    if contraction:
        _set_contraction_table(contraction)
        _set_brltty_text_table(default_lang)
    # Capture whatever the tables actually are after the switch attempt
    # (which may have no-op'd if contraction was unset or matched).
    _flash_default_contraction = _current_contraction_table
    _flash_default_brltty = _current_brltty_text_table


# "Focus line" state — what update_braille last set for the line of
# focus. Distinct from _current_* (which any patch can mutate) because
# speech for a flash message happens BEFORE braille.display_message,
# and that speech may legitimately change the current state to the
# flash's language. We need an independent record of the focus line's
# state to restore to after the flash.
_focus_line_contraction_table: str | None = None
_focus_line_brltty_text_table: str | None = None
_focus_line_language: str | None = None


def _record_focus_line_state() -> None:
    """Pin the current braille tables as the focus line's tables.

    Called from _patched_update_braille after it has driven a language
    switch for the current line. The focus-line snapshot is what flash
    save/restore uses, so it must not be perturbed by speech-time language
    switches -- speech for a flash message runs before the flash is
    displayed, and may legitimately move _current_* to the flash's own
    language.

    It deliberately records nothing about the line's text or language for
    anyone else to read. An earlier design did, and character announcements
    took their language from it; every bug in that area came from the record
    being out of step with what Orca was actually speaking. Characters now
    ask the object instead -- see _context_language.
    """
    global _focus_line_contraction_table, _focus_line_brltty_text_table
    global _focus_line_language
    _focus_line_contraction_table = _current_contraction_table
    _focus_line_brltty_text_table = _current_brltty_text_table
    _focus_line_language = _current_language


# Cache for the last container line we resolved a language for. Keyed on the
# text itself, so it cannot go stale: a different line simply misses.
_line_language_cache: tuple[str, str] | None = None


def _container_line(obj, offset=None) -> str | None:
    """The line of text ``obj`` is showing, or None.

    None means the object is not a piece of text at all -- a button, a menu
    item, a toolbar, a frame -- which is the signal that we are looking at
    the window's own furniture rather than at content.

    ``offset`` defaults to the caret. Braille passes its own, because
    panning moves along a line without moving the caret.
    """
    try:
        from orca.ax_object import AXObject
        if not AXObject.supports_text(obj):
            return None
        from orca.ax_text import AXText
        if offset is None:
            offset = AXText.get_caret_offset(obj)
        line = AXText.get_line_at_offset(obj, max(0, offset or 0))
    except Exception as error:  # pylint: disable=broad-exception-caught
        _debug(f"_container_line: {type(error).__name__}: {error}")
        return None
    text = line[0] if line else None
    return text if text and text.strip() else None


# Module level, not nested in the patch installer: _apply_braille_language
# below is module level too and cannot see a closure cell. Nested callers
# resolve this as a global, so promoting it changes nothing for them.
def _is_app_ignored():
    """Check if the currently focused app is in the ignored list."""
    try:
        if not _config or not _config.ignored_apps:
            return False
        app_name = None
        # Orca v50: use script_manager to get the active app
        try:
            from orca import script_manager
            app = script_manager.get_manager().get_active_script_app()
            if app:
                from orca.ax_object import AXObject
                app_name = AXObject.get_name(app)
        except Exception:
            pass
        # Fallback: use focus_manager + Atspi
        if not app_name:
            try:
                from orca import focus_manager
                from gi.repository import Atspi
                focus = focus_manager.get_manager().get_locus_of_focus()
                if focus:
                    app = Atspi.Accessible.get_application(focus)
                    if app:
                        app_name = Atspi.Accessible.get_name(app)
            except Exception:
                pass
        if not app_name:
            return False
        _debug(f"_is_app_ignored: app={app_name!r} ignored={_config.ignored_apps}")
        ignored_lower = {a.lower() for a in _config.ignored_apps}
        return app_name.lower() in ignored_lower
    except Exception as e:
        _debug(f"_is_app_ignored ERROR {e}")
        return False


def _rerender_braille() -> None:
    """Re-render what is already on the display under the new tables.

    Changing a table does not redraw anything by itself. Orca caches each
    line's rendered form (``Line._info_cache``), and with contracted braille
    on that cache holds the liblouis output, so a table change is invisible
    until something rebuilds or re-renders the line. If the caret has not
    moved -- switching windows, or coming back to one -- nothing does, and the
    display sits there in the old table showing the old cells. Panning away
    and back was the manual workaround: it re-renders.

    So invalidate the cached lines and refresh.

    ``pan_to_cursor=True``, which is Orca's own default everywhere else, and
    it is load-bearing. It was briefly False, on the idea that leaving the
    viewport alone was the polite thing to do -- but at the moment a table
    changes the viewport is NOT where the reader left it. A rebuild, or the
    restore at the end of a flash message, puts it back at the start of the
    line, and the start of an Orca braille line is the window title and the
    app name. False therefore parked the display on the window title after
    every window switch and after every flash message, and the only way back
    to the text was to pan several lines. Panning cannot be disturbed by
    panning to the cursor here, because panning moves no caret, so no table
    changes and this never runs.

    ``stop_flash=False`` lets a flash message finish rather than being cut
    off by a table change underneath it.

    Reaches into braille._STATE because Orca exposes no public way to drop
    those caches; guarded accordingly, and a failure only costs the redraw.
    """
    try:
        from orca import braille
        for line in getattr(braille, "_STATE").lines:
            try:
                line.invalidate_cache_internal()
            except Exception:  # pylint: disable=broad-exception-caught
                pass
        braille.refresh(pan_to_cursor=True, stop_flash=False)
        _debug("rerendered braille under the new tables")
    except Exception as error:  # pylint: disable=broad-exception-caught
        _debug(f"_rerender_braille: {type(error).__name__}: {error}")


def _redraw_braille_for(obj) -> None:
    """Rebuild the braille line for ``obj`` under the new tables.

    A plain refresh is the wrong tool here, and that is a bug I shipped once.
    ``braille.refresh`` redraws whatever is in ``_STATE.lines``, and those
    lines belong to whatever Orca last brailled -- which on a window switch
    is the FRAME, i.e. the window title. Orca does not necessarily rebuild
    after focus moves on to the document: measured, 18 seconds passed between
    focus landing on a Russian paragraph and the next ``update_braille``. So
    refreshing re-asserted the window title, now rendered in the Russian
    table, and it stayed there until the reader panned or moved the caret.

    Asking the active script to rebuild for ``obj`` instead gives the right
    content, in the right table, panned the way Orca pans it.

    No recursion: ``update_braille`` is patched, so it re-enters
    ``_apply_braille_language``, which finds the table already correct and
    reports no change, so nothing redraws a second time.
    """
    if obj is not None:
        try:
            from orca import script_manager
            script = script_manager.get_manager().get_active_script()
            if script is not None:
                script.update_braille(obj)
                _debug("redrew braille for the object under the new tables")
                return
        except Exception as error:  # pylint: disable=broad-exception-caught
            _debug(f"_redraw_braille_for: {type(error).__name__}: {error}")
    # No script, or the rebuild failed: fall back to re-rendering what is
    # there, which is at least in the right table.
    _rerender_braille()


def _apply_braille_language(obj, offset=None, source: str = "braille") -> bool:
    """Set the braille tables for the line ``obj`` is showing. Never raises.

    This is the one owner of the braille tables. It is deliberately NOT on the
    speech path: a braille line belongs to the focus line as a whole, and
    switching tables part-way through one is what produced hybrid cells --
    dots 1246 where German wanted 46 -- because the characters already written
    keep the table they were rendered with.

    Called from two places, because Orca has two:

      * Script.update_braille, which rebuilds the braille line from scratch.
      * Script._update_braille_caret_position, which runs on EVERY caret move
        and usually does not rebuild anything. See the patch for why that
        matters; in short, update_braille alone misses most of the reading.

    Within one line this costs a cached string comparison and then returns
    early from _switch_language, so firing it per keypress is cheap and cannot
    switch tables mid-line.
    """
    try:
        mode = _config.detection_mode if _config else "markup_text"
        if not (_config and _config.enabled and _detector and obj is not None
                and not _is_app_ignored() and mode != "off"):
            return False
        # Resolved the same way the speech path resolves it, which gates on
        # the object actually being text. It was previously asked for a line
        # from whatever it was handed -- a frame, a label -- and the English
        # it got back from those was why the contraction table was switched
        # to and fro several times per focus change: inside gedit, on a
        # German document, this logged en, de, en, de in a second.
        text = _container_line(obj, offset)
        if not text:
            return False
        detected = None
        # Prefer obj-locale (markup signal) in non-always modes.
        if mode != "always":
            try:
                from orca.ax_object import AXObject
                detected = _normalize_lang_code(AXObject.get_locale(obj))
            except Exception:  # pylint: disable=broad-exception-caught
                pass
        if not detected:
            if mode == "markup_only":
                detected = _detector.detect(
                    text, statistical=False, fallback_to_current=False)
                if not detected:
                    detected = _config.default_language
            elif mode in ("markup_text", "always"):
                # Sentinel first: a line of IPA or of Unicode dot patterns
                # names a table outright, and _language_of_line drops both
                # for not being enabled languages. Then the line's language,
                # cached per line text so the repeated calls Orca makes for
                # one event cost a string comparison rather than a fresh
                # detection and a churned word buffer.
                detected = (_braille_sentinel(text) or _language_of_line(text))
            else:
                detected = _detector.detect(text)
        if not detected:
            return False
        _debug(f"{source}: detected={detected}")
        before = (_current_contraction_table, _current_brltty_text_table)
        _switch_language(detected, also_braille=True)
        # Report whether the tables moved; the caller decides what to redraw,
        # because only the caller knows which object the display should be
        # showing by the time it is done.
        return (_current_contraction_table, _current_brltty_text_table) != before
        # Pin this as the focus-line state so the flash hook has a clean
        # snapshot regardless of any speech-time mutations, and so character
        # announcements within this line can read its language.
        _record_focus_line_state()
    except Exception as error:  # pylint: disable=broad-exception-caught
        _debug(f"{source} pre: ERROR {type(error).__name__}: {error}")
    return False


def _language_of_line(text: str) -> str | None:
    """Detect the language of a container line, remembering the last answer.

    Two things here are load-bearing.

    The detection mode is honoured, rather than the full detector being run
    regardless. This is the path a space or a single character takes to its
    language, and in markup-only mode it used to be the one place
    statistical detection still happened -- so on a German line the letters
    were read in the default language, having no script signal, while the
    spaces between them were read in German. That is the character-by-
    character flicker: not one language per character, but two paths to it
    disagreeing.

    Nothing is cached unless it was positively detected. Asking for the
    current language as a fallback and then caching the answer against the
    line's text would pin a volatile value to that line for good: read a
    short line while German is current and it stays German for the rest of
    the session, whatever is said in between.
    """
    global _line_language_cache
    if _detector is None or _config is None:
        return None
    if _line_language_cache is not None and _line_language_cache[0] == text:
        return _line_language_cache[1]
    statistical = _config.detection_mode in ("markup_text", "always")
    detected = _detector.detect(text, statistical=statistical,
                                fallback_to_current=False)
    if detected and detected in _configured_languages:
        _line_language_cache = (text, detected)
        _debug(f"_language_of_line: {detected} <- {text[:40]!r}")
        return detected
    return None


# The last line a sentinel was resolved for. Separate from
# _line_language_cache because the two callers want different answers about
# the same text: speech wants a spoken language, braille wants a table.
_line_sentinel_cache: tuple[str, str | None] | None = None


def _braille_sentinel(text: str) -> str | None:
    """"ipa" or "unicode_braille" if that is what this line is, else None.

    These name a braille table rather than a language, and _switch_language
    treats them that way: it sets the table and leaves the voice and the
    current language alone. Because there is no voice for either, neither is
    ever an enabled language, so neither survives _language_of_line -- which
    keeps only configured languages. The braille path therefore could not
    see them at all in markup_text or always mode, and an IPA or
    Unicode-braille line got its table only as a side effect of a
    speech-side switch that had no business touching braille. Closing that
    leak means asking for them here, deliberately.

    Cached like _language_of_line and for the same reason: Orca calls
    update_braille several times for one focus change.
    """
    global _line_sentinel_cache
    if _detector is None:
        return None
    if _line_sentinel_cache is not None and _line_sentinel_cache[0] == text:
        return _line_sentinel_cache[1]
    found = _detector.detect(text, statistical=False, fallback_to_current=False)
    found = found if found in _BRAILLE_ONLY_SENTINELS else None
    _line_sentinel_cache = (text, found)
    if found:
        _debug(f"_braille_sentinel: {found} <- {text[:40]!r}")
    return found


def _context_language(obj, string) -> str | None:
    """The language for a string with no content of its own.

    A single character, a space, a two-letter label: nothing in the text
    itself says what language it is, so the answer has to come from what it
    sits in. Asking the object directly is what makes this reliable -- an
    earlier design kept a remembered "current line" in module state, and
    every bug in this area came from that record being out of step with
    whatever Orca was actually speaking.

    Three outcomes, from the structure rather than from guesswork:

    * no object -- nothing to ask, so this is text being typed, and the
      current language is right: it is what the accumulating words have
      been teaching.
    * an object that is not text -- a button, a menu item. Its label is
      the window's own furniture, which is in the system language.
    * an object that is text -- detect its line. Every character of a
      German paragraph gets the same answer, spaces and punctuation
      included, and it stays right however much unrelated speech happens
      in between.
    """
    if _config is None:
        return None
    if obj is None:
        return _current_language

    line = _container_line(obj)
    if line is None:
        return _config.default_language
    from .language_detector import has_content
    if not has_content(line):
        # A text object with nothing to go on: a one-word entry, an empty
        # field. Still furniture as far as language goes.
        return _config.default_language
    return _language_of_line(line) or _current_language


def _save_pre_flash_state() -> None:
    """Snapshot the focus line's braille tables before entering a flash.

    Saves _focus_line_* rather than _current_* because speech for the
    flash message runs before us and has already perturbed _current_*
    to the flash's language. _focus_line_* is only updated by
    _patched_update_braille, so it still reflects the focus line.
    """
    global _in_flash, _pre_flash_focus_contraction, _pre_flash_focus_brltty
    # Only save once per flash session — matches Orca's own _init_flash
    # semantics where a back-to-back display_message doesn't re-save.
    if _in_flash:
        return
    _in_flash = True
    _pre_flash_focus_contraction = _focus_line_contraction_table
    _pre_flash_focus_brltty = _focus_line_brltty_text_table


def _restore_pre_flash_state() -> None:
    """Restore the focus line's braille tables — but only if nothing
    legitimate happened during the flash that would make the restore
    incorrect.

    Two situations leave tables in a state we mustn't undo:

      1. Speech during the flash switched tables to a different
         language (e.g. user navigated into German content while
         a flash was still active; ``_patched_speak`` updated the
         tables for the German speech). In this case tables no
         longer match ``_flash_default_*``.

      2. ``_patched_update_braille`` ran for a new line during the
         flash. ``_focus_line_*`` now differs from the snapshot we
         saved at flash entry.

    Either condition means the post-flash content is on a different
    line/language than where the flash started. Don't restore — the
    current state is correct.
    """
    global _in_flash, _pre_flash_focus_contraction, _pre_flash_focus_brltty
    global _flash_default_contraction, _flash_default_brltty
    if not _in_flash:
        return
    tables_still_flash_default = (
        _current_contraction_table == _flash_default_contraction
        and _current_brltty_text_table == _flash_default_brltty
    )
    focus_line_unchanged = (
        _focus_line_contraction_table == _pre_flash_focus_contraction
        and _focus_line_brltty_text_table == _pre_flash_focus_brltty
    )
    if tables_still_flash_default and focus_line_unchanged:
        if _pre_flash_focus_contraction is not None:
            _set_contraction_table(_pre_flash_focus_contraction)
        if _pre_flash_focus_brltty is not None:
            _set_brltty_text_table(_pre_flash_focus_brltty)
    _in_flash = False
    _pre_flash_focus_contraction = None
    _pre_flash_focus_brltty = None
    _flash_default_contraction = None
    _flash_default_brltty = None


def _switch_braille_tables(lang_settings):
    """Switch contraction table (Orca/liblouis) and text table (BrlTTY)."""
    contraction_table = lang_settings.get("contraction_table", "")
    if contraction_table:
        _set_contraction_table(contraction_table)


def _set_contraction_table(table_path):
    """Set the contraction table in Orca and BrlTTY text table.

    Orca handles contraction via liblouis (settings.brailleContractionTable).
    BrlTTY's TEXT table (not contraction table) must also change so the
    character-to-dot mapping matches the language.
    """
    global _current_contraction_table

    if table_path == _current_contraction_table:
        return

    _debug(f"_set_contraction_table: {_current_contraction_table} -> {table_path}")

    if not table_path:
        _current_contraction_table = table_path
        return

    # Orca (liblouis) contraction table. Cache the new value only on
    # success — otherwise a transient liblouis error would leave the
    # cache claiming we're set when we aren't, suppressing future
    # same-value calls.
    try:
        from orca import braille
        braille.set_contraction_table(table_path)
        _current_contraction_table = table_path
        _debug(f"_set_contraction_table: orca done")
    except Exception as e:
        _debug(f"_set_contraction_table: orca ERROR {e}")
        return

    # Also switch BrlTTY text table to match. Skip for braille-only tables
    # (IPA, unicode-braille) — those don't correspond to a spoken language,
    # and BRLTTY already renders Braille Pattern characters by their dots
    # regardless of which text table is active.
    import os
    table_name = os.path.splitext(os.path.basename(table_path))[0]
    if "IPA" in table_name or table_name.startswith("unicode-braille"):
        return
    lang_code = table_name.split("-")[0]
    _set_brltty_text_table(lang_code)


def _set_brltty_text_table(lang_code):
    """Set BrlTTY's computer braille (text) table to match the language."""
    global _brltty_conn, _brltty_failed, _current_brltty_text_table

    if lang_code == _current_brltty_text_table:
        return

    if _brltty_failed:
        return

    try:
        import brlapi

        if _brltty_conn is None:
            try:
                _brltty_conn = brlapi.Connection()
            except Exception:
                _brltty_conn = None
                _brltty_failed = True
                return

        _debug(f"_set_brltty_text_table: {_current_brltty_text_table} -> {lang_code}")
        _brltty_conn.setParameter(
            brlapi.PARAM_COMPUTER_BRAILLE_TABLE,
            0,
            brlapi.PARAMF_GLOBAL,
            lang_code,
        )
        _current_brltty_text_table = lang_code
        _debug(f"_set_brltty_text_table: done")
    except ImportError:
        _brltty_failed = True
    except Exception as e:
        _debug(f"_set_brltty_text_table: ERROR {e}")
        _brltty_conn = None


# Orca's stand-in for "whatever the synthesiser defaults to". It is not a
# voice Speech Dispatcher would recognise, so it must never be sent as one.
_PLACEHOLDER_VOICE_NAMES = frozenset({"", "default default voice"})

# lang -> family dict. Cleared whenever the configuration is rebuilt.
_fallback_families = {}


def _fallback_voice_family(lang_code):
    """A concrete synthesis voice for a language, as a floor under voice sets.

    Naming a voice here is not a duplication of Orca's voice sets -- it is
    what makes them safe to rely on. Speech Dispatcher's synthesis voice is
    connection state: ``_set_family`` sends ``set_synthesis_voice`` only
    when the family carries a name, and never clears it. So an utterance
    that names no voice is spoken by whatever voice the last one selected.
    Send German, then English with the language alone, and the English is
    read by the German voice -- ``set_language`` cannot rescue it, because a
    single-language embedded voice ignores it.

    Orca cannot close this itself: ``apply_voice_set`` has nothing to add
    for a language with no voice set, and it deliberately never maps a
    language onto the global set. So Polyglot supplies a name for every
    language it switches to, and the user's voice set overrides it whenever
    there is one -- ``apply_voice_overrides`` merges the set's family over
    ours, so configuring a voice in Orca still wins.
    """
    cached = _fallback_families.get(lang_code)
    if cached is not None:
        return cached

    from orca.speechserver import VoiceFamily
    from .available_voices import voices_for_language

    family = {VoiceFamily.LANG: lang_code}
    for name, full_lang, _variant in voices_for_language(lang_code):
        if name.lower() in _PLACEHOLDER_VOICE_NAMES:
            continue
        family[VoiceFamily.NAME] = name
        # Dialect comes from the same voice, never from another language:
        # apply_voice_overrides only drops a stale dialect when the set
        # changes the language, so a leaked "GB" would survive onto German.
        dialect = ""
        if "-" in full_lang:
            dialect = full_lang.split("-", 1)[1]
        elif "_" in full_lang:
            dialect = full_lang.split("_", 1)[1]
        if dialect:
            family[VoiceFamily.DIALECT] = dialect
        break
    else:
        log.warning(
            f"Polyglot: no Speech Dispatcher voice found for {lang_code}; "
            "it will be spoken by whichever voice is already active"
        )

    _fallback_families[lang_code] = family
    return family


def _boundary_marker_wanted() -> bool:
    """Whether to mark a language boundary with a sentence break.

    Polyglot used to carry its own setting for this, a pause in seconds
    that was implemented as a sleep on Orca's main loop. The duration was
    never the point and the sleep was indefensible, so the question is now
    answered by Orca's own "insert pauses between utterances" preference --
    which is what it was always asking -- and skipped at punctuation level
    "all" so the full stop is not read aloud, exactly as Orca skips its own
    pauses there.
    """
    try:
        from orca import speech_manager
        manager = speech_manager.get_manager()
        if manager.get_punctuation_level() == "all":
            return False
        return manager.get_insert_pauses_between_utterances()
    except Exception:  # pylint: disable=broad-exception-caught
        return True


def _end_with_boundary(text: str) -> str:
    """End a segment with a sentence break, so the voice change lands cleanly.

    Mirrors Orca's own pause handling, which appends "." to the text it is
    about to flush. Skipped when the segment already ends in punctuation
    that does the job.
    """
    stripped = text.rstrip()
    if not stripped or stripped[-1] in ".,;:!?\u2026":
        return text
    return stripped + "."




def _get_lang_acss(lang_code):
    """Build the ACSS for a language, or None if we do not handle it.

    Carries the language and a concrete voice for it. Everything else --
    rate, pitch, inflection, volume, and the voice itself where the user
    has configured one -- is filled in downstream by Orca's
    ``apply_voice_set``, inside ``speech_presenter._speak_single``.

    A fresh dict each time, because Orca's _resolve_acss() mutates the ACSS
    in place, replacing the family dict with a VoiceFamily object.
    """
    if lang_code not in _configured_languages:
        return None
    from orca.acss import ACSS
    return ACSS({ACSS.FAMILY: dict(_fallback_voice_family(lang_code))})


def _apply_patches():
    """Apply monkey-patches to Orca's speech presenter singleton.

    Orca 51 split the old `orca.speech` module into `speech_manager` (state)
    and `speech_presenter` (public speaking API). Instead of module-level
    function replacement, we now replace bound methods on the
    `speech_presenter.get_presenter()` singleton — same net effect."""
    try:
        from orca import speech_presenter
    except ImportError as e:
        log.error(f"Polyglot: cannot import orca.speech_presenter: {e}")
        return

    _presenter = speech_presenter.get_presenter()

    # Patch presenter._speak — detect language and switch voice before speaking
    _original_speak = _presenter._speak

    def _patched_speak(content, acss=None, obj=None):
        # Language detection and voice switching. _patched_speak has no
        # markup signal of its own; the upstream voice() patch already
        # applied the markup language (if any) to the ACSS. Here we run
        # our own text-based detection only when the mode allows it.
        #
        # Orca 51 added `obj` as a third parameter to SpeechPresenter._speak;
        # we accept and forward it. `text` renamed to `content` to match
        # master's signature.
        text = content
        try:
            if (_config.enabled and _detector and text
                    and isinstance(text, str) and not _is_app_ignored()
                    and _config.detection_mode != "off"):
                mode = _config.detection_mode
                # In non-mixed mode, if voice() already produced an
                # ACSS with a usable language (set from obj-locale at
                # the line/paragraph level), trust it. Skips re-
                # detecting per utterance, which would otherwise flip
                # voice mid-line on a German word in an English
                # paragraph or a low word-threshold statistical hit.
                # Mixed mode keeps per-utterance detection.
                trusted_lang = None
                if not _config.enable_mixed_language:
                    candidate = _acss_lang(acss)
                    if candidate and candidate in _configured_languages:
                        trusted_lang = candidate
                if trusted_lang:
                    _debug(f"_speak: trust acss lang={trusted_lang} text={text[:40]!r}")
                    _switch_language(trusted_lang, also_braille=False)
                elif mode == "markup_only":
                    # Strict rule: explicit signal → that language;
                    # otherwise default. The signal is either (a) the
                    # ACSS family.lang voice() resolved upstream, or
                    # (b) a non-Latin script in the text itself.
                    # Only overwrite the caller's acss when there is no
                    # acss to begin with — same policy as
                    # _patched_speak_character. Preserves any
                    # uppercase/hyperlink overrides voice() merged in.
                    explicit = _acss_lang(acss)
                    if explicit not in _configured_languages:
                        explicit = None
                    if not explicit:
                        explicit = _detector.detect(
                            text, statistical=False, fallback_to_current=False)
                    if not explicit:
                        explicit = _config.default_language
                    _debug(f"_speak: text={text[:40]!r} explicit={explicit}")
                    _switch_language(explicit, also_braille=False)
                    if acss is None:
                        lang_acss = _get_lang_acss(explicit)
                        if lang_acss:
                            acss = lang_acss
                else:
                    statistical = mode in ("markup_text", "always")
                    detected = _detector.detect(text, statistical=statistical)
                    _debug(f"_speak: text={text[:40]!r} detected={detected}")
                    if detected:
                        _switch_language(detected, also_braille=False)
                        lang_acss = _get_lang_acss(detected)
                        if lang_acss:
                            acss = lang_acss
        except Exception as e:
            _debug(f"_speak lang: ERROR {e}")

        # Mixed-language splitting — speech only, braille ignores this.
        # Only one braille table can be active at a time, so braille stays
        # on the whole-line language detected by update_braille. Mixed
        # splitting is Lingua-driven, so it only runs in modes that allow
        # statistical detection.
        try:
            if (_config.enabled and _config.enable_mixed_language and _detector
                    and text and isinstance(text, str) and not _is_app_ignored()
                    and _config.detection_mode in ("markup_text", "always")):
                segments = _detector.detect_mixed(text)
                if segments:
                    _debug(f"_speak mixed: {len(segments)} segments")
                    pending = []
                    for segment_text, lang_code in segments:
                        # Get the voice for this segment without switching
                        # braille tables — braille handles its own switching.
                        seg_acss = _get_lang_acss(lang_code) or acss
                        seg_text = segment_text
                        # Apply per-segment transformations
                        if _config.speak_emojis:
                            seg_text = _expand_emojis(seg_text, lang_code)
                        if _config.speak_emoticons:
                            seg_text = _expand_emoticons(seg_text)
                        # Mark a language boundary the way Orca marks a
                        # pause: end the previous segment with a full stop
                        # and let the synthesiser's own sentence prosody
                        # provide the gap. This used to be time.sleep() on
                        # Orca's main loop, which froze keyboard, AT-SPI
                        # and speech for the duration -- several times over
                        # on a line that alternated. The separate speak
                        # calls already produce an audible break; this just
                        # makes it a little more definite.
                        pending.append((seg_text, seg_acss, lang_code))

                    # Speak with a one-segment delay, so a segment can be
                    # given a sentence ending once we know the next one is
                    # in a different language. Orca marks its own pauses
                    # the same way -- appending to the text already queued,
                    # so the break is spoken in that segment's voice rather
                    # than opening the next one.
                    mark = _boundary_marker_wanted()
                    for index, (seg_text, seg_acss, lang_code) in enumerate(pending):
                        if mark and index + 1 < len(pending):
                            if pending[index + 1][2] != lang_code:
                                seg_text = _end_with_boundary(seg_text)
                        _original_speak(seg_text, seg_acss, obj)
                    return
        except Exception as e:
            _debug(f"_speak mixed: ERROR {e}")

        # Emoji expansion (independent of language switching)
        try:
            if _config.speak_emojis and text and isinstance(text, str):
                text = _expand_emojis(text, _current_language or _config.default_language)
        except Exception as e:
            _debug(f"_speak emoji: ERROR {e}")

        # Emoticon expansion
        try:
            if _config.speak_emoticons and text and isinstance(text, str):
                text = _expand_emoticons(text)
        except Exception as e:
            _debug(f"_speak emoticon: ERROR {e}")

        try:
            return _original_speak(text, acss, obj)
        except Exception as e:
            _debug(f"_speak ORIGINAL CRASHED: {type(e).__name__}: {e}")
            import traceback
            _debug(traceback.format_exc())

    _patch(_presenter, "_speak", _patched_speak)

    # Patch presenter.speak_message (public API) — expand emojis in list content.
    # This catches text that arrives as lists from speech generators, which is
    # the path used by line reading in apps like LibreOffice. Note: Orca 51
    # renamed the old speech.speak → speak_message and changed the second arg
    # from acss to voice_type. Polyglot uses this only for emoji expansion,
    # not voice switching, so we just forward voice_type unchanged.
    _original_public_speak = _presenter.speak_message

    def _patched_public_speak(text, voice_type=None):
        content = text
        try:
            if _config.speak_emojis and _emoji_available and isinstance(content, list):
                lang = _current_language or _config.default_language
                for i, element in enumerate(content):
                    if isinstance(element, str) and element:
                        content[i] = _expand_emojis(element, lang)
            elif _config.speak_emojis and _emoji_available and isinstance(content, str):
                lang = _current_language or _config.default_language
                content = _expand_emojis(content, lang)
        except Exception as e:
            _debug(f"speak emoji: ERROR {e}")
        if voice_type is None:
            return _original_public_speak(content)
        return _original_public_speak(content, voice_type)

    _patch(_presenter, "speak_message", _patched_public_speak)

    # Patch presenter.speak_character — use script detection for non-Latin chars.
    # Orca 51 changed the second arg from acss to voice_from (a voice-name
    # string) and added obj + language keyword args. Polyglot's original code
    # inspected acss for a language tag; in the new API, `language` is passed
    # directly, so we prefer it and fall back to script detection as before.
    # We do not construct a voice_from ourselves — polyglot's language switch
    # is handled by _switch_language() below, which updates the ACSS cache;
    # voice selection then flows through _speak (which we also patched).
    _original_speak_character = _presenter.speak_character

    def _patched_speak_character(character, voice_from="", cap_style=None, obj=None, language="", dialect=""):
        # Language resolution for character navigation. Same strict rule
        # as _patched_speak in markup-only mode: explicit signal → that
        # language, otherwise default. The signal in Orca 51 is the
        # `language` param (which upstream resolved from markup or obj-
        # locale) or a non-Latin script in the character itself.
        # Punctuation and plain Latin chars carry no signal — they go to
        # default voice.
        try:
            if (_config.enabled and _detector and character
                    and isinstance(character, str) and not _is_app_ignored()
                    and _config.detection_mode != "off"):
                mode = _config.detection_mode
                # Chain, in order of how much the signal is worth:
                #   1. the language Orca resolved from markup, except in
                #      "always" mode, which ignores markup by definition;
                #   2. the character's own Unicode script -- a Cyrillic
                #      letter is Russian even in the middle of a German
                #      line, so this outranks the line;
                #   3. the language of the line the character is in;
                #   4. the current language, then the default.
                explicit = None
                if mode != "always":
                    # Orca may hand us "en-GB" or "de_DE"; collapse to "de".
                    hinted = _normalize_lang_code(language)
                    if hinted in _configured_languages:
                        explicit = hinted
                if not explicit:
                    explicit = _detector.detect_character(
                        character, fallback_to_current=False)
                if not explicit:
                    explicit = _context_language(obj, character)
                if not explicit:
                    explicit = _current_language or _config.default_language
                _debug(f"speak_char: char={character!r} lang={explicit}")
                if explicit:
                    _switch_language(explicit, also_braille=False)
        except Exception as e:
            _debug(f"speak_char lang: ERROR {e}")

        # Emoji expansion for single characters (independent). Routing via
        # _speak (the internal method) speaks the whole emoji name as a
        # phrase — using speak_character here would treat each letter
        # individually, which is not what we want.
        try:
            if _config.speak_emojis and character and isinstance(character, str):
                emoji_name = _expand_emoji_char(character, _current_language or _config.default_language)
                if emoji_name:
                    _debug(f"speak_char: emoji -> {emoji_name!r}")
                    return _original_speak(
                        emoji_name, _get_lang_acss(_current_language), obj)
        except Exception as e:
            _debug(f"speak_char emoji: ERROR {e}")

        # Unpronounceable Unicode characters (box drawings, arrows, etc.)
        try:
            verbosity = _config.unicode_verbosity
            if verbosity != "off" and character and isinstance(character, str):
                char_name = _get_char_spoken_name(character, verbosity)
                if char_name == "":
                    # Invisible formatting char in brief mode — skip silently
                    return
                if char_name:
                    _debug(f"speak_char: unicode -> {char_name!r}")
                    # Named characters are spoken as words, so they need the
                    # language too; acss=None would get the global voice.
                    return _original_speak(
                        char_name, _get_lang_acss(_current_language), obj)
        except Exception as e:
            _debug(f"speak_char unicode: ERROR {e}")

        try:
            return _original_speak_character(
                character, voice_from=voice_from, cap_style=cap_style,
                obj=obj, language=language, dialect=dialect,
            )
        except Exception as e:
            _debug(f"speak_char ORIGINAL CRASHED: {type(e).__name__}: {e}")
            import traceback
            _debug(traceback.format_exc())

    _patch(_presenter, "speak_character", _patched_speak_character)


    # Patch presenter.say_all — expand emojis in the utterance iterator.
    # say_all bypasses _speak entirely, going directly to the speech server.
    # Signature unchanged in Orca 51.
    _original_say_all = _presenter.say_all

    def _patched_say_all(utterance_iterator, progress_callback):
        if _config and _config.speak_emojis and _emoji_available:
            def _emoji_iterator(iterator):
                for context, acss in iterator:
                    try:
                        lang = _current_language or _config.default_language
                        context.utterance = _expand_emojis(context.utterance, lang)
                    except Exception:
                        pass
                    yield context, acss
            utterance_iterator = _emoji_iterator(utterance_iterator)
        try:
            return _original_say_all(utterance_iterator, progress_callback)
        except Exception as e:
            _debug(f"say_all CRASHED: {type(e).__name__}: {e}")

    _patch(_presenter, "say_all", _patched_say_all)

    # Patch speech_generator.SpeechGenerator.voice to use language info
    try:
        from orca import speech_generator as sg
        _original_voice = sg.SpeechGenerator.voice

        def _patched_voice(self, key=None, **args):
            try:
                mode = _config.detection_mode if _config else "markup_text"
                if (_config.enabled and _detector and not _is_app_ignored()
                        and mode != "off"):
                    # "always" mode forces our own detection — ignore the
                    # markup language Orca passed in (some sources of
                    # markup are unreliable). All other modes prefer the
                    # markup hint when present. Normalize whatever we got
                    # so "de_DE", "de-DE", "DE" all collapse to "de".
                    raw_lang = args.get("language")
                    # "always" mode ignores all markup. In non-mixed
                    # mode, we also ignore range-specific markup
                    # (args.language comes from generate_line splitting
                    # by per-character language attributes) so the
                    # whole line reads in one language — the line's
                    # dominant one, determined by obj-locale just
                    # below. Mixed mode is the only place per-segment
                    # markup wins.
                    if mode == "always" or not _config.enable_mixed_language:
                        language = None
                    else:
                        language = _normalize_lang_code(raw_lang)

                    # Fall back to the object's reported locale. Mirrors
                    # Orca's _resolve_language_and_dialect. Required for
                    # paragraph/phrase reads (Ctrl+Up/Down): generate_phrase
                    # calls voice() with obj+string but no language arg, so
                    # without this we'd never see the markup.
                    if not language and mode != "always":
                        obj = args.get("obj")
                        if obj is not None:
                            try:
                                from orca.ax_object import AXObject
                                language = _normalize_lang_code(
                                    AXObject.get_locale(obj))
                            except Exception:
                                pass

                    string = args.get("string", "")
                    if not language and isinstance(string, str) and string.strip():
                        if mode == "markup_only":
                            # Tier 1 (script) only — never fall back to
                            # the previous language. If no script signal
                            # either, reset to default. Without the reset,
                            # voice would stick on the last detected
                            # language across context changes.
                            language = _detector.detect(
                                string, statistical=False,
                                fallback_to_current=False)
                            if not language:
                                language = _config.default_language
                        else:
                            statistical = mode in ("markup_text", "always")
                            # Without content, detect() has nothing to
                            # return but the language already in use, which
                            # would mask the context handling just below --
                            # and that context knows more than "whatever
                            # was last spoken". So ask for a plain no.
                            from .language_detector import has_content
                            language = _detector.detect(
                                string, statistical=statistical,
                                fallback_to_current=has_content(string))
                    if not language and isinstance(string, str):
                        # Nothing was detected, which for a single character
                        # is the correct outcome -- it has no content to
                        # detect from -- but the voice still has to be
                        # tagged with a language, or Orca resolves it from
                        # the markup it was given, finds none, and uses the
                        # global voice. That is why spaces and punctuation
                        # on a German line were announced in English: the
                        # name a character is given comes from Speech
                        # Dispatcher's symbol table for whichever language
                        # the voice is set to. So fall back to whatever
                        # context there is, markup first: with nothing to
                        # detect from there is no detection for markup to
                        # be preferred over, so it is consulted even in
                        # "always" mode. That mode means "do not trust
                        # markup over our own reading of the text", not
                        # "ignore it when we have no reading at all", and
                        # it is what gets a two-letter button in an English
                        # dialog announced in English.
                        language = _context_language(args.get("obj"), string)
                    if language:
                        _switch_language(language, also_braille=False)
                        lang_acss = _get_lang_acss(language)
                        if lang_acss:
                            from orca.acss import ACSS
                            from orca import speech_manager as sm
                            # Determine the effective voice type to overlay.
                            # For the default key, Orca checks if the string is
                            # uppercase to apply the uppercase voice override;
                            # replicate that here so the pitch change is preserved.
                            voice_key = key
                            if key in (None, "default"):
                                if (isinstance(string, str)
                                        and string.isupper()
                                        and string.strip().isalpha()):
                                    voice_key = "uppercase"
                            if voice_key and voice_key not in (None, "default"):
                                override = sm.get_manager().get_voice_properties(voice_key)
                                if override:
                                    merged = ACSS(dict(lang_acss))
                                    for k, v in override.items():
                                        if k != ACSS.FAMILY:
                                            merged[k] = v
                                    return [merged]
                            return [lang_acss]
            except Exception as e:
                _debug(f"voice pre: ERROR {e}")

            try:
                return _original_voice(self, key, **args)
            except Exception as e:
                _debug(f"voice ORIGINAL CRASHED: {type(e).__name__}: {e}")
                import traceback
                _debug(traceback.format_exc())
                return []

        _patch(sg.SpeechGenerator, "voice", _patched_voice)
    except Exception as e:
        log.warning(f"Polyglot: could not patch speech_generator.voice: {e}")

    # Patch adjust_for_presentation to expand unpronounceable Unicode characters
    # (box drawings, block elements, arrows, etc.) BEFORE the repeat handler runs.
    # This way "80 ─" becomes "80 horizontal line characters" instead of "80 characters".
    try:
        from orca import speech_presenter as sp
        _presenter = sp.get_presenter()
        _original_adjust = _presenter.adjust_for_presentation

        def _patched_adjust(obj, text, start_offset=None):
            # The user's speech dictionary runs first, on the text as it
            # stands. It has to be before the original: Orca's
            # adjust_for_presentation verbalises punctuation by padding every
            # symbol with spaces, which would turn "#5" into " # 5" and stop
            # a pattern like #(\d+) ever matching. Running before the
            # Unicode expansion below is deliberate too, so a rule can match
            # the character itself rather than the name it is about to be
            # given.
            try:
                if text and isinstance(text, str) and not _is_app_ignored():
                    from .speech_dictionary import apply as _apply_dictionary
                    text = _apply_dictionary(text, _current_language)
            except Exception as e:
                _debug(f"adjust_for_presentation dictionary: ERROR {e}")
            try:
                verbosity = _config.unicode_verbosity
                if verbosity != "off" and text and isinstance(text, str):
                    text = _expand_unpronounceable(text, verbosity)
            except Exception as e:
                _debug(f"adjust_for_presentation: ERROR {e}")
            return _original_adjust(obj, text, start_offset)

        _patch(_presenter, "adjust_for_presentation", _patched_adjust)
    except Exception as e:
        log.warning(f"Polyglot: could not patch adjust_for_presentation: {e}")

    # Patch update_braille on the default Script class (NOT the base class,
    # because default.Script overrides update_braille and doesn't call super).
    # This ensures we detect language and switch the contraction table BEFORE
    # braille regions are built (Region.__init__ captures the table).
    try:
        from orca.scripts.default import Script as DefaultScript

        _original_update_braille = DefaultScript.update_braille

        def _patched_update_braille(self, obj, **args):
            _debug(f"update_braille: ENTER")
            _apply_braille_language(obj, args.get("offset"), "update_braille")

            _debug("update_braille: calling original...")
            try:
                result = _original_update_braille(self, obj, **args)
                _debug("update_braille: done")
                return result
            except Exception as e:
                _debug(f"update_braille ORIGINAL CRASHED: {type(e).__name__}: {e}")

        _patch(DefaultScript, "update_braille", _patched_update_braille)

        # update_braille alone is not enough, and this is the whole of the
        # braille-lags-behind-speech bug.
        #
        # Orca only rebuilds the braille line when it has to. On a caret move
        # it first calls _update_braille_caret_position, which tries
        # braille.try_reposition_cursor(obj) -- and if the object whose caret
        # moved is already on the display, that succeeds, calls refresh() and
        # RETURNS, so update_braille is never reached:
        #
        #     if braille.try_reposition_cursor(obj):
        #         return
        #     self.update_braille(obj)
        #
        # In a word processor the body of the document is one accessible, so
        # arrowing from line to line takes that early return every time.
        # Measured in LibreOffice on a Russian document: speech switched to
        # Russian at 09:40:44 and update_braille did not fire until 09:40:54 --
        # ten seconds and many lines later, when the caret finally crossed
        # into a different object. Panning does not help either, for the same
        # reason: panning re-renders the existing line and never rebuilds it.
        # That is exactly "I have to physically move the keyboard cursor to
        # the right area".
        #
        # So hook the method that DOES run on every caret move, before Orca
        # re-renders. The web script's override calls super(), so patching the
        # default class covers it; soffice overrides _on_caret_moved but
        # delegates to super(), which reaches here.
        try:
            _original_caret_braille = DefaultScript._update_braille_caret_position

            def _patched_caret_braille(self, obj):
                # Mirror Orca's own guard: no braille in use, nothing to do.
                try:
                    from orca import braille_presenter
                    if not braille_presenter.get_presenter().use_braille():
                        return _original_caret_braille(self, obj)
                except Exception:  # pylint: disable=broad-exception-caught
                    pass
                # Before the original, so the table is in place whether Orca
                # repositions the cursor and refreshes, or rebuilds the line.
                changed = _apply_braille_language(obj, None, "caret-braille")
                try:
                    return _original_caret_braille(self, obj)
                finally:
                    # Orca may have taken its reposition fast path, which
                    # redraws the line from caches rendered in the old table.
                    # In a finally because once the table has moved the
                    # display is wrong until something redraws it, however
                    # the original turned out.
                    if changed:
                        _redraw_braille_for(obj)

            _patch(DefaultScript, "_update_braille_caret_position",
                   _patched_caret_braille)
            _debug("patched _update_braille_caret_position")
        except Exception as e:
            log.warning(
                f"Polyglot: could not patch _update_braille_caret_position: {e}")

        # Switching windows moves no caret, so neither hook above fires and
        # the display keeps the previous window's table -- sometimes showing
        # the old caret position in it. Focus changes all funnel through
        # FocusManager.set_locus_of_focus (window:activate ends in exactly
        # that call), so hook it and settle the table for whatever is taking
        # focus.
        try:
            from orca import focus_manager

            _original_set_locus = focus_manager.FocusManager.set_locus_of_focus

            def _patched_set_locus(self, event, obj, notify_script=True, force=False):
                # Before the original, not after: obj is handed to us, and
                # _container_line reads the line straight off it rather than
                # asking the focus manager, so nothing has to have settled
                # first. Doing it first also means the table is right before
                # Orca brailles the new focus, instead of a beat behind it.
                #
                # Non-text focus -- a frame, a button -- returns None from
                # _container_line and is left alone, so window furniture
                # cannot drag the table off the content.
                changed = _apply_braille_language(obj, None, "focus-braille")
                try:
                    return _original_set_locus(
                        self, event, obj, notify_script, force)
                finally:
                    # This is the window-switch case, and it is why the
                    # redraw rebuilds for obj rather than refreshing: at this
                    # point the display is still showing the FRAME's line --
                    # the window title -- and Orca will not necessarily
                    # replace it. Measured: 18 seconds between focus landing
                    # on a Russian paragraph and the next update_braille.
                    # In a finally for the same reason as the caret hook.
                    if changed:
                        _redraw_braille_for(obj)

            _patch(focus_manager.FocusManager, "set_locus_of_focus",
                   _patched_set_locus)
            _debug("patched set_locus_of_focus for braille on focus change")
        except Exception as e:
            log.warning(f"Polyglot: could not patch set_locus_of_focus: {e}")
    except Exception as e:
        log.warning(f"Polyglot: could not patch update_braille: {e}")

    # Patch braille flash-message lifecycle so notifications, time
    # announcements, and other non-line content are rendered in the
    # default-language tables, then revert when the flash ends and the
    # focus line is restored. Without this, a German line followed by
    # an English notification flashes in German contraction (or with a
    # German computer-braille text table on BRLTTY) — and after the
    # flash, the line content might also stick to whichever tables the
    # flash ended on.
    try:
        from orca import braille

        _original_display_message = braille.display_message
        _original_flash_callback = braille._flash_callback
        _original_kill_flash = braille.kill_flash

        def _patched_display_message(message, flash_time=0):
            try:
                if _config and _config.enabled:
                    _save_pre_flash_state()
                    _switch_to_default_braille_tables()
            except Exception as e:
                _debug(f"display_message pre: ERROR {e}")
            return _original_display_message(message, flash_time)

        def _patched_flash_callback():
            try:
                # Restore tables BEFORE the original runs, because the
                # original calls refresh() which re-renders the saved
                # line content using whichever tables are currently
                # active.
                if _config and _config.enabled:
                    _restore_pre_flash_state()
            except Exception as e:
                _debug(f"flash_callback pre: ERROR {e}")
            return _original_flash_callback()

        def _patched_kill_flash(restore_saved=True):
            # We always restore (regardless of restore_saved). When the
            # caller is about to render fresh content, that content's
            # update_braille will overwrite our restore — a harmless
            # no-op cache hit since _set_contraction_table short-
            # circuits on same-value calls. When the caller is NOT
            # about to update braille (detection_mode=off, empty text,
            # short-circuit paths), restoring is the right default
            # rather than letting the flash's tables stick.
            try:
                if _config and _config.enabled:
                    _restore_pre_flash_state()
            except Exception as e:
                _debug(f"kill_flash pre: ERROR {e}")
            return _original_kill_flash(restore_saved)

        _patch(braille, "display_message", _patched_display_message)
        _patch(braille, "_flash_callback", _patched_flash_callback)
        _patch(braille, "kill_flash", _patched_kill_flash)
    except Exception as e:
        log.warning(f"Polyglot: could not patch braille flash lifecycle: {e}")


# --- Keybinding registration ---

def uninstall():
    """Remove every monkey-patch and reset module state.

    Called from the Extension's on_disabled / on_shutdown hooks, so that
    disabling Polyglot in Orca's preferences actually stops it and a
    reload does not stack a second set of patches on the first.
    """
    global _installed, _detector, _config, _current_language
    global _current_names_locale, _line_language_cache, _in_flash

    if not _installed:
        return

    _unpatch_all()
    _restore_orca_state()

    _installed = False
    _detector = None
    _config = None
    _current_language = None
    _current_names_locale = None
    _line_language_cache = None
    _in_flash = False
    _fallback_families.clear()
    log.info("Polyglot: uninstalled")


def _restore_orca_state():
    """Undo the things Polyglot changed that are not monkey-patches.

    Removing the patches stops Polyglot acting, but three pieces of state
    it has already written would otherwise survive it: Orca's locale for
    role and symbol names, the liblouis contraction table, and the BRLTTY
    text table. Left behind, disabling Polyglot would leave Orca saying
    "Schaltflache" and rendering German braille with nothing running to
    explain it. The brlapi connection is closed for the same reason -- a
    disabled extension should not be holding one open.
    """
    global _brltty_conn

    if _current_names_locale is not None:
        try:
            from orca import orca_i18n
            # No argument is Orca's own "use the environment's locale":
            # setModuleLocale asks gettext for languages=[None], which
            # raises, and the except branch installs the plain gettext
            # functions. That is the state before we interfered.
            orca_i18n.setLocaleForNames()
        except Exception as error:  # pylint: disable=broad-exception-caught
            log.debug(f"Polyglot: could not restore the names locale: {error}")

    default_lang = getattr(_config, "default_language", None) if _config else None
    if default_lang:
        try:
            _switch_to_default_braille_tables()
        except Exception as error:  # pylint: disable=broad-exception-caught
            log.debug(f"Polyglot: could not restore the braille tables: {error}")

    if _brltty_conn is not None:
        try:
            _brltty_conn.closeConnection()
        except Exception:  # pylint: disable=broad-exception-caught
            pass
        _brltty_conn = None


def open_settings():
    """Command handler for Orca+Shift+L. Opens the hand-written dialog."""
    try:
        from gi.repository import GLib
        GLib.idle_add(_show_settings_ui)
    except Exception as e:
        log.error(f"Polyglot: could not open settings: {e}")
    return True


def _show_settings_ui():
    """Show the settings UI (must be called from GTK main thread)."""
    try:
        from .config_ui import show_settings_dialog
        show_settings_dialog(_config, on_save=reload_config)
    except Exception as e:
        log.error(f"Polyglot: could not show settings dialog: {e}")
        try:
            from orca import speech_presenter
            speech_presenter.get_presenter().speak_message(f"Error opening language switch settings: {e}")
        except Exception:
            pass
    return False


# --- Public API ---

def _schedule_dictionary_warmup():
    """Read the word lists on an idle callback rather than mid-utterance."""
    if _detector is None:
        return
    try:
        from gi.repository import GLib
    except Exception:  # pylint: disable=broad-exception-caught
        return

    def warm():
        try:
            # Returns [] when the tier is not in use, which makes this a
            # no-op rather than something needing its own guard.
            loaded = _detector.dictionary_status()
            if loaded:
                log.info(
                    "Polyglot: word lists warmed -- "
                    + ", ".join(f"{lang} ({count})" for lang, count, _ in loaded)
                )
        except Exception as error:  # pylint: disable=broad-exception-caught
            log.debug(f"Polyglot: word list warm-up skipped: {error}")
        return False

    GLib.idle_add(warm)


def _build_dictionary_detector():
    """Build the word-list tier from config, or return None if it is off.

    Returns None when the user has switched it off or when nothing is
    installed, which leaves the tier out of the chain entirely rather than
    having it decline every question.
    """
    if not getattr(_config, "dictionary_enabled", True):
        return None
    try:
        from .dictionary_detector import DictionaryDetector
        detector = DictionaryDetector(
            languages=_config.enabled_languages,
            min_words=_config.dictionary_min_words,
            min_share=_config.dictionary_min_share,
            max_entries=_config.dictionary_max_words,
        )
    except Exception as error:  # pylint: disable=broad-exception-caught
        log.warning(f"Polyglot: dictionary detection unavailable: {error}")
        return None

    available = detector.available_languages()
    if len(available) < 2:
        # One list cannot be compared against anything, so every unknown
        # word would look like a miss and every hit like a win.
        if available:
            log.info(
                f"Polyglot: only one word list installed ({available[0]}); "
                "the dictionary tier needs at least two. Run "
                "fetch-dictionaries.sh to add more."
            )
        return None
    log.info(f"Polyglot: word lists available for {', '.join(available)}")
    return detector


def reload_config():
    """Reload configuration and reinitialize detector."""
    global _detector, _current_language

    if _config is None:
        return

    _config.load()
    from .available_voices import invalidate as _invalidate_voices
    _invalidate_voices()

    if not _config.enabled:
        _detector = None
        return

    from .language_detector import LanguageDetector
    _detector = LanguageDetector(
        enabled_languages=_config.enabled_languages,
        word_threshold=_config.word_threshold,
        script_to_language=_config.script_to_language,
        default_language=_config.default_language,
        switch_confidence=_config.switch_confidence,
        mixed_max_words=_config.mixed_max_words,
        dictionaries=_build_dictionary_detector(),
        detection_order=_config.detection_order,
    )
    _current_language = _config.default_language
    _detector.current_language = _current_language
    _rebuild_configured_languages()
