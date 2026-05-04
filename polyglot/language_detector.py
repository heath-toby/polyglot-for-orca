"""Two-tier language detection: Unicode script (fast) + Lingua (slow for Latin)."""

import unicodedata
from collections import Counter
from functools import lru_cache

# Sentinel "language" codes — not real spoken languages, just trigger
# braille-table switches. They live in script_to_language but never in
# enabled_languages, so detect()/detect_character() must allow them
# through without the enabled-languages check.
_BRAILLE_ONLY_SENTINELS = ("ipa", "unicode_braille")

_LINGUA_AVAILABLE = False
try:
    from lingua import Language, LanguageDetectorBuilder
    _LINGUA_AVAILABLE = True
except ImportError:
    pass

# Map Unicode script keywords (from unicodedata.name()) to script identifiers
_CHAR_NAME_TO_SCRIPT = {
    "CYRILLIC": "CYRILLIC",
    "ARABIC": "ARABIC",
    "HEBREW": "HEBREW",
    "GREEK": "GREEK",
    "DEVANAGARI": "DEVANAGARI",
    "BENGALI": "BENGALI",
    "GURMUKHI": "GURMUKHI",
    "GUJARATI": "GUJARATI",
    "TAMIL": "TAMIL",
    "TELUGU": "TELUGU",
    "KANNADA": "KANNADA",
    "MALAYALAM": "MALAYALAM",
    "THAI": "THAI",
    "LAO": "LAO",
    "TIBETAN": "TIBETAN",
    "MYANMAR": "MYANMAR",
    "GEORGIAN": "GEORGIAN",
    "HANGUL": "HANGUL",
    "ETHIOPIC": "ETHIOPIC",
    "KHMER": "KHMER",
    "SINHALA": "SINHALA",
    "ARMENIAN": "ARMENIAN",
    "HIRAGANA": "CJK",
    "KATAKANA": "CJK",
    "CJK": "CJK",
}

# ISO 639-1 code mapping for Lingua Language enum
_LINGUA_LANG_MAP = {}
if _LINGUA_AVAILABLE:
    _LINGUA_LANG_MAP = {
        Language.ENGLISH: "en",
        Language.GERMAN: "de",
        Language.FRENCH: "fr",
        Language.SPANISH: "es",
        Language.ITALIAN: "it",
        Language.PORTUGUESE: "pt",
        Language.DUTCH: "nl",
        Language.POLISH: "pl",
        Language.CZECH: "cs",
        Language.SLOVAK: "sk",
        Language.ROMANIAN: "ro",
        Language.HUNGARIAN: "hu",
        Language.SWEDISH: "sv",
        Language.BOKMAL: "nb",
        Language.DANISH: "da",
        Language.FINNISH: "fi",
        Language.TURKISH: "tr",
        Language.RUSSIAN: "ru",
        Language.UKRAINIAN: "uk",
        Language.ARABIC: "ar",
        Language.HEBREW: "he",
        Language.HINDI: "hi",
        Language.CHINESE: "zh",
        Language.JAPANESE: "ja",
        Language.KOREAN: "ko",
        Language.GREEK: "el",
        Language.THAI: "th",
        Language.VIETNAMESE: "vi",
        Language.INDONESIAN: "id",
        Language.MALAY: "ms",
        Language.CATALAN: "ca",
        Language.CROATIAN: "hr",
        Language.SERBIAN: "sr",
        Language.BULGARIAN: "bg",
        Language.SLOVENE: "sl",
        Language.ESTONIAN: "et",
        Language.LATVIAN: "lv",
        Language.LITHUANIAN: "lt",
        Language.ALBANIAN: "sq",
        Language.PERSIAN: "fa",
        Language.TAMIL: "ta",
        Language.BENGALI: "bn",
        Language.GEORGIAN: "ka",
        Language.ARMENIAN: "hy",
        Language.ICELANDIC: "is",
        Language.IRISH: "ga",
        Language.WELSH: "cy",
        Language.BASQUE: "eu",
        # Language.GALICIAN not available in this version
        Language.AFRIKAANS: "af",
        Language.SWAHILI: "sw",
    }

    _ISO_TO_LINGUA = {v: k for k, v in _LINGUA_LANG_MAP.items()}


