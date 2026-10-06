"""Accessible GTK settings window for Polyglot for Orca.

Follows Orca v50+ preferences style: sidebar navigation, Gtk.Stack panels,
Gtk.Switch for booleans, FocusManagedListBox for keyboard navigation,
and AT-SPI event suspension during UI build/teardown.
"""

import logging
import os

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Atk", "1.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gtk, Atk, Gdk, GLib

log = logging.getLogger("polyglot")

# Language names in their own language for display
_LANG_DISPLAY_NAMES = {
    "af": "Afrikaans",
    "ar": "\u0627\u0644\u0639\u0631\u0628\u064a\u0629",
    "bg": "\u0411\u044a\u043b\u0433\u0430\u0440\u0441\u043a\u0438",
    "bn": "\u09ac\u09be\u0982\u09b2\u09be",
    "ca": "Catal\u00e0",
    "cs": "\u010ce\u0161tina",
    "cy": "Cymraeg",
    "da": "Dansk",
    "de": "Deutsch",
    "el": "\u0395\u03bb\u03bb\u03b7\u03bd\u03b9\u03ba\u03ac",
    "en": "English",
    "es": "Espa\u00f1ol",
    "et": "Eesti",
    "eu": "Euskara",
    "fa": "\u0641\u0627\u0631\u0633\u06cc",
    "fi": "Suomi",
    "fr": "Fran\u00e7ais",
    "ga": "Gaeilge",
    "gl": "Galego",
    "he": "\u05e2\u05d1\u05e8\u05d9\u05ea",
    "hi": "\u0939\u093f\u0928\u094d\u0926\u0940",
    "hr": "Hrvatski",
    "hu": "Magyar",
    "hy": "\u0540\u0561\u0575\u0565\u0580\u0565\u0576",
    "id": "Indonesia",
    "is": "\u00cdslenska",
    "it": "Italiano",
    "ja": "\u65e5\u672c\u8a9e",
    "ka": "\u10e5\u10d0\u10e0\u10d7\u10e3\u10da\u10d8",
    "ko": "\ud55c\uad6d\uc5b4",
    "lt": "Lietuvi\u0173",
    "lv": "Latvie\u0161u",
    "ms": "Melayu",
    "nb": "Norsk bokm\u00e5l",
    "nl": "Nederlands",
    "pl": "Polski",
    "pt": "Portugu\u00eas",
    "ro": "Rom\u00e2n\u0103",
    "ru": "\u0420\u0443\u0441\u0441\u043a\u0438\u0439",
    "sk": "Sloven\u010dina",
    "sl": "Sloven\u0161\u010dina",
    "sq": "Shqip",
    "sr": "\u0421\u0440\u043f\u0441\u043a\u0438",
    "sv": "Svenska",
    "sw": "Kiswahili",
    "ta": "\u0ba4\u0bae\u0bbf\u0bb4\u0bcd",
    "th": "\u0e44\u0e17\u0e22",
    "tr": "T\u00fcrk\u00e7e",
    "uk": "\u0423\u043a\u0440\u0430\u0457\u043d\u0441\u044c\u043a\u0430",
    "vi": "Ti\u1ebfng Vi\u1ec7t",
    "zh": "\u4e2d\u6587",
}

_SCRIPT_DISPLAY_NAMES = {
    "CYRILLIC": "Cyrillic",
    "ARABIC": "Arabic",
    "HEBREW": "Hebrew",
    "GREEK": "Greek",
    "DEVANAGARI": "Devanagari",
    "BENGALI": "Bengali",
    "THAI": "Thai",
    "GEORGIAN": "Georgian",
    "ARMENIAN": "Armenian",
    "HANGUL": "Hangul (Korean)",
    "CJK": "CJK (Chinese/Japanese/Korean)",
    "IPA": "IPA (International Phonetic Alphabet)",
    "BRAILLE": "Unicode Braille (dot patterns)",
}

# AT-SPI events to suppress during UI build/teardown
_EVENTS_TO_SUSPEND = (
    "object:state-changed:showing",
    "object:state-changed:visible",
    "object:children-changed:add",
    "object:children-changed:remove",
    "object:property-change:accessible-name",
    "object:property-change:accessible-description",
)

# Cache
_contraction_tables_cache = None


def _get_speech_dispatcher_languages():
    """The languages Speech Dispatcher has a voice for.

    Which voice is used for each is Orca's business now -- see the Voice
    Sets page in Orca's own preferences. All this page needs to know is
    which languages are worth offering to detect.
    """
    from .available_voices import languages
    return languages()


def _get_contraction_tables():
    """Get available liblouis contraction tables, cached."""
    global _contraction_tables_cache
    if _contraction_tables_cache is not None:
        return _contraction_tables_cache
    tables = {}
    try:
        louis_dir = "/usr/share/liblouis/tables"
        if os.path.isdir(louis_dir):
            for fname in sorted(os.listdir(louis_dir)):
                if fname.endswith((".ctb", ".utb")):
                    tables[fname[:-4]] = os.path.join(louis_dir, fname)
    except Exception:
        pass
    _contraction_tables_cache = tables
    return tables


# Offered orders for the detection tiers. Not every permutation: these are
# the ones with a reason to exist. The stored value is the comma-joined tier
# list, which is what config.detection_order holds.
_DETECTION_ORDER_CHOICES = (
    (("script", "dictionary", "lingua"), "Script, then word lists, then Lingua"),
    (("dictionary", "script", "lingua"), "Word lists, then script, then Lingua"),
    (("script", "lingua", "dictionary"), "Script, then Lingua, then word lists"),
    (("dictionary", "lingua", "script"), "Word lists, then Lingua, then script"),
)


def _suspend_events():
    """Deregister AT-SPI events that flood Orca during UI creation."""
    try:
        from orca import event_manager
        manager = event_manager.get_manager()
        for event in _EVENTS_TO_SUSPEND:
            manager.deregister_listener(event)
    except Exception:
        pass


def _resume_events():
    """Re-register AT-SPI events after UI creation/teardown."""
    try:
        from orca import event_manager
        manager = event_manager.get_manager()
        for event in _EVENTS_TO_SUSPEND:
            manager.register_listener(event)
    except Exception:
        pass
    return False


# ---------------------------------------------------------------------------
# FocusManagedListBox — keyboard-navigable list of settings rows
# ---------------------------------------------------------------------------

