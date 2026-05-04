# Changelog

All notable changes to Polyglot for Orca are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/).

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
