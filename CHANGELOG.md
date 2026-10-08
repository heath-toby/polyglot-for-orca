# Changelog

All notable changes to Polyglot for Orca are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [2.8.1] — 2026-10-08

### Fixed

- **A line whose braille table changed was rendered half in the old table.**
  Moving onto a German line showed something that was neither German nor
  English: the right number of cells, but hybrid dots — 1246 where German
  wants 46 — and it stayed that way until you moved off the line and back.

  Only one braille table can be active at a time, so the line on the display
  owns it, and `update_braille` is the one place that decides. That was
  always the design; it was documented in `_switch_language`'s own
  docstring. But `also_braille` defaulted to `True`, and four speech-side
  call sites simply did not pass `False`: two in `_patched_speak`, one in its
  markup-only branch, and one in `_patched_speak_character`. Speech runs
  after `update_braille` has settled the line, once per utterance and once
  per character, so a single English word or echoed letter re-pointed both
  the liblouis contraction table and BRLTTY's computer-braille table at
  English while the German line was still on the display. Changing BRLTTY's
  table re-renders what is already there, which is why the cell count stayed
  German and the dots did not. Arrowing down and back up ran
  `update_braille` again and put it right.

  Found in the debug log as `speak_char: char='n' lang=en` followed by
  `_switch_language: de -> en (also_braille=True)`, in gedit, on a German
  document.

  `also_braille` now defaults to `False`, so braille is opt-in and
  `update_braille` is the only caller that asks for it. A new call site that
  forgets is now harmless rather than wrong.

- **IPA and Unicode-braille lines got their table only by accident.** Both
  are braille-only sentinels: they name a contraction table and have no
  voice, so neither is ever an enabled language — and `_language_of_line`
  keeps only enabled languages. In `markup_text` and `always` modes the
  braille path therefore never saw them, and their tables were being set
  purely as a side effect of the speech-side leak above. Closing that leak
  without this would have taken IPA and Unicode-braille braille away
  altogether. `update_braille` now asks for them outright, through a new
  `_braille_sentinel`.

### Added

- Eight rows in `tests-language-matrix.py` (48 total), covering what the
  modes have in common: whatever table the focus line settles on, speaking
  English on it — as an utterance, a character, or a short label — must not
  move it; and a Unicode-braille or IPA line must get its table from the
  braille path. Each half was checked by reverting it: the three ownership
  rows fail with the leak restored, and the two sentinel rows fail with the
  leak closed but the sentinel lookup removed.

## [2.8.0] — 2026-10-06

### Changed

- **Polyglot is an Orca extension now, not a block in
  `orca-customizations.py`.** It installs into
  `~/.local/share/orca/extensions/polyglot/` and is loaded by Orca 51's own
  extension loader, which is what the 2.x series has been building towards.
  What that buys:

  - Orca manages the lifecycle. `on_ready`, `on_enabled` and `on_disabled`
    apply and remove the patches, so turning Polyglot off in Orca's
    preferences actually stops it and a reload does not stack a second set
    of patches on the first. Every patch is recorded with what was there
    before and restored exactly, verified by fingerprinting Orca's own
    methods before, during and after a disable.
  - Settings live in Orca's per-extension store
    (`/org/gnome/orca/default/extensions/polyglot/settings`), alongside
    every other extension's, and are imported once from the old
    `org.gnome.Orca.Polyglot` schema and the older JSON file. Nothing to do
    by hand.
  - The keybinding is registered as an Orca `KeyboardCommand`, so
    Orca+Shift+L appears in Orca's own key bindings list under "Polyglot"
    rather than being bolted on.
  - Orca approves an extension by hashing every file in its directory, so
    only code lives in the package. The venv, word lists, custom character
    names, speech dictionary and debug log live in
    `~/.local/share/orca/polyglot/`, which also means the venv -- whose
    scripts bake in an absolute path -- never has to be rebuilt when the
    package moves.

  `install.sh` removes the old `# --- polyglot begin ---` block from
  `orca-customizations.py` if it finds one, and carries settings and custom
  character names over from a `polyglot_v50` or `polyglot_v51` install.

- **Phoneme rules are gone**, rather than stored and never applied. A rule
  type that could only ever do nothing was not worth a third of the editor,
  and phonetic notation is not reachable through Speech Dispatcher's text
  protocol in any case. A rule of an unknown kind -- including a phoneme
  rule saved by 2.7.0 -- is now ignored with a line in the log rather than
  applied as a literal text replacement, which is what would otherwise have
  happened to it.

- The **Language detection** mode description now says what Markup only
  actually leaves out: word lists and statistical detection both, so text
  in a language that shares the Latin alphabet is read in the default
  language unless it is tagged. The labels are unchanged.

### Fixed

- **The Test field in the rule editor stopped working as soon as a
  dictionary had been saved.** `preview()` substitutes the unsaved rules
  and calls `apply()`, which calls `load()`, which compared the file's
  modification time against what it had last read, decided the rules in
  memory were stale and read the saved ones back over the ones being
  previewed. Every rule then reported "No change", which is precisely the
  answer the field exists to disprove. It had no saved dictionary to trip
  over when it was written, so it tested clean; seven rows of the matrix
  caught it once there was one.

- **Character-by-character flicker in Markup only mode.** A space and a
  letter reached their language by different routes: the letter through the
  mode's own rule, which reads nothing out of Latin text and so gave the
  default language, and the space -- having nothing to detect from at all --
  through the line it sits in, where the full detector ran regardless of
  mode. On a German line that meant English letters and German spaces. Line
  detection now honours the detection mode, so every character of a line
  agrees, and a new matrix row checks exactly that in every mode.

- **A backslash in a text replacement broke the rule.** A text rule's
  replacement went to `re.sub` as a replacement template, so `\1` in it was
  read as a group reference; a pattern with no groups then raised at
  substitution time, and the rule was disabled for the session with nothing
  but a line in the log to say so. A text replacement is now literal both
  ways, which is what "text replacement" means.

- **A line's language could be cached against a volatile value.** The line
  cache stored whatever `detect()` returned, including the current language
  it falls back to when nothing is found -- so reading a short line while
  German was current pinned that line to German for the rest of the session.
  Only positively detected languages are cached now.

- **Disabling Polyglot left three things behind.** Orca's locale for role
  and symbol names (so Orca went on saying "Schaltfläche" with nothing
  running to explain it), the liblouis contraction table, and the BRLTTY
  text table. All three are restored now, and the BrlAPI connection is
  closed -- a disabled extension should not be holding one open.

