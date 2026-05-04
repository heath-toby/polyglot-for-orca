"""Configuration management for Polyglot for Orca.

Supports GSettings as the primary backend with JSON fallback. On first
GSettings load, any existing JSON config is migrated automatically.
"""

import json
import logging
import os

log = logging.getLogger("polyglot")

_CONFIG_DIR = os.path.join(
    os.environ.get("XDG_DATA_HOME", os.path.expanduser("~/.local/share")),
    "orca", "polyglot"
)
_CONFIG_FILE = os.path.join(_CONFIG_DIR, "polyglot_config.json")
_MIGRATED_FILE = os.path.join(_CONFIG_DIR, "polyglot_config.json.migrated")

_SCHEMA_ID = "org.gnome.Orca.Polyglot"
_LANG_SCHEMA_ID = "org.gnome.Orca.Polyglot.Language"
_SCHEMA_PATH = "/org/gnome/orca/polyglot/"
_LANG_PATH_PREFIX = "/org/gnome/orca/polyglot/languages/"

_DEFAULT_SCRIPT_TO_LANGUAGE = {
    "CYRILLIC": "ru",
    "ARABIC": "ar",
    "HEBREW": "he",
    "GREEK": "el",
    "DEVANAGARI": "hi",
    "BENGALI": "bn",
    "THAI": "th",
    "GEORGIAN": "ka",
    "ARMENIAN": "hy",
    "HANGUL": "ko",
    "CJK": "zh",
    "IPA": "ipa",
    "BRAILLE": "unicode_braille",
}

# Sentinel "language" codes that don't correspond to a real voice — they
# only switch the braille contraction table. Treated specially in sync
# so they aren't pruned for not having a voice.
_BRAILLE_ONLY_SENTINELS = ("ipa", "unicode_braille")

_DEFAULTS = {
    "enabled": True,
    "word_threshold": 2,
    "enabled_languages": [],
    "language_settings": {},
    "script_to_language": _DEFAULT_SCRIPT_TO_LANGUAGE,
    "default_language": "en",
    "speak_emojis": True,
    "unicode_verbosity": "brief",
    "switch_confidence": 0.92,
    "speak_emoticons": True,
    "enable_mixed_language": False,
    "language_switch_pause": 0.3,
    "mixed_max_words": 600,
    # off | markup_only | markup_text | always.
    # markup_text preserves prior behaviour: trust Orca's language hints
    # (markup, AT-SPI, Orca's own detector) when present, else fall back
    # to our full detection.
    "detection_mode": "markup_text",
    "ignored_apps": [],
}

# Modes in which we run Lingua statistical detection on plain text.
# In "off" we run nothing; in "markup_only" we still run the deterministic
# script tier (Cyrillic, BRAILLE, IPA, …) but never Lingua.
_STATISTICAL_MODES = ("markup_text", "always")

# --- GSettings helpers ---

_gsettings_available = False
_schema_source = None


def _init_gsettings():
    """Try to load our GSettings schema from the user schema directory."""
    global _gsettings_available, _schema_source
    if _schema_source is not None:
        return _gsettings_available
    try:
        from gi.repository import Gio, GLib
        user_schema_dir = os.path.join(
            os.environ.get("XDG_DATA_HOME", os.path.expanduser("~/.local/share")),
            "glib-2.0", "schemas"
        )
        if not os.path.isdir(user_schema_dir):
            _schema_source = False
            return False
        default_source = Gio.SettingsSchemaSource.get_default()
        source = Gio.SettingsSchemaSource.new_from_directory(
            user_schema_dir, default_source, False
        )
        schema = source.lookup(_SCHEMA_ID, False)
        if schema is None:
            _schema_source = False
            return False
        _schema_source = source
        _gsettings_available = True
        return True
    except Exception as e:
        log.debug(f"GSettings not available: {e}")
        _schema_source = False
        return False


def _get_settings(schema_id, path):
    """Get a Gio.Settings instance using our custom schema source."""
    from gi.repository import Gio
    schema = _schema_source.lookup(schema_id, True)
    return Gio.Settings.new_full(schema, None, path)


def _variant_to_dict(variant):
    """Convert a GLib Variant a{ss} to a Python dict."""
    result = {}
    n = variant.n_children()
    for i in range(n):
        entry = variant.get_child_value(i)
        key = entry.get_child_value(0).get_string()
        val = entry.get_child_value(1).get_string()
        result[key] = val
    return result


