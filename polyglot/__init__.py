"""Polyglot for Orca.

Automatically detects the language of text and switches voice and braille
accordingly. Also provides emoji, emoticon, and Unicode character
announcement.

Orca 51 user extension. Install to $XDG_DATA_HOME/orca/extensions/ and
approve with ``orca --approve-extension polyglot``; Orca re-checks the
hash of every file in the package on each start, so re-approve after
editing. The venv, custom character names and debug log live outside the
package for exactly that reason -- see ``speech_interceptor._DATA_DIR``.
"""

__version__ = "2.8.0"

import logging

from orca import gsettings_registry
from orca.extension import Extension

# Import submodules as `from .module import name`, never as
# `from . import module`. The loader imports us as
# orca_user_extension.<name> but never creates `orca_user_extension`
# itself, and `from . import module` goes through __import__ with the
# full dotted path, which insists on importing that absent grandparent.
from .config import Config, migrate_legacy_settings
from .speech_interceptor import install as _install_patches
from .speech_interceptor import open_settings as _open_settings
from .speech_interceptor import reload_config as _reload_config
from .speech_interceptor import uninstall as _uninstall_patches

log = logging.getLogger("polyglot")

# Where Orca keeps per-extension settings: schema "extensions", one
# relocatable path per extension namespace, all under the single key
# "settings". The namespace is the extension's source id -- the name of
# this package -- which is the last component of __name__ once the
# loader has imported us as orca_user_extension.<namespace>.
_SETTINGS_SCHEMA = "extensions"
_SETTINGS_KEY = "settings"
_NAMESPACE = gsettings_registry.GSettingsRegistry.sanitize_gsettings_path(
    __name__.rsplit(".", 1)[-1]
)


class Polyglot(Extension):
    """Switches voice and braille table to match the language of the text."""

    GROUP_LABEL = "Polyglot"
    DESCRIPTION = "Detects the language of text as Orca speaks it and switches voice and braille contraction table to match, and announces emoji, emoticons and Unicode characters by name."
    VERSION = "2.8.0"  # keep in sync with __version__; read by AST, must be a literal
    AUTHOR = "Toby"

    def __init__(self) -> None:
        super().__init__()
        self._config = None
        # Kept alive deliberately: the change signal stops firing once
        # the Gio.Settings object is garbage-collected.
        self._watch = None

    def _get_commands(self) -> list:
        """Returns this extension's keyboard commands."""

        from orca import command_manager, keybindings

        keybinding = keybindings.KeyBinding("l", keybindings.ORCA_SHIFT_MODIFIER_MASK)
        return [
            command_manager.KeyboardCommand(
                name="polyglotSettingsHandler",
                function=_open_settings,
                group_label=self.GROUP_LABEL,
                description="Opens the Polyglot settings dialog",
                desktop_keybinding=keybinding,
                laptop_keybinding=keybinding,
            )
        ]

    # get_preferences() is deliberately not overridden. Orca's generated
    # preferences dialog can only render the declarative kinds, and
    # Polyglot's settings are nothing like a flat form: a per-language
    # voice table, modal sub-dialogs for voice and braille table choice,
    # a script-to-language mapping editor, custom character names. None
    # of that can be declared, and there is no hook to substitute a
    # custom dialog for the generated one. By declaring no preferences,
    # the Settings button in Orca Preferences -> User Extensions stays
    # inactive and Orca+Shift+L remains the single way in.

    # --- Lifecycle ------------------------------------------------------

    def on_ready(self) -> None:
        """Imports legacy settings if needed, then applies the patches."""

        self._start()

    def on_enabled(self) -> None:
        """Applies the patches after a reload."""

        self._start()

    def on_disabled(self) -> None:
        """Removes the patches, restoring Orca's own speech pipeline."""

        self._stop()

    def on_shutdown(self) -> None:
        """Deliberately does nothing.

        Orca runs shutdown hooks in a daemon thread with a timeout, but
        tearing this extension down means GLib source removal, GStreamer
        state changes and un-monkey-patching, all of which are main-thread
        work. Doing it off-thread risks a warning, an assertion or a hung
        exit -- and buys nothing, because the process is exiting anyway.
        on_disabled, which Orca does call on the main thread, still does
        the real teardown when the extension is disabled or reloaded.
        """

    def _start(self) -> None:
        if self._config is not None:
            return
        migrate_legacy_settings(self.settings)
        self._config = Config(settings=self.settings)
        self._watch_settings()
        _install_patches(self._config)

    def _stop(self) -> None:
        _uninstall_patches()
        self._watch = None
        self._config = None

    # --- Reacting to settings changes -----------------------------------

    def _watch_settings(self) -> None:
        """Re-read settings whenever the store changes.

        The dialog applies its own changes as it saves, but a write made
        any other way -- dconf, a second profile -- would otherwise not
        be noticed until Orca restarts.
        """
        if self._watch is not None:
            return
        try:
            registry = gsettings_registry.get_registry()
            gs = registry.get_settings(
                _SETTINGS_SCHEMA,
                registry.get_active_profile(),
                f"extensions/{_NAMESPACE}",
            )
            if gs is None:
                log.warning("Polyglot: no settings object to watch; changes need a reload.")
                return
            gs.connect(f"changed::{_SETTINGS_KEY}", self._on_settings_key_changed)
            self._watch = gs
        except Exception as error:  # pylint: disable=broad-exception-caught
            log.warning(f"Polyglot: could not watch settings ({error}); changes need a reload.")

    def _on_settings_key_changed(self, _settings, _key) -> None:
        # reload_config(), not _config.load(): the language detector and
        # the ACSS voice cache are built from the config at install time,
        # so re-reading the values alone would leave them stale.
        if self._config is not None:
            _reload_config()
