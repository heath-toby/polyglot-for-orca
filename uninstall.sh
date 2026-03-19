#!/usr/bin/env bash
# Polyglot for Orca — Uninstaller
# Completely removes the add-on and restores Orca to its original state.

set -euo pipefail

ADDON_NAME="polyglot"
OLD_ADDON_NAME="orca_autoswitch"
ORCA_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/orca"
ADDON_DIR="$ORCA_DIR/$ADDON_NAME"
OLD_ADDON_DIR="$ORCA_DIR/$OLD_ADDON_NAME"
CUSTOMIZATIONS="$ORCA_DIR/orca-customizations.py"

info()  { echo "  [+] $*"; }
warn()  { echo "  [!] $*"; }

echo ""
echo "=== Polyglot for Orca — Uninstaller ==="
echo ""

# --- Remove the loader from orca-customizations.py ---

if [ -f "$CUSTOMIZATIONS" ]; then
    # Remove new polyglot loader
    if grep -q "polyglot begin" "$CUSTOMIZATIONS" 2>/dev/null; then
        info "Removing Polyglot loader from orca-customizations.py..."
        sed -i '/# --- polyglot begin ---/,/# --- polyglot end ---/d' "$CUSTOMIZATIONS"
    fi

    # Also remove old orca-autoswitch loader if still present
    if grep -q "orca-autoswitch begin" "$CUSTOMIZATIONS" 2>/dev/null; then
        info "Removing old orca-autoswitch loader..."
        sed -i '/# --- orca-autoswitch begin ---/,/# --- orca-autoswitch end ---/d' "$CUSTOMIZATIONS"
    fi

    # Remove the file entirely if it's now empty (only whitespace left)
    if [ ! -s "$CUSTOMIZATIONS" ] || ! grep -q '[^[:space:]]' "$CUSTOMIZATIONS" 2>/dev/null; then
        rm -f "$CUSTOMIZATIONS"
        info "Removed empty orca-customizations.py."
    else
        info "Loader removed. Other customizations preserved."
    fi
else
    info "No orca-customizations.py found."
fi

# --- Remove GSettings schemas ---

SCHEMA_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/glib-2.0/schemas"

for SCHEMA_FILE in "org.gnome.Orca.Polyglot.gschema.xml" "org.gnome.Orca.AutoSwitch.gschema.xml"; do
    if [ -f "$SCHEMA_DIR/$SCHEMA_FILE" ]; then
        info "Removing GSettings schema $SCHEMA_FILE..."
        rm -f "$SCHEMA_DIR/$SCHEMA_FILE"
    fi
done

if command -v glib-compile-schemas >/dev/null 2>&1; then
    glib-compile-schemas "$SCHEMA_DIR" 2>/dev/null || true
fi

# Clear dconf settings (both old and new paths)
if command -v dconf >/dev/null 2>&1; then
    dconf reset -f /org/gnome/orca/polyglot/ 2>/dev/null || true
    dconf reset -f /org/gnome/orca/autoswitch/ 2>/dev/null || true
    info "GSettings data cleared."
fi

# --- Remove the add-on directories ---

for DIR in "$ADDON_DIR" "$OLD_ADDON_DIR"; do
    if [ -d "$DIR" ]; then
        info "Removing: $DIR"
        rm -rf "$DIR"
    fi
done
info "Add-on files removed."

# --- Done ---

echo ""
echo "=== Uninstall complete! ==="
echo ""
echo "  Restart Orca for changes to take effect."
echo "  Orca will return to its normal behaviour."
echo ""
