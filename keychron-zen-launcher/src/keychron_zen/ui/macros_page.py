"""The macro editor.

The keyboard stores every macro in one shared buffer, so slots compete for the
same bytes and the whole buffer is written at once. The page shows how much of
it is used and refuses to write something that will not fit, rather than
letting the firmware truncate it.
"""

from __future__ import annotations

from typing import Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gtk  # noqa: E402

from ..model.device import Keyboard  # noqa: E402
from ..protocol import macros  # noqa: E402

SYNTAX_HELP = (
    "Type the text you want. Use <tt>{KC_ENT}</tt> to tap a key, "
    "<tt>{+KC_LSFT}</tt> and <tt>{-KC_LSFT}</tt> to hold and release one, and "
    "<tt>{250}</tt> to wait 250 ms. Write <tt>\\{</tt> for a literal brace."
)


class MacrosPage(Adw.PreferencesPage):
    """One editable row per macro slot, written to the keyboard on save."""

    __gtype_name__ = "KeychronZenMacrosPage"

    def __init__(self, notify: Callable[[str], None]):
        super().__init__()
        self._keyboard: Keyboard | None = None
        self._rows: list[Adw.EntryRow] = []
        self._notify = notify

        self._actions = Adw.PreferencesGroup()
        self._usage = Adw.ActionRow(title="Storage", subtitle="—")

        save = Gtk.Button(label="Write to keyboard", css_classes=["suggested-action"],
                          valign=Gtk.Align.CENTER)
        save.connect("clicked", lambda *_: self.save())
        self._usage.add_suffix(save)

        revert = Gtk.Button(label="Reload", valign=Gtk.Align.CENTER)
        revert.set_tooltip_text("Discard edits and read the macros back from the keyboard")
        revert.connect("clicked", lambda *_: self._reload())
        self._usage.add_suffix(revert)

        self._actions.add(self._usage)
        self.add(self._actions)

        self._group = Adw.PreferencesGroup(title="Macros", description=SYNTAX_HELP)
        self.add(self._group)

    # -- content ---------------------------------------------------------

    def set_keyboard(self, keyboard: Keyboard | None) -> None:
        self._keyboard = keyboard
        self._rebuild()

    def _rebuild(self) -> None:
        for row in self._rows:
            self._group.remove(row)
        self._rows.clear()

        if self._keyboard is None:
            return
        for index, macro in enumerate(self._keyboard.macros):
            row = Adw.EntryRow(title=f"Macro {index}")
            row.set_text(macros.to_text(macro))
            row.connect("changed", self._on_changed)
            self._group.add(row)
            self._rows.append(row)
        self._update_usage()

    def _reload(self) -> None:
        if self._keyboard is None:
            return
        self._keyboard.reload_macros()
        self._rebuild()
        self._notify("Macros reloaded from the keyboard")

    # -- validation ------------------------------------------------------

    def _parse_all(self) -> list[list[macros.Action]] | None:
        parsed: list[list[macros.Action]] = []
        ok = True
        for index, row in enumerate(self._rows):
            try:
                parsed.append(macros.from_text(row.get_text()))
                row.remove_css_class("error")
            except macros.MacroError as exc:
                row.add_css_class("error")
                if ok:
                    self._notify(f"Macro {index}: {exc}")
                ok = False
        return parsed if ok else None

    def _on_changed(self, _row) -> None:
        self._update_usage()

    def _update_usage(self) -> None:
        if self._keyboard is None:
            return
        total = self._keyboard.macro_buffer_size
        parsed = []
        for row in self._rows:
            try:
                parsed.append(macros.encode(macros.from_text(row.get_text())))
            except macros.MacroError:
                self._usage.set_subtitle("A macro has a mistake in it — see the highlighted row")
                return
        used = sum(len(entry) + 1 for entry in parsed)
        suffix = "" if used <= total else "  ·  too big to fit"
        self._usage.set_subtitle(f"{used} of {total} bytes used{suffix}")

    # -- writing ---------------------------------------------------------

    def save(self) -> None:
        if self._keyboard is None:
            return
        parsed = self._parse_all()
        if parsed is None:
            return
        try:
            self._keyboard.set_macros(parsed)
        except Exception as exc:  # noqa: BLE001 - surfaced as a toast
            self._notify(f"Could not write the macros: {exc}")
            return
        self._update_usage()
        used = sum(1 for macro in parsed if macro)
        self._notify(f"{used} macro{'s' if used != 1 else ''} written to the keyboard")
