# Polyglot for Orca

An add-on for the [Orca screen reader](https://wiki.gnome.org/Projects/Orca) on Linux that enhances speech and braille with automatic language switching, emoji reading, and Unicode character pronunciation.

**This version is for Orca 51** (GNOME 49+), where it installs as a user extension. Version
1.x loaded itself from `orca-customizations.py` and is what to use on Orca 50 and earlier.

## Why this add-on when Orca has built-in language switching?

Orca switches voice when a document *tells* it the language. Polyglot is for everything else:

- **Detection, not just markup** -- Orca needs a language tag. Polyglot reads the text itself:
  Unicode script, then word lists, then a statistical model, in an order you choose. Most text
  on a Linux desktop carries no language tag at all.
- **Braille** -- Orca's own switching is speech-only. Polyglot switches both the liblouis
  contraction table and the BrlTTY text table, and keeps them in step with the focused line.
- **Characters, spaces and punctuation** -- a single character has no language, so Orca reads
  it in whatever voice is current. Polyglot answers from the line it sits in, which is why
  arrowing along a German sentence reads its commas and spaces in German too.
- **Mixed lines** -- one line, several languages, each segment in its own voice.
- **A speech dictionary with patterns** -- Orca's pronunciation dictionary swaps whole words
  and nothing else. See [Speech dictionary](#speech-dictionary).
- **Emoji and Unicode character reading** -- speaks emoji names and Unicode character names
  that TTS engines cannot pronounce.

Voices themselves are Orca's job: Polyglot tags an utterance with a language and Orca applies
the voice set you configured for it. See [Voices](#voices).

## Features

### Language Switching
- **Automatic voice switching** -- detects the language of text as it is spoken and tags the utterance with that language. Orca then applies the voice you configured for it in **Orca Preferences -> Voice Sets**, with its rate, pitch, inflection and volume. Polyglot deliberately stores no voices of its own; see [Voices](#voices).
- **Mixed-language support** -- optionally detects multiple languages on the same line and speaks each segment with the correct voice (speech only; braille stays on the whole-line language since only one table can be active).
- **Characters follow their line** -- arrowing through a line announces each character, comma and space in that line's language. A character has no language of its own, so the line it sits in is the only sensible answer, and the answer comes from asking the object Orca is speaking about rather than from anything Polyglot remembers. A non-Latin character still overrides it, so a Cyrillic letter in a German line is read as Russian.
- **Window chrome stays in the system language** -- a button, a menu item or a tab is not text, which is what tells Polyglot it is looking at the window's own furniture rather than at content. Those are read in your default language, so short labels are not announced in the language of whatever document you were just in.
- **Typing learns as you go** -- typed text has no object to ask, which is what distinguishes it from navigation. It starts in whichever language was previous and switches once enough words have accumulated to be sure.
- **Braille contraction table switching** -- automatically sets the correct liblouis contraction table for contracted braille output.
- **BrlTTY text table switching** -- keeps the BrlTTY computer braille (text) table in sync with the detected language, so character-to-dot mappings are always correct.
- **Three-tier detection** -- Unicode script analysis (instant, for Cyrillic, Arabic, Hebrew, Greek, CJK, etc.), then plain word lists (counts how many words belong to each language and to no other), then the [Lingua](https://github.com/pemistahl/lingua-py) library for anything the word lists cannot settle. The order is configurable. See [Word lists](#word-lists).
- **Default language bias** -- the default language is given priority to prevent false switches on short technical text like terminal commands.
- **Uppercase voice preservation** -- uppercase pitch changes and other voice-type overrides (hyperlink, system) keep working across a language switch, because Orca resolves the voice type inside the language's voice set.

### Emoji and Unicode Character Reading
- **Emoji reading** -- expands emojis to their spoken names (e.g. "grinning face", "thumbs up"). Works during line reading, character navigation, and flat review. Names follow the detected language, so emojis in German text are spoken in German ("grinsendes Gesicht", "Daumen hoch"), in Russian as Russian, and so on. Supports 14 languages.
- **Unicode character pronunciation** -- speaks the names of characters that TTS engines normally can't pronounce, covering virtually all of Unicode: box drawing characters, arrows, mathematical operators, geometric shapes, currency symbols, fractions, superscripts, subscripts, dashes, quotation marks, musical symbols, card suits, braille patterns, technical symbols, dingbats, and more. Common symbols use friendly names (e.g. "copyright", "en dash", "one half", "infinity"). Repeated characters are collapsed (e.g. "80 light horizontal characters" instead of silence).
- **Independent of language switching** -- emoji and Unicode character reading works even with auto language switching disabled.

### Setup and Configuration
- **Auto-configuration** -- on first launch, enables every language Speech Dispatcher has a voice for. No manual setup required.
- **Keeps up with your voices** -- on every launch, a language whose voices have all gone is dropped from detection. Whether a *particular* voice still exists is Orca's business, and Orca's Voice Sets page says so.
- **Settings dialog** -- press Orca+Shift+L to open settings at any time.

## Requirements

- **Orca 51 or later** -- Polyglot is a user extension, and the extension system did
  not exist before 51. (Version 1.x loaded itself from `orca-customizations.py` and
  works on Orca 50 and earlier.)
- **Python 3.10+**
- **Speech Dispatcher** with at least one TTS engine installed (e.g. espeak-ng, RHVoice, Piper)
- **pip** or **python3-venv** (for installing dependencies)

### Optional

- **BrlTTY** -- for braille display support and text table switching
- **liblouis** -- for contracted braille output (usually installed with Orca)
- Multiple TTS voices in different languages (the add-on discovers these automatically)
- **Word lists** -- for dictionary-based detection. Not bundled; run
  `./fetch-dictionaries.sh` to install them. See [Word lists](#word-lists).

## Installation

```bash
git clone https://github.com/heath-toby/polyglot-for-orca.git
cd polyglot-for-orca
./install.sh
orca --replace &
```

The installer puts **code only** in `~/.local/share/orca/extensions/polyglot/` and
approves it with `orca --approve-extension polyglot`. Everything else — the Python venv
holding `lingua` and `emoji`, your custom character names, the debug log — goes in
Polyglot's data directory, `~/.local/share/orca/polyglot/`.

That split is not tidiness. Orca approves a user extension by hashing **every file in its
directory** and refuses to load it if anything changed since approval, logging only a
debug line. Anything written at runtime therefore has to live outside the package, or the
extension would quietly stop loading. Keeping the venv out has a second benefit: its
scripts bake in an absolute path, so a venv inside the package would need rebuilding every
time the package moved.

Orca re-checks the hash on every start, so after editing anything under `polyglot/`
re-run `./install.sh` — it re-approves as part of installing.

### Upgrading from version 1.x

Nothing to do. Settings used to live in a private GSettings schema,
`org.gnome.Orca.Polyglot` (and before that a JSON file); they now use Orca's own
per-extension settings store. The first time the extension runs it imports every value
from whichever old backend it finds and marks the import done so it never runs twice.

Orca's store is one flat dictionary per extension, so the per-language relocatable
schemas are flattened to `languages.<code>.<setting>` keys — dots are legal in extension
setting names. Your per-language voice, rate, pitch, gain and braille contraction table
all come across.

The installer also rescues your custom character names from a pre-extension install
folder, and builds a fresh venv in the data directory.

## Uninstallation

```bash
chmod +x uninstall.sh
./uninstall.sh
```

This completely removes the add-on and restores Orca to its original state. If you had other customizations in `orca-customizations.py`, they are preserved.

## Usage

Once installed, Polyglot works automatically. Navigate text as usual -- when the language of the text changes, the voice and braille table switch to match. Emojis and special Unicode characters are spoken by name during all types of navigation.

### Settings

Press **Orca+Shift+L** to open the settings dialog. From here you can:

- Choose a language detection mode (Off, Markup only, Markup + text, Always — see below)
- Enable or disable Unicode character reading including emojis (independent of language switching)
- Edit the speech dictionary: text, pattern and per-language pronunciation rules (see [Speech dictionary](#speech-dictionary))
- Enable or disable mixed-language detection (speech only; braille always uses whole-line detection). Whether a language boundary is marked with a short break follows Orca's own "insert pauses between utterances" setting.
- Choose which languages are active
- Set the default language
- Tick the languages to detect, and set each one's braille contraction table
- Choose the detection order and tune the word lists (see [Word lists](#word-lists))
- Map Unicode scripts to languages (e.g. Cyrillic to Russian)
- Set the word threshold (how many words before switching)

Orca+Shift+L is the **only** place Polyglot is configured. Orca Preferences → User
Extensions → Polyglot is where you enable, disable, remove or read information about the
extension, but its **Settings button is deliberately inactive**: Orca's generated
preferences dialog can only render simple declarative controls, and Polyglot's settings
are nothing like a flat form — a per-language list of tick boxes and braille tables, a
script-to-language mapping editor, a custom character name editor. None of that can be
declared, and there is no hook to supply a custom dialog in its place, so declaring
preferences would only produce a second, poorer settings dialog beside the real one.

### Voices

Polyglot does not store voices. It works out *which language* is being spoken and tags the
utterance with it; Orca supplies the voice.

Configure them in **Orca Preferences -> Voice Sets**. "New Voice Set" creates a set for a
specific language, and each set holds a voice (person), rate, pitch, inflection and volume
per voice type — default, uppercase, hyperlink, system. Orca's own previews apply, and you
can bind a key to any set from the Commands page.

This replaces the per-language voice table Polyglot used to keep, for three reasons worth
stating: Orca's dialog has working previews where a generated extension pane cannot, the
voice-type overlay (uppercase pitch, hyperlink voice) is handled properly rather than
re-implemented, and there is only one place to look when a voice is wrong.

A language with **no** voice set still works. Polyglot names the first Speech Dispatcher
voice for that language and leaves rate and pitch at your global settings, so set a voice
set up only when you want that language to sound different.

Polyglot has to name *some* voice, which is worth knowing if you wonder why it still talks
about voices at all. Speech Dispatcher's synthesis voice is connection state: Orca sends
`set_synthesis_voice` only when a voice is named, and never clears it. An utterance that
named no voice would be spoken by whatever voice the previous one selected — so after a
German line, English would come out in the German voice, and `set_language` cannot rescue
it because a single-language embedded voice ignores it. Naming a voice for every language
is what makes voice sets safe to rely on; yours overrides it whenever you have one.

Two things to know:

1. **The global ("Global") set is your main language.** There is no need to create a set
   for it as well.
2. **A manually activated voice set overrides detection.** If you bind a key to the German
   set and press it, Orca uses that set for everything until you switch back to Global.

Upgrading from 2.1 or earlier imports your old per-language voices into Orca voice sets
once, skipping any language that already has a set and skipping the default language. If
you would rather start fresh, delete the sets in Orca Preferences and build them again.

### Detection modes

Polyglot has four detection modes:

- **Off** — never switch language. Emoji and Unicode-character reading still work.
- **Markup only** — trust language tags from documents and Orca (AT-SPI locales and Orca's own markup-aware detection), plus deterministic Unicode-script detection for non-Latin scripts (Cyrillic, Arabic, BRAILLE, IPA, …). Nothing is read out of the text itself, so short technical text is never misclassified — but neither is a German sentence, since German shares the Latin alphabet. Text in an untagged Latin-script language is read in your default language.
- **Markup + text** *(default)* — same as Markup only, plus Lingua statistical detection on plain Latin-script text. This is the previous behaviour and what most users want.
- **Always (ignore markup)** — never trust language tags from upstream; always run our own full detection. Useful when document `lang` attributes are stale or unreliable.

Mixed-language splitting and the word threshold only apply in the two modes that run statistical detection (Markup + text and Always).

Word lists count as content-based detection, so they too are only consulted in **Markup + text** and **Always**. In **Markup only** the sole non-markup tier is Unicode script detection — so if you have installed word lists and nothing seems to use them, this mode is why.

### Word lists

The question the word-list tier answers is deliberately a dull one: of the words on this line, how many are in the German list and in no other? No model, no training, no confidence score -- just set membership, which means a wrong answer can always be explained by naming the words that caused it.

Install them with:

```bash
./fetch-dictionaries.sh              # for the languages Polyglot has enabled
./fetch-dictionaries.sh de en ru     # or name them
WORDS=50000 ./fetch-dictionaries.sh  # keep more words (default 30000)
```

They land in `~/.local/share/orca/polyglot/dictionaries/<lang>.txt`, one word per line, most frequent first, `#` for comments. They are plain text on purpose: open them, read them, edit them. A word your synthesiser keeps getting wrong in the wrong voice is one line in a text file.

They live in the data directory rather than in the extension package because Orca approves an extension by hashing every file in its directory -- a list added after install would un-approve the add-on.

**Why this is worth having.** Lingua is a 292 MB shared library whose reasoning you cannot inspect. Three word lists of 30,000 words come to under 1 MB, answer in about 0.03 ms against Lingua's 0.11 ms on the same text, and say why.

**At least two lists are needed.** With one, every hit would win and every unknown word would look like a miss, so the tier stays out of the chain until a second list exists.

**Sources are cross-pruned.** The lists come from [FrequencyWords](https://github.com/hermitdave/FrequencyWords) (OpenSubtitles, CC-BY-SA 4.0), and a subtitle corpus is full of the other languages: "this" is the 17th most common word in the English list and the 5262nd in the German one, because German subtitles quote English. Left in, those words destroy the signal. So `fetch-dictionaries.sh` drops a word from a language when another language ranks it at least 5x more highly, which removes "this" from German and "guten" from English while leaving genuinely shared words ("Information", "Radio") in both, where they simply cast no vote.

A hunspell or myspell `.dic` under `/usr/share/hunspell` or `/usr/share/myspell` is used for any language with no list of its own. Those hold stems rather than the forms people write -- German "Haus" is listed, "Häuser" is not -- so a frequency list beats them for this purpose.

#### Detection order

Settings -> Detection -> Word Lists offers:

1. **Script, then word lists, then Lingua** *(default)* -- right when each script belongs to one language. Cyrillic text is Russian, and no word list is going to improve on that.
2. **Word lists, then script, then Lingua** -- right when two enabled languages share a script. Russian and Ukrainian are both Cyrillic, and script detection can only ever name one of them; the words can tell them apart.
3. **Script, then Lingua, then word lists**
4. **Word lists, then Lingua, then script**

Whichever is first, a tier that cannot decide passes the question to the next, and if none can, the current language is kept.

#### Tuning

- **Words unique to one language** (default 2) -- how many words must belong to one language's list and no other before that language is chosen.
- **Minimum share of those words** (default 0.60) -- the winner must hold at least this share of all such words, so a line with even evidence for two languages is left undecided.
- **Most common words to load** (default 30000) -- lists are frequency-ordered, so this keeps the commonest words only. 0 loads the whole list.

The **Words before switching** threshold on the General page applies to word-list results too, so one stray line cannot flip the voice.

### Speech dictionary

**Speech -> Edit Speech Dictionary** holds rules for how words and patterns are pronounced.
Orca has a pronunciation dictionary of its own, and it is worth knowing exactly what it does,
because the dialog does not say: it splits the text on non-word characters and looks up each
word exactly and case-insensitively. So it can replace one word with another, and that is all.
It cannot match a phrase, it cannot distinguish "US" from "us" (keys are lowercased when
saved), and it has **no regular expressions**.

Two kinds of rule here:

1. **Text replacement** -- a literal swap. Optionally case-sensitive, so "US" can become
   "U S" while "us" is left alone, and optionally whole-words-only, so "cat" does not fire
   inside "concatenate".
2. **Regular expression** -- a Python pattern, with backreferences in the replacement.
   `#(\d+)` -> `number \1` reads "#5" as "number 5"; `#([A-Za-z]\w*)` -> `hash tag \1`
   reads "#LINUX" as "hash tag LINUX". Backslash 1 stands for the first bracketed part of the
   pattern, backslash 2 for the second.

Every rule can be limited to **one language**, which is the thing Orca cannot do: a rule for
German text need not fire in English. Rules are applied in order, from the top, with Move Up
and Move Down to change it.

The **Test** field shows what a rule does to a sample as you type, and OK stays unavailable
while a rule is invalid, with the reason given. That is there because a regular expression
that does not work gives no clue as to why.

Rules live in `~/.local/share/orca/polyglot/speech_dictionary.json`, outside the extension
package, because Orca approves an extension by hashing every file in its directory.

#### Runaway patterns

A pattern like `(a+)+b` against a long run of a's does not finish in any useful time, and
Python's regular expressions cannot be interrupted. On the speech path that would freeze Orca
with no speech and no keyboard, so a pattern has to prove itself before it can be saved:
nested repetition is refused outright, and anything else is tried against inputs designed to
provoke it, in a separate process with a time limit. A rule that survives that but still
takes over 50 ms in use is switched off for the session, with a note in the log. The first
check also guards the rules as they are applied, so editing the file by hand cannot hang
speech either.

#### Respelling a word the voice gets wrong

Phonetic notation is not an option here, and not for a reason Polyglot can do anything about:
Speech Dispatcher's text protocol carries text, and the engines behind it either read phonetic
markup aloud as text or discard it. So the way to fix a word is to respell it -- "tomato" to
"tom-ah-toe", "Siobhan" to "shiv-awn" -- with a text or pattern rule. That works with every
voice, and unlike an engine's own pronunciation dictionary it can be limited to one language.

### Detection modes and the test matrix

`tests-language-matrix.py` checks the whole of language resolution in one run. Pick the mode
with `POLYGLOT_TEST_MODE`:

```bash
POLYGLOT_TEST_MODE=markup_text python3 tests-language-matrix.py
```

**markup_text** and **always** pass all 48 rows. **markup_only** fails seven of them, all
German, and that is the mode behaving as documented rather than a defect: with no language
markup to go on it uses the default language and does no content detection, so German text in
an unmarked document reads in the default voice. If you run markup_only and want German
recognised, or want the word lists used at all, you want **markup_text**.

One row is mode-independent and must pass in all three: every character of a line is read in
the same language as every other. A mode that cannot recognise German is a limitation; a line
read half in English and half in German is a bug, and that row is there to catch it coming
back.

### Debug logging

To enable debug logging for troubleshooting:

```bash
ORCA_POLYGLOT_DEBUG=1 orca
```

Or, if Orca runs via systemd:

```bash
systemctl --user set-environment ORCA_POLYGLOT_DEBUG=1
systemctl --user restart orca
```

Logs are written to `~/.local/share/orca/polyglot/debug.log`.

## How it works

Polyglot is an Orca 51 extension. Orca loads it from
`~/.local/share/orca/extensions/polyglot/`, having first checked that the hash of every file
in the package is one you approved, and calls `on_ready`, `on_enabled` and `on_disabled` to
start and stop it. Starting it means monkey-patching these, each recorded with what was there
before so that disabling Polyglot restores Orca exactly:

- `speech_presenter.speak_message` -- expands emojis and Unicode characters in list content from speech generators
- `speech_presenter._speak` -- detects language before speaking and substitutes the appropriate ACSS voice; expands emojis in text
- `speech_presenter.speak_character` -- detects script for character navigation; speaks emoji names and Unicode character names instead of passing unpronounceable characters to the TTS
- `speech_presenter.say_all` -- expands emojis during continuous reading
- `speech_generator.SpeechGenerator.voice` -- provides language-aware voice selection; the voice itself is resolved downstream by Orca's `apply_voice_set`
- `speech_presenter.adjust_for_presentation` -- applies the speech dictionary, then expands unpronounceable Unicode characters (box drawings, arrows, etc.) before Orca's repeat handler, so repeated characters get proper descriptions
- `default.Script.update_braille` -- detects language before building braille regions and sets the correct contraction table
- `braille.display_message`, `braille._flash_callback`, `braille.kill_flash` -- render flash messages in the default language's tables and restore the focus line's afterwards

Language detection uses three tiers, in a configurable order:
1. **Unicode script detection** (fast) -- identifies non-Latin scripts (Cyrillic, Arabic, etc.) by examining character names. This is instant and needs only a few characters.
2. **Word lists** -- counts how many words are in each enabled language's list, and how many are in exactly one of them. The decision is made on those exclusive words, because shared vocabulary is real in both languages and so tells us nothing. Inactive until at least two lists are installed. See [Word lists](#word-lists).
3. **Lingua statistical detection** (slower) -- distinguishes between Latin-script languages (English vs German vs French etc.) using n-gram models. A confidence threshold and noise filter prevent false switches on technical text.

A tier that cannot answer passes the question down, and if none of them can, the language already in use is kept.

## Troubleshooting

**No language switching happens:**
- Check that the add-on is enabled: Orca+Shift+L, ensure "Enable auto language switching" is ticked
- Check that at least two languages are ticked on the Languages page
- If you expect detection on plain Latin-script text, check the detection mode is **Markup + text** or **Always**. **Markup only** runs Unicode-script detection and nothing else, by design.
- Enable debug logging and check `debug.log`

**Wrong language detected:**
- Increase the word threshold in settings (default is 2)
- The default language is biased -- short technical text stays in the default language by design
- The log says which method decided and why, e.g. `4 of 4 unique words are de-only (100%)`

**Right language, wrong voice:**
- Voices are Orca's, not Polyglot's. Check **Orca Preferences -> Voice Sets** for that language; see [Voices](#voices).
- If no voice set exists for it, Speech Dispatcher picks the voice, which may not be the one you want.
- If *every* language is speaking in one voice, a voice set is probably still manually active -- switch back to "Global".

**Braille table not switching:**
- Ensure the contraction table is set for the language on the Languages page (Orca+Shift+L -> Languages)
- Contracted braille must be enabled in Orca's braille settings

**A language is missing from the Languages page:**
- Only languages Speech Dispatcher has a voice for are offered. Run `spd-list -s` to see what is available.
- If a voice was installed after Orca started, restart Orca -- the list is read once at startup.

**Emojis not spoken in some applications:**
- Emoji reading works best in web browsers and terminals. Some applications (e.g. LibreOffice) may not expose emoji characters through their accessibility interface, which prevents expansion during line reading. Character and word navigation may still work.

## License

This project is free software. You may use, modify, and distribute it freely.
