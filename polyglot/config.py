"""Configuration management for Polyglot for Orca.

Values live in Orca's own per-extension settings store (dconf, under
``/org/gnome/orca/<profile>/extensions/polyglot/settings``), which is what
the Orca 51 extension system reads and writes.

Two older backends are kept purely as one-time import sources: the private
GSettings schema ``org.gnome.Orca.Polyglot`` used before the extension
system, and before that a JSON file. See ``migrate_legacy_settings``.

The store is one flat dict per extension, so the per-language relocatable
schemas are flattened to ``languages.<code>.<key>`` keys -- dots are legal
in extension setting names. The public attributes of ``Config`` are
unchanged, so ``config_ui`` works against either backend untouched.
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
    "mixed_max_words": 600,
    # off | markup_only | markup_text | always.
    # markup_text preserves prior behaviour: trust Orca's language hints
    # (markup, AT-SPI, Orca's own detector) when present, else fall back
    # to our full detection.
    "detection_mode": "markup_text",
    "ignored_apps": [],
    # Which detection tiers to try, in order. See language_detector.
    "detection_order": ["script", "dictionary", "lingua"],
    "dictionary_enabled": True,
    # A language needs this many words that no other enabled language's
    # word list holds before the dictionary tier will name it.
    "dictionary_min_words": 2,
    # ...and that must be this share of all such words found, so text with
    # German and English evidence in equal measure stays undecided.
    "dictionary_min_share": 0.6,
    # Word lists are frequency-ordered, so this caps them at the N most
    # common words. 0 reads the whole list.
    "dictionary_max_words": 30000,
}

# --- Extension settings backend -------------------------------------------

# Bumped when the shape of the stored settings changes. Its presence also
# marks the legacy import as done, so it never runs twice -- including
# when the user has deliberately reset everything back to defaults.
SETTINGS_VERSION = 2
_VERSION_KEY = "settings-version"

# attribute name -> (store key, kind). Kind drives both the legacy import
# and the coercion on read; "dict" is a flat str->str mapping.
_TOP_LEVEL_KEYS = (
    ("enabled", "enabled", "bool"),
    ("word_threshold", "word-threshold", "int"),
    ("speak_emojis", "speak-emojis", "bool"),
    ("unicode_verbosity", "unicode-verbosity", "str"),
    ("default_language", "default-language", "str"),
    ("enabled_languages", "enabled-languages", "strlist"),
    ("script_to_language", "script-to-language", "dict"),
    ("switch_confidence", "switch-confidence", "float"),
    ("speak_emoticons", "speak-emoticons", "bool"),
    ("enable_mixed_language", "enable-mixed-language", "bool"),
    ("mixed_max_words", "mixed-max-words", "int"),
    ("detection_mode", "detection-mode", "str"),
    ("ignored_apps", "ignored-apps", "strlist"),
    ("detection_order", "detection-order", "strlist"),
    ("dictionary_enabled", "dictionary-enabled", "bool"),
    ("dictionary_min_words", "dictionary-min-words", "int"),
    ("dictionary_min_share", "dictionary-min-share", "float"),
    ("dictionary_max_words", "dictionary-max-words", "int"),
)

# per-language dict key -> (store key suffix, kind)
#
# Only the braille table is left. Voice, rate, pitch and volume used to
# live here too; Orca 51 owns them now, in its own Voice Sets preferences,
# and an utterance that carries only a language gets the right voice
# applied downstream of us. Braille is not covered by voice sets, so the
# contraction table stays Polyglot's job.
_LANGUAGE_KEYS = (
    ("contraction_table", "contraction-table", "str"),
)

_LANGUAGE_DEFAULTS = {
    "contraction_table": "",
}

# Written by versions before voice handling moved to Orca. Pruned on save
# so they do not sit in dconf for ever, but read once first by
# migrate_voice_sets_to_orca.
_OBSOLETE_LANGUAGE_SUFFIXES = (
    "voice-name", "voice-lang", "voice-dialect", "rate", "average-pitch", "gain",
)

# Top-level keys from earlier versions, reset on save so they do not linger
# in dconf. "language-switch-pause" was a sleep duration that blocked
# Orca's main loop; the pause it stood for is now Orca's own
# "insert pauses between utterances" preference.
_OBSOLETE_KEYS = ("language-switch-pause",)

_LANGUAGE_PREFIX = "languages."
_IS_CONFIGURED_KEY = "is-configured"
# One-shot marker for the import of old per-language voice settings into
# Orca's own voice sets. Separate from the settings-version marker because
# it is a different question: that one asks "have we read the old backend",
# this one asks "have we handed the voices over to Orca".
_VOICE_SETS_IMPORTED_KEY = "voice-sets-imported"

_VALID_DETECTION_MODES = ("off", "markup_only", "markup_text", "always")

# Kept here rather than imported from language_detector so that reading the
# config never drags the detector -- and through it Lingua -- into memory.
_VALID_DETECTION_TIERS = ("script", "dictionary", "lingua")


def _language_key(lang_code, suffix):
    """Return the flat store key for one per-language setting."""
    return f"{_LANGUAGE_PREFIX}{lang_code}.{suffix}"


def _coerce(value, kind, fallback):
    """Return value coerced to kind, or fallback if that is not possible."""
    try:
        if kind == "bool":
            return bool(value)
        if kind == "int":
            return int(value)
        if kind == "float":
            return float(value)
        if kind == "str":
            return str(value)
        if kind == "strlist":
            return [str(item) for item in value or []]
        if kind == "dict":
            return {str(k): str(v) for k, v in dict(value or {}).items()}
    except (TypeError, ValueError):
        log.warning(f"Polyglot: ignoring unusable stored value {value!r}")
    return fallback


def migrate_legacy_settings(settings):
    """Import settings from the pre-extension backends, once.

    ``settings`` is the extension's ExtensionSettings. Prefers the private
    GSettings schema; falls back to the older JSON file. Returns True if
    values were actually imported. Writes the version marker either way,
    so a missing or already-migrated legacy backend costs one lookup at
    most once in the life of the install.
    """
    if settings.get(_VERSION_KEY) is not None:
        return False

    imported = False
    try:
        if _init_gsettings():
            imported = _import_from_gsettings(settings)
        if not imported:
            imported = _import_from_json(settings)
    except Exception as error:  # pylint: disable=broad-exception-caught
        # Leave the version marker unset so a later run can try again
        # rather than silently stranding the user on defaults.
        log.error(f"Polyglot: importing legacy settings failed: {error}")
        return False

    settings.set(_VERSION_KEY, SETTINGS_VERSION)
    if imported:
        log.info("Polyglot: imported settings from the pre-extension backend.")
    else:
        log.info("Polyglot: nothing to import; using defaults.")
    return imported


def _import_from_gsettings(settings):
    """Copy the private GSettings schema into the extension store."""
    gs = _get_settings(_SCHEMA_ID, _SCHEMA_PATH)
    getters = {
        "bool": gs.get_boolean,
        "int": gs.get_int,
        "float": gs.get_double,
        "str": gs.get_string,
        "strlist": lambda key: list(gs.get_strv(key)),
        "dict": lambda key: _variant_to_dict(gs.get_value(key)),
    }

    enabled_languages = list(gs.get_strv("enabled-languages"))
    for attr, key, kind in _TOP_LEVEL_KEYS:
        try:
            value = getters[kind](key)
        except Exception as error:  # pylint: disable=broad-exception-caught
            log.debug(f"Polyglot: no legacy value for {key}: {error}")
            continue
        # An empty script map means "never saved", not "user cleared it".
        if key == "script-to-language" and not value:
            continue
        settings.set(key, value)

    for lang_code in enabled_languages:
        path = f"{_LANG_PATH_PREFIX}{lang_code}/"
        try:
            lang_gs = _get_settings(_LANG_SCHEMA_ID, path)
        except Exception as error:  # pylint: disable=broad-exception-caught
            log.debug(f"Polyglot: no legacy settings for language {lang_code}: {error}")
            continue
        lang_getters = {
            "float": lang_gs.get_double,
            "str": lang_gs.get_string,
        }
        for attr, suffix, kind in _LANGUAGE_KEYS:
            try:
                settings.set(_language_key(lang_code, suffix), lang_getters[kind](suffix))
            except Exception as error:  # pylint: disable=broad-exception-caught
                log.debug(f"Polyglot: no legacy {suffix} for {lang_code}: {error}")

    try:
        settings.set(_IS_CONFIGURED_KEY, gs.get_boolean(_IS_CONFIGURED_KEY))
    except Exception:  # pylint: disable=broad-exception-caught
        pass

    return bool(enabled_languages)


def _import_from_json(settings):
    """Copy the oldest JSON backend into the extension store."""
    for path in (_CONFIG_FILE, _MIGRATED_FILE):
        if not os.path.exists(path):
            continue
        try:
            with open(path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, json.JSONDecodeError) as error:
            log.debug(f"Polyglot: could not read {path}: {error}")
            continue

        for attr, key, kind in _TOP_LEVEL_KEYS:
            if attr in data:
                settings.set(key, _coerce(data[attr], kind, _DEFAULTS[attr]))
        for lang_code, lang_data in (data.get("language_settings") or {}).items():
            for attr, suffix, kind in _LANGUAGE_KEYS:
                if attr in lang_data:
                    settings.set(
                        _language_key(lang_code, suffix),
                        _coerce(lang_data[attr], kind, _LANGUAGE_DEFAULTS[attr]),
                    )
        settings.set(_IS_CONFIGURED_KEY, True)
        return True
    return False


# --- GSettings helpers (legacy import source only) ---

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


def normalize_detection_order(order):
    """Return a usable tier order, dropping unknown names and adding missing.

    Mirrors language_detector.normalize_detection_order so a hand-edited
    setting can neither disable a tier by typo nor leave detection with
    nothing to try. Kept in both places because each module is used
    without the other.
    """
    result = []
    for tier in order or ():
        tier = str(tier).strip().lower()
        if tier in _VALID_DETECTION_TIERS and tier not in result:
            result.append(tier)
    for tier in _DEFAULTS["detection_order"]:
        if tier not in result:
            result.append(tier)
    return result


class Config:
    """Manages add-on configuration with GSettings or JSON fallback."""

    def __init__(self, config_path=None, settings=None):
        self._path = config_path or _CONFIG_FILE
        self._use_gsettings = False
        # Orca's per-extension settings store; the only backend written to.
        self._settings = settings
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
        self.mixed_max_words = _DEFAULTS["mixed_max_words"]
        self.detection_mode = _DEFAULTS["detection_mode"]
        self.ignored_apps = list(_DEFAULTS["ignored_apps"])
        self.detection_order = list(_DEFAULTS["detection_order"])
        self.dictionary_enabled = _DEFAULTS["dictionary_enabled"]
        self.dictionary_min_words = _DEFAULTS["dictionary_min_words"]
        self.dictionary_min_share = _DEFAULTS["dictionary_min_share"]
        self.dictionary_max_words = _DEFAULTS["dictionary_max_words"]
        # See _load_extension_settings; stays empty for a bare Config.
        self._known_languages = set()

    def load(self):
        """Load config from Orca's extension settings store.

        Falls back to the pre-extension backends only when no store was
        supplied, which happens in tooling that constructs a bare Config.
        """
        if self._settings is not None:
            return self._load_extension_settings()
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
        """Save config to Orca's extension settings store."""
        if self._settings is not None:
            self._save_extension_settings()
            return
        if self._use_gsettings:
            self._save_gsettings()
        else:
            self._save_json()

    # --- Extension settings backend ---

    def _load_extension_settings(self):
        """Load from Orca's extension store. Returns True if data was found."""
        settings = self._settings
        for attr, key, kind in _TOP_LEVEL_KEYS:
            default = getattr(self, attr)
            stored = settings.get(key, None)
            if stored is None:
                continue
            # An empty script map means "never saved", not "user cleared
            # it" -- keep the built-in mapping rather than blanking it.
            if key == "script-to-language" and not stored:
                continue
            setattr(self, attr, _coerce(stored, kind, default))

        if self.detection_mode not in _VALID_DETECTION_MODES:
            log.warning(f"Polyglot: ignoring invalid detection mode {self.detection_mode!r}")
            self.detection_mode = _DEFAULTS["detection_mode"]

        self.detection_order = normalize_detection_order(self.detection_order)

        self.language_settings = {}
        for lang_code in self.enabled_languages:
            entry = {}
            for attr, suffix, kind in _LANGUAGE_KEYS:
                fallback = _LANGUAGE_DEFAULTS[attr]
                stored = settings.get(_language_key(lang_code, suffix), None)
                entry[attr] = fallback if stored is None else _coerce(stored, kind, fallback)
            self.language_settings[lang_code] = entry

        # Languages the store is known to hold keys for. Needed at save
        # time: ExtensionSettings has no way to list its keys, so pruning
        # a language the user has just unticked depends on remembering
        # that it was there when we loaded.
        self._known_languages |= set(self.enabled_languages)

        return bool(self.enabled_languages) or not self.enabled

    def _save_extension_settings(self):
        """Write every value back to Orca's extension store."""
        settings = self._settings
        for attr, key, kind in _TOP_LEVEL_KEYS:
            settings.set(key, _coerce(getattr(self, attr), kind, _DEFAULTS[attr]))

        for lang_code, lang_data in self.language_settings.items():
            for attr, suffix, kind in _LANGUAGE_KEYS:
                value = lang_data.get(attr, _LANGUAGE_DEFAULTS[attr])
                settings.set(
                    _language_key(lang_code, suffix),
                    _coerce(value, kind, _LANGUAGE_DEFAULTS[attr]),
                )

        # Drop keys for languages the user has removed, so a language does
        # not come back with stale voice settings if it is re-enabled.
        self._prune_removed_languages()
        self._known_languages = set(self.language_settings)
        for key in _OBSOLETE_KEYS:
            settings.reset(key)

        settings.set(_IS_CONFIGURED_KEY, True)

    def _prune_removed_languages(self):
        """Remove stored per-language keys we no longer have any use for.

        Two kinds: keys for a language the user has unticked, and the voice
        keys every language used to carry before Orca took voices over.
        """
        settings = self._settings
        keep = set(self.language_settings)
        try:
            stored_keys = settings.get_all_keys()
        except AttributeError:
            # ExtensionSettings has no key listing; reset only the keys we
            # know we may have written, which covers both cases without
            # needing to enumerate the store.
            suffixes = [suffix for _attr, suffix, _kind in _LANGUAGE_KEYS]
            # _known_languages, not enabled_languages: by the time the
            # dialog saves, the language the user unticked is already gone
            # from enabled_languages, and keying off that would leave its
            # settings in the store for ever.
            seen = self._known_languages | set(self.enabled_languages) | keep
            stored_keys = [
                _language_key(code, suffix)
                for code in seen - keep
                for suffix in suffixes
            ]
            stored_keys += [
                _language_key(code, suffix)
                for code in seen
                for suffix in _OBSOLETE_LANGUAGE_SUFFIXES
            ]
        for key in stored_keys:
            if not key.startswith(_LANGUAGE_PREFIX):
                continue
            remainder = key[len(_LANGUAGE_PREFIX):]
            code, _, suffix = remainder.rpartition(".")
            if code not in keep or suffix in _OBSOLETE_LANGUAGE_SUFFIXES:
                settings.reset(key)

    def _is_first_run_from_extension_settings(self):
        """First-run check against Orca's extension store."""
        settings = self._settings
        if settings.get(_IS_CONFIGURED_KEY):
            return False
        return not settings.get("enabled-languages")

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
            "mixed_max_words": self.mixed_max_words,
            "detection_mode": self.detection_mode,
            "ignored_apps": self.ignored_apps,
        }
        with open(self._path, "w") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)

    def _migrate_from_profiles(self, language_to_profile):
        """Migrate the oldest JSON format, which mapped languages to Orca profiles.

        All it used to do was look the profile's voice up and copy the
        voice, rate and pitch into Polyglot's own per-language settings.
        Orca owns those now, so the only thing left worth salvaging is
        which languages the user had set up at all.
        """
        for lang_code in language_to_profile:
            self.language_settings.setdefault(lang_code, dict(_LANGUAGE_DEFAULTS))

    # --- Common methods ---

    def migrate_voice_settings_to_orca(self):
        """One-time: turn the old per-language voices into Orca voice sets.

        Polyglot used to store a voice, rate, pitch and volume per
        language. Orca 51 has language voice sets that do the same job in
        its own preferences, so those settings were dropped -- but silently
        dropping a user's tuned voices would be rude. This copies them
        across once, then never runs again.

        Deliberately conservative:
          * A language Orca already has a voice set for is left alone. The
            user's own set wins over anything we remember.
          * The default language is skipped: Orca's global ("primary") set
            already is the main voice, and adding a set for the same
            language would shadow it for no gain.
          * Volume is only copied when it is within 0-10, which is Orca's
            range. Polyglot's spin button allowed 0-100 although its
            default matched Orca's 10.0, so a larger number cannot be
            trusted to mean the same thing -- and guessing wrong makes
            speech suddenly loud.

        Returns True if the store was touched, so the caller can save.
        """
        settings = self._settings
        if settings is None or settings.get(_VOICE_SETS_IMPORTED_KEY):
            return False

        try:
            from orca import speech_manager, speechserver
            from orca.acss import ACSS
            manager = speech_manager.get_manager()
            existing = set(manager.get_voice_set_names())
        except Exception as error:  # pylint: disable=broad-exception-caught
            # No Orca voice-set API: nothing to import into. Leave the
            # marker unset so a later start can try again.
            log.debug(f"Polyglot: voice sets unavailable, not importing: {error}")
            return False

        imported = []
        for lang_code in self.enabled_languages:
            if lang_code == self.default_language or lang_code in existing:
                continue
            voice_name = settings.get(_language_key(lang_code, "voice-name"))
            if not voice_name:
                continue

            family = {speechserver.VoiceFamily.NAME: str(voice_name),
                      speechserver.VoiceFamily.LANG: lang_code}
            dialect = settings.get(_language_key(lang_code, "voice-dialect"))
            if dialect:
                family[speechserver.VoiceFamily.DIALECT] = str(dialect)

            properties = {ACSS.FAMILY: family}
            rate = settings.get(_language_key(lang_code, "rate"))
            if rate is not None:
                properties[ACSS.RATE] = int(rate)
            pitch = settings.get(_language_key(lang_code, "average-pitch"))
            if pitch is not None:
                properties[ACSS.AVERAGE_PITCH] = float(pitch)
            gain = settings.get(_language_key(lang_code, "gain"))
            if gain is not None and 0.0 <= float(gain) <= 10.0:
                properties[ACSS.GAIN] = float(gain)

            try:
                manager.set_voice_set_properties(
                    speechserver.VoiceType.DEFAULT, lang_code, ACSS(properties)
                )
            except Exception as error:  # pylint: disable=broad-exception-caught
                log.warning(f"Polyglot: could not create {lang_code} voice set: {error}")
                continue
            imported.append(f"{lang_code} ({voice_name})")

        settings.set(_VOICE_SETS_IMPORTED_KEY, True)
        if imported:
            log.info(
                "Polyglot: created Orca voice sets from the old per-language "
                "settings: " + ", ".join(imported)
            )
        else:
            log.info("Polyglot: no per-language voices needed importing into Orca.")
        return True

    def auto_configure(self):
        """Pick sensible settings on first run.

        Enables every language Speech Dispatcher has a voice for, and seeds
        the script map. It no longer chooses voices: an utterance carrying
        only a language gets the right one applied by Orca, from whatever
        the user has set up in Orca's Voice Sets preferences.
        """
        from .available_voices import languages as available_languages
        available = available_languages()
        if not available:
            return

        self.enabled_languages = list(available)

        if "en" in available:
            self.default_language = "en"
        elif self.enabled_languages:
            self.default_language = self.enabled_languages[0]

        for lang_code in self.enabled_languages:
            self.language_settings.setdefault(lang_code, dict(_LANGUAGE_DEFAULTS))

        for script, default_lang in _DEFAULT_SCRIPT_TO_LANGUAGE.items():
            if default_lang in _BRAILLE_ONLY_SENTINELS or default_lang in self.enabled_languages:
                self.script_to_language[script] = default_lang

    def prune_unavailable_languages(self):
        """Drop enabled languages Speech Dispatcher can no longer speak.

        Replaces the old voice-availability sync, which also checked that each
        configured voice still existed and substituted a replacement when
        it did not. That is Orca's business now -- a voice set naming a
        removed voice is something Orca's own preferences surface. All that
        is left for us is not offering to detect a language nothing can
        say. Returns True if anything changed.
        """
        from .available_voices import languages as available_languages
        available = set(available_languages())
        if not available:
            # Speech Dispatcher could not be reached. Removing every
            # language on that basis would be destructive, so do nothing.
            log.debug("Polyglot: no voices reported; leaving languages alone")
            return False

        changed = False
        for lang_code in list(self.enabled_languages):
            if lang_code not in available:
                self.enabled_languages.remove(lang_code)
                self.language_settings.pop(lang_code, None)
                log.info(f"Polyglot: no voice for {lang_code} any more; disabled it")
                changed = True

        if self.default_language not in self.enabled_languages:
            if self.enabled_languages:
                self.default_language = self.enabled_languages[0]
                changed = True

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
        if self._settings is not None:
            return self._is_first_run_from_extension_settings()
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
