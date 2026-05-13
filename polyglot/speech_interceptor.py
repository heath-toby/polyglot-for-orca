"""Polyglot for Orca — core speech pipeline patches.

Monkey-patches Orca's speech and braille systems to provide automatic
language switching, emoji/emoticon expansion, and Unicode announcement.
"""

import logging
import os
import sys

log = logging.getLogger("polyglot")

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
            log_path = os.path.join(
                os.environ.get("XDG_DATA_HOME", os.path.expanduser("~/.local/share")),
                "orca", "polyglot", "debug.log",
            )
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

    result = _re.sub(r":([^:]+):", _replace, demojized)
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
        from . import custom_names as _custom_names_mod
        custom = _custom_names_mod.get_name(char, verbosity)
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
    """
    if not text:
        return text
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
_mapper = None
_config = None
_current_language = None
_lang_acss_cache = {}
_in_detection = False  # reentrancy guard


def _add_venv_to_path():
    """Add the bundled venv's site-packages to sys.path for lingua."""
    venv_site = os.path.join(
        os.path.dirname(__file__), ".venv", "lib"
    )
    if not os.path.isdir(venv_site):
        return
    for entry in os.listdir(venv_site):
        sp = os.path.join(venv_site, entry, "site-packages")
        if os.path.isdir(sp) and sp not in sys.path:
            sys.path.insert(0, sp)
            break


def install():
    """Install the language-switching monkey-patches into Orca's speech system."""
    global _installed, _detector, _mapper, _config, _current_language

    if _installed:
        return

    _add_venv_to_path()
    _init_emoji()

    from . import custom_names as _custom_names_mod
    _custom_names_mod.load()

    from .config import Config
    from .voice_mapper import VoiceMapper
    from .language_detector import LanguageDetector, is_lingua_available

    _config = Config()
    first_run = _config.is_first_run
    _config.load()

    _mapper = VoiceMapper()

    if first_run:
        _config.auto_configure_from_profiles(_mapper)
        _config.save()
        log.info("Polyglot: first run, auto-configured from profiles")
    else:
        # Sync with available voices on every startup — detects removed/changed
        # voices and updates config without overwriting user customisations.
        if _config.sync_from_voices(_mapper):
            _config.save()
            log.info("Polyglot: synced config with available voices")

    # Always register the keybinding so the user can open settings even when
    # the add-on is disabled (otherwise there's no way to re-enable it).
    _register_keybinding_deferred()

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
    )
    _current_language = _config.default_language
    _detector.current_language = _current_language

    _rebuild_acss_cache()
    _installed = True

    lang_count = len(_config.enabled_languages)
    lingua_status = "with Lingua" if is_lingua_available() else "script detection only"
    log.info(
        f"Polyglot: installed ({lang_count} languages, {lingua_status})"
    )

    if first_run:
        try:
            from gi.repository import GLib
            GLib.idle_add(_speak_first_run_notification, lang_count, lingua_status)
        except Exception:
            pass


def _speak_first_run_notification(lang_count, lingua_status):
    """Speak a notification about the auto-configuration (called from GLib idle)."""
    try:
        from orca import speech
        speech.speak(
            f"Polyglot configured with {lang_count} languages, {lingua_status}.",
        )
    except Exception:
        pass
    return False


def _rebuild_acss_cache():
    """Build ACSS dicts for each configured language from language_settings."""
    global _lang_acss_cache
    _lang_acss_cache = {}

    from orca.acss import ACSS

    for lang_code, lang_settings in _config.language_settings.items():
        if lang_code not in _config.enabled_languages:
            continue

        voice_name = lang_settings.get("voice_name", "")
        voice_lang = lang_settings.get("voice_lang", lang_code)
        voice_dialect = lang_settings.get("voice_dialect", "")
        rate = lang_settings.get("rate")
        pitch = lang_settings.get("average_pitch")
        gain = lang_settings.get("gain")

        if not voice_name:
            continue

        family = {
            "name": voice_name,
            "lang": voice_lang,
            "dialect": voice_dialect,
        }

        acss = ACSS({ACSS.FAMILY: family})
        if rate is not None:
            acss[ACSS.RATE] = rate
        if pitch is not None:
            acss[ACSS.AVERAGE_PITCH] = pitch
        if gain is not None:
            acss[ACSS.GAIN] = gain

        _lang_acss_cache[lang_code] = acss
        log.info(f"Polyglot: cached ACSS for {lang_code}: {voice_name} rate={rate} pitch={pitch} gain={gain}")