class FocusManagedListBox(Gtk.ListBox):
    """A ListBox that manages Tab/Shift+Tab focus between interactive widgets.

    Matches the pattern from Orca v50's preferences_grid_base.py.
    """

    def __init__(self, focus_sidebar_func=None):
        super().__init__()
        self.set_selection_mode(Gtk.SelectionMode.NONE)
        self.get_style_context().add_class("frame")
        self.set_can_focus(False)
        self.set_header_func(self._separator_header_func, None)
        self._widgets = []
        self._rows = []
        self._exiting_backward = [False]
        self._focus_sidebar_func = focus_sidebar_func

    @staticmethod
    def _separator_header_func(row, before, _user_data):
        if before is not None:
            row.set_header(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))

    def add_row_with_widget(self, row, widget):
        widget.connect("key-press-event", self._on_widget_key_press)
        row.connect("focus-in-event", self._on_row_focus_in, widget)
        self.add(row)
        self._rows.append(row)
        self._widgets.append(widget)

    def _focus_next_sensitive_widget(self, widget):
        try:
            idx = self._widgets.index(widget)
            for i in range(idx + 1, len(self._widgets)):
                if self._widgets[i].get_sensitive():
                    self._widgets[i].grab_focus()
                    return True
        except ValueError:
            pass
        return False

    def _focus_prev_sensitive_widget(self, widget):
        try:
            idx = self._widgets.index(widget)
            for i in range(idx - 1, -1, -1):
                if self._widgets[i].get_sensitive():
                    self._widgets[i].grab_focus()
                    return True
            if self._rows:
                self._exiting_backward[0] = True
                self._rows[0].grab_focus()
        except ValueError:
            pass
        return False

    def _navigate_left_from_widget(self, widget):
        if isinstance(widget, (Gtk.Scale, Gtk.SpinButton)):
            return False
        if self._focus_sidebar_func:
            self._focus_sidebar_func()
            return True
        return False

    def _on_widget_key_press(self, widget, event):
        if event.keyval == Gdk.KEY_Tab:
            return self._focus_next_sensitive_widget(widget)
        if event.keyval == Gdk.KEY_ISO_Left_Tab:
            return self._focus_prev_sensitive_widget(widget)
        if event.keyval == Gdk.KEY_Left:
            return self._navigate_left_from_widget(widget)
        return False

    def _on_row_focus_in(self, _row, _event, widget):
        if self._exiting_backward[0]:
            self._exiting_backward[0] = False
            return False
        widget.grab_focus()
        if isinstance(widget, Gtk.Entry):
            widget.set_position(-1)
        return False


# ---------------------------------------------------------------------------
# Row creation helpers
# ---------------------------------------------------------------------------

def _create_switch_row(label_text, state, atk_name=None, atk_desc=None):
    """Create a ListBoxRow with Label (left) + Switch (right)."""
    row = Gtk.ListBoxRow()
    row.set_activatable(False)
    hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
    hbox.set_margin_start(12)
    hbox.set_margin_end(12)
    hbox.set_margin_top(12)
    hbox.set_margin_bottom(12)
    label = Gtk.Label(label=label_text)
    label.set_use_underline(True)
    label.set_xalign(0)
    label.set_hexpand(True)
    switch = Gtk.Switch()
    switch.set_valign(Gtk.Align.CENTER)
    switch.set_active(state)
    label.set_mnemonic_widget(switch)
    atk_obj = switch.get_accessible()
    if atk_obj:
        atk_obj.set_role(Atk.Role.SWITCH)
        if atk_name:
            atk_obj.set_name(atk_name)
        if atk_desc:
            atk_obj.set_description(atk_desc)
    hbox.pack_start(label, True, True, 0)
    hbox.pack_end(switch, False, False, 0)
    row.add(hbox)
    return row, switch, label


def _create_combo_row(label_text, atk_name=None, atk_desc=None):
    """Create a ListBoxRow with Label (left) + ComboBoxText (right)."""
    row = Gtk.ListBoxRow()
    row.set_activatable(False)
    hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
    hbox.set_margin_start(12)
    hbox.set_margin_end(12)
    hbox.set_margin_top(12)
    hbox.set_margin_bottom(12)
    label = Gtk.Label(label=label_text)
    label.set_use_underline(True)
    label.set_xalign(0)
    label.set_hexpand(True)
    combo = Gtk.ComboBoxText()
    label.set_mnemonic_widget(combo)
    atk_obj = combo.get_accessible()
    if atk_obj:
        if atk_name:
            atk_obj.set_name(atk_name)
        if atk_desc:
            atk_obj.set_description(atk_desc)
    hbox.pack_start(label, True, True, 0)
    hbox.pack_end(combo, False, False, 0)
    row.add(hbox)
    return row, combo, label


def _create_spin_row(label_text, lower, upper, step, digits=0,
                     value=0, atk_name=None, atk_desc=None):
    """Create a ListBoxRow with Label (left) + SpinButton (right)."""
    row = Gtk.ListBoxRow()
    row.set_activatable(False)
    hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
    hbox.set_margin_start(12)
    hbox.set_margin_end(12)
    hbox.set_margin_top(12)
    hbox.set_margin_bottom(12)
    label = Gtk.Label(label=label_text)
    label.set_use_underline(True)
    label.set_xalign(0)
    label.set_hexpand(True)
    spin = Gtk.SpinButton.new_with_range(lower, upper, step)
    spin.set_digits(digits)
    spin.set_value(value)
    label.set_mnemonic_widget(spin)
    atk_obj = spin.get_accessible()
    if atk_obj:
        if atk_name:
            atk_obj.set_name(atk_name)
        if atk_desc:
            atk_obj.set_description(atk_desc)
    hbox.pack_start(label, True, True, 0)
    hbox.pack_end(spin, False, False, 0)
    row.add(hbox)
    return row, spin, label


def _create_text_row(label_text, value="", atk_name=None, atk_desc=None):
    """Create a ListBoxRow with Label (left) + Entry (right)."""
    row = Gtk.ListBoxRow()
    row.set_activatable(False)
    hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
    hbox.set_margin_start(12)
    hbox.set_margin_end(12)
    hbox.set_margin_top(12)
    hbox.set_margin_bottom(12)
    label = Gtk.Label(label=label_text)
    label.set_use_underline(True)
    label.set_xalign(0)
    entry = Gtk.Entry()
    entry.set_text(value or "")
    entry.set_hexpand(True)
    label.set_mnemonic_widget(entry)
    atk_obj = entry.get_accessible()
    if atk_obj:
        if atk_name:
            atk_obj.set_name(atk_name)
        if atk_desc:
            atk_obj.set_description(atk_desc)
    hbox.pack_start(label, False, False, 0)
    hbox.pack_start(entry, True, True, 0)
    row.add(hbox)
    return row, entry, label


def _create_section_heading(text):
    """Create a section heading label."""
    label = Gtk.Label(label=text)
    label.set_xalign(0)
    label.get_style_context().add_class("heading")
    label.set_margin_top(12)
    label.set_margin_bottom(6)
    return label


# ---------------------------------------------------------------------------
# Speech dictionary editor
# ---------------------------------------------------------------------------

_RULE_TYPE_LABELS = (
    ("text", "Text replacement"),
    ("regex", "Regular expression"),
)


