"""Key tester.

Reads the switch matrix straight from the firmware rather than listening for
key events, so it shows what the hardware is doing regardless of what the key
is mapped to, whether the window has focus, or whether the key produces any
character at all.
"""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, GLib, Gtk  # noqa: E402

from ..model.device import Keyboard  # noqa: E402
from ..protocol import labels  # noqa: E402
from .keyboard_view import KeyboardView  # noqa: E402
from .palette import Palette  # noqa: E402

POLL_INTERVAL_MS = 40


class TesterPage(Gtk.Box):
    """Live matrix view; polls only while the page is actually on screen."""

    __gtype_name__ = "KeychronZenTesterPage"

    def __init__(self, palette: Palette):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self._keyboard: Keyboard | None = None
        self._tested: set[tuple[int, int]] = set()
        self._source: int | None = None
        self._failures = 0

        self._view = KeyboardView(palette, self._legend)
        self._view.interactive = False
        self._view.set_focusable(False)
        self._view.set_margin_start(12)
        self._view.set_margin_end(12)
        self._view.set_margin_top(12)

        holder = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER,
                         vexpand=True)
        holder.append(self._view)
        self.append(holder)

        self._status = Adw.ActionRow(
            title="Press keys to test them",
            subtitle="Read live from the switch matrix, so every key registers here.",
        )
        clear = Gtk.Button(label="Start over", valign=Gtk.Align.CENTER)
        clear.connect("clicked", lambda *_: self._clear())
        self._status.add_suffix(clear)

        group = Adw.PreferencesGroup(margin_start=12, margin_end=12,
                                     margin_top=6, margin_bottom=12)
        group.add(self._status)
        self.append(group)

    # -- content ---------------------------------------------------------

    def set_keyboard(self, keyboard: Keyboard | None) -> None:
        self._keyboard = keyboard
        self._clear()
        if keyboard is not None and keyboard.has_layout:
            self._view.set_keys(keyboard.definition.keys(keyboard.variant))
        else:
            self._view.set_keys(())

    def set_palette(self, palette: Palette) -> None:
        self._view.set_palette(palette)

    def _legend(self, key) -> tuple[str, str]:
        """Base-layer legends, so the tester reads like the physical keyboard."""
        if self._keyboard is None or not self._keyboard.keymap:
            return "", ""
        try:
            keycode = self._keyboard.keycode(0, key.row, key.column)
        except IndexError:
            return "", ""
        return labels.legend(keycode, self._keyboard.custom_keycode_labels)

    def _clear(self) -> None:
        self._tested.clear()
        self._view.set_tested(set())
        self._view.set_pressed(set())
        self._update_status()

    # -- polling ---------------------------------------------------------

    def start(self) -> None:
        if self._source is None and self._keyboard is not None:
            self._failures = 0
            self._source = GLib.timeout_add(POLL_INTERVAL_MS, self._poll)

    def stop(self) -> None:
        if self._source is not None:
            GLib.source_remove(self._source)
            self._source = None

    def _poll(self) -> bool:
        keyboard = self._keyboard
        if keyboard is None:
            self._source = None
            return GLib.SOURCE_REMOVE
        try:
            state = keyboard.matrix_state()
        except Exception:  # noqa: BLE001 - a disconnect should not spam errors
            self._failures += 1
            if self._failures > 3:
                self._status.set_title("Lost contact with the keyboard")
                self._source = None
                return GLib.SOURCE_REMOVE
            return GLib.SOURCE_CONTINUE

        self._failures = 0
        pressed = {
            (row, column)
            for row, columns in enumerate(state)
            for column, down in enumerate(columns)
            if down
        }
        self._view.set_pressed(pressed)
        if pressed - self._tested:
            self._tested |= pressed
            self._view.set_tested(set(self._tested))
            self._update_status()
        return GLib.SOURCE_CONTINUE

    def _update_status(self) -> None:
        total = len(self._view_keys())
        if not total:
            return
        done = len(self._tested & {key.cell for key in self._view_keys()})
        self._status.set_title(f"{done} of {total} keys tested")
        if done == total:
            self._status.set_subtitle("Every key on this layout registered. Nothing is dead.")
        else:
            self._status.set_subtitle(
                "Read live from the switch matrix, so every key registers here."
            )

    def _view_keys(self):
        if self._keyboard is None or not self._keyboard.has_layout:
            return ()
        return self._keyboard.definition.keys(self._keyboard.variant)
