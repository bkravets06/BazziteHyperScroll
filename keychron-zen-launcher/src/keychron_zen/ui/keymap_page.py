"""The remapping page: pick a layer, click a key, choose what it does."""

from __future__ import annotations

from typing import Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gtk  # noqa: E402

from ..model.device import Keyboard  # noqa: E402
from ..protocol import keycodes, labels  # noqa: E402
from .keyboard_view import KeyboardView  # noqa: E402
from .keycode_picker import KeycodePicker  # noqa: E402
from .palette import Palette  # noqa: E402


class KeymapPage(Gtk.Box):
    """Layer switcher, drawn keyboard, and the details of the selected key."""

    __gtype_name__ = "KeychronZenKeymapPage"

    def __init__(self, palette: Palette, notify: Callable[[str], None]):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self._keyboard: Keyboard | None = None
        self._layer = 0
        self._notify = notify

        self._layer_bar = Gtk.Box(
            spacing=0,
            halign=Gtk.Align.CENTER,
            margin_top=12,
            margin_bottom=6,
            css_classes=["linked"],
        )
        self.append(self._layer_bar)

        self._view = KeyboardView(palette, self._legend)
        self._view.set_margin_start(12)
        self._view.set_margin_end(12)
        self._view.connect("key-activated", self._on_key_activated)
        self._view.connect("key-selected", lambda *_: self._update_details())

        holder = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER,
                         vexpand=True)
        holder.append(self._view)
        self.append(holder)

        self._details = Adw.ActionRow(
            title="Click a key to remap it",
            subtitle="Changes are written to the keyboard straight away.",
        )
        self._reset_key = Gtk.Button(
            label="Restore default", valign=Gtk.Align.CENTER, sensitive=False
        )
        self._reset_key.set_tooltip_text("Put back the keycode this keyboard shipped with")
        self._reset_key.connect("clicked", self._on_reset_key)
        self._details.add_suffix(self._reset_key)

        group = Adw.PreferencesGroup(margin_start=12, margin_end=12,
                                     margin_top=6, margin_bottom=12)
        group.add(self._details)
        self.append(group)

    # -- content ---------------------------------------------------------

    def set_keyboard(self, keyboard: Keyboard | None) -> None:
        self._keyboard = keyboard
        self._layer = 0
        self._rebuild_layer_bar()
        if keyboard is not None and keyboard.has_layout:
            self._view.set_keys(keyboard.definition.keys(keyboard.variant))
        else:
            self._view.set_keys(())
        self.refresh()

    def set_palette(self, palette: Palette) -> None:
        self._view.set_palette(palette)

    def refresh(self) -> None:
        self._view.set_changed(
            self._keyboard.changed_cells(self._layer) if self._keyboard else set()
        )
        self._view.queue_draw()
        self._update_details()

    # -- layer bar -------------------------------------------------------

    def _rebuild_layer_bar(self) -> None:
        child = self._layer_bar.get_first_child()
        while child is not None:
            following = child.get_next_sibling()
            self._layer_bar.remove(child)
            child = following

        if self._keyboard is None:
            return
        first: Gtk.ToggleButton | None = None
        for index in range(self._keyboard.layer_count):
            name = (
                self._keyboard.definition.layer_name(index)
                if self._keyboard.definition
                else f"Layer {index}"
            )
            button = Gtk.ToggleButton(label=name)
            if first is None:
                first = button
                button.set_active(True)
            else:
                button.set_group(first)
            button.connect("toggled", self._on_layer_toggled, index)
            self._layer_bar.append(button)

    def _on_layer_toggled(self, button: Gtk.ToggleButton, index: int) -> None:
        if button.get_active() and index != self._layer:
            self._layer = index
            self.refresh()

    # -- keys ------------------------------------------------------------

    def _legend(self, key) -> tuple[str, str]:
        if self._keyboard is None or not self._keyboard.keymap:
            return "", ""
        try:
            keycode = self._keyboard.keycode(self._layer, key.row, key.column)
        except IndexError:
            return "", ""
        return labels.legend(keycode, self._keyboard.custom_keycode_labels)

    def _selected_keycode(self) -> int | None:
        key = self._view.selected
        if key is None or self._keyboard is None or not self._keyboard.keymap:
            return None
        return self._keyboard.keycode(self._layer, key.row, key.column)

    def _update_details(self) -> None:
        key = self._view.selected
        keycode = self._selected_keycode()
        if key is None or keycode is None or self._keyboard is None:
            self._details.set_title("Click a key to remap it")
            self._details.set_subtitle("Changes are written to the keyboard straight away.")
            self._reset_key.set_sensitive(False)
            return

        main, sub = labels.legend(keycode, self._keyboard.custom_keycode_labels)
        shown = f"{main} {sub}".strip() or "Nothing"
        default = self._keyboard.default_keycode(self._layer, key.row, key.column)
        detail = f"{keycodes.name_for(keycode)} · row {key.row}, column {key.column}"
        if default is not None and default != keycode:
            detail += f" · was {keycodes.name_for(default)}"
        self._details.set_title(shown)
        self._details.set_subtitle(detail)
        self._reset_key.set_sensitive(default is not None and default != keycode)

    def _on_key_activated(self, _view, row: int, column: int) -> None:
        if self._keyboard is None or not self._keyboard.keymap:
            return
        current = self._keyboard.keycode(self._layer, row, column)
        window = self.get_root()
        picker = KeycodePicker(
            window,
            current=current,
            layer_count=self._keyboard.layer_count,
            macro_texts=_macro_texts(self._keyboard),
            custom_keycodes=self._keyboard.variant.custom_keycodes
            if self._keyboard.variant
            else (),
            subtitle=f"Row {row}, column {column} on {self._layer_title()}",
        )
        picker.connect(
            "keycode-chosen",
            lambda _picker, keycode: self._assign(row, column, keycode),
        )
        picker.present()

    def _layer_title(self) -> str:
        if self._keyboard and self._keyboard.definition:
            return self._keyboard.definition.layer_name(self._layer)
        return f"layer {self._layer}"

    def _assign(self, row: int, column: int, keycode: int) -> None:
        if self._keyboard is None:
            return
        try:
            self._keyboard.set_keycode(self._layer, row, column, keycode)
        except Exception as exc:  # noqa: BLE001 - surfaced to the user as a toast
            self._notify(f"Could not write that key: {exc}")
            return
        self.refresh()
        self._notify(f"{keycodes.name_for(keycode)} written to the keyboard")

    def _on_reset_key(self, _button) -> None:
        key = self._view.selected
        if key is None or self._keyboard is None:
            return
        default = self._keyboard.default_keycode(self._layer, key.row, key.column)
        if default is not None:
            self._assign(key.row, key.column, default)


def _macro_texts(keyboard: Keyboard) -> list[str]:
    from ..protocol import macros

    return [macros.to_text(macro) for macro in keyboard.macros]