class SpeechRuleDialog(Gtk.Dialog):
    """Add or edit one speech dictionary rule.

    The Test field is the point of this dialog rather than an extra: a
    regular expression that does not work gives no clue as to why, and
    nothing here is visible on a braille display or in speech unless it is
    spelled out. Typing a sample shows what the rule does to it, as it is
    typed.
    """

    def __init__(self, parent, entry=None, languages=(), sample=""):
        editing = entry is not None
        super().__init__(
            title="Edit Pronunciation" if editing else "Add Pronunciation",
            transient_for=parent,
            flags=Gtk.DialogFlags.MODAL | Gtk.DialogFlags.DESTROY_WITH_PARENT,
        )
        self._result = None
        # Set while a deep validation is pending; see _refresh.
        self._deep_timer = None
        self._deep_checked = None
        self._languages = list(languages)
        self.set_default_size(560, 460)
        self.set_border_width(12)

        entry = dict(entry) if entry else {
            "type": "text", "pattern": "", "replacement": "", "language": "",
            "case_sensitive": False, "whole_word": True, "enabled": True,
            "comment": "",
        }

        atk_obj = self.get_accessible()
        if atk_obj:
            atk_obj.set_name("Edit pronunciation" if editing else "Add pronunciation")

        content = self.get_content_area()
        listbox = FocusManagedListBox()

        row, self._type_combo, _ = _create_combo_row(
            "_Kind of rule:",
            atk_name="Kind of rule",
            atk_desc="Text replacement swaps one piece of text for another. "
                     "Regular expression matches a pattern and can reuse parts "
                     "of what it matched.")
        for value, label in _RULE_TYPE_LABELS:
            self._type_combo.append(value, label)
        self._type_combo.set_active_id(entry["type"])
        if self._type_combo.get_active_id() is None:
            self._type_combo.set_active_id("text")
        listbox.add_row_with_widget(row, self._type_combo)

        row, self._pattern_entry, _ = _create_text_row(
            "_Replace:", entry["pattern"],
            atk_name="Text or pattern to replace",
            atk_desc="The text to look for, or the pattern when the rule is a "
                     "regular expression")
        listbox.add_row_with_widget(row, self._pattern_entry)

        row, self._replacement_entry, _ = _create_text_row(
            "_With:", entry["replacement"],
            atk_name="Replacement",
            atk_desc="What to say instead. In a regular expression, backslash 1 "
                     "stands for the first bracketed part of the pattern, "
                     "backslash 2 for the second, and so on")
        listbox.add_row_with_widget(row, self._replacement_entry)

        row, self._language_combo, _ = _create_combo_row(
            "_Language:",
            atk_name="Language this rule applies to",
            atk_desc="Restrict the rule to one language, or apply it to all of them")
        self._language_combo.append("", "All languages")
        for code in self._languages:
            self._language_combo.append(
                code, f"{_LANG_DISPLAY_NAMES.get(code, code)} ({code})")
        self._language_combo.set_active_id(entry["language"])
        if self._language_combo.get_active_id() is None:
            self._language_combo.set_active_id("")
        listbox.add_row_with_widget(row, self._language_combo)

        row, self._case_switch, _ = _create_switch_row(
            "Match _capitals exactly", entry["case_sensitive"],
            atk_name="Match capitals exactly",
            atk_desc="When off, US and us are treated as the same text")
        listbox.add_row_with_widget(row, self._case_switch)

        row, self._whole_switch, self._whole_label = _create_switch_row(
            "Whole _words only", entry["whole_word"],
            atk_name="Whole words only",
            atk_desc="When on, cat does not match inside concatenate. Applies "
                     "to text replacement only")
        listbox.add_row_with_widget(row, self._whole_switch)

        row, self._test_entry, _ = _create_text_row(
            "_Test with:", sample,
            atk_name="Test text",
            atk_desc="Type a sample here to see what this rule does to it")
        listbox.add_row_with_widget(row, self._test_entry)

        content.pack_start(listbox, False, False, 0)

        self._result_label = Gtk.Label()
        self._result_label.set_xalign(0)
        self._result_label.set_line_wrap(True)
        self._result_label.set_selectable(True)
        self._result_label.set_margin_top(8)
        result_atk = self._result_label.get_accessible()
        if result_atk:
            result_atk.set_name("Test result")
        content.pack_start(self._result_label, False, False, 0)

        self._note_label = Gtk.Label()
        self._note_label.set_xalign(0)
        self._note_label.set_line_wrap(True)
        self._note_label.set_selectable(True)
        self._note_label.set_margin_top(8)
        note_atk = self._note_label.get_accessible()
        if note_atk:
            note_atk.set_name("Rule notes")
        content.pack_start(self._note_label, False, False, 0)

        for widget in (self._pattern_entry, self._replacement_entry, self._test_entry):
            widget.connect("changed", self._refresh)
        self._type_combo.connect("changed", self._refresh)
        self._language_combo.connect("changed", self._refresh)
        for widget in (self._case_switch, self._whole_switch):
            widget.connect("notify::active", self._refresh)

        self.add_button("Cancel", Gtk.ResponseType.CANCEL)
        self._ok_button = self.add_button("OK", Gtk.ResponseType.OK)
        self.set_default_response(Gtk.ResponseType.OK)
        self.connect("response", self._on_response)
        self._refresh()

    def _current_entry(self):
        return {
            "type": self._type_combo.get_active_id() or "text",
            "pattern": self._pattern_entry.get_text(),
            "replacement": self._replacement_entry.get_text(),
            "language": self._language_combo.get_active_id() or "",
            "case_sensitive": self._case_switch.get_active(),
            "whole_word": self._whole_switch.get_active(),
            "enabled": True,
            "comment": "",
        }

    def _refresh(self, *_args):
        """Validate and show what the rule does, on every keystroke.

        Only the cheap checks run here. The last of the three -- running the
        pattern against inputs built to provoke runaway backtracking -- costs
        a subprocess launch, so doing it per keystroke would stall the
        dialog on every letter typed. It is scheduled instead, once typing
        has stopped.
        """
        from . import speech_dictionary as sd
        entry = self._current_entry()
        is_text = entry["type"] == "text"
        self._whole_switch.set_sensitive(is_text)
        self._whole_label.set_sensitive(is_text)

        ok, message = sd.validate(entry, deep=False)
        self._ok_button.set_sensitive(ok)
        self._schedule_deep_check(entry if ok else None)

        notes = []
        if not ok:
            notes.append(message)
        elif entry["type"] == "regex":
            notes.append("Backslash 1 in the replacement stands for the first "
                         "bracketed part of the pattern.")
        self._note_label.set_text("  ".join(notes))

        sample = self._test_entry.get_text()
        if not sample:
            self._result_label.set_text("Type something in Test with to see the result.")
            return
        if not ok:
            self._result_label.set_text("The rule is not valid yet, so there is "
                                        "nothing to test.")
            return
        result, _trace = sd.preview(sample, [entry], entry["language"] or None)
        if result == sample:
            self._result_label.set_text(f"No change: {result}")
        else:
            self._result_label.set_text(f"Result: {result}")

    def _schedule_deep_check(self, entry):
        """Run the slow safety check a moment after typing stops."""
        if self._deep_timer is not None:
            GLib.source_remove(self._deep_timer)
            self._deep_timer = None
        if entry is None or entry["type"] != "regex":
            return
        key = (entry["pattern"], entry["replacement"])
        if key == self._deep_checked:
            return
        self._deep_timer = GLib.timeout_add(500, self._run_deep_check, key)

    def _run_deep_check(self, key):
        """Refuse a pattern that is unsafe to run, and say why."""
        from . import speech_dictionary as sd
        self._deep_timer = None
        entry = self._current_entry()
        if (entry["pattern"], entry["replacement"]) != key:
            return False
        self._deep_checked = key
        ok, message = sd.validate(entry)
        self._ok_button.set_sensitive(ok)
        if not ok:
            self._note_label.set_text(message)
        return False

    def _on_response(self, _dialog, response_id):
        if self._deep_timer is not None:
            GLib.source_remove(self._deep_timer)
            self._deep_timer = None
        if response_id == Gtk.ResponseType.OK:
            self._result = self._current_entry()
        self.destroy()

    def get_result(self):
        return self._result


