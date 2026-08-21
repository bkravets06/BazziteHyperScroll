"""Backlight controls.

RGB boards get hue and saturation as well as brightness, effect and speed;
single-colour boards get everything except the colour. Which one you have comes
from the definition, not from guessing, because Keychron sells both under the
same model name.
"""

from __future__ import annotations

import colorsys
from typing import Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gtk  # noqa: E402

from ..model.device import Keyboard  # noqa: E402
from ..protocol import via  # noqa: E402


def hsv_to_rgb(hue: int, saturation: int, value: int) -> tuple[float, float, float]:
    """QMK's 0-255 HSV into the 0-1 RGB Cairo wants."""
    return colorsys.hsv_to_rgb(hue / 255, saturation / 255, value / 255)


class LightingPage(Adw.PreferencesPage):
    """Effect, brightness, speed and colour, applied live."""

    __gtype_name__ = "KeychronZenLightingPage"

    def __init__(self, notify: Callable[[str], None]):
        super().__init__()
        self._keyboard: Keyboard | None = None
        self._loading = False
        self._notify = notify

        self._group = Adw.PreferencesGroup(
            title="Backlight",
            description="Changes apply immediately and are saved to the keyboard.",
        )
        self.add(self._group)

        self._effect = Adw.ComboRow(title="Effect")
        self._effect.connect("notify::selected", self._on_changed)
        self._group.add(self._effect)

        self._brightness = self._slider_row("Brightness", 0, 255)
        self._speed = self._slider_row("Effect speed", 0, 255)

        self._color_group = Adw.PreferencesGroup(title="Colour")
        self._hue = self._slider_row("Hue", 0, 255, group=self._color_group)
        self._saturation = self._slider_row("Saturation", 0, 255, group=self._color_group)

        self._swatch = Gtk.DrawingArea(content_width=48, content_height=28,
                                       valign=Gtk.Align.CENTER)
        self._swatch.set_draw_func(self._draw_swatch)
        swatch_row = Adw.ActionRow(title="Preview")
        swatch_row.add_suffix(self._swatch)
        self._color_group.add(swatch_row)
        self.add(self._color_group)

        self._unsupported = Adw.PreferencesGroup()
        self._unsupported_row = Adw.ActionRow(
            title="No backlight control",
            subtitle="This keyboard did not report a lighting channel.",
        )
        self._unsupported.add(self._unsupported_row)
        self.add(self._unsupported)

    def _slider_row(self, title: str, lower: int, upper: int,
                    group: Adw.PreferencesGroup | None = None) -> Gtk.Scale:
        scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, lower, upper, 1)
        scale.set_size_request(260, -1)
        scale.set_draw_value(False)
        scale.set_valign(Gtk.Align.CENTER)

        # A separate label keeps the number clear of the slider handle at the
        # ends of the range, where Gtk.Scale would draw them on top of one another.
        value_label = Gtk.Label(width_chars=3, xalign=1.0, valign=Gtk.Align.CENTER,
                                css_classes=["dim-label", "numeric"])
        value_label.set_label(str(lower))
        scale.connect("value-changed",
                      lambda widget: value_label.set_label(str(int(widget.get_value()))))
        scale.connect("value-changed", self._on_changed)

        row = Adw.ActionRow(title=title)
        row.add_suffix(scale)
        row.add_suffix(value_label)
        (group or self._group).add(row)
        return scale

    # -- content ---------------------------------------------------------

    def set_keyboard(self, keyboard: Keyboard | None) -> None:
        self._keyboard = keyboard
        self.refresh()

    def refresh(self) -> None:
        keyboard = self._keyboard
        supported = (
            keyboard is not None
            and keyboard.lighting is not None
            and keyboard.variant is not None
        )
        self._group.set_visible(bool(supported))
        self._unsupported.set_visible(not supported)
        if not supported:
            self._color_group.set_visible(False)
            return

        lighting = keyboard.variant.lighting
        state = keyboard.lighting

        self._loading = True
        names = Gtk.StringList()
        for effect in lighting.effects:
            names.append(effect.name)
        self._effect.set_model(names)
        selected = next(
            (index for index, effect in enumerate(lighting.effects)
             if effect.value == state.effect),
            0,
        )
        self._effect.set_selected(selected)
        self._brightness.set_value(state.brightness)
        self._speed.set_value(state.speed)
        self._color_group.set_visible(lighting.has_color)
        if lighting.has_color:
            self._hue.set_value(state.hue or 0)
            self._saturation.set_value(state.saturation or 0)
        self._loading = False
        self._swatch.queue_draw()

    # -- applying --------------------------------------------------------

    def _on_changed(self, *_args) -> None:
        if self._loading or self._keyboard is None or self._keyboard.variant is None:
            return
        lighting = self._keyboard.variant.lighting
        index = self._effect.get_selected()
        if index >= len(lighting.effects):
            return
        state = via.LightingState(
            brightness=int(self._brightness.get_value()),
            effect=lighting.effects[index].value,
            speed=int(self._speed.get_value()),
            hue=int(self._hue.get_value()) if lighting.has_color else None,
            saturation=int(self._saturation.get_value()) if lighting.has_color else None,
        )
        try:
            self._keyboard.apply_lighting(state)
        except Exception as exc:  # noqa: BLE001 - surfaced as a toast
            self._notify(f"Could not change the lighting: {exc}")
            return
        self._swatch.queue_draw()

    def _draw_swatch(self, _area, cr, width, height, *_args) -> None:
        if self._keyboard is None or self._keyboard.lighting is None:
            return
        state = self._keyboard.lighting
        red, green, blue = hsv_to_rgb(
            state.hue or 0, state.saturation or 0, max(state.brightness, 24)
        )
        cr.set_source_rgb(red, green, blue)
        cr.rectangle(0, 0, width, height)
        cr.fill()
        cr.set_source_rgba(0, 0, 0, 0.25)
        cr.set_line_width(1)
        cr.rectangle(0.5, 0.5, width - 1, height - 1)
        cr.stroke()
