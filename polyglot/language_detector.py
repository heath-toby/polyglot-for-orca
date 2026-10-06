"""Layered language detection: Unicode script, word lists, then Lingua.

Three tiers, each cheaper and more explainable than the next:

``script``
    Unicode script of the characters. Deterministic -- Cyrillic really is
    Cyrillic -- and the only tier that can answer from a single character.
``dictionary``
    How many words are in each language's word list, and how many are in
    only one of them. See :mod:`dictionary_detector`. Costs microseconds
    and can be explained by naming the words that decided it.
``lingua``
    The statistical model. Handles languages with no word list installed,
    and short Latin text that the word lists cannot settle.

The order is configurable, because which one should win depends on the
languages in play. ``script`` first is right when each script maps to one
language -- Cyrillic text is Russian, and no word list is going to improve
on that. ``dictionary`` first is right when two enabled languages share a
script, since Russian and Ukrainian are both Cyrillic and only the words
can tell them apart.

A tier that cannot answer passes the question down. If none of them can,
the caller keeps the language it already had.
"""

import re
import unicodedata
from collections import Counter

# Sentinel "language" codes — not real spoken languages, just trigger
# braille-table switches. They live in script_to_language but never in
# enabled_languages, so detect()/detect_character() must allow them
# through without the enabled-languages check.
_BRAILLE_ONLY_SENTINELS = ("ipa", "unicode_braille")

# Detection tiers, in the default order. "dictionary" is a no-op unless word
# lists are installed, so this default is safe on a fresh install.
TIER_SCRIPT = "script"
TIER_DICTIONARY = "dictionary"
TIER_LINGUA = "lingua"
DEFAULT_DETECTION_ORDER = (TIER_SCRIPT, TIER_DICTIONARY, TIER_LINGUA)
VALID_TIERS = DEFAULT_DETECTION_ORDER

# Returned by a tier that found real evidence but not enough of it to switch
# yet. It stops the chain -- a later tier guessing from the same text would
# only be guessing worse -- and leaves the current language in place.
_NO_SWITCH = object()

# Below this many characters, text has no content to detect a language from
# and the content-based tiers are skipped entirely. A single character is
# the case that matters: the word lists decline on it, but Lingua will
# happily name a language for one letter, and letters are shared between
# languages, so the answer is close to a coin toss. Asked once per keypress
# while arrowing along a line, that reads as the voice changing at random
# from character to character. The script tier is unaffected -- it works on
# one character by design, which is how Cyrillic is recognised.
_MIN_CONTENT_CHARS = 3

