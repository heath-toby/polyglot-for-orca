# Changelog

All notable changes to Polyglot for Orca are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/).

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
