"""Discovers available voices from Speech Dispatcher and maps languages to voices.

Optionally reads Orca profiles for rate/pitch preferences, but does not require them.
"""

import json
import logging
import os

log = logging.getLogger("polyglot")

_DEFAULT_RATE = 50.0
_DEFAULT_PITCH = 5.0
_DEFAULT_GAIN = 10.0


class VoiceMapper:
    """Discovers voices from Speech Dispatcher, optionally enhanced by Orca profiles."""

    def __init__(self, settings_path=None):
        if settings_path is None:
            settings_path = os.path.join(
                os.environ.get("XDG_DATA_HOME", os.path.expanduser("~/.local/share")),
                "orca", "user-settings.conf"
            )
        self._settings_path = settings_path
        # {lang_code: {voice_name, full_lang, dialect, voices: [list of all voices]}}
        self._lang_to_voice = {}
        # {lang_code: profile_name} — only populated if profiles exist
        self._lang_to_profile = {}
        self._speechd_voices = {}
        # Default profile's voice settings (rate, pitch, gain) — used as baseline
        self._default_profile_settings = {
            "rate": _DEFAULT_RATE,
            "average-pitch": _DEFAULT_PITCH,
            "gain": _DEFAULT_GAIN,
        }
        self._load()

    def _load(self):
        """Discover voices from Speech Dispatcher, then overlay Orca profile preferences."""
        self._speechd_voices = self._query_speechd_voices()
        self._build_from_speechd()
        self._overlay_profile_preferences()

    @staticmethod
    def _query_speechd_voices():
        """Query Speech Dispatcher for all available synthesis voices.

        Returns a dict mapping base language code (e.g. 'en', 'de') to a list of
        (voice_name, full_lang, variant) tuples.
        """
        lang_to_voices = {}
        try:
            import speechd
            client = speechd.SSIPClient("polyglot-mapper")
            try:
                for voice_name, lang_code, variant in client.list_synthesis_voices():
                    if lang_code:
                        base = lang_code.split("-")[0].split("_")[0].lower()
                        lang_to_voices.setdefault(base, []).append(
                            (voice_name, lang_code, variant)
                        )
            finally:
                client.close()
        except Exception as e:
            log.debug(f"Could not query Speech Dispatcher voices: {e}")
        return lang_to_voices

    def _build_from_speechd(self):
        """Build language-to-voice mapping from Speech Dispatcher voices."""
        for lang_code, voices in self._speechd_voices.items():
            if not voices:
                continue
            # Pick the first voice as default
            voice_name, full_lang, variant = voices[0]
            # Parse dialect from full_lang (e.g. "en-GB" -> "GB")
            dialect = ""
            if "-" in full_lang:
                dialect = full_lang.split("-", 1)[1]
            elif "_" in full_lang:
                dialect = full_lang.split("_", 1)[1]

            self._lang_to_voice[lang_code] = {
                "family": {
                    "name": voice_name,
                    "lang": lang_code,
                    "dialect": dialect,
                },
                "rate": _DEFAULT_RATE,
                "average-pitch": _DEFAULT_PITCH,
                "all_voices": voices,
            }

    @staticmethod
    def _lenient_json_load(path):
        """Load Orca's user-settings.conf, tolerating malformed JSON.

        Orca's settings file can have JSON errors (missing commas, etc.)
        especially in the 'general' section. We try strict parsing first,
        then fall back to extracting top-level sections individually by
        matching braces.
        """
        with open(path, "r") as f:
            text = f.read()

        # Try strict parse first
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # Fall back: extract top-level sections by finding their brace-matched content
        result = {}
        for section in ("profiles", "general"):
            extracted = VoiceMapper._extract_json_section(text, section)
            if extracted is not None:
                result[section] = extracted
        return result if result else None

    @staticmethod
    def _extract_json_section(text, key):
        """Extract a top-level JSON section by key, matching braces.

        Finds '"key": {' and returns the parsed content of the matched object.
        """
        import re
        pattern = rf'"{re.escape(key)}"\s*:\s*\{{'
        match = re.search(pattern, text)
        if not match:
            return None

        # Find the opening brace
        brace_start = text.index("{", match.start() + len(key) + 2)
        depth = 0
        in_string = False
        escape_next = False
        for i in range(brace_start, len(text)):
            ch = text[i]
            if escape_next:
                escape_next = False
                continue
            if ch == "\\":
                escape_next = True
                continue
            if ch == '"':
                in_string = not in_string
                continue
            if in_string:
                continue
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    section_text = text[brace_start:i + 1]
                    try:
                        return json.loads(section_text)
                    except json.JSONDecodeError:
                        return None
        return None

    def _overlay_profile_preferences(self):
        """If Orca profiles exist, use their voice/rate/pitch as preferences."""
        try:
            data = self._lenient_json_load(self._settings_path)
        except FileNotFoundError:
            return
        if data is None:
            return

        # Read the default profile's voice settings as baseline for all languages
        self._extract_default_profile_settings(data)

        profiles = data.get("profiles", {})

        for profile_name, profile_data in profiles.items():
            voices = profile_data.get("voices", {})
            default_voice = voices.get("default", {})
            family = default_voice.get("family", {})
            lang = family.get("lang", "")

            if not lang:
                continue

            voice_name = family.get("name", "")

            # Skip Orca placeholder voices — use the speechd-discovered one
            if voice_name.lower() in {"default default voice", ""}:
                # Still record profile for rate/pitch
                if lang in self._lang_to_voice:
                    voice_config = self._lang_to_voice[lang]
                    rate = default_voice.get("rate")
                    if rate is not None:
                        voice_config["rate"] = rate
                    pitch = default_voice.get("average-pitch")
                    if pitch is not None:
                        voice_config["average-pitch"] = pitch
                    self._lang_to_profile[lang] = profile_name
                continue

            # Verify this voice actually exists in Speech Dispatcher
            available = self._speechd_voices.get(lang, [])
            voice_exists = any(v[0] == voice_name for v in available)

            voice_config = self._lang_to_voice.get(lang, {
                "family": {},
                "rate": _DEFAULT_RATE,
                "average-pitch": _DEFAULT_PITCH,
            })

            if voice_exists:
                voice_config["family"] = {
                    "name": voice_name,
                    "lang": lang,
                    "dialect": family.get("dialect", ""),
                }
            # If the profile voice doesn't exist any more, keep the speechd default

            rate = default_voice.get("rate")
            if rate is not None:
                voice_config["rate"] = rate
            pitch = default_voice.get("average-pitch")
            if pitch is not None:
                voice_config["average-pitch"] = pitch

            braille_table = profile_data.get("brailleContractionTable", "")
            if braille_table:
                voice_config["brailleContractionTable"] = braille_table

            self._lang_to_voice[lang] = voice_config
            self._lang_to_profile[lang] = profile_name

    def _extract_default_profile_settings(self, data):
        """Extract rate/pitch/gain from the default Orca profile or general section.

        These serve as the baseline for languages that don't have their own profile.
        Checks 'profiles.default' first, falls back to 'general'.
        """
        for section_key in ("profiles", "general"):
            if section_key == "profiles":
                section = data.get("profiles", {}).get("default", {})
            else:
                section = data.get("general", {})

            voices = section.get("voices", {})
            default_voice = voices.get("default", {})

            rate = default_voice.get("rate")
            if rate is not None:
                self._default_profile_settings["rate"] = rate
                pitch = default_voice.get("average-pitch")
                if pitch is not None:
                    self._default_profile_settings["average-pitch"] = pitch
                gain = default_voice.get("gain")
                if gain is not None:
                    self._default_profile_settings["gain"] = gain
                # Found settings in this section, no need to check the next
                return

    def get_default_profile_settings(self):
        """Return the default profile's voice settings (rate, pitch, gain).

        Used as baseline defaults for languages that don't have their own Orca profile.
        """
        return self._default_profile_settings.copy()

    def get_voice_for_language(self, lang_code):
        """Return voice config dict for the given ISO 639-1 language code, or None."""
        return self._lang_to_voice.get(lang_code)

    def get_profile_for_language(self, lang_code):
        """Return profile name for the given language code, or None."""
        return self._lang_to_profile.get(lang_code)

    def get_language_to_profile_map(self):
        """Return {lang_code: profile_name} mapping (only languages with profiles)."""
        return self._lang_to_profile.copy()

    def get_available_languages(self):
        """Return list of all language codes with available voices."""
        return list(self._lang_to_voice.keys())

    def get_voices_for_language(self, lang_code):
        """Return list of (voice_name, full_lang, variant) for a language."""
        config = self._lang_to_voice.get(lang_code)
        if config:
            return config.get("all_voices", [])
        return self._speechd_voices.get(lang_code, [])

    def get_all_speechd_voices(self):
        """Return the full {lang_code: [(voice_name, full_lang, variant)]} dict."""
        return self._speechd_voices

    def reload(self):
        """Re-query Speech Dispatcher and reload profiles."""
        self._lang_to_voice.clear()
        self._lang_to_profile.clear()
        self._speechd_voices.clear()
        self._load()