# How many Lingua answers one detector remembers. Cleared wholesale when
# full, which for a lookaside cache is both cheap and good enough.
_LINGUA_CACHE_SIZE = 128

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
                 mixed_max_words=600, dictionaries=None, detection_order=None):
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
        # text -> (language, confidence). See
        # _cached_lingua_detect_with_confidence for why this is not an
        # lru_cache on the method.
        self._lingua_cache = {}
        # A DictionaryDetector, or None to leave that tier out.
        self._dictionaries = dictionaries
        self._detection_order = normalize_detection_order(detection_order)
        # The last dictionary verdict, kept so the log can say why.
        self._last_dictionary_verdict = None

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

        # Tokenised once and shared by both word-based tiers, however the
        # order puts them.
        natural = None
        # Cleared per call so the log can never attribute an answer to a
        # verdict from an earlier line that a different tier decided.
        self._last_dictionary_verdict = None

        for tier in self._detection_order:
            result = None
            if tier == TIER_SCRIPT:
                result = self._detect_by_script(text, fallback_to_current)
            elif not statistical or not self._has_content(text):
                # Both word-based tiers guess from content rather than
                # reading a declared language, so markup-only mode skips
                # them -- and so does text with no content to go on.
                continue
            elif tier == TIER_DICTIONARY:
                if self._dictionaries is None:
                    continue
                if natural is None:
                    natural = self._natural_words(text)
                result = self._detect_by_dictionary(natural)
            elif tier == TIER_LINGUA:
                if not self._lingua_detector:
                    continue
                if natural is None:
                    natural = self._natural_words(text)
                if not natural:
                    continue
                result = self._detect_with_lingua(" ".join(natural), len(natural))

            if result is _NO_SWITCH:
                break
            if result is not None:
                return result

        return self._current_language if fallback_to_current else None

    @staticmethod
    def _has_content(text):
        """True if text is long enough for a language to be guessed from it."""
        return has_content(text)

    def _detect_by_script(self, text, fallback_to_current):
        """Tier: the Unicode script of the text. Returns a language or None.

        Braille-only sentinels (ipa, unicode_braille) aren't in
        enabled_languages but are valid signals — they just trigger a
        contraction-table switch in _switch_language without changing
        voice. Allow them through without the enabled check, and don't
        write _current_language for them (it stays whatever spoken
        language was active).
        """
        script = detect_script(text)
        if not script:
            return None
        lang = self._script_to_language.get(script)
        if lang in _BRAILLE_ONLY_SENTINELS:
            return lang
        if lang and lang in self._enabled_languages:
            if fallback_to_current:
                self._current_language = lang
                self._word_buffer.clear()
            return lang
        return None

    def _detect_by_dictionary(self, natural):
        """Tier: word-list membership. A language, None, or _NO_SWITCH."""
        if not natural:
            return None
        verdict = self._dictionaries.detect(natural, candidates=self._enabled_languages)
        self._last_dictionary_verdict = verdict
        if verdict.conclusive:
            # matched, not considered: the stability rule should count the
            # words that carried evidence, not the ones we failed to place.
            return self._commit(verdict.language, verdict.matched, confident=True)

        if verdict.leader:
            # Too thin to conclude, but unambiguous: these words belong to
            # one language's list and no other's. That is worth more than a
            # statistical guess on the same text, which on single words is
            # confidently wrong often enough to matter -- so claim the
            # answer rather than letting Lingua have it. Still subject to
            # the stability rule, so a lone word only nudges the buffer.
            committed = self._commit(verdict.leader, verdict.matched, confident=True)
            return committed if committed is not None else _NO_SWITCH

        return None

    @staticmethod
    def _natural_words(text):
        """Tokenise text into likely natural-language words.

        Strips non-letter characters (braille dots, symbols, …) and then
        technical noise (paths, flags, identifiers).
        """
        clean = "".join(c for c in text if unicodedata.category(c).startswith(("L", "Z")))
        if not clean.strip():
            return []
        return _filter_natural_words(clean)

    def _commit(self, detected, word_count, confident=False):
        """Apply the word-threshold stability rule to a detected language.

        Returns the language to speak with, or None when the evidence is
        too thin to switch yet. Shared by every tier that guesses from
        content, so one knob governs how twitchy detection is.

        ``confident`` marks evidence worth acting on from a short utterance
        -- a word-list match, or Lingua above the switch threshold.
        """
        if detected == self._current_language:
            self._word_buffer.clear()
            return detected

        # Coming home to the default language is cheap; leaving it is not.
        # The threshold exists to stop a stray line dragging the voice off
        # the language the user mostly reads -- it has no business making
        # the way back just as slow. Without this, a single-word utterance
        # needs a run of agreeing detections to return, so after one German
        # line every short English utterance (typing echo above all, which
        # arrives one word or one character at a time) keeps being read in
        # German until four of them agree; character echo never recovers at
        # all, having no content to detect from.
        #
        # Only on confident evidence, though. Letting any guess home in
        # reads a German sentence word by word in English, because Lingua
        # calls "Kaffee" English at 0.91.
        if confident and self._default_language and detected == self._default_language:
            self._current_language = detected
            self._word_buffer.clear()
            return detected

        if word_count >= self._word_threshold:
            self._current_language = detected
            self._word_buffer.clear()
            return detected

        self._word_buffer.append(detected)
        if len(self._word_buffer) >= self._word_threshold:
            recent = self._word_buffer[-self._word_threshold:]
            if all(lang == detected for lang in recent):
                self._current_language = detected
                self._word_buffer.clear()
                return detected
        return None

    def dictionary_status(self):
        """Return (language, word_count, source) per installed word list."""
        if self._dictionaries is None:
            return []
        return self._dictionaries.describe()

    @property
    def detection_order(self):
        return self._detection_order

    @property
    def last_dictionary_verdict(self):
        """The most recent dictionary verdict, for logging. May be None."""
        return self._last_dictionary_verdict

    def _detect_with_lingua(self, text, natural_word_count):
        """Tier: the statistical model. Returns a language or None.

        Returning None rather than the current language is what lets a
        later tier have a go when the order puts Lingua before it.
        """
        detected, confidence = self._cached_lingua_detect_with_confidence(text)
        if not detected:
            return None

        if detected == self._current_language:
            self._word_buffer.clear()
            return detected

        # When switching AWAY from the default language, require higher
        # confidence and more words — short technical text often gets misidentified
        if (self._default_language
                and detected != self._default_language
                and self._current_language == self._default_language):
            if confidence < self._SWITCH_AWAY_CONFIDENCE:
                return None
            if natural_word_count < self._SWITCH_AWAY_MIN_WORDS:
                # Too few words to trust on its own; only a run of
                # agreeing detections may switch.
                self._word_buffer.append(detected)
                if len(self._word_buffer) >= self._word_threshold:
                    if all(lang == detected for lang in self._word_buffer[-self._word_threshold:]):
                        self._current_language = detected
                        self._word_buffer.clear()
                        return detected
                return None

        return self._commit(
            detected, natural_word_count,
            confident=confidence >= self._SWITCH_AWAY_CONFIDENCE,
        )

    def _cached_lingua_detect_with_confidence(self, text):
        """Lingua detection with confidence score, cached per detector.

        The cache is an instance attribute rather than an ``lru_cache`` on
        the method. A decorated method caches on ``(self, text)``, so it
        holds a strong reference to every detector it has been called on --
        and a detector owns a built Lingua model. Settings are re-read on
        every change, each time building a new detector, so the decorated
        form kept the old ones and their models alive for the life of the
        process.
        """
        cached = self._lingua_cache.get(text)
        if cached is not None:
            return cached

        values = self._lingua_detector.compute_language_confidence_values(text)
        if values:
            best = values[0]
            result = (_LINGUA_LANG_MAP.get(best.language), best.value)
        else:
            result = (None, 0.0)

        if len(self._lingua_cache) >= _LINGUA_CACHE_SIZE:
            self._lingua_cache.clear()
        self._lingua_cache[text] = result
        return result

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

            segments = self._validate_segments(segments)
            # Only return if we actually found multiple different languages
            if len(set(code for _, code in segments)) >= 2:
                return segments
        except Exception:
            pass

        return None

    def _validate_segments(self, segments):
        """Correct Lingua's segment languages against the word lists, and merge.

        ``detect_multiple_languages_of`` is handed the raw text, noise and
        all -- it has to be, since we need character offsets back -- and on
        number-heavy prose it mislabels badly. "I have 1 apple 2 oranges 3
        pears 4 plums and 5 bananas in the basket" comes back as German for
        the first half and English for the second, with no German in it at
        all.

        A spurious language change is expensive: it switches voice
        mid-sentence and splits one utterance into several. So each segment
        is weighed against the word lists, which have the final say when
        they are sure, and neighbours that then agree are merged back into
        one segment.
        """
        if self._dictionaries is None:
            return segments

        corrected = []
        for text, lang in segments:
            natural = self._natural_words(text)
            if natural:
                verdict = self._dictionaries.detect(
                    natural, candidates=self._enabled_languages)
                decided = verdict.language or verdict.leader
                if decided and decided != lang:
                    lang = decided
            corrected.append((text, lang))

        merged = []
        for text, lang in corrected:
            if merged and merged[-1][1] == lang:
                # The texts are consecutive slices of the original, so
                # joining them reconstructs the span exactly.
                merged[-1] = (merged[-1][0] + text, lang)
            else:
                merged.append((text, lang))
        return merged

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

        all_segments = self._validate_segments(all_segments)
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


def has_content(text):
    """True if text is long enough for a language to be guessed from it.

    Public because callers need to know whether a detection result means
    anything: with no content, ``detect`` has nothing but the current
    language to return, and a caller with better context of its own should
    use that instead.
    """
    return bool(text) and len(text.strip()) >= _MIN_CONTENT_CHARS


def normalize_detection_order(order):
    """Return a usable tier order from whatever the settings hold.

    Unknown names are dropped and missing tiers appended in their default
    positions, so a hand-edited setting can neither disable a tier by
    typo nor leave detection with nothing to try.
    """
    if not order:
        return DEFAULT_DETECTION_ORDER
    seen = []
    for tier in order:
        tier = str(tier).strip().lower()
        if tier in VALID_TIERS and tier not in seen:
            seen.append(tier)
    for tier in DEFAULT_DETECTION_ORDER:
        if tier not in seen:
            seen.append(tier)
    return tuple(seen)


def is_lingua_available():
    return _LINGUA_AVAILABLE