class SpeechDictionaryDialog(Gtk.Dialog):
    """The list of pronunciation rules, in the order they are applied."""

    COL_ENABLED = 0
    COL_KIND = 1
    COL_PATTERN = 2
    COL_REPLACEMENT = 3
    COL_LANGUAGE = 4

    def __init__(self, parent, languages=()):
        super().__init__(
            title="Speech Dictionary",
            transient_for=parent,
            flags=Gtk.DialogFlags.MODAL | Gtk.DialogFlags.DESTROY_WITH_PARENT,
        )
        self._languages = list(languages)
        self.set_default_size(720, 480)
        self.set_border_width(12)
        atk_obj = self.get_accessible()
        if atk_obj:
            atk_obj.set_name("Speech dictionary")

        content = self.get_content_area()

        info = Gtk.Label(
            label="Rules are applied in order, from the top. Orca's own "
                  "pronunciation dictionary runs as well, and matches whole "
                  "words only; these rules can match patterns and can be "
                  "limited to one language.")
        info.set_line_wrap(True)
        info.set_xalign(0)
        content.pack_start(info, False, False, 0)

        self._store = Gtk.ListStore(bool, str, str, str, str)
        self._view = Gtk.TreeView(model=self._store)
        self._view.set_headers_visible(True)
        view_atk = self._view.get_accessible()
        if view_atk:
            view_atk.set_name("Pronunciation rules")

        toggle = Gtk.CellRendererToggle()
        toggle.connect("toggled", self._on_enabled_toggled)
        self._view.append_column(Gtk.TreeViewColumn("On", toggle, active=self.COL_ENABLED))
        for title, column in (("Kind", self.COL_KIND), ("Replace", self.COL_PATTERN),
                              ("With", self.COL_REPLACEMENT),
                              ("Language", self.COL_LANGUAGE)):
            renderer = Gtk.CellRendererText()
            col = Gtk.TreeViewColumn(title, renderer, text=column)
            col.set_resizable(True)
            self._view.append_column(col)

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_vexpand(True)
        scrolled.add(self._view)
        content.pack_start(scrolled, True, True, 0)

        buttons = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        buttons.set_margin_top(8)
        for label, handler, name in (
            ("_Add...", self._on_add, "Add a pronunciation rule"),
            ("_Edit...", self._on_edit, "Edit the selected rule"),
            ("_Remove", self._on_remove, "Remove the selected rule"),
            ("Move _Up", self._on_move_up, "Apply the selected rule earlier"),
            ("Move _Down", self._on_move_down, "Apply the selected rule later"),
        ):
            button = Gtk.Button(label=label, use_underline=True)
            button.connect("clicked", handler)
            button_atk = button.get_accessible()
            if button_atk:
                button_atk.set_name(name)
            buttons.pack_start(button, False, False, 0)
        content.pack_start(buttons, False, False, 0)

        self._entries = []
        self._reload()

        self.add_button("Cancel", Gtk.ResponseType.CANCEL)
        self.add_button("Save", Gtk.ResponseType.OK)
        self.set_default_response(Gtk.ResponseType.OK)
        self.connect("response", self._on_response)

    def _reload(self):
        from . import speech_dictionary as sd
        self._entries = sd.get_entries()
        self._refill()

    def _refill(self, select=None):
        self._store.clear()
        kinds = dict(_RULE_TYPE_LABELS)
        for entry in self._entries:
            self._store.append([
                bool(entry.get("enabled", True)),
                kinds.get(entry.get("type"), "Text replacement"),
                entry.get("pattern", ""),
                entry.get("replacement", ""),
                entry.get("language") or "All",
            ])
        if select is not None and 0 <= select < len(self._entries):
            self._view.set_cursor(Gtk.TreePath.new_from_indices([select]))

    def _selected_index(self):
        model, it = self._view.get_selection().get_selected()
        if it is None:
            return None
        return model.get_path(it).get_indices()[0]

    def _on_enabled_toggled(self, _renderer, path):
        index = Gtk.TreePath.new_from_string(path).get_indices()[0]
        self._entries[index]["enabled"] = not self._entries[index].get("enabled", True)
        self._refill(select=index)

    def _on_add(self, _button):
        dialog = SpeechRuleDialog(self, None, self._languages)
        dialog.show_all()
        dialog.run()
        result = dialog.get_result()
        if result:
            self._entries.append(result)
            self._refill(select=len(self._entries) - 1)

    def _on_edit(self, _button):
        index = self._selected_index()
        if index is None:
            return
        dialog = SpeechRuleDialog(self, self._entries[index], self._languages)
        dialog.show_all()
        dialog.run()
        result = dialog.get_result()
        if result:
            result["enabled"] = self._entries[index].get("enabled", True)
            self._entries[index] = result
            self._refill(select=index)

    def _on_remove(self, _button):
        index = self._selected_index()
        if index is None:
            return
        del self._entries[index]
        self._refill(select=min(index, len(self._entries) - 1))

    def _move(self, offset):
        index = self._selected_index()
        if index is None:
            return
        target = index + offset
        if not 0 <= target < len(self._entries):
            return
        self._entries[index], self._entries[target] = (
            self._entries[target], self._entries[index])
        self._refill(select=target)

    def _on_move_up(self, _button):
        self._move(-1)

    def _on_move_down(self, _button):
        self._move(1)

    def _on_response(self, _dialog, response_id):
        if response_id == Gtk.ResponseType.OK:
            from . import speech_dictionary as sd
            sd.save(self._entries)
        self.destroy()

# ---------------------------------------------------------------------------
# Character Names editor dialog
# ---------------------------------------------------------------------------

