# Polyglot for Orca

An add-on for the [Orca screen reader](https://wiki.gnome.org/Projects/Orca) on Linux that enhances speech and braille with automatic language switching, emoji reading, and Unicode character pronunciation.

**This version is for Orca 50** (GNOME 48+).

## Why this add-on when Orca 50 has built-in language switching?

Orca 50 introduced its own automatic language switching for speech. However, the built-in implementation has limitations that Polyglot addresses:

- **Per-language voice settings** -- Orca 50's built-in switching changes the voice family but does not support different rates, pitches, or volumes per language. If you need German at rate 65 and English at rate 100, only Polyglot can do that.
- **Braille support** -- Orca 50's built-in switching is speech-only. Polyglot switches both the liblouis contraction table and the BrlTTY text table automatically.
- **Emoji and Unicode character reading** -- speaks emoji names and Unicode character names that TTS engines cannot pronounce.

## Features

### Language Switching
- **Automatic voice switching** -- detects the language of text as it is spoken and switches to the appropriate voice with per-language rate, pitch, and volume settings.
- **Mixed-language support** -- optionally detects multiple languages on the same line and speaks each segment with the correct voice (speech only; braille stays on the whole-line language since only one table can be active).
- **Braille contraction table switching** -- automatically sets the correct liblouis contraction table for contracted braille output.
- **BrlTTY text table switching** -- keeps the BrlTTY computer braille (text) table in sync with the detected language, so character-to-dot mappings are always correct.
- **Two-tier detection** -- uses Unicode script analysis (instant, for Cyrillic, Arabic, Hebrew, Greek, CJK, etc.) combined with the [Lingua](https://github.com/pemistahl/lingua-py) library for Latin-script languages (English, German, French, Spanish, etc.).
- **Default language bias** -- the default language is given priority to prevent false switches on short technical text like terminal commands.
- **Uppercase voice preservation** -- uppercase pitch changes and other voice-type overrides (hyperlink, system) are correctly applied on top of per-language voice settings.

### Emoji and Unicode Character Reading
- **Emoji reading** -- expands emojis to their spoken names (e.g. "grinning face", "thumbs up"). Works during line reading, character navigation, and flat review. Names follow the detected language, so emojis in German text are spoken in German ("grinsendes Gesicht", "Daumen hoch"), in Russian as Russian, and so on. Supports 14 languages.
- **Unicode character pronunciation** -- speaks the names of characters that TTS engines normally can't pronounce, covering virtually all of Unicode: box drawing characters, arrows, mathematical operators, geometric shapes, currency symbols, fractions, superscripts, subscripts, dashes, quotation marks, musical symbols, card suits, braille patterns, technical symbols, dingbats, and more. Common symbols use friendly names (e.g. "copyright", "en dash", "one half", "infinity"). Repeated characters are collapsed (e.g. "80 light horizontal characters" instead of silence).
- **Independent of language switching** -- emoji and Unicode character reading works even with auto language switching disabled.

### Setup and Configuration
- **Auto-configuration** -- on first launch, discovers all installed voices from Speech Dispatcher and configures language switching automatically. No manual setup required.
- **Voice sync on startup** -- on every launch, checks that configured voices still exist. If a voice was removed or changed, it is automatically replaced.
- **Settings dialog** -- press Orca+Shift+L to open settings at any time.

## Requirements

- **Orca 50** (GNOME 48+)
- **Python 3.10+**
- **Speech Dispatcher** with at least one TTS engine installed (e.g. espeak-ng, RHVoice, Piper)
- **pip** or **python3-venv** (for installing dependencies)

### Optional

- **BrlTTY** -- for braille display support and text table switching
- **liblouis** -- for contracted braille output (usually installed with Orca)
- Multiple TTS voices in different languages (the add-on discovers these automatically)

## Installation

1. Extract or clone this repository.
2. Run the installer:

```bash
chmod +x install.sh
./install.sh
```

3. Restart Orca. On first launch, Polyglot will:
   - Discover all voices available from Speech Dispatcher
   - Enable all languages that have voices
   - If you already have Orca language profiles set up, use their voice, rate, pitch, and braille table preferences as its starting configuration
   - Set the default language to English (if available)
   - Speak a brief confirmation

**Note:** You do not need to create Orca profiles for each language. Polyglot discovers voices directly from Speech Dispatcher and handles switching itself. However, if you do already have profiles, it will respect your existing voice choices.

### What the installer does

- Copies the `polyglot` Python package to `~/.local/share/orca/`
- Adds a loader block to `~/.local/share/orca/orca-customizations.py`
- Creates a Python virtual environment and installs dependencies (Lingua for language detection, emoji for emoji names)
- Preserves any existing configuration from a previous installation
- Migrates settings from the old `orca_autoswitch` package if present

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

- Enable or disable auto language switching
- Enable or disable Unicode character reading including emojis (independent of language switching)
- Enable or disable mixed-language detection (speech only; braille always uses whole-line detection)
- Choose which languages are active
- Set the default language
- Configure voice, rate, and pitch per language
- Set contraction tables per language (for contracted braille)
- Map Unicode scripts to languages (e.g. Cyrillic to Russian)
- Set the word threshold (how many words before switching)

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

Polyglot monkey-patches several Orca functions at startup:

- `speech.speak` -- expands emojis and Unicode characters in list content from speech generators
- `speech._speak` -- detects language before speaking and substitutes the appropriate ACSS voice; expands emojis in text
- `speech.speak_character` -- detects script for character navigation; speaks emoji names and Unicode character names instead of passing unpronounceable characters to the TTS
- `speech.say_all` -- expands emojis during continuous reading
- `speech_generator.SpeechGenerator.voice` -- provides language-aware voice selection with uppercase/hyperlink voice-type overlay
- `speech_presenter.adjust_for_presentation` -- expands unpronounceable Unicode characters (box drawings, arrows, etc.) before Orca's repeat handler, so repeated characters get proper descriptions
- `default.Script.update_braille` -- detects language before building braille regions and sets the correct contraction table
- `braille.refresh` -- detects language from braille line content during panning

Language detection uses two tiers:
1. **Unicode script detection** (fast) -- identifies non-Latin scripts (Cyrillic, Arabic, etc.) by examining character names. This is instant and needs only a few characters.
2. **Lingua statistical detection** (slower) -- distinguishes between Latin-script languages (English vs German vs French etc.) using n-gram models. A confidence threshold and noise filter prevent false switches on technical text.

## Troubleshooting

**No language switching happens:**
- Check that the add-on is enabled: Orca+Shift+L, ensure "Enable auto language switching" is ticked
- Check that at least two languages are enabled with voices configured
- Enable debug logging and check `debug.log`

**Wrong language detected:**
- Increase the word threshold in settings (default is 2)
- The default language is biased -- short technical text stays in the default language by design

**Braille table not switching:**
- Ensure contraction tables are set in the language settings (Orca+Shift+L, click the settings button for each language)
- Contracted braille must be enabled in Orca's braille settings

**Voices not found on first run:**
- Polyglot discovers voices from Speech Dispatcher. Run `spd-list -s` to see available voices.
- If voices were installed after Polyglot, restart Orca -- it syncs on every startup.

**Emojis not spoken in some applications:**
- Emoji reading works best in web browsers and terminals. Some applications (e.g. LibreOffice) may not expose emoji characters through their accessibility interface, which prevents expansion during line reading. Character and word navigation may still work.

## License

This project is free software. You may use, modify, and distribute it freely.