- **Every settings change leaked a Lingua model.** The cache on Lingua
  lookups was an `lru_cache` on a method, which caches on `(self, text)` and
  so holds a strong reference to every detector it is called on. Settings
  are re-read on every change, each time building a new detector with a
  built Lingua model, and the old ones were never collected. The cache is
  an instance attribute now.

### Removed

- Dead state in the braille path: a remembered focus-line text and names
  locale, written on every line change and read by nothing. Worth removing
  rather than leaving: every bug in character language resolution has come
  from a remembered line record drifting out of step with what Orca was
  actually speaking, and this was the last of them.

- Unused helpers: `available_voices.all_voices`,
  `speech_dictionary.describe`, `speech_interceptor.get_config` and
  `get_detector`.

### Notes

- The test matrix is **40 rows**, run as `POLYGLOT_TEST_MODE=<mode>
  python3 tests-language-matrix.py`: **markup_text 40/40, always 40/40,
  markup_only 33/40**. The seven markup_only failures are the German rows
  and are that mode's documented behaviour -- German is Latin script, and
  that mode reads nothing out of the text itself. They now fail
  *uniformly*, which is the point of the flicker fix above: wrong in one
  language is a mode's limitation, wrong in two within one line was a bug.

## [2.7.0] — 2026-10-06

### Added

- **A speech dictionary with patterns, not just word swaps.** Speech ->
  Edit Speech Dictionary. Orca has a pronunciation dictionary of its own,
  but it is a flat word list: it splits the text on non-word characters and
  looks each word up exactly, so it can turn "ACME" into "acky" and nothing
  more. It cannot match a phrase, cannot tell "US" from "us" (keys are
  lowercased when saved, and Orca's own source carries a TODO about it), and
  **has no regular expressions** -- the question could not be answered from
  the dialog because the answer is no.

  Two kinds of rule:

  1. **Text replacement** -- a literal swap, optionally case-sensitive and
     optionally whole-words-only.
  2. **Regular expression** -- with backreferences, so `#(\d+)` ->
     `number \1` says "number 5" for "#5", while `#([A-Za-z]\w*)` ->
     `hash tag \1` says "hash tag LINUX" for "#LINUX".

  Each rule can be limited to one language, which is the part Orca cannot
  do: a rule for German text need not fire in English.

  Rules are applied in order, with Move Up and Move Down to change it, and
  live outside the extension package in
  `~/.local/share/orca/polyglot/speech_dictionary.json`, because Orca
  approves an extension by hashing its directory.

- **A Test field in the rule editor**, which is the point rather than a
  nicety: a regular expression that does not work gives no clue why, and
  none of it is visible without being read aloud. Typing a sample shows what
  the rule does to it, updated on every keystroke, and the OK button stays
  insensitive while the rule is invalid, with the reason stated.

### Security

- **A runaway regular expression cannot reach the speech path.** A pattern
  like `(a+)+b` against a run of a's does not finish in any useful time, and
  Python's `re` has no timeout to interrupt it with; on the speech path that
  freezes Orca outright, which for a screen reader is the worst failure
  there is. Three layers:

  1. Nested repetition is refused when a rule is saved, with an explanation
     of what to write instead.
  2. Any other pattern is run against inputs built to provoke backtracking
     -- long runs, near-misses -- **in a subprocess with a time limit**, so
     one that cannot be interrupted is killed rather than taking Orca with
     it.
  3. A pattern that survives all that but still takes over 50 ms in use is
     disabled for the session with a warning.

  Layer 1 also guards the apply path, not just the editor, so a rule written
  into the file by hand cannot hang speech either.

### Fixed

- **`tests-language-matrix.py` was testing the wrong detection mode.** It
  set `detection_mode` before calling `install()`, which calls
  `Config.load()` and reads the stored value straight back over it. Every
  run so far has therefore tested whichever mode was saved rather than the
  one it named. The mode is now set after install and can be chosen with
  `POLYGLOT_TEST_MODE`. Results: **markup_text 36/36, always 36/36,
  markup_only 30/36** -- the six failures are the German rows, and are that
  mode's documented behaviour rather than new breakage. See README.

## [2.6.1] — 2026-10-04

### Fixed

- **The braille contraction table was switched to and fro several times per
  focus change.** Found in a real debug log: inside gedit, on a German
  document, `update_braille` reported `en`, `de`, `en`, `de` within one
  second, each switch loading a liblouis table and making a BrlTTY round
  trip. The speech path had resolved the same line as German correctly at
  the same moment, which is what showed the braille side to be wrong rather
  than merely busy.

  The cause: `update_braille` asked for a line from whatever object Orca
  handed it — a frame, a label, a toolbar — and detected a language from
  whatever came back. It now resolves its line through the same
  `_container_line` the speech path uses, which returns None for an object
  that is not text, and leaves the table alone in that case.

  Detection for the line is also now shared with the speech path's cache, so
  the repeated calls Orca makes for one event cost a string comparison
  rather than a fresh detection and a churned word buffer.

### Added

- Four braille rows in `tests-language-matrix.py`: the table follows a
  German line and an English line, a button and a frame do not move it at
  all, and repeated calls for one line do not re-switch. 22 rows in total,
  all green.

  Two flaws in the test harness itself were fixed while writing them, both
  of which would have produced green rows for the wrong reason: the stub for
  `_set_contraction_table` did not mimic the real function's early return,
  so a repeat call looked like a switch; and the braille helper swallowed
  every exception, so a row could pass because nothing had run.

## [2.6.0] — 2026-10-04

Today's run of fixes to character and short-string language resolution had
reached the point where each one broke the last. This replaces the lot with
one rule, and deletes the machinery they had accumulated.

### Changed

- **Text with no language of its own now asks the object it came from,
  rather than consulting remembered state.** A single character, a space, a
  two-letter label: nothing in the text says what language it is. Every bug
  in this area came from the previous approach — a module-level record of
  "the line currently being navigated" that had to be kept in step with
  whatever Orca was actually speaking, and repeatedly was not.

  `_context_language(obj, string)` reads the answer off the structure
  instead, in three cases:

  1. **No object** — nothing to ask, so this is text being typed. The
     current language is right: it is what the accumulating words have been
     teaching.
  2. **An object that is not text** — a button, a menu item. Its label is
     the window's own furniture and belongs in the system language.
  3. **An object that is text** — detect its line. Every character of a
     German paragraph gets the same answer, spaces and punctuation
     included, and it stays right however much unrelated speech happens in
     between.

  Nothing can go stale, because nothing is remembered beyond a cache keyed
  on the line text itself: a different line simply misses.

### Removed

- `_in_char_navigation` and the `speak_character_at_offset` wrapper that set
  it; `_note_navigated_line`, `_navigated_line_language`, `_nav_line_text`
  and `_nav_line_language`; `_string_belongs_to_navigated_line`;
  `_is_single_character`; `_context_language_for_voice`; `_markup_hint_for`;
  and `_reset_language_on_app_change` with its two call sites. All were
  scaffolding for the remembered-record design, and the application-change
  reset is no longer needed at all — case 2 above handles window chrome
  directly.

### Fixed

- **Orca announced roles in the wrong language indefinitely.** Two early
  returns in `_switch_language` — "already the current language" and the
  re-entrancy guard — were both reached before `_set_orca_names_locale`, so
  Orca's own vocabulary could stay stuck on German ("Schaltfläche" for
  "button") long after the voice had returned to English. Worse, that
  German then fed straight back into detection, which is its own reason for
  the language to stick. The names locale is now set before either return;
  it is cached and idempotent, so the cost is a comparison.