def _get_script(char):
    """Get the script of a single character."""
    cp = ord(char)
    # Braille Patterns are category So (symbol), not L/M/N — check first
    if 0x2800 <= cp <= 0x28FF:
        return "BRAILLE"
    cat = unicodedata.category(char)
    if cat.startswith(("L", "M", "N")):
        # IPA Extensions range — must check before name lookup since
        # IPA chars have names like "LATIN SMALL LETTER TURNED A"
        if 0x0250 <= cp <= 0x02AF:
            return "IPA"
        try:
            name = unicodedata.name(char, "")
        except ValueError:
            return None
        for keyword, script in _CHAR_NAME_TO_SCRIPT.items():
            if keyword in name:
                return script
        if "LATIN" in name:
            return "LATIN"
    return None


def detect_script(text):
    """Detect the dominant non-Latin script in text.

    Returns the script name (e.g., 'CYRILLIC', 'ARABIC', 'CJK') or None if Latin/ambiguous.
    """
    if not text:
        return None

    scripts = Counter()
    for char in text:
        script = _get_script(char)
        if script and script != "LATIN":
            scripts[script] += 1

    if not scripts:
        return None

    dominant, count = scripts.most_common(1)[0]
    # Count letter/mark/number characters plus braille patterns (which are
    # symbols, not letters) so a pure-braille line can register as dominant.
    total_letters = sum(
        1 for c in text
        if unicodedata.category(c).startswith(("L", "M", "N"))
        or 0x2800 <= ord(c) <= 0x28FF
    )
    if total_letters > 0 and count / total_letters >= 0.5:
        return dominant

    return None


import re

# Sentence boundary splitter for chunked mixed-language detection.
# Splits on .!? followed by whitespace, and on newlines (which often
# delimit list items, log lines, or code that has no sentence punctuation).
_SENTENCE_SPLIT = re.compile(r'(?<=[.!?])\s+|\n+')

# Above this many words, mixed detection runs per-sentence instead of one
# big call. Lingua's multi-language detection on long text is slow enough
# to block Orca's main thread; per-sentence calls each return quickly.
_MIXED_CHUNK_THRESHOLD = 30

# Hard ceiling for any single chunk passed to detect_multiple_languages_of.
# If sentence splitting leaves a chunk longer than this (e.g., unpunctuated
# prose), we fall back to a fixed word-count split so no individual call
# can block the main thread.
_MIXED_HARD_CHUNK_WORDS = 40

# Tokens that look like paths, flags, URLs, variables — not real words
_NOISE_PATTERN = re.compile(
    r'^(?:'
    r'[/~]'               # starts with / or ~ (paths)
    r'|--?\w'             # CLI flags like -v or --verbose
    r'|\w+[=:]\S'         # assignments like KEY=val or key:val
    r'|\w+\.\w+\.\w+'    # dotted names like com.example.foo
    r'|\w+[_]\w+'         # snake_case identifiers
    r'|\d[\d.]*'          # numbers and version strings
    r'|[<>|&;$(){}\[\]]'  # shell operators
    r')',
    re.ASCII
)


def _filter_natural_words(text):
    """Extract likely natural-language words, discarding technical noise."""
    words = text.split()
    natural = []
    for word in words:
        # Strip surrounding punctuation
        stripped = word.strip('.,;:!?"\'"()[]{}')
        if not stripped:
            continue
        if _NOISE_PATTERN.match(stripped):
            continue
        # Skip words that are all uppercase and short (likely acronyms/commands)
        if stripped.isupper() and len(stripped) <= 4:
            continue
        # Skip if it contains path separators or other technical chars
        if any(c in stripped for c in '/\\|<>{}$'):
            continue
        natural.append(stripped)
    return natural