def _switch_language(lang_code, also_braille: bool = True):
    """Switch voice (and optionally braille tables) for the detected language.

    ``also_braille`` controls whether the contraction + BRLTTY text tables
    are switched as a side effect. ``_patched_update_braille`` is the
    canonical authority for braille — speech-side patches (``_patched_voice``,
    ``_patched_speak``, ``_patched_speak_character``) pass ``False`` so that
    a transient speech-time language switch (e.g. an English notification
    arriving while a German line is focused) doesn't perturb the focus
    line's braille tables. Symbol-name locale is treated as speech-side
    state and switches regardless — it follows the active speech.
    """
    global _current_language, _in_detection

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

    # If the language is already current AND the caller doesn't care
    # about braille, there's nothing to do. But when also_braille=True
    # the braille tables may still be lagging — speech-side calls with
    # also_braille=False set _current_language but skip the table
    # switch, so a follow-up update_braille for the same language
    # needs to fall through to _switch_braille_tables.
    if lang_code == _current_language and not also_braille:
        return

    if lang_code not in _lang_acss_cache:
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
        # Symbol-name locale is speech-side: it follows whichever language
        # is currently being spoken, regardless of braille state.
        _set_orca_names_locale(lang_code)
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
_focus_line_names_locale: str | None = None


def _record_focus_line_state() -> None:
    """Pin the current state as the focus line's state.

    Called from _patched_update_braille after it has driven a language
    switch for the current line. The focus-line snapshot is what flash
    save/restore uses, so it must not be perturbed by speech-time
    language switches.
    """
    global _focus_line_contraction_table, _focus_line_brltty_text_table
    global _focus_line_language, _focus_line_names_locale
    _focus_line_contraction_table = _current_contraction_table
    _focus_line_brltty_text_table = _current_brltty_text_table
    _focus_line_language = _current_language
    _focus_line_names_locale = _current_names_locale


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


def _get_lang_acss(lang_code):
    """Get a COPY of the ACSS for a language, or None.

    Must return a copy because Orca's __resolve_acss() mutates the ACSS
    in place (replacing the family dict with a VoiceFamily object).
    If we returned the cached original, subsequent uses would have a
    corrupted family dict.
    """
    cached = _lang_acss_cache.get(lang_code)
    if cached is None:
        return None
    from orca.acss import ACSS
    return ACSS(cached)