### Added

- `tests-language-matrix.py` — every case checked in one run, as a table.
  Each fix today was verified in isolation and broke another case that was
  not being checked at the same time; this is the thing that should have
  existed first. 17 rows: characters of German, English and Russian lines
  including spaces, with the current language variously poisoned; a Cyrillic
  character inside a German line; sixteen UI labels; a German UI phrase;
  typing starting from the previous language and learning; whole-line
  detection; number-heavy text not splitting; real mixing splitting; and the
  names locale tracking the language.

## [2.5.1] — 2026-10-04

### Fixed

- **Character reading broke again in 2.5.0.** Preferring the default
  language for text that is not part of the remembered line was right for a
  button label and wrong for a character: a character is always being read
  out of some line, so when the line is not on record the language in use is
  the best thing left, and the default is certainly wrong. One character is
  now excluded from that fallback — the length of the string is what tells a
  character being spelled from a label like "OK".

- **Per-character membership testing removed from the character path.**
  Asking whether a character occurs in the remembered line is nearly
  useless, since almost every letter occurs in almost every line: it mostly
  answers yes, and answers inconsistently across the characters of one
  line — the same flicker as 2.2.2. The record is kept current by
  `_note_navigated_line` on every navigation keystroke, so it is simply
  trusted. Membership is still tested for multi-character strings, where it
  is cheap insurance against a label borrowing from a line.

- **The application-change reset no longer clears the remembered line.** It
  runs from the voice path, which is reached *after* the navigation path has
  resolved the line for that keystroke, so clearing there threw away a
  record just set and the first character announced after every application
  change lost its language. Resetting the current language is enough; the
  record cannot mislead for long, because a navigation keystroke refreshes
  it and a label has to pass the membership test to borrow from it.

  Confirmed this was never what fixed the labels: with the clearing gone,
  0 of 18 remain correct after tabbing.

### Verified

Five character-navigation scenarios, all 0 wrong and 0 mid-line changes:
record present; record cleared with the current language German; a stale
record refreshed by navigation; the current language poisoned to English;
and spaces specifically. Plus labels correct in the same window and after
tabbing, typing still learning, and the detector suite unchanged.

## [2.5.0] — 2026-10-04

### Fixed

- **Short button labels were read in the German voice when tabbing between
  windows.** "OK", "Go", "Up" and "No" are all under three characters, so
  there is nothing in them to detect a language from — and the context they
  fell back to was still whatever the last document had established. Four
  of twenty-four common UI labels came out German after reading a German
  page.

  Three changes, each closing a different part of it:

  1. **Focus moving to another application returns the language to the
     default and forgets the remembered line.** A window's chrome is in the
     system language, not in the language of whatever was last read. Orca
     keeps one script per application, so the active script changing is the
     signal — an identity comparison, no AT-SPI round trip.
  2. **A remembered line may only lend its language to its own text.** Every
     character of a German line passes, spaces included; a button in some
     other element does not. Where it does not, the default language is
     preferred over whatever was last spoken, because there is no positive
     evidence for anything else. (This is a per-*string* test, unlike the
     per-character one that made characters within a line disagree in
     2.2.2.)
  3. **Markup is consulted for text with no content, even in Always mode.**
     That mode means "do not trust markup over our own reading of the text",
     not "ignore it when we have no reading at all".

  Making that work needed one more thing: `detect` returns the current
  language when it has nothing to go on, which silently masked all of the
  above. It is now asked for a plain "no" when the text has no content, via
  the new public `language_detector.has_content`.

  Measured: tabbing from a German document to another window, 0 of 18
  labels in the wrong language (was 4); short labels in the *same* window as
  German text also now English; and the German line itself still reads
  entirely in German, spaces included.

## [2.4.1] — 2026-10-04

### Fixed

- **Spaces and punctuation on a non-English line were announced in English.**
  A side effect of 2.4.0. Stopping single characters from being
  content-detected was right, but detection was also the only thing tagging
  the character's voice with a language — so `SpeechGenerator.voice` fell
  through to Orca's own resolution, which reads the language from the text
  attributes at that offset, finds nothing in an unmarked document, and
  uses the global voice.

  That matters most for characters with no sound of their own. The name a
  space or a comma is given comes from Speech Dispatcher's symbol table for
  whichever language the voice is set to, so an English-voiced space is
  announced "space" in the middle of a German sentence.

  A string too short to detect from now takes its language from context
  instead: the line being navigated, or the current language. Nothing is
  detected, so the per-character flicker stays fixed.

  Measured on a 44-character German line, counting the language on each
  announcement as it reaches the speech server: all 44 now go out as German,
  including all 7 spaces, and they still do when the current language has
  been left on English by something else.

- **Typing is excluded from that**, by the same test as everywhere else: an
  object to read the character from means existing text, no object means
  typing. Otherwise a single typed character would have taken the language
  of whatever line the caret was last on, undoing the learning. Verified:
  typing English after a German line still starts German and settles on
  English.

- **Characters Polyglot names itself** — arrows, box drawing, emoji — were
  spoken with `acss=None`, which is the global voice for the same reason.
  They now carry the current language, so an arrow in a German line is
  named in German.

## [2.4.0] — 2026-10-03

### Fixed

- **Characters were still being detected individually, so the voice changed
  from one keypress to the next.** Two causes, both independent of the 2.3.1
  fix:

  1. `SpeechGenerator.voice` ran full content detection on whatever string it
     was given — **including a single character**. The word lists decline on
     one letter, but Lingua will happily name a language for it, and letters
     are shared between languages, so the answer was close to a coin toss.
     Asked once per keypress while arrowing along a line, that is exactly
     "processing each individual character every time it is read". Text
     shorter than three characters is now never content-detected; the script
     tier is unaffected, so a lone Cyrillic letter is still Russian.

  2. **Web content never took the path that knew about lines.** Caret
     navigation goes through `speak_character_at_offset`, but
     `scripts/web/script.py` announces navigated characters by calling
     `speak_character` directly, so the navigation flag was never set and
     browsing looked like typing. Navigation is now recognised by Orca
     passing an object to read the character from — typing echo passes none
     — which covers web content, spelling and flat review as well as caret
     navigation.

  Measured on the web path, which was the one still flickering: German,
  English and German lines again, 0 mid-line language changes in each.