class CharacterNamesDialog(Gtk.Dialog):
    """Editor for character pronunciation names."""

    COL_CHAR = 0
    COL_UNICODE_NAME = 1
    COL_BRIEF = 2
    COL_VERBOSE = 3
    COL_IS_CUSTOM = 4
    COL_ORIG_BRIEF = 5
    COL_ORIG_VERBOSE = 6

    def __init__(self, parent, builtin_friendly_names):
        super().__init__(
            title="Character Names",
            transient_for=parent,
            modal=True,
            destroy_with_parent=True,
        )
        self.set_default_size(700, 500)
        self.add_buttons("Close", Gtk.ResponseType.CLOSE)
        self._builtin = builtin_friendly_names
        self._changed = False

        # import_module(".x", __package__), not `from . import x`: as an
        # Orca user extension this package is imported as
        # orca_user_extension.<name> with no `orca_user_extension` parent
        # ever created, and `from . import x` insists on importing it.
        from importlib import import_module
        self._custom_names = import_module(".custom_names", __package__)
        self._custom_names.load()

        content = self.get_content_area()
        content.set_spacing(8)
        content.set_border_width(8)

        # Search entry
        search_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        search_label = Gtk.Label(label="Search:")
        self._search_entry = Gtk.SearchEntry()
        self._search_entry.set_placeholder_text("Type to filter characters...")
        search_label.set_mnemonic_widget(self._search_entry)
        atk_search = self._search_entry.get_accessible()
        if atk_search:
            atk_search.set_name("Search characters")
        self._search_entry.connect("search-changed", self._on_search_changed)
        search_box.pack_start(search_label, False, False, 0)
        search_box.pack_start(self._search_entry, True, True, 0)
        content.pack_start(search_box, False, False, 0)

        # TreeView
        self._store = Gtk.ListStore(str, str, str, str, bool, str, str)
        self._filter = self._store.filter_new()
        self._filter.set_visible_func(self._filter_func)
        self._treeview = Gtk.TreeView(model=self._filter)
        self._treeview.set_search_column(self.COL_UNICODE_NAME)
        atk_tv = self._treeview.get_accessible()
        if atk_tv:
            atk_tv.set_name("Character pronunciation table")

        col_sym = Gtk.TreeViewColumn("Symbol", Gtk.CellRendererText(), text=self.COL_CHAR)
        col_sym.set_resizable(True)
        col_sym.set_min_width(60)
        self._treeview.append_column(col_sym)

        col_name = Gtk.TreeViewColumn("Unicode Name", Gtk.CellRendererText(),
                                      text=self.COL_UNICODE_NAME)
        col_name.set_resizable(True)
        col_name.set_expand(True)
        col_name.set_min_width(200)
        self._treeview.append_column(col_name)

        renderer_brief = Gtk.CellRendererText()
        renderer_brief.set_property("editable", True)
        renderer_brief.connect("edited", self._on_brief_edited)
        col_brief = Gtk.TreeViewColumn("Brief", renderer_brief, text=self.COL_BRIEF)
        col_brief.set_resizable(True)
        col_brief.set_min_width(150)
        self._treeview.append_column(col_brief)

        renderer_verbose = Gtk.CellRendererText()
        renderer_verbose.set_property("editable", True)
        renderer_verbose.connect("edited", self._on_verbose_edited)
        col_verbose = Gtk.TreeViewColumn("Verbose", renderer_verbose, text=self.COL_VERBOSE)
        col_verbose.set_resizable(True)
        col_verbose.set_min_width(150)
        self._treeview.append_column(col_verbose)

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_vexpand(True)
        scrolled.add(self._treeview)
        content.pack_start(scrolled, True, True, 0)

        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        add_btn = Gtk.Button(label="Add Character...")
        add_btn.connect("clicked", self._on_add_character)
        btn_box.pack_start(add_btn, False, False, 0)
        reset_btn = Gtk.Button(label="Reset Selected to Default")
        reset_btn.connect("clicked", self._on_reset_selected)
        btn_box.pack_start(reset_btn, False, False, 0)
        content.pack_start(btn_box, False, False, 0)

        self._populate()
        self.connect("response", self._on_response)

    def _populate(self):
        self._store.clear()
        for char, uname, brief, verbose, is_custom in \
                self._custom_names.get_all_with_builtins(self._builtin):
            self._store.append([char, uname, brief, verbose, is_custom, brief, verbose])

    def _filter_func(self, model, iter_, data=None):
        text = self._search_entry.get_text().strip().lower()
        if not text:
            return True
        for col in (self.COL_CHAR, self.COL_UNICODE_NAME, self.COL_BRIEF, self.COL_VERBOSE):
            val = model[iter_][col] or ""
            if text in val.lower():
                return True
        return False

    def _on_search_changed(self, entry):
        self._filter.refilter()

    def _get_store_iter(self, filter_path_str):
        filter_path = Gtk.TreePath.new_from_string(filter_path_str)
        child_path = self._filter.convert_path_to_child_path(filter_path)
        return self._store.get_iter(child_path) if child_path else None

    def _on_brief_edited(self, renderer, path, new_text):
        it = self._get_store_iter(path)
        if it:
            self._store[it][self.COL_BRIEF] = new_text
            self._mark_changed(it)

    def _on_verbose_edited(self, renderer, path, new_text):
        it = self._get_store_iter(path)
        if it:
            self._store[it][self.COL_VERBOSE] = new_text
            self._mark_changed(it)

    def _mark_changed(self, it):
        char = self._store[it][self.COL_CHAR]
        self._custom_names.set_name(
            char, brief=self._store[it][self.COL_BRIEF],
            verbose=self._store[it][self.COL_VERBOSE])
        self._store[it][self.COL_IS_CUSTOM] = True
        self._changed = True

    def _on_add_character(self, button):
        dialog = Gtk.Dialog(
            title="Add Character", transient_for=self,
            modal=True, destroy_with_parent=True)
        dialog.add_buttons("Cancel", Gtk.ResponseType.CANCEL, "Add", Gtk.ResponseType.OK)
        dialog.set_default_size(400, -1)
        content = dialog.get_content_area()
        content.set_spacing(8)
        content.set_border_width(12)

        grid = Gtk.Grid()
        grid.set_column_spacing(8)
        grid.set_row_spacing(6)
        for i, (lbl, maxlen) in enumerate([("Character:", 2), ("Brief name:", 0), ("Verbose name:", 0)]):
            l = Gtk.Label(label=lbl)
            l.set_halign(Gtk.Align.END)
            e = Gtk.Entry()
            if maxlen:
                e.set_max_length(maxlen)
            l.set_mnemonic_widget(e)
            grid.attach(l, 0, i, 1, 1)
            grid.attach(e, 1, i, 1, 1)
        content.pack_start(grid, False, False, 0)
        dialog.show_all()

        entries = [grid.get_child_at(1, i) for i in range(3)]
        if dialog.run() == Gtk.ResponseType.OK:
            char = entries[0].get_text().strip()
            brief = entries[1].get_text().strip()
            verbose = entries[2].get_text().strip()
            if char and (brief or verbose):
                import unicodedata
                ch = char[0]
                uname = unicodedata.name(ch, f"U+{ord(ch):04X}")
                self._custom_names.set_name(ch, brief=brief, verbose=verbose)
                found = False
                it = self._store.get_iter_first()
                while it:
                    if self._store[it][self.COL_CHAR] == ch:
                        self._store[it][self.COL_BRIEF] = brief
                        self._store[it][self.COL_VERBOSE] = verbose
                        self._store[it][self.COL_IS_CUSTOM] = True
                        found = True
                        break
                    it = self._store.iter_next(it)
                if not found:
                    self._store.append([ch, uname, brief, verbose, True, "", ""])
                self._changed = True
        dialog.destroy()

    def _on_reset_selected(self, button):
        model, tree_iter = self._treeview.get_selection().get_selected()
        if tree_iter is None:
            return
        child_iter = self._filter.convert_iter_to_child_iter(tree_iter)
        char = self._store[child_iter][self.COL_CHAR]
        self._custom_names.remove_name(char)
        self._store[child_iter][self.COL_BRIEF] = self._store[child_iter][self.COL_ORIG_BRIEF]
        self._store[child_iter][self.COL_VERBOSE] = self._store[child_iter][self.COL_ORIG_VERBOSE]
        self._store[child_iter][self.COL_IS_CUSTOM] = False
        self._changed = True

    def _on_response(self, dialog, response_id):
        if self._changed:
            self._custom_names.save()
        self.destroy()


# ---------------------------------------------------------------------------
# Main settings window (Orca v50 style: sidebar + stack)
# ---------------------------------------------------------------------------