def _apply_patches():
    """Apply monkey-patches to Orca's speech module."""
    try:
        from orca import speech
    except ImportError as e:
        log.error(f"Polyglot: cannot import orca.speech: {e}")
        return

    # Patch speech._speak — detect language and switch voice before speaking
    _original_speak = speech._speak

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

    def _patched_speak(text, acss=None):
        # Language detection and voice switching. _patched_speak has no
        # markup signal of its own; the upstream voice() patch already
        # applied the markup language (if any) to the ACSS. Here we run
        # our own text-based detection only when the mode allows it.
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
                    if candidate and candidate in _lang_acss_cache:
                        trusted_lang = candidate
                if trusted_lang:
                    _debug(f"_speak: trust acss lang={trusted_lang} text={text[:40]!r}")
                    _switch_language(trusted_lang)
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
                    if explicit not in _lang_acss_cache:
                        explicit = None
                    if not explicit:
                        explicit = _detector.detect(
                            text, statistical=False, fallback_to_current=False)
                    if not explicit:
                        explicit = _config.default_language
                    _debug(f"_speak: text={text[:40]!r} explicit={explicit}")
                    _switch_language(explicit)
                    if acss is None:
                        lang_acss = _get_lang_acss(explicit)
                        if lang_acss:
                            acss = lang_acss
                else:
                    statistical = mode in ("markup_text", "always")
                    detected = _detector.detect(text, statistical=statistical)
                    _debug(f"_speak: text={text[:40]!r} detected={detected}")
                    if detected:
                        _switch_language(detected)
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
                    prev_lang = None
                    pause = _config.language_switch_pause
                    for segment_text, lang_code in segments:
                        # Insert pause when switching between languages
                        if prev_lang is not None and lang_code != prev_lang and pause > 0:
                            import time
                            time.sleep(pause)
                        # Get the voice for this segment without switching
                        # braille tables — braille handles its own switching.
                        seg_acss = _get_lang_acss(lang_code) or acss
                        seg_text = segment_text
                        # Apply per-segment transformations
                        if _config.speak_emojis:
                            seg_text = _expand_emojis(seg_text, lang_code)
                        if _config.speak_emoticons:
                            seg_text = _expand_emoticons(seg_text)
                        _original_speak(seg_text, seg_acss)
                        prev_lang = lang_code
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
            return _original_speak(text, acss)
        except Exception as e:
            _debug(f"_speak ORIGINAL CRASHED: {type(e).__name__}: {e}")
            import traceback
            _debug(traceback.format_exc())

    speech._speak = _patched_speak

    # Patch speech.speak (public API) — expand emojis in list content
    # This catches text that arrives as lists from speech generators,
    # which is the path used by line reading in apps like LibreOffice.
    _original_public_speak = speech.speak

    def _patched_public_speak(content, acss=None):
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
        return _original_public_speak(content, acss)

    speech.speak = _patched_public_speak

    # Patch speech.speak_character — use script detection for non-Latin chars
    _original_speak_character = speech.speak_character

    def _patched_speak_character(character, acss=None, cap_style=None):
        # Language resolution for character navigation. Same strict rule
        # as _patched_speak in markup-only mode: explicit signal → that
        # language, otherwise default. The signal is acss.family.lang
        # (which voice() resolved upstream from markup or obj-locale) or
        # a non-Latin script in the character itself. Punctuation and
        # plain Latin chars carry no signal — they go to default voice.
        try:
            if (_config.enabled and _detector and character
                    and isinstance(character, str) and not _is_app_ignored()
                    and _config.detection_mode != "off"):
                mode = _config.detection_mode
                if mode == "markup_only":
                    explicit = _acss_lang(acss)
                    if explicit not in _lang_acss_cache:
                        explicit = None
                    if not explicit:
                        explicit = _detector.detect_character(
                            character, fallback_to_current=False)
                    if not explicit:
                        explicit = _config.default_language
                    # Chain: voice() markup → Unicode-script tier
                    # (with current-language fallback, since per-char
                    # detection can't run Lingua and Latin chars have
                    # no script signal — falling back to current is
                    # the only way to inherit line context) → default.
                    if not explicit:
                        explicit = _detector.detect_character(
                            character, fallback_to_current=True)
                    if not explicit:
                        explicit = _config.default_language
                    _debug(f"speak_char: char={character!r} explicit={explicit}")
                    _switch_language(explicit)
                    if acss is None:
                        lang_acss = _get_lang_acss(explicit)
                        if lang_acss:
                            acss = lang_acss
                else:
                    detected = _detector.detect_character(character)
                    _debug(f"speak_char: char={character!r} detected={detected}")
                    if detected:
                        _switch_language(detected)
                        if acss is None:
                            lang_acss = _get_lang_acss(detected)
                            if lang_acss:
                                acss = lang_acss
        except Exception as e:
            _debug(f"speak_char lang: ERROR {e}")

        # Emoji expansion for single characters (independent)
        try:
            if _config.speak_emojis and character and isinstance(character, str):
                emoji_name = _expand_emoji_char(character, _current_language or _config.default_language)
                if emoji_name:
                    _debug(f"speak_char: emoji -> {emoji_name!r}")
                    return _original_speak(emoji_name, acss)
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
                    return _original_speak(char_name, acss)
        except Exception as e:
            _debug(f"speak_char unicode: ERROR {e}")

        try:
            return _original_speak_character(character, acss, cap_style=cap_style)
        except Exception as e:
            _debug(f"speak_char ORIGINAL CRASHED: {type(e).__name__}: {e}")
            import traceback
            _debug(traceback.format_exc())

    speech.speak_character = _patched_speak_character

    # Patch speech.say_all — expand emojis in the utterance iterator
    # say_all bypasses _speak entirely, going directly to the speech server
    _original_say_all = speech.say_all

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

    speech.say_all = _patched_say_all

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
                            language = _detector.detect(
                                string, statistical=statistical)
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

        sg.SpeechGenerator.voice = _patched_voice
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
            try:
                verbosity = _config.unicode_verbosity
                if verbosity != "off" and text and isinstance(text, str):
                    text = _expand_unpronounceable(text, verbosity)
            except Exception as e:
                _debug(f"adjust_for_presentation: ERROR {e}")
            return _original_adjust(obj, text, start_offset)

        _presenter.adjust_for_presentation = _patched_adjust
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
            try:
                mode = _config.detection_mode if _config else "markup_text"
                if (_config.enabled and _detector and obj is not None
                        and not _is_app_ignored() and mode != "off"):
                    from orca.ax_text import AXText
                    offset = args.get("offset")
                    if offset is None:
                        offset = AXText.get_caret_offset(obj)
                    line = AXText.get_line_at_offset(obj, offset)
                    if line and line[0]:
                        text = line[0]
                        if isinstance(text, str) and text.strip():
                            detected = None
                            # Prefer obj-locale (markup signal) in non-always modes
                            if mode != "always":
                                try:
                                    from orca.ax_object import AXObject
                                    detected = _normalize_lang_code(
                                        AXObject.get_locale(obj))
                                except Exception:
                                    pass
                            if not detected:
                                if mode == "markup_only":
                                    detected = _detector.detect(
                                        text, statistical=False,
                                        fallback_to_current=False)
                                    if not detected:
                                        detected = _config.default_language
                                else:
                                    statistical = mode in ("markup_text", "always")
                                    detected = _detector.detect(
                                        text, statistical=statistical)
                            if detected:
                                _debug(f"update_braille: detected={detected}")
                                _switch_language(detected)
                                # Pin this as the focus-line state so the
                                # flash hook has a clean snapshot
                                # regardless of any speech-time mutations.
                                _record_focus_line_state()
            except Exception as e:
                _debug(f"update_braille pre: ERROR {type(e).__name__}: {e}")

            _debug("update_braille: calling original...")
            try:
                result = _original_update_braille(self, obj, **args)
                _debug("update_braille: done")
                return result
            except Exception as e:
                _debug(f"update_braille ORIGINAL CRASHED: {type(e).__name__}: {e}")

        DefaultScript.update_braille = _patched_update_braille
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

        braille.display_message = _patched_display_message
        braille._flash_callback = _patched_flash_callback
        braille.kill_flash = _patched_kill_flash
    except Exception as e:
        log.warning(f"Polyglot: could not patch braille flash lifecycle: {e}")