### Removed

- **The "Switch pause (seconds)" setting is gone.** It and its
  `time.sleep()` dated from the initial release with no recorded rationale,
  and the duration never had a purpose: each utterance already carries its
  own voice before being queued, and separate utterances already produce an
  audible break. What it was really asking — whether to mark the boundary
  between two languages — is now answered by Orca's own **insert pauses
  between utterances** preference, which is the same question, and still
  skipped at punctuation level "all" so the full stop is not read aloud.
  The stored key is reset on the first save.

## [2.3.1] — 2026-10-03

### Fixed

- **Characters within one line disagreed about their language.** 2.2.2 decided
  whether to trust the remembered line by asking whether the character being
  spoken appeared anywhere in that line's text. That is a *per-character*
  test, so whenever the record was stale the answer depended on which letters
  happened to occur in the previous line — and letters are shared between
  languages, so the answer changed from keypress to keypress. Reading an
  English line with a stale German record gave this, for 57 characters:

  ```
  DDDDDEDDDDDDDDEDDDDDDDEDEDDDDEDDDDDDDDDEDDDDDDDEEDDDDDDDD
  ```

  Fourteen language changes inside one line, 49 characters wrong.

  The record is now keyed off the **line**, not the character: the navigation
  entry point resolves the line for the object and offset Orca is announcing,
  re-detects it only when it has actually changed, and every character in that
  line then gets the same answer. Measured across German, English and Russian
  lines, and an English line whose every letter also occurs in the German one:
  **0 mid-line language changes** in all of them. A Cyrillic character still
  overrides on script, and a notification arriving mid-line no longer disturbs
  the rest of it.

  Kept apart from the `_focus_line_*` snapshot, which belongs to the braille
  flash save/restore and must not be written from the speech path.

### Changed

- The language-boundary marker now **ends the previous segment** instead of
  opening the next one, which is both how Orca does it and acoustically what
  is wanted: the sentence break is spoken in the voice that is finishing, not
  the one starting. Segments are therefore queued one behind, so a segment can
  be marked once the following one is known to be in another language.

## [2.3.0] — 2026-10-03

### Fixed

- **Speech and the keyboard froze on mixed-language lines.** The
  mixed-language path called `time.sleep(language_switch_pause)` on Orca's
  main loop between segments, once per language change. At the default 0.3s
  that is 0.3s of frozen keyboard, AT-SPI and speech per switch — and a
  156-word alternating line produces 23 switches, so **6.9 seconds** of dead
  main loop for one line. Measured.

  Replaced with Orca's own idiom for a pause: end the previous utterance and
  let the synthesiser's sentence prosody provide the gap, exactly as
  `speech_generator._generate_pause` does, and skipped at punctuation level
  "all" for the same reason Orca skips it. The separate speak calls already
  produced an audible break, so nothing is lost. **The setting is no longer
  a duration** — any value above zero marks the boundary, 0 leaves it
  unmarked. Its label is unchanged.

- **Numbers were read as German.** `detect_multiple_languages_of` is handed
  the raw text, noise and all — it has to be, since character offsets are
  needed back — and on number-heavy prose it mislabels badly. "I have 1
  apple 2 oranges 3 pears 4 plums and 5 bananas in the basket" came back as
  German for the first half, with no German in it at all. That spurious
  switch then triggered the sleep above, which is why numbers and freezing
  arrived together.

  Mixed-language segments are now weighed against the word lists, which have
  the final say when they are sure, and neighbours that then agree are
  merged back into one segment. Four number-heavy English lines that used to
  split no longer split at all; genuinely mixed German and Russian text still
  splits correctly.

### Changed

- **Typing analyses again, as it did before 2.2.2.** Reading a character and
  typing a character both arrive at `speech_presenter.speak_character` and
  are otherwise indistinguishable, but they want opposite things: a
  navigated character belongs to a line whose language is known, while a
  typed one has no line yet — only what has been typed so far, whose
  language has to be learned as it grows. 2.2.2 gave both the line's
  language, which fixed navigation and broke typing.

  Orca separates them one level up: caret navigation and flat review go
  through `speak_character_at_offset`, while typing and key echo call
  `speak_character` directly. Wrapping the former is enough to tell the two
  apart. Navigation reads the line's language; typing goes back to the
  ordinary detection chain, so it starts in whichever language was previous
  and switches as the words accumulate.

  Measured: navigating a German line after an English utterance, 0 of 10
  characters wrong; typing English after a German line starts German and
  settles on English by the fourth character; typing German after an English
  line does the reverse.

## [2.2.2] — 2026-10-03

### Changed

- **A character is now read in the language of the line it is in.** A single
  character has no language of its own -- a Latin letter is a Latin letter --
  so character announcements had nothing to go on and fell back to
  `_current_language`, which is volatile: any utterance between two
  keystrokes (a notification, a status message, a role name) moves it. The
  result was arrowing through a German line and hearing every letter, and
  every comma and space, in English.

  The line's language was already being detected and recorded, in
  `_record_focus_line_state`, but only the braille flash save/restore ever
  read it. Character announcements now consult it, and the recorded line
  text goes with it so a character that cannot have come from that line
  falls back rather than trusting a stale record.

  The resolution order for a character is now: the language Orca resolved
  from markup (except in **Always** mode, which ignores markup by
  definition), then the character's own Unicode script, then the line's
  language, then the current language, then the default. The script still
  outranks the line, so a Cyrillic letter inside a German line is read as
  Russian.

  Measured, arrowing through a German line after an English utterance has
  moved the current language: 16 of 16 characters read in the wrong
  language before, 0 of 16 after.

### Fixed

- The markup language hint in character announcements was compared raw, so
  Orca handing over `en-GB` or `de_DE` never matched a configured language
  and the hint was silently discarded. It is now normalised the same way
  the rest of the add-on normalises language tags.

- The character-language chain in **Markup only** mode had an unreachable
  branch: it assigned the default language before trying the Unicode-script
  fallback, so the fallback could never run. All modes now share one chain.

## [2.2.1] — 2026-10-03

### Fixed