class LanguageDetector:
    """Two-tier language detector with word threshold for stability."""

    # Minimum confidence to switch away from the default language.
    # Lingua confidence ranges from 0.0 to 1.0.
    # Set high enough that "git commit message" (0.785) won't trigger,
    # but real sentences like "Dies ist ein deutscher Satz" (1.0) will.
    _SWITCH_AWAY_CONFIDENCE = 0.85
    # Minimum natural words needed to switch away from default
    _SWITCH_AWAY_MIN_WORDS = 3

    def __init__(self, enabled_languages, word_threshold, script_to_language,
                 default_language=None, switch_confidence=None,
                 mixed_max_words=600):
        self._enabled_languages = enabled_languages
        self._word_threshold = max(1, word_threshold)
        self._script_to_language = script_to_language
        self._default_language = default_language
        self._mixed_max_words = max(8, mixed_max_words)
        self._current_language = None
        self._word_buffer = []
        self._lingua_detector = None
        self._lingua_langs = []
        self._mixed_detector = None  # lazy-built for detect_mixed()

        # Allow user override of confidence threshold
        if switch_confidence is not None:
            self._SWITCH_AWAY_CONFIDENCE = switch_confidence

        if _LINGUA_AVAILABLE and enabled_languages:
            lingua_langs = []
            for lang_code in enabled_languages:
                lingua_lang = _ISO_TO_LINGUA.get(lang_code)
                if lingua_lang:
                    lingua_langs.append(lingua_lang)
            self._lingua_langs = lingua_langs
            if len(lingua_langs) >= 2:
                self._lingua_detector = (
                    LanguageDetectorBuilder
                    .from_languages(*lingua_langs)
                    .with_low_accuracy_mode()
                    .build()
                )

    @property
    def current_language(self):
        return self._current_language

    @current_language.setter
    def current_language(self, value):
        self._current_language = value

    def detect(self, text, statistical=True, fallback_to_current=True):
        """Detect language of text. Returns ISO 639-1 code or None.

        ``statistical=False`` skips the Lingua tier — useful in markup-only
        mode where we still want deterministic Unicode-script detection
        (Cyrillic, BRAILLE, IPA …) but no statistical guessing on Latin text.

        ``fallback_to_current=False`` returns ``None`` when no positive
        signal is found instead of echoing the previous language. Callers
        that want to detect "no signal at all" (so they can reset to
        default rather than stick on a stale language) should pass False.
        """
        if not text or not text.strip():
            return self._current_language if fallback_to_current else None

        # Tier 1: Script detection (fast path) — always runs.
        # Braille-only sentinels (ipa, unicode_braille) aren't in
        # enabled_languages but are valid signals — they just trigger a
        # contraction-table switch in _switch_language without changing
        # voice. Allow them through without the enabled check, and don't
        # write _current_language for them (it stays whatever spoken
        # language was active).
        script = detect_script(text)
        if script:
            lang = self._script_to_language.get(script)
            if lang in _BRAILLE_ONLY_SENTINELS:
                return lang
            if lang and lang in self._enabled_languages:
                if fallback_to_current:
                    self._current_language = lang
                    self._word_buffer.clear()
                return lang

        if not statistical:
            return self._current_language if fallback_to_current else None

        # Tier 2: Lingua detection (slow path, Latin scripts)
        if self._lingua_detector:
            # Strip non-letter characters (braille dots, symbols, etc.)
            clean = "".join(c for c in text if unicodedata.category(c).startswith(("L", "Z")))
            if clean.strip():
                # Filter out technical noise (paths, flags, identifiers)
                natural = _filter_natural_words(clean)
                if natural:
                    clean_text = " ".join(natural)
                    return self._detect_with_lingua(clean_text, len(natural))

        return self._current_language

    def _detect_with_lingua(self, text, natural_word_count):
        """Use Lingua for Latin-script language detection with confidence check."""
        detected, confidence = self._cached_lingua_detect_with_confidence(text)
        if not detected:
            return self._current_language

        if detected == self._current_language:
            self._word_buffer.clear()
            return detected

        # When switching AWAY from the default language, require higher
        # confidence and more words — short technical text often gets misidentified
        if (self._default_language
                and detected != self._default_language
                and self._current_language == self._default_language):
            if confidence < self._SWITCH_AWAY_CONFIDENCE:
                return self._current_language
            if natural_word_count < self._SWITCH_AWAY_MIN_WORDS:
                self._word_buffer.append(detected)
                if len(self._word_buffer) >= self._word_threshold:
                    if all(lang == detected for lang in self._word_buffer[-self._word_threshold:]):
                        self._current_language = detected
                        self._word_buffer.clear()
                        return detected
                return self._current_language

        # For multi-word text, switch if above threshold
        if natural_word_count >= self._word_threshold:
            self._current_language = detected
            self._word_buffer.clear()
            return detected

        # For short text, apply word threshold buffer
        self._word_buffer.append(detected)
        if len(self._word_buffer) >= self._word_threshold:
            if all(lang == detected for lang in self._word_buffer[-self._word_threshold:]):
                self._current_language = detected
                self._word_buffer.clear()
                return detected

        return self._current_language

    @lru_cache(maxsize=128)
    def _cached_lingua_detect_with_confidence(self, text):
        """Cached Lingua detection with confidence score."""
        values = self._lingua_detector.compute_language_confidence_values(text)
        if values:
            best = values[0]
            lang_code = _LINGUA_LANG_MAP.get(best.language)
            return lang_code, best.value
        return None, 0.0

    def detect_character(self, char, fallback_to_current=True):
        """Detect language for a single character (character-by-character navigation).

        ``fallback_to_current=False`` returns ``None`` when the character has
        no positive script signal (Latin, punctuation, …) instead of echoing
        the previous language. Used by markup-only mode so a char read after
        a context switch doesn't keep the stale voice.
        """
        if not char:
            return self._current_language if fallback_to_current else None

        script = _get_script(char)
        if script and script != "LATIN":
            lang = self._script_to_language.get(script)
            if lang in _BRAILLE_ONLY_SENTINELS:
                return lang
            if lang and lang in self._enabled_languages:
                if fallback_to_current:
                    self._current_language = lang
                return lang

        # No positive signal — Latin char, punctuation, etc.
        return self._current_language if fallback_to_current else None

    def reset_buffer(self):
        """Reset the word buffer (e.g., when navigating to a new line)."""
        self._word_buffer.clear()

    def detect_mixed(self, text):
        """Detect multiple languages in mixed-language text.

        Returns a list of (text_segment, iso_code) tuples, or None if
        mixed detection is unavailable or the text is too short.

        Strategy:
          - Texts under ~30 words: single Lingua call (fast, current behaviour).
          - Up to ``mixed_max_words``: split on sentence boundaries and run
            detection per chunk. Each call is short, so no individual
            detection blocks Orca's main thread for long.
          - Beyond ``mixed_max_words``: skip mixed detection so speech can
            start immediately. The single-language detector handles voice.

        Uses a separate high-accuracy detector (lazy-built on first call)
        with preloaded language models for better mixed-language splitting.
        """
        if not _LINGUA_AVAILABLE or not text or not self._lingua_langs:
            return None

        # Only attempt on longer text — short text isn't reliably splittable
        words = text.split()
        if len(words) < 8:
            return None

        # Above the user-configured cap, fall back to single-language detection
        if len(words) > self._mixed_max_words:
            return None

        # Lazy-build high-accuracy detector on first use
        if self._mixed_detector is None:
            if len(self._lingua_langs) < 2:
                return None
            try:
                builder = LanguageDetectorBuilder.from_languages(
                    *self._lingua_langs).with_preloaded_language_models()
                self._mixed_detector = builder.build()
            except Exception:
                return None

        if len(words) > _MIXED_CHUNK_THRESHOLD:
            return self._detect_mixed_chunked(text)

        try:
            results = self._mixed_detector.detect_multiple_languages_of(text)
            if not results or len(results) <= 1:
                return None  # Single language or no results — not mixed

            segments = []
            for r in results:
                segment_text = text[r.start_index:r.end_index]
                lang_code = _LINGUA_LANG_MAP.get(r.language)
                if lang_code and segment_text.strip():
                    segments.append((segment_text, lang_code))

            # Only return if we actually found multiple different languages
            if len(set(code for _, code in segments)) >= 2:
                return segments
        except Exception:
            pass

        return None

    def _detect_mixed_chunked(self, text):
        """Run mixed detection per sentence and concatenate the segments.

        Sentence-split first; any chunk still longer than
        ``_MIXED_HARD_CHUNK_WORDS`` (e.g., unpunctuated prose) is further
        split by word count so no single Lingua call gets a long string.
        """
        all_segments = []

        for chunk in self._iter_chunks(text):
            chunk = chunk.strip()
            if not chunk:
                continue
            try:
                if len(chunk.split()) < 8:
                    detected, _ = self._cached_lingua_detect_with_confidence(chunk)
                    if detected:
                        all_segments.append((chunk, detected))
                    continue
                results = self._mixed_detector.detect_multiple_languages_of(chunk)
                if not results:
                    continue
                for r in results:
                    seg_text = chunk[r.start_index:r.end_index]
                    lang_code = _LINGUA_LANG_MAP.get(r.language)
                    if lang_code and seg_text.strip():
                        all_segments.append((seg_text, lang_code))
            except Exception:
                continue

        if len(set(code for _, code in all_segments)) >= 2:
            return all_segments
        return None

    def _iter_chunks(self, text):
        """Yield text chunks, each at most _MIXED_HARD_CHUNK_WORDS words.

        First splits on sentence boundaries. Any sentence that's still too
        long is further split into fixed-size word groups.
        """
        for sentence in _SENTENCE_SPLIT.split(text):
            words = sentence.split()
            if len(words) <= _MIXED_HARD_CHUNK_WORDS:
                yield sentence
                continue
            for i in range(0, len(words), _MIXED_HARD_CHUNK_WORDS):
                yield " ".join(words[i:i + _MIXED_HARD_CHUNK_WORDS])


def is_lingua_available():
    return _LINGUA_AVAILABLE