# --- Keybinding registration ---

def _register_keybinding_deferred():
    """Schedule keybinding registration after Orca is fully initialized."""
    try:
        from gi.repository import GLib
        GLib.idle_add(_register_keybinding)
    except Exception as e:
        log.warning(f"Polyglot: could not schedule keybinding: {e}")


_keybinding_registered = False

def _register_keybinding():
    """Register the Orca+Shift+L keybinding for the settings dialog."""
    global _keybinding_registered
    if _keybinding_registered:
        return False

    try:
        from orca import keybindings
        from orca import command_manager
        from orca import orca_modifier_manager

        kb = keybindings.KeyBinding("l", keybindings.ORCA_SHIFT_MODIFIER_MASK)
        cmd = command_manager.KeyboardCommand(
            "polyglotSettingsHandler",
            _open_settings_dialog,
            "Polyglot",
            "Opens the Polyglot settings dialog",
            desktop_keybinding=kb,
            laptop_keybinding=kb,
        )

        mgr = command_manager.get_manager()
        mgr.add_command(cmd)

        # Add key grabs so the binding is active immediately
        active_kb = cmd.get_keybinding()
        if active_kb:
            orca_modifiers = orca_modifier_manager.get_manager().get_orca_modifier_keys()
            active_kb.add_grabs(orca_modifiers)

        _keybinding_registered = True
        log.info("Polyglot: keybinding registered via CommandManager")

    except Exception as e:
        log.warning(f"Polyglot: could not register keybinding: {e}")

    return False


def _open_settings_dialog(script, event=None):
    """Handler for the Orca+Shift+L keybinding."""
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
        show_settings_dialog(_config, _mapper, on_save=reload_config)
    except Exception as e:
        log.error(f"Polyglot: could not show settings dialog: {e}")
        try:
            from orca import speech
            speech.speak(f"Error opening language switch settings: {e}")
        except Exception:
            pass
    return False


# --- Public API ---

def get_config():
    return _config

def get_detector():
    return _detector

def get_mapper():
    return _mapper

def reload_config():
    """Reload configuration and reinitialize detector."""
    global _detector, _current_language

    if _config is None:
        return

    _config.load()
    _mapper.reload()

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
    )
    _current_language = _config.default_language
    _detector.current_language = _current_language
    _rebuild_acss_cache()
