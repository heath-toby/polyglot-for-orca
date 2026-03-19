"""User-editable character pronunciation dictionary.

Manages a JSON file of custom character names with brief and verbose forms.
User entries override built-in defaults from speech_interceptor._FRIENDLY_NAMES.
"""

import json
import logging
import os
import unicodedata

log = logging.getLogger("polyglot")

_CUSTOM_NAMES_DIR = os.path.join(
    os.environ.get("XDG_DATA_HOME", os.path.expanduser("~/.local/share")),
    "orca", "polyglot"
)
_CUSTOM_NAMES_FILE = os.path.join(_CUSTOM_NAMES_DIR, "custom_names.json")

# {char: {"brief": str, "verbose": str}}
_custom_names = {}
_file_mtime = 0.0


def load():
    """Load custom names from JSON file. Safe to call repeatedly — only
    re-reads if the file has been modified."""
    global _custom_names, _file_mtime

    try:
        mtime = os.path.getmtime(_CUSTOM_NAMES_FILE)
    except OSError:
        return

    if mtime == _file_mtime:
        return

    try:
        with open(_CUSTOM_NAMES_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        _custom_names = {}
        for char, entry in data.items():
            if isinstance(entry, dict):
                _custom_names[char] = {
                    "brief": entry.get("brief", ""),
                    "verbose": entry.get("verbose", ""),
                }
            elif isinstance(entry, str):
                # Simple format: just a name used for both modes
                _custom_names[char] = {"brief": entry, "verbose": entry}
        _file_mtime = mtime
        log.debug(f"Loaded {len(_custom_names)} custom character names")
    except Exception as e:
        log.error(f"Failed to load custom names: {e}")


def save():
    """Save custom names to JSON file."""
    global _file_mtime

    os.makedirs(_CUSTOM_NAMES_DIR, exist_ok=True)
    try:
        with open(_CUSTOM_NAMES_FILE, "w", encoding="utf-8") as f:
            json.dump(_custom_names, f, ensure_ascii=False, indent=2)
        _file_mtime = os.path.getmtime(_CUSTOM_NAMES_FILE)
    except Exception as e:
        log.error(f"Failed to save custom names: {e}")


def get_name(char, verbosity="verbose"):
    """Look up a custom name for a character. Returns None if not found."""
    entry = _custom_names.get(char)
    if entry is None:
        return None
    name = entry.get(verbosity, "") or entry.get("verbose", "")
    return name if name else None


def set_name(char, brief="", verbose=""):
    """Set a custom name for a character."""
    _custom_names[char] = {"brief": brief, "verbose": verbose}


def remove_name(char):
    """Remove a custom name entry."""
    _custom_names.pop(char, None)


def has_custom_name(char):
    """Check if a character has a user-defined custom name."""
    return char in _custom_names


def get_all_entries():
    """Return a copy of all custom name entries.

    Returns: dict of {char: {"brief": str, "verbose": str}}
    """
    return {ch: dict(entry) for ch, entry in _custom_names.items()}


def get_all_with_builtins(builtin_friendly_names):
    """Return all characters — builtins merged with user overrides.

    Converts built-in _FRIENDLY_NAMES (keyed by Unicode name) into
    character-keyed entries, then overlays user custom names on top.

    Returns: list of (char, unicode_name, brief, verbose, is_custom) tuples,
    sorted by Unicode name.
    """
    entries = {}

    # First, add all built-in friendly names
    for unicode_name, friendly in builtin_friendly_names.items():
        try:
            char = unicodedata.lookup(unicode_name)
        except KeyError:
            continue
        entries[char] = {
            "unicode_name": unicode_name,
            "brief": friendly,
            "verbose": friendly,
            "is_custom": False,
        }

    # Overlay user custom names
    for char, custom in _custom_names.items():
        unicode_name = unicodedata.name(char, f"U+{ord(char):04X}")
        if char in entries:
            entries[char]["brief"] = custom.get("brief", "") or entries[char]["brief"]
            entries[char]["verbose"] = custom.get("verbose", "") or entries[char]["verbose"]
            entries[char]["is_custom"] = True
        else:
            entries[char] = {
                "unicode_name": unicode_name,
                "brief": custom.get("brief", ""),
                "verbose": custom.get("verbose", ""),
                "is_custom": True,
            }

    # Sort by Unicode name
    result = []
    for char, info in sorted(entries.items(), key=lambda x: x[1]["unicode_name"]):
        result.append((
            char,
            info["unicode_name"],
            info["brief"],
            info["verbose"],
            info["is_custom"],
        ))
    return result
