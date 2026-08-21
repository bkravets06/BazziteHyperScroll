"""The drawn keyboard: one widget that shows the layout and takes clicks.

Keys are painted with Cairo rather than assembled from buttons. A keyboard is
a grid of fractional-width caps -- 1.25u here, 6.25u there -- which fights
every box layout, and drawing it directly also makes the key tester and the
"changed from default" markers trivial to render.

Keyboard navigation is wired up by hand for the same reason: arrow keys move
to the nearest cap in that direction, Enter and Space open the picker.
"""

from __future__ import annotations

from typing import Callable, Iterable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("PangoCairo", "1.0")

from gi.repository import Gdk, GObject, Gtk, Pango, PangoCairo  # noqa: E402

from ..model.definitions import KeyPosition  # noqa: E402
from .palette import Palette  # noqa: E402

# Layout metrics, all in fractions of one key unit.
GAP = 0.06
RADIUS = 0.14
MAIN_TEXT = 0.30
SUB_TEXT = 0.20

# Pixels per key unit at the widget's natural size.
NATURAL_UNIT = 44
MINIMUM_UNIT = 18

LegendFunc = Callable[[KeyPosition], tuple[str, str]]


def layout_bounds(keys: Iterable[KeyPosition]) -> tuple[float, float]:
    """The keyboard's size in key units."""
    width = height = 0.0
    for key in keys:
        width = max(width, key.x + key.width)
        height = max(height, key.y + key.height)
    return width or 1.0, height or 1.0


def _rounded_rect(cr, x: float, y: float, width: float, height: float, radius: float) -> None:
    from math import pi

    radius = min(radius, width / 2, height / 2)
    cr.new_sub_path()
    cr.arc(x + width - radius, y + radius, radius, -pi / 2, 0)
    cr.arc(x + width - radius, y + height - radius, radius, 0, pi / 2)
    cr.arc(x + radius, y + height - radius, radius, pi / 2, pi)
    cr.arc(x + radius, y + radius, radius, pi, 3 * pi / 2)
    cr.close_path()


def _draw_text(cr, layout, text: str, x: float, y: float, width: float, size: float,
               color, bold: bool = False) -> float:
    """Draw one centred line, shrinking it if it will not fit. Returns its height."""
    description = Pango.FontDescription()
    description.set_family("Cantarell, sans-serif")
    description.set_absolute_size(size * Pango.SCALE)
    if bold:
        description.set_weight(Pango.Weight.BOLD)
    layout.set_font_description(description)
    layout.set_text(text, -1)

    extent_width, extent_height = layout.get_pixel_size()
    if extent_width > width and extent_width > 0:
        description.set_absolute_size(size * (width / extent_width) * Pango.SCALE)
        layout.set_font_description(description)
        extent_width, extent_height = layout.get_pixel_size()

    cr.set_source_rgba(*color)
    cr.move_to(x + (width - extent_width) / 2, y)
    PangoCairo.show_layout(cr, layout)
    return extent_height


