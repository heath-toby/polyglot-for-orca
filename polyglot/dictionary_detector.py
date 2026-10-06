"""Dictionary-based language detection.

The question this answers is deliberately a dull one: of the words in this
text, how many appear in the German word list and not the English one? That
is all. There is no model, no training and no confidence score pulled out of
a statistical hat -- just set membership, which means a wrong answer can
always be explained by naming the words that caused it.

Word lists live outside the extension package, in

    $XDG_DATA_HOME/orca/polyglot/dictionaries/<lang>.txt

one word per line, ``#`` for comments, most frequent first. They have to
live there rather than in the package because Orca approves an extension by
hashing every file in its directory, so a list added or refreshed after
install would un-approve the add-on.

Lists are plain text on purpose: they are meant to be opened, read and
edited. Adding a word your synthesiser keeps getting wrong is one line in a
text file.

A hunspell/myspell ``.dic`` is accepted as a fallback source where no word
list exists. Those hold stems plus affix flags rather than surface forms, so
for an inflected language they under-match ("Haus" is listed, "Häuser" is
not); a frequency list of real surface forms beats them for this purpose.
"""

import logging
import os

log = logging.getLogger("polyglot")

# Below this length a word carries almost no signal and plenty of noise:
# "a", "an", "in", "is", "so", "no", "die" exist across too many languages
# to be worth the false switches.
_MIN_WORD_LENGTH = 3

# Where lists are looked for, relative to the data directory.
DICTIONARY_SUBDIR = "dictionaries"

# Searched in order for a language with no word list of its own.
_HUNSPELL_DIRS = ("/usr/share/hunspell", "/usr/share/myspell")


def default_directory():
    """Return the directory word lists are read from."""
    return os.path.join(
        os.environ.get("XDG_DATA_HOME", os.path.expanduser("~/.local/share")),
        "orca", "polyglot", DICTIONARY_SUBDIR,
    )


class Verdict:
    """The outcome of one dictionary lookup, and why.

    ``reason`` is written for a human reading the log, because the point of
    this tier over a statistical one is that its mistakes are legible.
    """

    __slots__ = ("language", "leader", "hits", "exclusive", "considered",
                 "matched", "reason")

    def __init__(self, language, hits, exclusive, considered, matched, reason,
                 leader=None):
        self.language = language
        # The one language with exclusive words when no other has any, even
        # if there were too few to conclude. Thin evidence, but honest: a
        # single word that is in the German list and no other really is
        # German, and that beats a statistical guess on the same word.
        # "Kaffee" and "Zucker" are each one exclusive German word; Lingua
        # calls them English at 0.91 and 0.94.
        self.leader = leader
        self.hits = hits
        self.exclusive = exclusive
        self.considered = considered
        self.matched = matched
        self.reason = reason

    @property
    def conclusive(self):
        return self.language is not None

    def __repr__(self):
        return f"<Verdict {self.language or 'inconclusive'}: {self.reason}>"