class PolyglotSettingsWindow(Gtk.Window):
    """Accessible settings window for Polyglot.

    Uses sidebar navigation + Gtk.Stack to match Orca v50 preferences style.
    """

    def __init__(self, config, on_save=None):
        super().__init__(title="Polyglot Settings")
        self._config = config
        self._on_save = on_save
        self._lang_checks = {}
        self._lang_table_combos = {}
        self._script_combos = {}
        self._app_checks = {}

        self.set_default_size(700, 600)

        atk_obj = self.get_accessible()
        if atk_obj:
            atk_obj.set_name("Polyglot Settings")

        _suspend_events()
        self._build_ui()
        self.connect("delete-event", self._on_delete)
        self.connect("key-press-event", self._on_key_press)

    def focus_sidebar(self):
        self._sidebar.grab_focus()
        GLib.timeout_add(500, _resume_events)

    def _build_ui(self):
        # Header bar
        headerbar = Gtk.HeaderBar()
        headerbar.set_show_close_button(True)
        headerbar.set_title("Polyglot")
        self.set_titlebar(headerbar)

        save_btn = Gtk.Button(label="Save")
        save_btn.get_style_context().add_class("suggested-action")
        save_btn.connect("clicked", self._on_save_clicked)
        atk_save = save_btn.get_accessible()
        if atk_save:
            atk_save.set_name("Save settings")
        headerbar.pack_end(save_btn)

        # Main layout: sidebar | separator | content
        main_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        self.add(main_box)

        # Sidebar
        sidebar_scroll = Gtk.ScrolledWindow()
        sidebar_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        sidebar_scroll.set_size_request(180, -1)

        self._sidebar = Gtk.ListBox()
        self._sidebar.set_selection_mode(Gtk.SelectionMode.BROWSE)
        self._sidebar.get_style_context().add_class("navigation-sidebar")
        atk_sidebar = self._sidebar.get_accessible()
        if atk_sidebar:
            atk_sidebar.set_name("Settings categories")

        sidebar_scroll.add(self._sidebar)
        main_box.pack_start(sidebar_scroll, False, False, 0)

        sep = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL)
        main_box.pack_start(sep, False, False, 0)

        # Content stack
        content_scroll = Gtk.ScrolledWindow()
        content_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self._stack = Gtk.Stack()
        self._stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self._stack.set_transition_duration(150)
        content_scroll.add(self._stack)
        main_box.pack_start(content_scroll, True, True, 0)

        # Pages
        pages = [
            ("general", "General"),
            ("speech", "Speech"),
            ("detection", "Detection"),
            ("languages", "Languages"),
            ("scripts", "Script Detection"),
            ("exceptions", "Exceptions"),
        ]

        for page_id, page_label in pages:
            row = Gtk.ListBoxRow()
            label = Gtk.Label(label=page_label)
            label.set_xalign(0)
            label.set_margin_start(12)
            label.set_margin_end(12)
            label.set_margin_top(8)
            label.set_margin_bottom(8)
            row.add(label)
            row._page_id = page_id
            self._sidebar.add(row)

        self._sidebar.connect("row-selected", self._on_sidebar_selected)

        self._stack.add_named(self._build_general_page(), "general")
        self._stack.add_named(self._build_speech_page(), "speech")
        self._stack.add_named(self._build_detection_page(), "detection")
        self._stack.add_named(self._build_languages_page(), "languages")
        self._stack.add_named(self._build_scripts_page(), "scripts")
        self._stack.add_named(self._build_exceptions_page(), "exceptions")

        self._update_default_combo()

        first_row = self._sidebar.get_row_at_index(0)
        if first_row:
            self._sidebar.select_row(first_row)

    def _on_sidebar_selected(self, listbox, row):
        if row and hasattr(row, '_page_id'):
            self._stack.set_visible_child_name(row._page_id)

    # --- Page builders ---

    def _build_general_page(self):
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        page.set_border_width(24)
        page.set_margin_start(40)
        page.set_margin_end(40)

        listbox = FocusManagedListBox(self.focus_sidebar)

        row, self._detection_mode_combo, _ = _create_combo_row(
            "_Language detection:",
            atk_name="Language detection mode",
            atk_desc=("Off: never switch language. Markup only: trust language "
                      "tags from documents and Orca, plus deterministic "
                      "Unicode-script detection -- word lists and statistical "
                      "detection are both left out, so text in a language that "
                      "shares the Latin alphabet is read in the default "
                      "language unless it is tagged. Markup + text: also read "
                      "the text itself, using word lists and then statistical "
                      "detection. Always: ignore markup hints and read the "
                      "text."))
        self._detection_mode_combo.append("off", "Off")
        self._detection_mode_combo.append("markup_only", "Markup only")
        self._detection_mode_combo.append("markup_text", "Markup + text")
        self._detection_mode_combo.append("always", "Always (ignore markup)")
        if not self._config.enabled:
            self._detection_mode_combo.set_active_id("off")
        else:
            self._detection_mode_combo.set_active_id(self._config.detection_mode)
        listbox.add_row_with_widget(row, self._detection_mode_combo)

        row, self._threshold_spin, _ = _create_spin_row(
            "_Words before switching:", 1, 10, 1,
            value=self._config.word_threshold,
            atk_name="Words before switching")
        listbox.add_row_with_widget(row, self._threshold_spin)

        # Default language combo
        row, self._default_combo, _ = _create_combo_row(
            "_Default language:",
            atk_name="Default language",
            atk_desc="The primary language — used when no language is detected")
        listbox.add_row_with_widget(row, self._default_combo)

        page.pack_start(listbox, False, False, 0)
        return page

    def _build_speech_page(self):
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        page.set_border_width(24)
        page.set_margin_start(40)
        page.set_margin_end(40)

        listbox = FocusManagedListBox(self.focus_sidebar)

        row, self._emoji_switch, _ = _create_switch_row(
            "Speak _emojis by name",
            self._config.speak_emojis,
            atk_name="Speak emojis by name")
        listbox.add_row_with_widget(row, self._emoji_switch)

        row, self._unicode_combo, _ = _create_combo_row(
            "_Unicode character names:",
            atk_name="Unicode character names",
            atk_desc="Off: skip. Brief: short names, hide invisible chars. Verbose: full names.")
        self._unicode_combo.append("off", "Off")
        self._unicode_combo.append("brief", "Brief")
        self._unicode_combo.append("verbose", "Verbose")
        self._unicode_combo.set_active_id(self._config.unicode_verbosity)
        listbox.add_row_with_widget(row, self._unicode_combo)

        row, self._emoticon_switch, _ = _create_switch_row(
            "Speak text _emoticons",
            self._config.speak_emoticons,
            atk_name="Speak text emoticons",
            atk_desc="Text emoticons like :) and :( are spoken as descriptions")
        listbox.add_row_with_widget(row, self._emoticon_switch)

        page.pack_start(listbox, False, False, 0)

        # Character names editor button
        char_btn = Gtk.Button(label="Edit Character Names...")
        char_btn.set_halign(Gtk.Align.START)
        char_btn.set_margin_top(12)
        char_btn.connect("clicked", self._on_edit_char_names)
        atk_btn = char_btn.get_accessible()
        if atk_btn:
            atk_btn.set_name("Edit character names")
            atk_btn.set_description(
                "Open an editor to customise how symbols and special "
                "characters are pronounced in brief and verbose modes")
        page.pack_start(char_btn, False, False, 0)

        dict_btn = Gtk.Button(label="Edit Speech Dictionary...")
        dict_btn.set_halign(Gtk.Align.START)
        dict_btn.set_margin_top(6)
        dict_btn.connect("clicked", self._on_edit_speech_dictionary)
        atk_dict = dict_btn.get_accessible()
        if atk_dict:
            atk_dict.set_name("Edit speech dictionary")
            atk_dict.set_description(
                "Open an editor for how words and patterns are pronounced, "
                "including regular expressions and rules for a single language")
        page.pack_start(dict_btn, False, False, 0)

        return page

    def _build_detection_page(self):
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        page.set_border_width(24)
        page.set_margin_start(40)
        page.set_margin_end(40)

        # Confidence threshold
        page.pack_start(_create_section_heading("Thresholds"), False, False, 0)

        thresh_listbox = FocusManagedListBox(self.focus_sidebar)

        row, self._confidence_spin, _ = _create_spin_row(
            "_Confidence threshold:", 0.50, 1.00, 0.01, digits=2,
            value=self._config.switch_confidence,
            atk_name="Detection confidence threshold",
            atk_desc="Minimum confidence to switch away from default language (0.50 to 1.00)")
        thresh_listbox.add_row_with_widget(row, self._confidence_spin)

        page.pack_start(thresh_listbox, False, False, 0)

        # Mixed language
        page.pack_start(_create_section_heading("Mixed Language"), False, False, 0)

        mixed_listbox = FocusManagedListBox(self.focus_sidebar)

        row, self._mixed_lang_switch, _ = _create_switch_row(
            "_Split mixed-language text into segments",
            self._config.enable_mixed_language,
            atk_name="Enable mixed-language splitting",
            atk_desc="Text with multiple languages is split and each segment spoken with the correct voice")
        mixed_listbox.add_row_with_widget(row, self._mixed_lang_switch)

        row, self._mixed_max_words_spin, _ = _create_spin_row(
            "_Max words for mixed-language detection:", 50, 5000, 50,
            value=self._config.mixed_max_words,
            atk_name="Mixed-language word cap",
            atk_desc="Above this many words, mixed-language detection is "
                     "skipped so speech can start immediately. Default 600.")
        mixed_listbox.add_row_with_widget(row, self._mixed_max_words_spin)

        page.pack_start(mixed_listbox, False, False, 0)

        # Word lists. Appended rather than placed at the top so that the
        # headings already on this page stay where they have always been.
        page.pack_start(_create_section_heading("Word Lists"), False, False, 0)

        dict_listbox = FocusManagedListBox(self.focus_sidebar)

        row, self._dict_enabled_switch, _ = _create_switch_row(
            "Use word _lists to detect language",
            self._config.dictionary_enabled,
            atk_name="Use word lists to detect language",
            atk_desc="Decide the language by counting how many words belong to "
                     "each language's word list. Needs lists for at least two "
                     "languages; run fetch-dictionaries.sh to install them.")
        dict_listbox.add_row_with_widget(row, self._dict_enabled_switch)

        row, self._detection_order_combo, _ = _create_combo_row(
            "Detection _order:",
            atk_name="Detection order",
            atk_desc=("Which kind of detection gets the first say. Script "
                      "detection is deterministic and best when each script "
                      "belongs to one language. Word lists come first when two "
                      "languages share a script, such as Russian and Ukrainian. "
                      "Whichever is first, a method that cannot decide passes "
                      "the question to the next."))
        for order, label in _DETECTION_ORDER_CHOICES:
            self._detection_order_combo.append(",".join(order), label)
        self._detection_order_combo.set_active_id(
            ",".join(self._config.detection_order))
        if self._detection_order_combo.get_active_id() is None:
            self._detection_order_combo.set_active_id(
                ",".join(_DETECTION_ORDER_CHOICES[0][0]))
        dict_listbox.add_row_with_widget(row, self._detection_order_combo)

        row, self._dict_min_words_spin, _ = _create_spin_row(
            "Words _unique to one language:", 1, 10, 1,
            value=self._config.dictionary_min_words,
            atk_name="Words unique to one language",
            atk_desc="How many words must belong to one language's list and no "
                     "other before that language is chosen. Shared words such "
                     "as 'Information' are ignored either way. Default 2.")
        dict_listbox.add_row_with_widget(row, self._dict_min_words_spin)

        row, self._dict_min_share_spin, _ = _create_spin_row(
            "Minimum _share of those words:", 0.30, 1.00, 0.05, digits=2,
            value=self._config.dictionary_min_share,
            atk_name="Minimum share of unique words",
            atk_desc="The winning language must hold at least this share of all "
                     "the words found to be unique to one language, so text with "
                     "even evidence for two languages is left undecided. "
                     "Default 0.60.")
        dict_listbox.add_row_with_widget(row, self._dict_min_share_spin)

        row, self._dict_max_words_spin, _ = _create_spin_row(
            "_Most common words to load:", 0, 200000, 5000,
            value=self._config.dictionary_max_words,
            atk_name="Most common words to load",
            atk_desc="Word lists are ordered by how common each word is, so this "
                     "keeps only the most common ones. 0 loads the whole list. "
                     "Default 30000.")
        dict_listbox.add_row_with_widget(row, self._dict_max_words_spin)

        page.pack_start(dict_listbox, False, False, 0)
        page.pack_start(self._create_dictionary_status_label(), False, False, 0)
        return page

    def _create_dictionary_status_label(self):
        """A read-only line naming the word lists that are actually installed.

        The settings above are meaningless without lists on disk, and there
        is nowhere else in the dialog that would say so.
        """
        label = Gtk.Label()
        label.set_xalign(0)
        label.set_line_wrap(True)
        label.set_margin_top(6)
        label.set_selectable(True)
        installed = []
        directory = "Polyglot's dictionaries directory"
        try:
            from .dictionary_detector import DictionaryDetector, default_directory
            directory = default_directory()
            installed = DictionaryDetector(
                languages=self._config.enabled_languages,
                max_entries=self._config.dictionary_max_words,
            ).available_languages()
        except Exception as error:  # pylint: disable=broad-exception-caught
            log.debug(f"Polyglot: could not inspect word lists: {error}")
        if len(installed) >= 2:
            text = "Word lists installed for: " + ", ".join(installed) + "."
        elif installed:
            text = (f"Only one word list is installed ({installed[0]}). "
                    "At least two are needed, since detection works by "
                    "comparing them.")
        else:
            text = ("No word lists are installed, so this method is inactive. "
                    f"Run fetch-dictionaries.sh to install them into {directory}.")
        label.set_text(text)
        atk_obj = label.get_accessible()
        if atk_obj:
            atk_obj.set_name("Word list status")
        return label

    def _build_languages_page(self):
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        page.set_border_width(24)
        page.set_margin_start(40)
        page.set_margin_end(40)

        info_label = Gtk.Label(
            label="Select languages to detect. "
                  "Voices are configured in Orca's own Voice Sets preferences."
        )
        info_label.set_line_wrap(True)
        info_label.set_xalign(0)
        page.pack_start(info_label, False, False, 0)

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_vexpand(True)

        lang_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        available_langs = _get_speech_dispatcher_languages()

        for lang_code in available_langs:
            display = _LANG_DISPLAY_NAMES.get(lang_code, lang_code)
            row_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            row_box.set_margin_start(8)
            row_box.set_margin_end(8)
            row_box.set_margin_top(4)
            row_box.set_margin_bottom(4)

            check = Gtk.CheckButton(label=f"{display} ({lang_code})")
            check.set_active(lang_code in self._config.enabled_languages)
            check.connect("toggled", self._on_lang_toggled, lang_code)
            self._lang_checks[lang_code] = check

            # The braille table is the one per-language setting Orca's voice
            # sets do not cover, so it stays here -- inline rather than
            # behind a Customize dialog, since it is now the only thing
            # that dialog would have held.
            table_label = Gtk.Label(label="_Contraction table:")
            table_label.set_use_underline(True)
            table_combo = Gtk.ComboBoxText()
            table_label.set_mnemonic_widget(table_combo)
            table_combo.append("", "(No change)")
            for table_display, full_path in sorted(_get_contraction_tables().items()):
                table_combo.append(full_path, table_display)
            current = (self._config.language_settings.get(lang_code, {})
                       .get("contraction_table", ""))
            table_combo.set_active_id(current)
            if table_combo.get_active_id() is None:
                table_combo.set_active(0)
            table_combo.set_sensitive(check.get_active())
            combo_atk = table_combo.get_accessible()
            if combo_atk:
                combo_atk.set_name(f"Contraction table for {display}")
                combo_atk.set_description(
                    "The liblouis table used for contracted braille when this "
                    "language is detected")
            self._lang_table_combos[lang_code] = table_combo

            row_box.pack_start(check, True, True, 0)
            row_box.pack_end(table_combo, False, False, 0)
            row_box.pack_end(table_label, False, False, 0)
            lang_box.pack_start(row_box, False, False, 0)

        scrolled.add(lang_box)
        page.pack_start(scrolled, True, True, 0)
        return page

    def _build_scripts_page(self):
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        page.set_border_width(24)
        page.set_margin_start(40)
        page.set_margin_end(40)

        info_label = Gtk.Label(
            label="Map Unicode scripts to languages. When text in a non-Latin "
                  "script is detected, it automatically switches to the assigned language."
        )
        info_label.set_line_wrap(True)
        info_label.set_xalign(0)
        page.pack_start(info_label, False, False, 6)

        listbox = FocusManagedListBox(self.focus_sidebar)
        available_langs = _get_speech_dispatcher_languages()

        for script_id, script_display in sorted(_SCRIPT_DISPLAY_NAMES.items()):
            lang_values = []
            if script_id == "IPA":
                lang_values = [("ipa", "IPA braille only")]
            elif script_id == "BRAILLE":
                lang_values = [("unicode_braille", "Unicode braille only")]
            else:
                for lc in available_langs:
                    display = _LANG_DISPLAY_NAMES.get(lc, lc)
                    lang_values.append((lc, f"{display} ({lc})"))

            row, combo, _ = _create_combo_row(
                f"{script_display}:",
                atk_name=f"Language for {script_display} script")
            combo.append("", "(Not assigned)")
            for val, label in lang_values:
                combo.append(val, label)

            current = self._config.script_to_language.get(script_id, "")
            if current:
                combo.set_active_id(current)
            else:
                combo.set_active(0)

            self._script_combos[script_id] = combo
            listbox.add_row_with_widget(row, combo)

        page.pack_start(listbox, False, False, 0)
        return page

    def _build_exceptions_page(self):
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        page.set_border_width(24)
        page.set_margin_start(40)
        page.set_margin_end(40)

        info_label = Gtk.Label(
            label="Select applications where automatic language switching "
                  "should be disabled."
        )
        info_label.set_line_wrap(True)
        info_label.set_xalign(0)
        page.pack_start(info_label, False, False, 0)

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_vexpand(True)

        listbox = FocusManagedListBox(self.focus_sidebar)
        listbox.set_selection_mode(Gtk.SelectionMode.NONE)

        # Discover running applications via AT-SPI
        running_apps = set()
        system_apps = {
            "mutter-x11-frames", "orca", "niri", "waynotify", "nm-applet",
            "udiskie", "xdg-desktop-portal-gtk", "xdg-desktop-portal-gnome",
            "blueman-applet", "blueman-tray", "soteria", "gnome-shell", "kwin",
            "kwin_wayland", "plasma-desktop", "plasmashell", "discovernotifier",
            "systemsettings", "gsd-xsettings", "gsd-keyboard", "gsd-media-keys",
            "electron"
        }
        try:
            import gi as _gi
            _gi.require_version("Atspi", "2.0")
            from gi.repository import Atspi
            desktop = Atspi.get_desktop(0)
            if desktop:
                for i in range(Atspi.Accessible.get_child_count(desktop)):
                    child = Atspi.Accessible.get_child_at_index(desktop, i)
                    if child:
                        app_name = Atspi.Accessible.get_name(child)
                        if app_name and app_name.lower() not in system_apps:
                            running_apps.add(app_name.lower())
        except Exception as e:
            log.warning(f"Failed to fetch running apps via Atspi: {e}")

        # Combine with already-configured ignored apps
        all_apps = sorted(running_apps.union(
            {a.lower() for a in self._config.ignored_apps}))

        for app_name in all_apps:
            row_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            row_box.set_margin_start(8)
            row_box.set_margin_end(8)
            row_box.set_margin_top(4)
            row_box.set_margin_bottom(4)

            check = Gtk.CheckButton(label=app_name)
            check.set_active(app_name in self._config.ignored_apps)
            self._app_checks[app_name] = check

            row_box.pack_start(check, True, True, 0)
            listbox.add_row_with_widget(row_box, check)

        scrolled.add(listbox)
        page.pack_start(scrolled, True, True, 0)
        return page

    # --- Event handlers ---

    def _on_lang_toggled(self, check, lang_code):
        combo = self._lang_table_combos.get(lang_code)
        if combo:
            combo.set_sensitive(check.get_active())
        self._update_default_combo()

    def _on_edit_speech_dictionary(self, _button):
        dialog = SpeechDictionaryDialog(self, self._config.enabled_languages)
        dialog.show_all()
        dialog.run()

    def _on_edit_char_names(self, button):
        from .speech_interceptor import _FRIENDLY_NAMES
        dialog = CharacterNamesDialog(self, _FRIENDLY_NAMES)
        dialog.show_all()
        dialog.run()

    def _update_default_combo(self):
        self._default_combo.remove_all()
        for lang_code, check in self._lang_checks.items():
            if check.get_active():
                display = _LANG_DISPLAY_NAMES.get(lang_code, lang_code)
                self._default_combo.append(lang_code, f"{display} ({lang_code})")
        if self._config.default_language:
            self._default_combo.set_active_id(self._config.default_language)
        if self._default_combo.get_active() < 0 and len(self._lang_checks) > 0:
            self._default_combo.set_active(0)

    def _on_save_clicked(self, button):
        self._save_config()
        _suspend_events()
        self.destroy()
        GLib.timeout_add(500, _resume_events)

    def _on_delete(self, window, event):
        _suspend_events()
        GLib.timeout_add(500, _resume_events)
        return False

    def _on_key_press(self, window, event):
        if event.keyval == Gdk.KEY_Escape:
            _suspend_events()
            self.destroy()
            GLib.timeout_add(500, _resume_events)
            return True
        return False

    def _save_config(self):
        """Save configuration from dialog state."""
        # General
        mode = self._detection_mode_combo.get_active_id() or "markup_text"
        self._config.detection_mode = mode
        self._config.enabled = mode != "off"
        self._config.word_threshold = int(self._threshold_spin.get_value())
        default_lang = self._default_combo.get_active_id()
        if default_lang:
            self._config.default_language = default_lang

        # Speech
        self._config.speak_emojis = self._emoji_switch.get_active()
        self._config.unicode_verbosity = self._unicode_combo.get_active_id() or "brief"
        self._config.speak_emoticons = self._emoticon_switch.get_active()

        # Detection
        self._config.switch_confidence = self._confidence_spin.get_value()
        self._config.enable_mixed_language = self._mixed_lang_switch.get_active()
        self._config.mixed_max_words = int(self._mixed_max_words_spin.get_value())
        self._config.dictionary_enabled = self._dict_enabled_switch.get_active()
        order = self._detection_order_combo.get_active_id()
        if order:
            self._config.detection_order = order.split(",")
        self._config.dictionary_min_words = int(self._dict_min_words_spin.get_value())
        self._config.dictionary_min_share = self._dict_min_share_spin.get_value()
        self._config.dictionary_max_words = int(self._dict_max_words_spin.get_value())

        # Languages
        enabled = []
        for lang_code, check in self._lang_checks.items():
            if check.get_active():
                enabled.append(lang_code)
        self._config.enabled_languages = enabled

        # Braille tables, for the languages that are still ticked. The rest
        # are dropped so an unticked language does not keep a stale table.
        self._config.language_settings = {
            lang_code: {
                "contraction_table": self._lang_table_combos[lang_code].get_active_id() or ""
            }
            for lang_code in enabled
            if lang_code in self._lang_table_combos
        }

        # Script Detection
        script_map = {}
        for script_id, combo in self._script_combos.items():
            lang = combo.get_active_id()
            if lang:
                script_map[script_id] = lang
        self._config.script_to_language = script_map

        # Exceptions
        ignored = []
        for app_name, check in self._app_checks.items():
            if check.get_active():
                ignored.append(app_name)
        self._config.ignored_apps = ignored

        self._config.save()

        if self._on_save:
            self._on_save()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def show_settings_dialog(config, on_save=None):
    """Show the settings window. Must be called from the GTK main thread."""
    window = PolyglotSettingsWindow(config, on_save)
    window.show_all()
    return window