def draw_keyboard(
    cr,
    width: int,
    height: int,
    keys: Iterable[KeyPosition],
    palette: Palette,
    legend: LegendFunc,
    *,
    selected: KeyPosition | None = None,
    hovered: KeyPosition | None = None,
    pressed: set[tuple[int, int]] | None = None,
    tested: set[tuple[int, int]] | None = None,
    changed: set[tuple[int, int]] | None = None,
    focused: bool = False,
) -> None:
    """Paint the whole keyboard into ``cr``.

    Kept as a plain function so it can be rendered to an image surface in
    tests, without a display or a widget.
    """
    keys = list(keys)
    pressed = pressed or set()
    tested = tested or set()
    changed = changed or set()

    board_width, board_height = layout_bounds(keys)
    unit = min(width / board_width, height / board_height)
    offset_x = (width - board_width * unit) / 2
    offset_y = (height - board_height * unit) / 2

    layout = PangoCairo.create_layout(cr)
    layout.set_alignment(Pango.Alignment.CENTER)

    for key in keys:
        x = offset_x + key.x * unit + GAP * unit / 2
        y = offset_y + key.y * unit + GAP * unit / 2
        cap_width = key.width * unit - GAP * unit
        cap_height = key.height * unit - GAP * unit
        main, sub = legend(key)

        is_selected = selected is not None and key.cell == selected.cell
        is_pressed = key.cell in pressed
        is_tested = key.cell in tested and not is_pressed

        if is_pressed:
            fill, ink, subink = palette.pressed, palette.pressed_text, palette.pressed_text
        elif is_selected:
            fill, ink, subink = palette.selected, palette.selected_text, palette.selected_text
        elif is_tested:
            fill, ink, subink = palette.tested, palette.text, palette.text_dim
        elif not main and not sub:
            fill, ink, subink = palette.cap_empty, palette.text_dim, palette.text_dim
        else:
            fill, ink, subink = palette.cap, palette.text, palette.text_dim

        _rounded_rect(cr, x, y, cap_width, cap_height, RADIUS * unit)
        cr.set_source_rgba(*fill)
        cr.fill_preserve()
        cr.set_source_rgba(*palette.cap_border)
        cr.set_line_width(max(1.0, unit * 0.02))
        cr.stroke()

        if hovered is not None and key.cell == hovered.cell and not is_selected:
            _rounded_rect(cr, x, y, cap_width, cap_height, RADIUS * unit)
            cr.set_source_rgba(*palette.hover)
            cr.fill()

        if is_selected and focused:
            _rounded_rect(
                cr,
                x - unit * 0.03,
                y - unit * 0.03,
                cap_width + unit * 0.06,
                cap_height + unit * 0.06,
                RADIUS * unit,
            )
            cr.set_source_rgba(*palette.selected)
            cr.set_line_width(max(1.5, unit * 0.05))
            cr.stroke()

        if key.cell in changed:
            marker = unit * 0.09
            cr.set_source_rgba(*palette.modified)
            cr.arc(x + cap_width - marker * 1.6, y + marker * 1.6, marker, 0, 6.2832)
            cr.fill()

        # Two lines when there is a sub-legend, otherwise one centred line.
        inner_x = x + unit * 0.08
        inner_width = cap_width - unit * 0.16
        if sub:
            total = (MAIN_TEXT + SUB_TEXT) * unit
            top = y + (cap_height - total) / 2
            used = _draw_text(cr, layout, main, inner_x, top, inner_width,
                              MAIN_TEXT * unit, ink, bold=True)
            _draw_text(cr, layout, sub, inner_x, top + used, inner_width,
                       SUB_TEXT * unit, subink)
        elif main:
            top = y + (cap_height - MAIN_TEXT * unit * 1.35) / 2
            _draw_text(cr, layout, main, inner_x, top, inner_width,
                       MAIN_TEXT * unit, ink, bold=True)


