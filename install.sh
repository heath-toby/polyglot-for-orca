#!/usr/bin/env bash
# Polyglot for Orca -- Installer
#
# Installs Polyglot as an Orca 51 user extension, into
# ~/.local/share/orca/extensions/, and approves it so Orca will load it.
#
# Only code goes in the extension package. The Python venv, custom
# character names and the debug log live in Polyglot's data directory,
# ~/.local/share/orca/polyglot/. That split is deliberate: Orca approves
# an extension by hashing every file in its directory, so anything
# written at runtime has to live elsewhere. It also means the venv --
# whose scripts bake in an absolute path -- never has to be rebuilt for a
# package move again.
#
# Re-running is safe. Because approval is by content hash, the script
# re-approves on every run, which is what you want after editing.

set -euo pipefail

ADDON_NAME="polyglot"
ORCA_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/orca"
EXTENSIONS_DIR="$ORCA_DIR/extensions"
ADDON_DIR="$EXTENSIONS_DIR/$ADDON_NAME"
DATA_DIR="$ORCA_DIR/$ADDON_NAME"
VENV_DIR="$DATA_DIR/.venv"
CUSTOMIZATIONS="$ORCA_DIR/orca-customizations.py"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SOURCE_DIR="$SCRIPT_DIR/$ADDON_NAME"

LINGUA_PKG="lingua-language-detector>=2.0"

BEGIN_MARKER="# --- polyglot begin ---"
END_MARKER="# --- polyglot end ---"

# Pre-extension install locations to carry user data across from.
LEGACY_DIRS=("$ORCA_DIR/polyglot_v51" "$ORCA_DIR/polyglot_v50")

info()  { echo "  [+] $*"; }
warn()  { echo "  [!] $*"; }
error() { echo "  [ERROR] $*" >&2; exit 1; }

echo ""
echo "=== Polyglot for Orca -- Installer ==="
echo ""

# Probe via extension_loader, not orca.extension: importing orca.extension
# first hits a circular import inside Orca itself (live_region_presenter
# imports it mid-initialisation). extension_loader pulls in command_manager
# ahead of it, so this import order is the one that works.
if ! python3 -c "import orca.extension_loader" 2>/dev/null; then
    error "Orca 51 or later with extension support not found."
fi
info "Orca with extension support found."

[ -d "$SOURCE_DIR" ] || error "Source directory '$SOURCE_DIR' not found."
rm -rf "$SOURCE_DIR/__pycache__"

# --- Data directory, and anything to rescue from an older install ---

mkdir -p "$DATA_DIR"

for legacy in "${LEGACY_DIRS[@]}"; do
    [ -d "$legacy" ] || continue
    # Custom character names. The pre-extension code already read these
    # from the data directory, so a copy sitting in a renamed add-on
    # folder is one the add-on had stopped loading.
    if [ -f "$legacy/custom_names.json" ] && [ ! -f "$DATA_DIR/custom_names.json" ]; then
        cp "$legacy/custom_names.json" "$DATA_DIR/custom_names.json"
        info "Recovered custom character names from $(basename "$legacy")."
    fi
    if [ -f "$legacy/polyglot_config.json" ] && [ ! -f "$DATA_DIR/polyglot_config.json" ]; then
        cp "$legacy/polyglot_config.json" "$DATA_DIR/polyglot_config.json"
        info "Recovered the legacy JSON config from $(basename "$legacy")."
    fi
done

# --- The venv, in the data directory ---

if [ ! -d "$VENV_DIR" ]; then
    # A venv from an older install lives inside the add-on folder and its
    # scripts hardcode that path, so copying it across would leave a
    # broken pip. Build a fresh one instead.
    info "Creating the Python environment (this may take a moment)..."
    python3 -m venv "$VENV_DIR" || error "Could not create the venv at $VENV_DIR"
fi

if [ -x "$VENV_DIR/bin/pip" ]; then
    "$VENV_DIR/bin/pip" install --quiet --upgrade pip >/dev/null 2>&1 || true
    info "Installing/upgrading lingua and emoji..."
    "$VENV_DIR/bin/pip" install --quiet --upgrade "$LINGUA_PKG" emoji >/dev/null 2>&1 || {
        warn "Package installation failed. Language detection may fall back to"
        warn "script-based detection only. Retry with:"
        warn "  $VENV_DIR/bin/pip install '$LINGUA_PKG' emoji"
    }
    if "$VENV_DIR/bin/python3" -c "import lingua" 2>/dev/null; then
        LINGUA_VER=$("$VENV_DIR/bin/pip" show lingua-language-detector 2>/dev/null \
            | awk '/^Version:/{print $2}')
        info "lingua ${LINGUA_VER:-installed} ready."
    else
        warn "lingua is not importable; statistical detection will be unavailable."
    fi
else
    warn "No pip in $VENV_DIR; skipping package installation."
fi

# --- Word lists for the dictionary detection tier ---

# Optional, and kept out of this script's critical path on purpose: the
# lists are a download from a third party, so installing them is a separate
# decision the user makes by running the fetcher.
DICT_DIR="$DATA_DIR/dictionaries"
dict_count=$(find "$DICT_DIR" -maxdepth 1 -name '*.txt' 2>/dev/null | wc -l)
if [ "$dict_count" -ge 2 ]; then
    info "Word lists installed for dictionary detection: $dict_count languages."
else
    info "No word lists yet. For dictionary-based detection, run:"
    info "  ./fetch-dictionaries.sh"
fi

# --- The extension package: code only ---

mkdir -p "$ADDON_DIR"
# Remove files that no longer exist in the source, so the installed
# package -- and therefore its approval hash -- matches the source.
find "$ADDON_DIR" -maxdepth 1 -name '*.py' -delete
rm -rf "$ADDON_DIR/__pycache__" "$ADDON_DIR/.venv"
cp "$SOURCE_DIR"/*.py "$ADDON_DIR/"
info "Installed extension package to $ADDON_DIR"

if orca --approve-extension "$ADDON_NAME" >/dev/null 2>&1; then
    info "Approved '$ADDON_NAME' with Orca."
else
    error "Could not approve the extension. Run: orca --approve-extension $ADDON_NAME"
fi

# Clean up after the pre-extension installer, if its block is still there.
if [ -f "$CUSTOMIZATIONS" ] && grep -qF "$BEGIN_MARKER" "$CUSTOMIZATIONS" 2>/dev/null; then
    sed -i "/${BEGIN_MARKER//\//\\/}/,/${END_MARKER//\//\\/}/d" "$CUSTOMIZATIONS"
    info "Removed the obsolete Polyglot block from orca-customizations.py."
fi

echo ""
echo "=== Installation complete ==="
echo ""
echo "  Restart Orca to activate:"
echo "    orca --replace &"
echo ""
echo "  Settings: Orca+Shift+L. Data and venv: $DATA_DIR"
echo "  Word lists (optional, for dictionary detection): ./fetch-dictionaries.sh"
echo "  Settings from the old org.gnome.Orca.Polyglot schema are imported"
echo "  on first run; nothing to do by hand."
echo ""