- **Everything was read in the last foreign voice used.** 2.2.0 emitted an
  utterance carrying only a language, on the assumption that Orca would
  always supply a voice. It does not, and cannot: `apply_voice_set` has
  nothing to add for a language with no voice set, and it deliberately
  never maps a language onto the global set — so the user's main language
  got no voice at all.

  Speech Dispatcher's synthesis voice is connection state.
  `speechdispatcherfactory._set_family` sends `set_synthesis_voice` only
  when the family carries a name, and never clears it. Recorded what
  actually reached the server for `de -> en -> ru -> en`:

  ```
  de: set_synthesis_voice('viktor-embedded-high')   set_language de
  en: *** nothing ***                               set_language en
  ru: set_synthesis_voice('yuri-embedded-high')     set_language ru
  en: *** nothing ***                               set_language en
  ```

  So every English utterance after a German or Russian one was spoken by
  that voice. `set_language` could not rescue it, a single-language
  embedded voice ignoring it. This is what made line reading erratic,
  punctuation come out in the wrong language, and typing echo sound German
  or Russian on English text.

  Polyglot now names a concrete voice for every language it switches to,
  taken from Speech Dispatcher when the user has no voice set for it. A
  configured voice set still overrides it — `apply_voice_overrides` merges
  the set's family over ours — so tuned voices are untouched.

- **Short utterances could not get back to the default language.** The
  word-threshold rule is meant to stop a stray line dragging the voice off
  the language you mostly read; it was also making the way back just as
  slow. A one-word utterance had to be matched by a run of agreeing
  detections, so after a single German line every short English utterance
  kept being read in German. Typing echo, arriving one word at a time, was
  the worst case, and character echo never recovered at all, having no
  content to detect from. Returning to the default language is now
  immediate on confident evidence.

- **Word-list evidence now outranks Lingua on short text.** Measured on
  single words, Lingua is confidently wrong often enough to matter — it
  calls "Kaffee" English at 0.91 and "Zucker" English at 0.94 — while the
  word lists have both as German-exclusive and are right. A verdict too
  thin to conclude but unambiguous (words from one language's list and no
  other's) now claims the answer rather than letting Lingua have it, and
  still goes through the stability rule.

  Measured effect, reading a German sentence word by word after making
  "return to default" cheap: 5 of 10 words wrongly read as English before
  this, 0 of 10 after. Typing English after a German line: 8 of 10 words
  wrong in 2.2.0, 2 of 10 now (the two being "I" and "am", which no word
  list claims). The dictionary tier's score on short UI fragments rose
  from 12/16 to 16/16.

## [2.2.0] — 2026-10-03

### Changed

- **Voices are Orca's job now.** Polyglot no longer stores a voice, rate,
  pitch or volume per language. It tags each utterance with nothing but a
  language, and Orca 51's `speech_manager.apply_voice_set` overlays the
  matching voice set — which the user configures in Orca's own
  **Voice Sets** preferences, with Orca's own previews and keybindings.

  Measured: an ACSS carrying only `lang='de'` comes back from
  `apply_voice_set` as `viktor-embedded-high` at the configured rate,
  pitch, inflection and volume. A language with no voice set still works —
  Speech Dispatcher is told to switch language and picks its own voice.

  This also fixes a quiet old trap: a language used to be skipped unless it
  had a voice name stored, so enabling one without choosing a voice meant
  it silently never switched. Ticking it is now enough.

- **The Languages page is a list of tick boxes and braille tables.** The
  per-language "Customize..." dialog is gone, because voice, rate, pitch
  and volume all moved to Orca. The braille contraction table is the one
  per-language setting voice sets do not cover, so it stays — inline on the
  row rather than behind a dialog that would otherwise hold one combo box.

- Uppercase, hyperlink and system voice types are now handled by Orca's own
  per-voice-type lookup inside the voice set, rather than by Polyglot
  overlaying them itself.

### Added

- **A one-time import of the old per-language voices into Orca voice
  sets**, so upgrading does not silently discard tuned voices. It is
  deliberately conservative: a language Orca already has a voice set for is
  left alone, the default language is skipped (the global set already is
  the main voice), and volume is only copied when it falls within Orca's
  0–10 range, because Polyglot's spin button allowed 0–100 and a larger
  number cannot be trusted to mean the same thing.

- `available_voices.py` — 73 lines that answer the one question left after
  the above: which languages Speech Dispatcher has a voice for. Replaces
  `voice_mapper.py` (293 lines), which discovered every voice, parsed
  Orca's `user-settings.conf` by hand (with a lenient JSON fallback for
  when that file is malformed) and maintained a voice table.
  `config_ui` now shares this instead of carrying a second copy of the
  Speech Dispatcher query.

### Removed

- `voice_mapper.py`, `VoiceMapper`, `get_mapper()`, the per-language ACSS
  cache, `auto_configure_from_profiles`, `sync_from_voices`, and
  `LanguageSettingsDialog`.
- The `voice-name`, `voice-lang`, `voice-dialect`, `rate`, `average-pitch`
  and `gain` settings per language. They are pruned from the store on the
  first save after the import above.

### Fixed

- **Per-language settings were never pruned from the store.** The prune
  path had a `get_all_keys()` fast path and a fallback for stores without
  one; `ExtensionSettings` has no such method, so the fallback was the only
  path ever taken — and it worked out which languages to prune from
  `enabled_languages`, which by save time no longer contains the language
  the user had just unticked. Nothing was ever removed. `Config` now
  remembers the languages the store was loaded with.

## [2.1.0] — 2026-10-03

### Added

- **Dictionary-based language detection.** A third detection tier that
  decides by counting word-list membership: of the words on this line,
  how many are in the German list and in no other? No model, no
  training, no confidence score — just set membership, so a wrong answer
  can always be explained by naming the words that caused it.

  The decision is made on *exclusive* words — those held by exactly one
  enabled language. Shared vocabulary ("Information", "Radio") is real in
  both languages and so tells us nothing, while "der" and "the" each
  settle the matter on their own.

  Three 30,000-word lists come to under 1 MB and answer in about 0.03 ms,
  against Lingua's 292 MB shared library and 0.11 ms on the same text.

- **`fetch-dictionaries.sh`** installs the word lists into
  `~/.local/share/orca/polyglot/dictionaries/<lang>.txt` — plain text,
  one word per line, most frequent first, meant to be read and edited.
  They live in the data directory rather than the extension package
  because Orca approves an extension by hashing every file in its
  directory, so a list added after install would un-approve the add-on.

  The lists are cross-pruned as they are written. A subtitle corpus is
  full of the other languages — "this" is the 17th most common word in
  the English list and the 5262nd in the German one, because German
  subtitles quote English — and left in, those words destroy the signal
  entirely. A word is dropped from a language when another language ranks
  it at least 5x more highly.

  A hunspell/myspell `.dic` is used for any language with no list of its
  own. Those hold stems rather than written forms ("Haus" is listed,
  "Häuser" is not), so a frequency list beats them for this purpose.