class DictionaryDetector:
    """Decides a language by counting word-list membership.

    Scoring counts a word for every language whose list holds it, and
    separately counts the words held by exactly one language. The decision
    is made on those exclusive words: shared vocabulary ("international",
    "Information", "Radio") is real in both languages and so tells us
    nothing, while "der" and "the" each settle the matter on their own.
    """

    def __init__(self, languages, directory=None, min_words=2, min_share=0.6,
                 max_entries=30000):
        self._directory = directory or default_directory()
        self._min_words = max(1, int(min_words))
        self._min_share = min(1.0, max(0.0, float(min_share)))
        self._max_entries = max(0, int(max_entries))
        # lang -> frozenset of words, built on first lookup for that language.
        self._words = {}
        # lang -> path the words came from. Populated at construction so the
        # status command can report what is installed without loading it all.
        self._sources = {}
        for lang in languages:
            source = self._find_source(lang)
            if source:
                self._sources[lang] = source

    # --- sources ---------------------------------------------------------

    def _find_source(self, lang):
        """Return the file a language's words come from, or None."""
        own = os.path.join(self._directory, f"{lang}.txt")
        if os.path.isfile(own):
            return own
        for directory in _HUNSPELL_DIRS:
            if not os.path.isdir(directory):
                continue
            try:
                entries = sorted(os.listdir(directory))
            except OSError:
                continue
            # Prefer an exact "de.dic" over a regional "de_DE.dic", then
            # take the first region alphabetically so the choice is stable.
            for name in (f"{lang}.dic", *(e for e in entries
                                          if e.startswith(f"{lang}_") and e.endswith(".dic"))):
                path = os.path.join(directory, name)
                if os.path.isfile(path):
                    return path
        return None

    def available_languages(self):
        """Return the languages that have a word list, loaded or not."""
        return sorted(self._sources)

    def describe(self):
        """Return (language, word_count, source) for each available language.

        Loads every list, so this is for the status command rather than the
        speech path.
        """
        result = []
        for lang in sorted(self._sources):
            result.append((lang, len(self._load(lang)), self._sources[lang]))
        return result

    def _load(self, lang):
        """Return the word set for a language, reading it on first use."""
        cached = self._words.get(lang)
        if cached is not None:
            return cached

        path = self._sources.get(lang)
        words = frozenset()
        if path:
            try:
                words = self._read(path)
            except OSError as error:
                log.warning(f"Polyglot: could not read dictionary {path}: {error}")
        self._words[lang] = words
        if path:
            log.info(f"Polyglot: loaded {len(words)} {lang} words from {path}")
        return words

    def _read(self, path):
        """Read a word list or a hunspell .dic into a set of lowercase words."""
        is_dic = path.endswith(".dic")
        words = set()
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            if is_dic:
                # First line of a .dic is the entry count, not a word.
                handle.readline()
            for line in handle:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if is_dic:
                    # "Haus/NA" -> "Haus"; also drop morphological fields.
                    line = line.split("/", 1)[0].split("\t", 1)[0].strip()
                else:
                    # A frequency list may carry a count after the word.
                    line = line.split(None, 1)[0]
                if len(line) < _MIN_WORD_LENGTH:
                    continue
                words.add(line.lower())
                if self._max_entries and len(words) >= self._max_entries:
                    break
        return frozenset(words)

    # --- detection -------------------------------------------------------

    def detect(self, words, candidates=None):
        """Weigh ``words`` against the candidate languages' lists.

        ``words`` is an iterable of already-tokenised words -- the caller
        has usually filtered technical noise out first. ``candidates``
        limits which languages are considered; it defaults to every
        language that has a list.
        """
        languages = [lang for lang in (candidates or self.available_languages())
                     if lang in self._sources]
        if len(languages) < 2:
            # With one list there is nothing to compare against, so every
            # hit would "win" and any unknown word would look like a miss.
            return Verdict(None, {}, {}, 0, 0, "fewer than two word lists available")

        sets = {lang: self._load(lang) for lang in languages}
        hits = {lang: 0 for lang in languages}
        exclusive = {lang: 0 for lang in languages}
        considered = 0
        matched = 0

        for word in words:
            word = word.lower().strip("'’-")
            if len(word) < _MIN_WORD_LENGTH:
                continue
            considered += 1
            owners = [lang for lang in languages if word in sets[lang]]
            if not owners and "-" in word:
                # Hyphenated compounds: let the parts speak for the whole.
                owners = self._owners_of_parts(word, languages, sets)
            if not owners:
                continue
            matched += 1
            for lang in owners:
                hits[lang] += 1
            if len(owners) == 1:
                exclusive[owners[0]] += 1

        return self._decide(hits, exclusive, considered, matched)

    @staticmethod
    def _owners_of_parts(word, languages, sets):
        """Return the languages holding every long part of a hyphenated word."""
        parts = [p for p in word.split("-") if len(p) >= _MIN_WORD_LENGTH]
        if not parts:
            return []
        owners = [lang for lang in languages
                  if all(part in sets[lang] for part in parts)]
        return owners

    def _decide(self, hits, exclusive, considered, matched):
        """Turn the counts into a verdict."""
        if not matched:
            return Verdict(None, hits, exclusive, considered, matched,
                           f"none of {considered} words are in any word list")

        total_exclusive = sum(exclusive.values())
        if total_exclusive:
            winner = max(exclusive, key=lambda lang: (exclusive[lang], hits[lang]))
            count = exclusive[winner]
            share = count / total_exclusive
            # Only one language's words are present at all, so there is
            # nothing to weigh it against, however few of them there were.
            sole = winner if count == total_exclusive else None
            if count < self._min_words:
                return Verdict(None, hits, exclusive, considered, matched,
                               f"only {count} word(s) unique to {winner}; "
                               f"{self._min_words} needed",
                               leader=sole)
            if share < self._min_share:
                return Verdict(None, hits, exclusive, considered, matched,
                               f"{winner} holds {count} of {total_exclusive} unique "
                               f"words ({share:.0%}), below {self._min_share:.0%}",
                               leader=sole)
            return Verdict(winner, hits, exclusive, considered, matched,
                           f"{count} of {total_exclusive} unique words are "
                           f"{winner}-only ({share:.0%})",
                           leader=sole)

        # Every matched word is shared by several languages. Fall back to
        # plain hit counts, which can still separate them when one list has
        # the words and another merely overlaps on a few.
        total_hits = sum(hits.values())
        winner = max(hits, key=lambda lang: hits[lang])
        share = hits[winner] / total_hits if total_hits else 0.0
        if matched >= self._min_words and share >= self._min_share:
            return Verdict(winner, hits, exclusive, considered, matched,
                           f"no unique words; {winner} matched {hits[winner]} of "
                           f"{total_hits} ({share:.0%})")
        return Verdict(None, hits, exclusive, considered, matched,
                       f"{matched} word(s) matched but none uniquely")