class KeyboardView(Gtk.DrawingArea):
    """Interactive keyboard layout."""

    __gtype_name__ = "KeychronZenKeyboardView"

    __gsignals__ = {
        # Emitted with (row, column) when a key is clicked or activated.
        "key-activated": (GObject.SignalFlags.RUN_FIRST, None, (int, int)),
        "key-selected": (GObject.SignalFlags.RUN_FIRST, None, (int, int)),
    }

    def __init__(self, palette: Palette, legend: LegendFunc):
        super().__init__()
        self._keys: tuple[KeyPosition, ...] = ()
        self._palette = palette
        self._legend = legend
        self._selected: KeyPosition | None = None
        self._hovered: KeyPosition | None = None
        self._pressed: set[tuple[int, int]] = set()
        self._tested: set[tuple[int, int]] = set()
        self._changed: set[tuple[int, int]] = set()
        self.interactive = True

        self.set_draw_func(self._on_draw)
        self.set_focusable(True)
        self.set_hexpand(True)
        self.set_vexpand(True)

        click = Gtk.GestureClick()
        click.connect("pressed", self._on_pressed)
        self.add_controller(click)

        motion = Gtk.EventControllerMotion()
        motion.connect("motion", self._on_motion)
        motion.connect("leave", self._on_leave)
        self.add_controller(motion)

        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self._on_key_pressed)
        self.add_controller(keys)

        focus = Gtk.EventControllerFocus()
        focus.connect("enter", lambda *_: self.queue_draw())
        focus.connect("leave", lambda *_: self.queue_draw())
        self.add_controller(focus)

    # -- content ---------------------------------------------------------

    def set_keys(self, keys: Iterable[KeyPosition]) -> None:
        self._keys = tuple(keys)
        if self._selected is not None and self._selected not in self._keys:
            self._selected = None
        self.queue_resize()
        self.queue_draw()

    def set_palette(self, palette: Palette) -> None:
        self._palette = palette
        self.queue_draw()

    @property
    def selected(self) -> KeyPosition | None:
        return self._selected

    def select(self, cell: tuple[int, int] | None) -> None:
        key = None if cell is None else self._key_for_cell(cell)
        if key is not self._selected:
            self._selected = key
            self.queue_draw()
            if key is not None:
                self.emit("key-selected", key.row, key.column)

    def set_pressed(self, cells: set[tuple[int, int]]) -> None:
        """Keys physically held down right now (key tester)."""
        if cells != self._pressed:
            self._pressed = set(cells)
            self.queue_draw()

    def set_tested(self, cells: set[tuple[int, int]]) -> None:
        """Keys that have been pressed at least once (key tester)."""
        if cells != self._tested:
            self._tested = set(cells)
            self.queue_draw()

    def set_changed(self, cells: set[tuple[int, int]]) -> None:
        """Keys differing from the reference keymap; drawn with a dot."""
        if cells != self._changed:
            self._changed = set(cells)
            self.queue_draw()

    # -- geometry --------------------------------------------------------

    def do_get_request_mode(self):
        return Gtk.SizeRequestMode.HEIGHT_FOR_WIDTH

    def do_measure(self, orientation, for_size):
        if not self._keys:
            return 0, 0, -1, -1

        board_width, board_height = layout_bounds(self._keys)
        if orientation == Gtk.Orientation.HORIZONTAL:
            return (
                int(board_width * MINIMUM_UNIT),
                int(board_width * NATURAL_UNIT),
                -1,
                -1,
            )

        minimum = int(board_height * MINIMUM_UNIT)
        if for_size > 0:
            # Height follows width so the keyboard keeps its proportions. Only
            # the natural size scales: a minimum that grew with width would
            # propagate up through every ancestor as a demand for that height.
            natural = max(minimum, int(for_size * board_height / board_width))
        else:
            natural = int(board_height * NATURAL_UNIT)
        return minimum, natural, -1, -1

    def _metrics(self) -> tuple[float, float, float]:
        board_width, board_height = layout_bounds(self._keys)
        width, height = self.get_width(), self.get_height()
        unit = min(width / board_width, height / board_height)
        return unit, (width - board_width * unit) / 2, (height - board_height * unit) / 2

    def key_at(self, x: float, y: float) -> KeyPosition | None:
        if not self._keys:
            return None
        unit, offset_x, offset_y = self._metrics()
        if unit <= 0:
            return None
        for key in self._keys:
            left = offset_x + key.x * unit
            top = offset_y + key.y * unit
            if left <= x < left + key.width * unit and top <= y < top + key.height * unit:
                return key
        return None

    def _key_for_cell(self, cell: tuple[int, int]) -> KeyPosition | None:
        for key in self._keys:
            if key.cell == cell:
                return key
        return None

    # -- input -----------------------------------------------------------

    def _on_draw(self, _area, cr, width, height, *_args) -> None:
        draw_keyboard(
            cr,
            width,
            height,
            self._keys,
            self._palette,
            self._legend,
            selected=self._selected,
            hovered=self._hovered if self.interactive else None,
            pressed=self._pressed,
            tested=self._tested,
            changed=self._changed,
            focused=self.has_focus(),
        )

    def _on_pressed(self, gesture, n_press, x, y) -> None:
        if not self.interactive:
            return
        key = self.key_at(x, y)
        if key is None:
            return
        self.grab_focus()
        self.select(key.cell)
        self.emit("key-activated", key.row, key.column)

    def _on_motion(self, _controller, x, y) -> None:
        key = self.key_at(x, y)
        if key is not self._hovered:
            self._hovered = key
            self.queue_draw()

    def _on_leave(self, _controller) -> None:
        if self._hovered is not None:
            self._hovered = None
            self.queue_draw()

    def _on_key_pressed(self, _controller, keyval, _keycode, _state) -> bool:
        if not self.interactive or not self._keys:
            return False
        if keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter, Gdk.KEY_space):
            if self._selected is None:
                self.select(self._keys[0].cell)
            if self._selected is not None:
                self.emit("key-activated", self._selected.row, self._selected.column)
            return True

        directions = {
            Gdk.KEY_Left: (-1, 0),
            Gdk.KEY_Right: (1, 0),
            Gdk.KEY_Up: (0, -1),
            Gdk.KEY_Down: (0, 1),
        }
        if keyval not in directions:
            return False
        if self._selected is None:
            self.select(self._keys[0].cell)
            return True
        neighbour = self._neighbour(self._selected, *directions[keyval])
        if neighbour is not None:
            self.select(neighbour.cell)
        return True

    def _neighbour(self, key: KeyPosition, dx: int, dy: int) -> KeyPosition | None:
        """The nearest key in a direction, measured from cap centres."""
        origin_x = key.x + key.width / 2
        origin_y = key.y + key.height / 2
        best: KeyPosition | None = None
        best_score = float("inf")
        for candidate in self._keys:
            if candidate is key:
                continue
            center_x = candidate.x + candidate.width / 2
            center_y = candidate.y + candidate.height / 2
            along = (center_x - origin_x) * dx + (center_y - origin_y) * dy
            if along <= 0.01:
                continue
            across = abs((center_x - origin_x) * dy) + abs((center_y - origin_y) * dx)
            # Prefer keys straight ahead: sideways drift costs three times as
            # much as distance in the direction being moved.
            score = along + across * 3
            if score < best_score:
                best, best_score = candidate, score
        return best