- **Configurable detection order** (Settings → Detection → Word Lists).
  Script first is right when each script belongs to one language —
  Cyrillic text is Russian, and no word list improves on that. Word lists
  first is right when two enabled languages share a script, since Russian
  and Ukrainian are both Cyrillic and only the words can separate them.

- **Word-list tuning**: words unique to one language (default 2), minimum
  share of those words (default 0.60), and most common words to load
  (default 30000).

### Changed

- `LanguageDetector.detect` now walks a configurable list of tiers
  instead of a hardcoded script-then-Lingua pair. The word-threshold
  stability rule moved into a shared `_commit`, so one knob governs how
  twitchy every content-based tier is.

- The dictionary tier is inactive until word lists for at least two
  languages are installed. With one list, every hit would win and every
  unknown word would look like a miss, so it stays out of the chain.

- Word lists count as content-based detection, so they are consulted only
  in the **Markup + text** and **Always** detection modes. **Markup only**
  still runs Unicode script detection alone.

- `emoji` dependency upgraded to 2.16.0. `lingua-language-detector` 2.2.0
  is current.

### Fixed

- `detect(fallback_to_current=False)` now really does return `None` when
  no tier finds a signal. The Lingua tier used to return the current
  language from several of its own exit paths, which the documented
  behaviour said it would not do.

## [1.1.10] — 2026-05-12

### Fixed

- **Multi-component emoji names (ZWJ sequences) like
  `:family_man_woman_girl:` no longer mangle when preceded by a
  literal label colon.** `_expand_emojis`'s regex was
  `r":([^:]+):"` — character class excluded colons but not
  whitespace. For input "Family: :family_man_woman_girl:", that
  greedily matched `": :"` (label colon, space, emoji's leading
  colon) before reaching the real emoji name, eating its start
  and leaving the rest unmatched. Symptom: ZWJ family sequences
  rendered as `"Family family_man_woman_girl:"` with underscores
  un-substituted and a trailing colon. Fix is a one-character
  regex tweak — `[^\s:]` instead of `[^:]` — so the emoji name
  match can't span whitespace.

  Now reads cleanly:
  - `"Family: 👨‍👩‍👧"` → `"Family: family man woman girl"`
  - `"Reactions: 👨‍👩‍👧‍👦 then 🇬🇧"` →
    `"Reactions: family man woman girl boy then United Kingdom"`
  - Label colons in non-emoji contexts (URLs, times like
    `12:30`, `var:value`) pass through untouched.

## [1.1.9] — 2026-05-12

### Fixed

- **Flag emoji (regional-indicator pairs) silently dropped from
  speech and braille after v1.1.8.** The v1.1.8 regional-indicator
  silencing in `_is_invisible_formatting` fired in
  `_expand_unpronounceable`, which runs in
  `presenter.adjust_for_presentation` — that's *upstream* of
  `_patched_speak`'s `_expand_emojis` call. So the regional
  indicators were stripped from the text before the emoji module
  ever saw them, and the flag was never resolved to its country
  name. Symptom: a chat message ending in `🇬🇧` produced silence
  instead of "United Kingdom".
- **Fix**: `_expand_unpronounceable` now runs whole-string emoji
  expansion FIRST (idempotent — if `_patched_speak` runs it again
  later, the second call no-ops). Multi-codepoint sequences
  (flag pairs, heart+VS-16, ZWJ family sequences) get resolved to
  their full names while their constituent codepoints are still
  intact. Orphan regional indicators (a single unpaired letter)
  still get silenced in brief mode, since they're not part of a
  valid emoji sequence.

## [1.1.8] — 2026-05-12

### Changed

- **Brief-mode Unicode announcements now silence variation
  selectors and regional indicator letters.** Both were leaking
  through the existing invisible-formatting filter because
  variation selectors are category Mn (combining mark) and
  regional indicators are So (other symbol) — neither caught
  by the catch-all Cf check.
  - **Variation selectors** U+FE00..FE0F + U+E0100..E01EF.
    VS-16 in particular is attached to most emoji to request
    emoji-style rendering; you'd hear "red heart variation
    selector 16" instead of just "red heart". Now: silent in
    brief, still named in verbose for users who need to know.
  - **Regional indicator letters** U+1F1E6..1F1FF. Pairs of
    these form flag emojis ("🇬🇧" = "G" + "B" → UK flag); the
    emoji module resolves complete pairs into country names in
    line reading. Reading each letter individually as "REGIONAL
    INDICATOR SYMBOL LETTER G" added noise without information.
    Now: silent in brief, still named in verbose.

Verbose mode is unchanged — both ranges still announce by name
for users who want to know about every codepoint. Skin-tone
emoji modifiers (U+1F3FB..1F3FF) are left as-is: they carry real
semantic content and already read tolerably ("medium skin tone"
etc.) via the emoji module.

## [1.1.7] — 2026-05-12

### Fixed

- **Flash restore no longer undoes legitimate post-flash language
  switches.** When a flash message (e.g. "Focus mode" on app
  switch) was active and the user navigated into content of a
  different language during the flash, `_patched_speak` correctly
  switched braille tables to the new language — and then the
  flash's `_restore_pre_flash_state` ran on flash expiry and put
  the tables back to the pre-flash values. The user had to bump
  the caret (line up + line down) to trigger another
  `update_braille` and re-switch the tables. Symptom traced
  live in the debug log:

      _speak: trust acss lang=de text='Versuchen wir, …'
      _set_contraction_table: en -> de           ← correct
      _set_brltty_text_table: en -> de
      _set_contraction_table: de -> en           ← flash restore stomped it
      _set_brltty_text_table: de -> en

  Restore now checks two conditions before applying: (a) the
  tables are still at the flash-default values (no speech-side
  switch has happened), AND (b) `_focus_line_*` is unchanged
  (no `update_braille` has fired for a new line). If either
  changed during the flash, the current state already reflects
  the right language for what the user is doing — leave alone.
- Dropped `_current_language` and `_current_names_locale` from
  flash save/restore. Those are speech-side state and self-
  correct on the next voice resolution. Restoring them
  unconditionally was the secondary mechanism causing the
  symptom above to feel "sticky" even after a single caret
  movement (it took a `update_braille` to fully clear).

## [1.1.6] — 2026-05-12

### Changed

