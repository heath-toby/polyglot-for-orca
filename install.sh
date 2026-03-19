#!/usr/bin/env bash
# Polyglot for Orca — Installer
# Installs the add-on into Orca's user data directory.

set -euo pipefail

ADDON_NAME="polyglot"
OLD_ADDON_NAME="orca_autoswitch"
ORCA_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/orca"
ADDON_DIR="$ORCA_DIR/$ADDON_NAME"
OLD_ADDON_DIR="$ORCA_DIR/$OLD_ADDON_NAME"
CUSTOMIZATIONS="$ORCA_DIR/orca-customizations.py"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SOURCE_DIR="$SCRIPT_DIR/$ADDON_NAME"

# --- Helpers ---

info()  { echo "  [+] $*"; }
warn()  { echo "  [!] $*"; }
error() { echo "  [ERROR] $*" >&2; exit 1; }

# --- Pre-flight checks ---

echo ""
echo "=== Polyglot for Orca — Installer ==="
echo ""

# Check that Orca is installed
if ! python3 -c "import orca" 2>/dev/null; then
    error "Orca screen reader not found. Please install Orca first."
fi
info "Orca found."

# Check that Speech Dispatcher is available
if ! python3 -c "import speechd" 2>/dev/null; then
    warn "Speech Dispatcher Python bindings not found."
    warn "Voice discovery will be limited. Install python-speechd if available."
fi

# Check source files exist
if [ ! -d "$SOURCE_DIR" ]; then
    error "Source directory '$SOURCE_DIR' not found. Run this script from the extracted archive."
fi

# --- Migration from old orca_autoswitch installation ---

if [ -d "$OLD_ADDON_DIR" ] && [ ! -d "$ADDON_DIR" ]; then
    info "Migrating from orca_autoswitch to polyglot..."
    cp -a "$OLD_ADDON_DIR" "$ADDON_DIR"

    # Rename config file if it exists
    if [ -f "$ADDON_DIR/autoswitch_config.json" ]; then
        mv "$ADDON_DIR/autoswitch_config.json" "$ADDON_DIR/polyglot_config.json"
    fi
    if [ -f "$ADDON_DIR/autoswitch_config.json.migrated" ]; then
        mv "$ADDON_DIR/autoswitch_config.json.migrated" "$ADDON_DIR/polyglot_config.json.migrated"
    fi

    # Migrate GSettings data from old dconf path to new
    if command -v dconf >/dev/null 2>&1; then
        OLD_DCONF=$(dconf dump /org/gnome/orca/autoswitch/ 2>/dev/null || true)
        if [ -n "$OLD_DCONF" ]; then
            echo "$OLD_DCONF" | dconf load /org/gnome/orca/polyglot/ 2>/dev/null || true
            info "GSettings data migrated."
        fi
    fi

    info "Migration complete. Removing old installation..."
    rm -rf "$OLD_ADDON_DIR"
fi

# --- Installation ---

# Create the Orca data directory if needed
mkdir -p "$ORCA_DIR"

# Back up existing installation if present
if [ -d "$ADDON_DIR" ]; then
    # Preserve the user's config file
    if [ -f "$ADDON_DIR/polyglot_config.json" ]; then
        info "Backing up existing configuration..."
        cp "$ADDON_DIR/polyglot_config.json" "/tmp/polyglot_config.json.bak"
    fi
    info "Removing previous installation..."
    # Remove old Python files but keep .venv if it exists (saves re-downloading lingua)
    find "$ADDON_DIR" -maxdepth 1 -name "*.py" -delete
    find "$ADDON_DIR" -maxdepth 1 -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
fi