def _dict_to_variant(d):
    """Convert a Python dict to a GLib Variant a{ss}."""
    from gi.repository import GLib
    builder = GLib.VariantBuilder.new(GLib.VariantType.new("a{ss}"))
    for key, val in d.items():
        entry = GLib.Variant.new_dict_entry(
            GLib.Variant.new_string(str(key)),
            GLib.Variant.new_string(str(val)),
        )
        builder.add_value(entry)
    return builder.end()


class Config:
    """Manages add-on configuration with GSettings or JSON fallback."""

    def __init__(self, config_path=None):
        self._path = config_path or _CONFIG_FILE
        self._use_gsettings = False
        self.enabled = _DEFAULTS["enabled"]
        self.word_threshold = _DEFAULTS["word_threshold"]
        self.enabled_languages = list(_DEFAULTS["enabled_languages"])
        self.language_settings = dict(_DEFAULTS["language_settings"])
        self.script_to_language = dict(_DEFAULTS["script_to_language"])
        self.default_language = _DEFAULTS["default_language"]
        self.speak_emojis = _DEFAULTS["speak_emojis"]
        self.unicode_verbosity = _DEFAULTS["unicode_verbosity"]
        self.switch_confidence = _DEFAULTS["switch_confidence"]
        self.speak_emoticons = _DEFAULTS["speak_emoticons"]
        self.enable_mixed_language = _DEFAULTS["enable_mixed_language"]
        self.language_switch_pause = _DEFAULTS["language_switch_pause"]
        self.mixed_max_words = _DEFAULTS["mixed_max_words"]
        self.detection_mode = _DEFAULTS["detection_mode"]
        self.ignored_apps = list(_DEFAULTS["ignored_apps"])

    def load(self):
        """Load config. Tries GSettings first, falls back to JSON."""
        if _init_gsettings():
            loaded = self._load_gsettings()
            if loaded:
                self._use_gsettings = True
                # Migrate JSON if it still exists (first GSettings load)
                if os.path.exists(self._path) and not os.path.exists(_MIGRATED_FILE):
                    self._migrate_json_to_gsettings()
                return True
            # GSettings schema exists but no data yet — try JSON, then migrate
            if self._load_json():
                self._use_gsettings = True
                self._save_gsettings()
                self._rename_json_migrated()
                return True
            self._use_gsettings = True
            return False
        return self._load_json()

    def save(self):
        """Save config to GSettings or JSON."""
        if self._use_gsettings:
            self._save_gsettings()
        else:
            self._save_json()

    # --- GSettings backend ---

    def _load_gsettings(self):
        """Load configuration from GSettings. Returns True if data was found."""
        try:
            settings = _get_settings(_SCHEMA_ID, _SCHEMA_PATH)
            # Check if we have any enabled languages — if empty and default,
            # it means no data has been written yet
            enabled = list(settings.get_strv("enabled-languages"))

            self.enabled = settings.get_boolean("enabled")
            self.word_threshold = settings.get_int("word-threshold")
            self.speak_emojis = settings.get_boolean("speak-emojis")
            self.unicode_verbosity = settings.get_string("unicode-verbosity")
            self.default_language = settings.get_string("default-language")
            self.enabled_languages = enabled
            # Don't clobber the constructor's default mapping if the
            # GSettings store has the schema empty default — that just
            # means nothing's been saved here yet, not that the user
            # cleared every script binding.
            stored_script_map = _variant_to_dict(
                settings.get_value("script-to-language")
            )
            if stored_script_map:
                self.script_to_language = stored_script_map
            self.switch_confidence = settings.get_double("switch-confidence")
            self.speak_emoticons = settings.get_boolean("speak-emoticons")
            self.enable_mixed_language = settings.get_boolean("enable-mixed-language")
            self.language_switch_pause = settings.get_double("language-switch-pause")
            try:
                self.mixed_max_words = settings.get_int("mixed-max-words")
            except Exception:
                self.mixed_max_words = _DEFAULTS["mixed_max_words"]
            try:
                mode = settings.get_string("detection-mode")
                if mode in ("off", "markup_only", "markup_text", "always"):
                    self.detection_mode = mode
            except Exception:
                pass
            self.ignored_apps = list(settings.get_strv("ignored-apps"))

            # Load per-language settings from relocatable schemas
            self.language_settings = {}
            for lang_code in enabled:
                path = f"{_LANG_PATH_PREFIX}{lang_code}/"
                try:
                    lang_s = _get_settings(_LANG_SCHEMA_ID, path)
                    self.language_settings[lang_code] = {
                        "voice_name": lang_s.get_string("voice-name"),
                        "voice_lang": lang_s.get_string("voice-lang"),
                        "voice_dialect": lang_s.get_string("voice-dialect"),
                        "rate": lang_s.get_double("rate"),
                        "average_pitch": lang_s.get_double("average-pitch"),
                        "gain": lang_s.get_double("gain"),
                        "contraction_table": lang_s.get_string("contraction-table"),
                    }
                except Exception as e:
                    log.debug(f"Could not load GSettings for language {lang_code}: {e}")

            # Return True if there was meaningful data
            return bool(enabled) or not settings.get_boolean("enabled")
        except Exception as e:
            log.debug(f"GSettings load failed: {e}")
            return False

    def _save_gsettings(self):
        """Save configuration to GSettings."""
        try:
            settings = _get_settings(_SCHEMA_ID, _SCHEMA_PATH)
            settings.set_boolean("enabled", self.enabled)
            settings.set_int("word-threshold", self.word_threshold)
            settings.set_boolean("speak-emojis", self.speak_emojis)
            settings.set_string("unicode-verbosity", self.unicode_verbosity)
            settings.set_string("default-language", self.default_language)
            settings.set_strv("enabled-languages", self.enabled_languages)
            settings.set_value("script-to-language",
                               _dict_to_variant(self.script_to_language))
            settings.set_double("switch-confidence", self.switch_confidence)
            settings.set_boolean("speak-emoticons", self.speak_emoticons)
            settings.set_boolean("enable-mixed-language", self.enable_mixed_language)
            settings.set_double("language-switch-pause", self.language_switch_pause)
            try:
                settings.set_int("mixed-max-words", int(self.mixed_max_words))
            except Exception:
                pass
            try:
                settings.set_string("detection-mode", self.detection_mode)
            except Exception:
                pass
            settings.set_strv("ignored-apps", self.ignored_apps)
            # Mark as configured so is_first_run can distinguish "user has
            # cleared all languages" from "fresh install".
            try:
                settings.set_boolean("is-configured", True)
            except Exception:
                pass

            for lang_code, lang_data in self.language_settings.items():
                path = f"{_LANG_PATH_PREFIX}{lang_code}/"
                try:
                    lang_s = _get_settings(_LANG_SCHEMA_ID, path)
                    lang_s.set_string("voice-name", lang_data.get("voice_name", ""))
                    lang_s.set_string("voice-lang", lang_data.get("voice_lang", ""))
                    lang_s.set_string("voice-dialect", lang_data.get("voice_dialect", ""))
                    lang_s.set_double("rate", lang_data.get("rate", 50.0))
                    lang_s.set_double("average-pitch", lang_data.get("average_pitch", 5.0))
                    lang_s.set_double("gain", lang_data.get("gain", 10.0))
                    lang_s.set_string("contraction-table",
                                      lang_data.get("contraction_table", ""))
                except Exception as e:
                    log.debug(f"Could not save GSettings for language {lang_code}: {e}")
        except Exception as e:
            log.warning(f"GSettings save failed, falling back to JSON: {e}")
            self._save_json()

    def _migrate_json_to_gsettings(self):
        """Migrate existing JSON config into GSettings and rename the file."""
        try:
            self._save_gsettings()
            self._rename_json_migrated()
            log.info("Polyglot: migrated JSON config to GSettings")
        except Exception as e:
            log.warning(f"JSON to GSettings migration failed: {e}")

    def _rename_json_migrated(self):
        """Rename JSON config to .migrated so it's not loaded again."""
        try:
            if os.path.exists(self._path):
                os.rename(self._path, _MIGRATED_FILE)
        except OSError:
            pass

    # --- JSON backend ---

    def _load_json(self):
        """Load config from JSON file. Returns True if file existed."""
        if not os.path.exists(self._path):
            return False
        try:
            with open(self._path, "r") as f:
                data = json.load(f)
            self.enabled = data.get("enabled", self.enabled)
            self.word_threshold = data.get("word_threshold", self.word_threshold)
            self.enabled_languages = data.get("enabled_languages", self.enabled_languages)
            self.language_settings = data.get("language_settings", self.language_settings)
            self.script_to_language = data.get("script_to_language", self.script_to_language)
            self.default_language = data.get("default_language", self.default_language)
            self.speak_emojis = data.get("speak_emojis",
                data.get("speak_unicode", self.speak_emojis))
            self.unicode_verbosity = data.get("unicode_verbosity",
                # Migrate: old speak_unicode=true -> "brief", false -> "off"
                "brief" if data.get("speak_unicode", True) else "off")
            self.switch_confidence = data.get("switch_confidence", self.switch_confidence)
            self.speak_emoticons = data.get("speak_emoticons", self.speak_emoticons)
            self.enable_mixed_language = data.get("enable_mixed_language", self.enable_mixed_language)
            self.language_switch_pause = data.get("language_switch_pause", self.language_switch_pause)
            self.mixed_max_words = data.get("mixed_max_words", self.mixed_max_words)
            mode = data.get("detection_mode", self.detection_mode)
            if mode in ("off", "markup_only", "markup_text", "always"):
                self.detection_mode = mode
            self.ignored_apps = data.get("ignored_apps", self.ignored_apps)

            # Migrate old format: language_to_profile -> language_settings
            if "language_to_profile" in data and not self.language_settings:
                self._migrate_from_profiles(data["language_to_profile"])

            return True
        except (json.JSONDecodeError, OSError):
            return False

    def _save_json(self):
        """Save config to JSON file."""
        os.makedirs(os.path.dirname(self._path), exist_ok=True)
        data = {
            "enabled": self.enabled,
            "word_threshold": self.word_threshold,
            "enabled_languages": self.enabled_languages,
            "language_settings": self.language_settings,
            "script_to_language": self.script_to_language,
            "default_language": self.default_language,
            "speak_emojis": self.speak_emojis,
            "unicode_verbosity": self.unicode_verbosity,
            "switch_confidence": self.switch_confidence,
            "speak_emoticons": self.speak_emoticons,
            "enable_mixed_language": self.enable_mixed_language,
            "language_switch_pause": self.language_switch_pause,
            "mixed_max_words": self.mixed_max_words,
            "detection_mode": self.detection_mode,
            "ignored_apps": self.ignored_apps,
        }
        with open(self._path, "w") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)

    def _migrate_from_profiles(self, language_to_profile):
        """Migrate old profile-based config to direct voice settings."""
        try:
            from .voice_mapper import VoiceMapper
            mapper = VoiceMapper()
            for lang_code, profile_name in language_to_profile.items():
                voice_config = mapper.get_voice_for_language(lang_code)
                if voice_config:
                    family = voice_config.get("family", {})
                    self.language_settings[lang_code] = {
                        "voice_name": family.get("name", ""),
                        "voice_lang": family.get("lang", lang_code),
                        "voice_dialect": family.get("dialect", ""),
                        "rate": voice_config.get("rate", 50.0),
                        "average_pitch": voice_config.get("average-pitch", 5.0),
                        "contraction_table": voice_config.get("brailleContractionTable", ""),
                    }
        except Exception:
            pass

    # --- Common methods ---

    def auto_configure_from_profiles(self, voice_mapper):
        """Auto-generate config from available voices on first run.

        Uses all languages discovered from Speech Dispatcher. The default
        Orca profile's rate/pitch/gain are used as the baseline for the
        default language. Other languages get rate 50 (a safe default) but
        inherit gain from the default profile. Languages with their own
        Orca profile get that profile's rate/pitch instead.
        """
        available = voice_mapper.get_available_languages()
        if not available:
            return

        self.enabled_languages = list(available)

        # Get the user's default profile settings as baseline
        defaults = voice_mapper.get_default_profile_settings()
        default_rate = defaults.get("rate", 50.0)
        default_pitch = defaults.get("average-pitch", 5.0)
        default_gain = defaults.get("gain", 10.0)

        # Determine default language
        if "en" in available:
            self.default_language = "en"
        elif self.enabled_languages:
            self.default_language = self.enabled_languages[0]

        for lang_code in self.enabled_languages:
            voice_config = voice_mapper.get_voice_for_language(lang_code)
            if voice_config:
                family = voice_config.get("family", {})
                # Default language inherits rate/pitch/gain from the default profile.
                # Other languages: use their profile rate/pitch if available (voice_mapper
                # already overlaid it), otherwise rate 50.0 (safe default).
                # All languages inherit gain from default profile.
                is_default = (lang_code == self.default_language)
                fallback_rate = default_rate if is_default else 50.0
                fallback_pitch = default_pitch if is_default else 5.0

                self.language_settings[lang_code] = {
                    "voice_name": family.get("name", ""),
                    "voice_lang": family.get("lang", lang_code),
                    "voice_dialect": family.get("dialect", ""),
                    "rate": voice_config.get("rate", fallback_rate),
                    "average_pitch": voice_config.get("average-pitch", fallback_pitch),
                    "gain": default_gain,
                    "contraction_table": voice_config.get("brailleContractionTable", ""),
                }

        for script, default_lang in _DEFAULT_SCRIPT_TO_LANGUAGE.items():
            if default_lang in _BRAILLE_ONLY_SENTINELS or default_lang in self.enabled_languages:
                self.script_to_language[script] = default_lang

    def sync_from_voices(self, voice_mapper):
        """Sync config with currently available Speech Dispatcher voices.

        - Checks that configured voices still exist; replaces with alternatives
        - Removes languages that have no voices available at all
        - Does NOT auto-add new languages (user enables those via settings)
        - Preserves user-set fields like contraction_table
        Returns True if anything changed.
        """
        available = set(voice_mapper.get_available_languages())
        changed = False

        for lang_code in list(self.enabled_languages):
            existing = self.language_settings.get(lang_code)
            if not existing:
                continue

            if lang_code not in available:
                # No voices at all for this language — remove it
                self.enabled_languages.remove(lang_code)
                self.language_settings.pop(lang_code, None)
                changed = True
                continue

            # Check if the configured voice still exists
            configured_voice = existing.get("voice_name", "")
            voices = voice_mapper.get_voices_for_language(lang_code)
            voice_names = [v[0] for v in voices]

            if configured_voice and configured_voice not in voice_names:
                # Voice was removed — pick the first available replacement
                if voices:
                    voice_name, full_lang, variant = voices[0]
                    dialect = ""
                    if "-" in full_lang:
                        dialect = full_lang.split("-", 1)[1]
                    elif "_" in full_lang:
                        dialect = full_lang.split("_", 1)[1]
                    existing["voice_name"] = voice_name
                    existing["voice_lang"] = lang_code
                    existing["voice_dialect"] = dialect
                    changed = True

        # Remove stale script_to_language entries
        for script, lang in list(self.script_to_language.items()):
            if lang not in self.enabled_languages and lang not in _BRAILLE_ONLY_SENTINELS:
                del self.script_to_language[script]
                changed = True

        # Fix default_language if it was removed
        if self.default_language not in self.enabled_languages:
            if self.enabled_languages:
                self.default_language = self.enabled_languages[0]
                changed = True

        # Add script_to_language entries for newly enabled languages
        for script, default_lang in _DEFAULT_SCRIPT_TO_LANGUAGE.items():
            if script not in self.script_to_language:
                if default_lang in _BRAILLE_ONLY_SENTINELS or default_lang in self.enabled_languages:
                    self.script_to_language[script] = default_lang
                    changed = True

        return changed

    @property
    def is_first_run(self):
        """True if neither GSettings data nor JSON config exists.

        Uses the ``is-configured`` sentinel as the primary signal so that a
        user who deliberately clears every language is not treated as a
        first-run user on next start. Falls back to checking for any
        enabled-languages or a JSON config file for older installs that
        were saved before the sentinel existed.
        """
        if _init_gsettings():
            try:
                settings = _get_settings(_SCHEMA_ID, _SCHEMA_PATH)
                try:
                    if settings.get_boolean("is-configured"):
                        return False
                except Exception:
                    pass
                if settings.get_strv("enabled-languages"):
                    return False
            except Exception:
                pass
        return not os.path.exists(self._path) and not os.path.exists(_MIGRATED_FILE)