- **The "Split mixed-language text into segments" setting is now
  the single switch for mid-line language changes.** With it
  **off** (default), every line speaks (and brailles) in its
  dominant language — the value `AXObject.get_locale` reports for
  the paragraph / line obj. With it **on**, per-segment markup
  and Lingua-driven splitting can flip mid-line as before.
  - `_patched_voice` ignores `args.language` (range-specific
    markup from `generate_line`'s `split_substring_by_language`)
    in non-mixed mode. Falls through to obj-locale, which is one
    consistent value per line.
  - `_patched_speak` trusts the ACSS family.lang voice() resolved
    in non-mixed mode. Skips per-utterance text detection, which
    was the source of word-navigation language flips on
    statistically-ambiguous short text. The "Words before
    switching" threshold becomes largely advisory in non-mixed
    mode; switches still happen but at line boundaries (where
    update_braille drives them), not per word.

Fixes the user-reported pattern: "word navigation sometimes
thinks I'm reading English, then line navigation correctly says
German" — the line's obj-locale is consistent; only per-utterance
detection on a single word's worth of text was ambiguous.

The mixed-language checkbox stays as the user-facing knob for
"I have multilingual content and want mid-line switching".

## [1.1.5] — 2026-05-05

### Fixed

- **`_switch_language` no longer short-circuits braille work when
  the same language has already been set with `also_braille=False`.**
  Speech-side patches pass `also_braille=False` so they don't flap
  tables mid-utterance; they still update `_current_language`.
  When `_patched_update_braille` then called `_switch_language` for
  the same language with the default `also_braille=True`, the early
  return `if lang_code == _current_language: return` fired *before*
  reaching the braille block — so tables stayed on the previous
  language indefinitely. Symptom: caught live on the user's debug
  log:

      _switch_language: en -> de (also_braille=False)
      update_braille: detected=de         ← never followed by a set_contraction_table

  Fix: only short-circuit when the caller doesn't want braille
  switched. If `also_braille=True`, fall through so the table-
  level helpers can decide whether they're actually no-ops (they
  already short-circuit on identical values, so this is cheap).

## [1.1.4] — 2026-05-05

### Fixed

- **`_patched_speak` now switches braille tables again** (reverts
  the `also_braille=False` from v1.1.2 for this patch only).
  v1.1.2 disabled it to fix the flash-snapshot bug; v1.1.3
  introduced the `_focus_line_*` tracker which makes the flash
  snapshot correct *regardless* of what speech-side patches do.
  With that protection in place, restoring v1.1.0's speech-driven
  table updates is safe — and it restores speech's role as a
  "second pass" that corrects any miss from `update_braille`.
  Symptom this fixes: in *always* mode (Lingua statistical
  detection), braille tables would lag a long way behind speech
  — German content reading in default tables for half a passage
  before switching, and not switching back to default until well
  past the word threshold.
- **`_patched_speak_character` markup-only fallback chain** —
  removed the `_focus_line_language` step that v1.1.3 added,
  reverted `detect_character` to `fallback_to_current=True`. The
  `_focus_line_language` tracker was stale on intra-line caret
  movement (update_braille doesn't fire there), so it could
  point at a previous line's language. The detector's own
  `_current_language` is kept fresh by speech and is the better
  per-character fallback.

`_patched_voice` keeps `also_braille=False`. Voice() is called
per-segment in mixed-language line reading; if it switched braille
each call, the line's braille would flap mid-line between
segment languages. The line should braille in one language (the
dominant or first), set once by `update_braille`. Speech-side
calls (speak, speak_character) are different — they're per
utterance / per character within a single language context, so
their table updates are corrective, not flappy.

## [1.1.3] — 2026-05-05

Restores two pre-v1.1.2 behaviours that the v1.1.2 architectural
change accidentally regressed, by introducing a "focus line"
state tracker that decouples flash-message correctness from
speech-side mutations.

### Fixed

- **Character navigation now updates braille tables again.** v1.1.2
  blanket-disabled braille-table switching from speech-side patches
  to fix a flash-message snapshot bug. But Orca's `update_braille`
  doesn't always fire on intra-line caret movement, so the braille
  table stayed stale during character navigation and the user had
  to scroll line-by-line for braille to track language changes.
  `_patched_speak_character` now switches braille tables again
  (the bug it was indirectly causing is fixed differently — see
  next entry).
- **Character speech now falls back to the focus line's language
  before defaulting.** When `voice()` couldn't resolve a markup
  language for a single character and the character itself had no
  script signal (i.e., plain Latin in a markup-tagged line), the
  fallback chain hit "default language" — so a Latin character in
  a German-marked line would silently read in English. Chain is
  now: voice()'s ACSS family.lang → Unicode-script detection →
  focus-line language → default. Closes the "markup reads right
  on line, but character navigation reads English" gap.
- **Flash-message snapshot now reads from a focus-line tracker
  rather than `_current_*`.** This is what makes the two fixes
  above safe to ship together. `_record_focus_line_state` runs
  inside `_patched_update_braille` after the language switch, and
  the flash hook saves/restores that snapshot — so speech for the
  flash message can perturb `_current_*` (which it does, because
  `_patched_speak` still detects the flash language) without
  contaminating the saved focus-line state. The v1.1.2 fix
  prevented contamination by stopping speech-side patches from
  touching braille at all; this release prevents it via state
  separation instead, which is the right architectural answer.

## [1.1.2] — 2026-05-05

Polish release fixing one **High** issue and a handful of **Medium**
and **Low** items that surfaced in a follow-up audit of the v1.1.1
flash-message work.

### Fixed

- **Flash message snapshot was taken too late.** Orca calls
  `speech.speak()` *before* `braille.display_message()`, and our
  `_patched_speak` was switching braille tables as a side effect of
  detecting the flash text's language. By the time
  `_patched_display_message` snapshotted the "current" tables, they
  were already the flash's language, not the focus line's — so the
  later "restore" put braille onto the wrong tables for a window
  after the flash. Symptom: focus on an English line, German
  notification arrives, after the flash the still-displayed English
  line was in German contraction / BRLTTY tables until the next
  AT-SPI event triggered `update_braille`. **Fix at the root**:
  `_patched_speak`, `_patched_speak_character`, and `_patched_voice`
  no longer touch braille tables (`_switch_language` accepts an
  `also_braille=False` argument they all pass). `_patched_update_braille`
  is now the sole authority for the contraction + BRLTTY text tables;
  the snapshot at flash entry is correct by construction.
- **Flash patches now wrap their bodies in try/except and respect
  `_config.enabled`** — bringing them in line with every other
  monkey-patch in the module. A transient error in our save/restore
  no longer prevents Orca's flash from rendering.
- **Flash-state save/restore now covers `_current_language` and the
  symbol-name locale**, not just the two braille tables. After a
  flash, character announcements no longer use the flash's name
  locale ("Komma" for a comma in an English line).
- **Replaced the dual-`None` "in flash" gate with an explicit
  `_in_flash` boolean**, fixing a sentinel collision where the very
  first event after Orca startup could "save" `(None, None)` and
  leave the state machine confused.
- **`_set_contraction_table` no longer caches the new value before
  the underlying call succeeds.** A transient liblouis error would
  previously leave the cache claiming a successful set, suppressing
  future same-value calls.
- **`_switch_to_default_braille_tables` now switches contraction +
  BRLTTY together or not at all** — half-switched states (BRLTTY on
  one language, contraction on another) produced wrong braille.
- **`_patched_kill_flash(restore_saved=False)` now restores
  pre-flash state too.** Caller-overwrite is a harmless cache hit;
  caller-no-overwrite (detection_mode=off, empty text, short-circuit
  paths) gets the right tables instead of leaving the flash's tables
  to stick.
- **Detection mode "Off" now writes `detection_mode = "off"`**
  instead of leaving the prior value in place. State transitions are
  cleaner; no behavioural change in normal use.

### Removed

- Dead constant `_STATISTICAL_MODES` in `config.py`.

## [1.1.1] — 2026-05-05

### Fixed

- **Flash messages now use the default-language braille tables** and
  revert when the focus line is restored. Previously, a flash
  (notification, time announcement, mode string) inherited whichever
  braille tables were active for the focus line — so a German line
  followed by an English notification flashed in German contraction,
  or with German computer-braille text-table mappings on BRLTTY.
  Worse, after the flash, the line content sometimes stayed on the
  flash's tables until the next caret movement. Now: on
  `display_message`, contraction (liblouis) and BRLTTY text table
  switch to the default language; on `_flash_callback` and
  `kill_flash(restore_saved=True)`, both tables restore to whatever
  was active before the flash, *before* Orca re-renders the focus
  line.

## [1.1.0] — 2026-05-04

### Added

- **Detection-mode combo** replaces the previous on/off toggle. Four
  values:
  - **Off** — never switch language. Emoji and Unicode-character reading
    still work.
  - **Markup only** — trust language tags from documents and Orca (which
    include AT-SPI text-attribute language and Orca 50's own markup-aware
    detection), plus deterministic Unicode-script detection for non-Latin
    scripts (Cyrillic, Arabic, BRAILLE, IPA, …). Skips statistical
    detection — short technical text is no longer misclassified.
  - **Markup + text** *(default)* — markup or script signals, plus Lingua
    statistical detection on plain Latin-script text. This matches the
    previous default behaviour.
  - **Always (ignore markup)** — never trust markup hints; always run our
    own full detection. Useful when document `lang` attributes are stale.
- **Object-locale fallback.** When `voice()` is called without an explicit
  language argument (paragraph and phrase reads via Ctrl+Up/Ctrl+Down),
  Polyglot now consults `AXObject.get_locale(obj)` — the same path
  Orca's built-in resolver uses — so per-language voice profiles and
  braille tables follow paragraph navigation, not just line navigation.
- **Localised symbol announcements.** When the active language changes,
  Orca's character/symbol-name modules (`mathsymbols`, `keynames`,
  `cmdnames`, …) reload under that locale via `setLocaleForNames`.
  Reading German content announces "Komma" with the German voice;
  switching back to English content reverts to "comma". Cached so the
  reload only fires on actual locale transitions.