# Copy add-on files
info "Installing add-on files to $ADDON_DIR..."
mkdir -p "$ADDON_DIR"
cp "$SOURCE_DIR"/*.py "$ADDON_DIR/"

# Restore config if we backed it up
if [ -f "/tmp/polyglot_config.json.bak" ]; then
    cp "/tmp/polyglot_config.json.bak" "$ADDON_DIR/polyglot_config.json"
    rm -f "/tmp/polyglot_config.json.bak"
    info "Configuration restored."
fi

# --- Remove old orca_autoswitch remnants ---

if [ -d "$OLD_ADDON_DIR" ]; then
    info "Removing old orca_autoswitch directory..."
    rm -rf "$OLD_ADDON_DIR"
fi

# Remove old GSettings schema if present
OLD_SCHEMA_FILE="org.gnome.Orca.AutoSwitch.gschema.xml"
SCHEMA_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/glib-2.0/schemas"
if [ -f "$SCHEMA_DIR/$OLD_SCHEMA_FILE" ]; then
    rm -f "$SCHEMA_DIR/$OLD_SCHEMA_FILE"
    info "Removed old GSettings schema."
fi

# Clear old dconf settings
if command -v dconf >/dev/null 2>&1; then
    dconf reset -f /org/gnome/orca/autoswitch/ 2>/dev/null || true
fi

# --- Install GSettings schema ---

SCHEMA_FILE="org.gnome.Orca.Polyglot.gschema.xml"

if [ -f "$SOURCE_DIR/$SCHEMA_FILE" ]; then
    info "Installing GSettings schema..."
    mkdir -p "$SCHEMA_DIR"
    cp "$SOURCE_DIR/$SCHEMA_FILE" "$SCHEMA_DIR/"
    if command -v glib-compile-schemas >/dev/null 2>&1; then
        glib-compile-schemas "$SCHEMA_DIR" 2>/dev/null && \
            info "GSettings schema compiled." || \
            warn "Could not compile GSettings schema. Settings will fall back to JSON."
    else
        warn "glib-compile-schemas not found. Settings will fall back to JSON."
    fi
else
    warn "GSettings schema file not found. Settings will use JSON."
fi

# --- Set up orca-customizations.py ---

LOADER_BLOCK='# --- polyglot begin ---
import sys as _sys, os as _os, logging as _logging
_polyglot_log = _logging.getLogger("polyglot")
_orca_dir = _os.path.join(
    _os.environ.get("XDG_DATA_HOME", _os.path.expanduser("~/.local/share")),
    "orca"
)
if _orca_dir not in _sys.path:
    _sys.path.insert(0, _orca_dir)
try:
    from polyglot import speech_interceptor
    speech_interceptor.install()
except Exception as _e:
    _polyglot_log.error(f"Failed to load Polyglot: {_e}", exc_info=True)
# --- polyglot end ---'

if [ -f "$CUSTOMIZATIONS" ]; then
    # Remove old orca-autoswitch loader block if present
    if grep -q "orca-autoswitch begin" "$CUSTOMIZATIONS" 2>/dev/null; then
        info "Removing old orca-autoswitch loader block..."
        sed -i '/# --- orca-autoswitch begin ---/,/# --- orca-autoswitch end ---/d' "$CUSTOMIZATIONS"
    fi

    # Remove the new polyglot loader block if present (for re-installs)
    if grep -q "polyglot begin" "$CUSTOMIZATIONS" 2>/dev/null; then
        info "Removing previous Polyglot loader block..."
        sed -i '/# --- polyglot begin ---/,/# --- polyglot end ---/d' "$CUSTOMIZATIONS"
    fi

    # Remove any old-style unmarked loader that imports orca_autoswitch
    if grep -q "orca_autoswitch" "$CUSTOMIZATIONS" 2>/dev/null; then
        info "Removing old-style loader..."
        python3 -c "
import re, sys
with open(sys.argv[1]) as f:
    content = f.read()
lines = content.split('\n')
clean = []
skip = False
for line in lines:
    if 'auto-language-switch' in line.lower() and (line.strip().startswith('\"\"\"') or line.strip().startswith('#')):
        continue
    if 'orca_autoswitch' in line or 'orca-autoswitch' in line:
        skip = True
        continue
    if skip and (line.strip().startswith('except') or line.strip().startswith('_log.')):
        continue
    skip = False
    clean.append(line)
result = '\n'.join(clean).strip()
with open(sys.argv[1], 'w') as f:
    f.write(result + '\n' if result else '')
" "$CUSTOMIZATIONS"
        info "Old-style loader removed."
    fi

    # If the file still has content, append; otherwise overwrite
    if [ -s "$CUSTOMIZATIONS" ] && grep -q '[^[:space:]]' "$CUSTOMIZATIONS" 2>/dev/null; then
        echo "" >> "$CUSTOMIZATIONS"
        echo "$LOADER_BLOCK" >> "$CUSTOMIZATIONS"
        info "Loader appended to existing orca-customizations.py."
    else
        echo "$LOADER_BLOCK" > "$CUSTOMIZATIONS"
        info "Created orca-customizations.py with loader."
    fi
else
    echo "$LOADER_BLOCK" > "$CUSTOMIZATIONS"
    info "Created orca-customizations.py with loader."
fi

# --- Install lingua (language detection library) ---

info "Setting up language detection library..."

VENV_DIR="$ADDON_DIR/.venv"
LINGUA_PKG="lingua-language-detector>=2.0"

# Create venv if it doesn't exist
if [ ! -d "$VENV_DIR" ]; then
    info "Creating virtual environment..."
    python3 -m venv "$VENV_DIR" 2>/dev/null || {
        warn "Could not create venv. Trying without venv..."
        pip install --user "$LINGUA_PKG" 2>/dev/null || {
            warn "Could not install lingua. The add-on will work with"
            warn "script-based detection only (Cyrillic, Arabic, etc.)."
            warn "Latin-script languages (English/German/French/etc.) will"
            warn "not be auto-detected. Install manually with:"
            warn "  pip install '$LINGUA_PKG'"
        }
    }
fi

if [ -d "$VENV_DIR" ]; then
    info "Upgrading pip..."
    "$VENV_DIR/bin/pip" install --quiet --upgrade pip 2>&1 || true
    info "Installing/upgrading lingua (this may take a moment)..."
    "$VENV_DIR/bin/pip" install --quiet --upgrade "$LINGUA_PKG" 2>&1 || {
        warn "Lingua installation failed. Latin-script detection unavailable."
    }
    info "Installing/upgrading numpy and emoji..."
    "$VENV_DIR/bin/pip" install --quiet --upgrade numpy emoji 2>&1 || {
        warn "numpy/emoji installation failed. Some features may be unavailable."
    }
    if "$VENV_DIR/bin/python3" -c "import lingua" 2>/dev/null; then
        LINGUA_VER=$("$VENV_DIR/bin/pip" show lingua-language-detector 2>/dev/null | grep Version | cut -d' ' -f2)
        info "Lingua $LINGUA_VER installed successfully."
    else
        warn "Lingua could not be loaded. Latin-script detection unavailable."
        warn "Try: $VENV_DIR/bin/pip install '$LINGUA_PKG' numpy"
    fi
fi

# --- Done ---

echo ""
echo "=== Installation complete! ==="
echo ""
echo "  Restart Orca for changes to take effect."
echo "  On first launch, Polyglot will auto-detect your installed"
echo "  voices and configure language switching."
echo ""
echo "  Settings: press Orca+Shift+L at any time."
echo "  Debug logging: ORCA_POLYGLOT_DEBUG=1 orca"
echo "  Uninstall: run ./uninstall.sh"
echo ""