- **Unicode braille auto-detection.** Lines made of U+2800–U+28FF braille
  pattern characters automatically switch the liblouis contraction table
  to `unicode-braille.utb` so the raw dot patterns are preserved on a
  refreshable display. No manual setting change needed for transcription
  work.
- **Configurable mixed-language word cap** (Detection page → Mixed
  Language → "Max words for mixed-language detection", default 600). Long
  multi-language lines no longer hang Orca on Lingua's high-accuracy
  splitter.
- Per-sentence and per-word chunking for mixed-language detection on
  long text — Lingua now sees short chunks individually instead of one
  monolithic call.
- Language-code normalisation across BCP 47 (`de-DE`, `en-Latn-US`),
  POSIX locale (`de_DE`, `de_DE.UTF-8`, `de@variant`), and stray casing
  variants. All collapse to a bare ISO 639-1 code.
- `is-configured` GSettings sentinel so deliberately clearing every
  language is no longer treated as a fresh install on next start.

### Fixed

- **BRAILLE and IPA auto-switching now actually fire** from the
  dispatcher. The contraction-table swap was wired up at every layer
  except the topmost `detect()` check, which gated on
  `enabled_languages` and so silently rejected the sentinel codes.
- **Markup-only mode no longer keeps a stale voice across context
  switches** (alt-tab, app changes, paragraph navigation). The detector's
  internal "current language" stayed out of sync with the speech
  interceptor's, so `_patched_speak` would echo the previous language
  whenever there was no script signal in the new context.
- **First-run auto-config writes to the correct contraction-table key**
  (`contraction_table`, not the orphaned `braille_table`); the
  auto-discovered braille table from existing Orca per-language profiles
  is no longer silently dropped on first save.
- **Sentinel script mappings populated on first run** — IPA and BRAILLE
  rows on the Scripts page no longer require a second Orca launch to
  appear.
- `_load_gsettings` no longer clobbers `script_to_language` defaults when
  the GSettings store has the schema's empty default.
- `_extract_default_profile_settings` resolves `rate`, `average-pitch`,
  and `gain` independently across `profiles.default` and `general`. A
  profile that only set `rate` no longer shadows `general`'s pitch and
  gain.
- `_patched_voice` now guards `_detector` against `None` so debug logs
  don't fill with `AttributeError`s when the addon is enabled but no
  languages are configured yet.
- `_patched_say_all` guards `_config` against `None` (consistent with
  every other patch entry point).
- Removed dead `_patch_braille_refresh` function (defined but never
  called; reached into Orca-internal `_STATE.lines`).

### Changed

- `_patched_speak` markup-only path now only overwrites the caller's ACSS
  when no ACSS was passed in, matching `_patched_speak_character`'s
  policy. Preserves uppercase/hyperlink overrides voice() merged in
  upstream.
- `LanguageDetector.detect()` and `detect_character()` accept a
  `fallback_to_current` kwarg. With `False`, callers get `None` for
  no-signal text instead of a stale previous language. Side-effect-free
  in this mode — the detector's `_current_language` is no longer
  mutated as a side effect of a fallback=False call.

## [1.0.0]

Initial release.
