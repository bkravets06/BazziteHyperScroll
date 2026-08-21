"""Discovering keyboards and holding an open session with one.

This is the layer both the GUI and the CLI sit on. Keymap edits are written
through to the keyboard immediately, the way VIA and Keychron's own launcher
behave -- there is no separate "flash" step and nothing is lost if the app is
closed.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..protocol import macros, via
from ..protocol.hidraw import HidDeviceInfo, HidRawDevice, enumerate_raw_hid
from ..protocol.simulator import SimulatedKeyboard
from . import definitions
from .definitions import Definition, Variant


@dataclass(frozen=True)
class Discovery:
    """A raw-HID interface found on the system, with its definition if known."""

    info: HidDeviceInfo
    definition: Definition | None
    variant: Variant | None

    @property
    def title(self) -> str:
        if self.definition and self.variant:
            return f"{self.definition.name} — {self.variant.title}"
        return self.info.product

    @property
    def problem(self) -> str | None:
        """Why this device cannot be configured, if it cannot."""
        if not self.info.readable:
            return (
                f"No permission to open {self.info.node}. Install the udev rule "
                "(see the README), then unplug and replug the keyboard."
            )
        if self.info.is_bluetooth:
            return (
                "This keyboard is connected over Bluetooth. Keychron's firmware "
                "only accepts configuration over the USB cable — switch the side "
                "toggle to the cable position and plug it in."
            )
        return None

    @property
    def usable(self) -> bool:
        return self.problem is None


def discover(known_only: bool = False) -> list[Discovery]:
    """Find every keyboard on the system that speaks VIA.

    Unknown devices are still returned: their macros and lighting can be
    configured even without a layout definition, and saying "found something
    but I do not know its layout" beats saying nothing at all.
    """
    results = []
    for info in enumerate_raw_hid():
        match = definitions.find(info.vendor_id, info.product_id)
        if match is None and known_only:
            continue
        definition, variant = match if match else (None, None)
        results.append(Discovery(info, definition, variant))
    return results


class Keyboard:
    """An open configuration session with one keyboard."""

    def __init__(
        self,
        transport,
        info: HidDeviceInfo,
        definition: Definition | None = None,
        variant: Variant | None = None,
    ):
        self.transport = transport
        self.info = info
        self.definition = definition
        self.variant = variant
        self.via = via.ViaKeyboard(transport)

        self.protocol_version = 0
        self.firmware_version = 0
        self.layer_count = 0
        self.keymap: list[list[list[int]]] = []
        self.macros: list[list[macros.Action]] = []
        self.macro_buffer_size = 0
        self.lighting: via.LightingState | None = None

    # -- lifecycle -------------------------------------------------------

    @classmethod
    def open(cls, discovery: Discovery, timeout: float = 1.0) -> "Keyboard":
        device = HidRawDevice(discovery.info, timeout=timeout)
        keyboard = cls(device, discovery.info, discovery.definition, discovery.variant)
        keyboard.refresh()
        return keyboard

    @classmethod
    def demo(cls) -> "Keyboard":
        """A simulated K13 Max, for trying the app with nothing plugged in."""
        match = definitions.find(0x3434, 0x0AD0)
        definition, variant = match if match else (None, None)
        transport = SimulatedKeyboard(
            rows=definition.rows if definition else 6,
            columns=definition.columns if definition else 17,
        )
        if definition and variant:
            # Start demo mode from the real stock keymap so the window shows a
            # believable keyboard rather than a grid of placeholder letters.
            transport.load_keymap(definition.default_keymap(variant))
        keyboard = cls(transport, transport.info, definition, variant)
        keyboard.refresh()
        return keyboard

    def close(self) -> None:
        self.transport.close()

    @property
    def is_demo(self) -> bool:
        return isinstance(self.transport, SimulatedKeyboard)

    # -- shape -----------------------------------------------------------

    @property
    def rows(self) -> int:
        return self.definition.rows if self.definition else 0

    @property
    def columns(self) -> int:
        return self.definition.columns if self.definition else 0

    @property
    def has_layout(self) -> bool:
        return self.definition is not None and self.variant is not None

    @property
    def lighting_channel(self) -> int | None:
        if self.variant is None:
            return None
        return via.CHANNEL_FOR_LIGHTING.get(self.variant.lighting.kind)

    @property
    def custom_keycode_labels(self) -> dict[int, str]:
        """Keyboard-specific keycodes, for rendering legends."""
        if self.variant is None:
            return {}
        return {entry.value: entry.label for entry in self.variant.custom_keycodes}

    # -- loading ---------------------------------------------------------

    def refresh(self) -> None:
        """Read the keyboard's current state into memory."""
        self.protocol_version = self.via.protocol_version()
        try:
            self.firmware_version = self.via.firmware_version()
        except via.ViaError:
            self.firmware_version = 0
        self.layer_count = self.via.layer_count()
        self.reload_keymap()
        self.reload_macros()
        self.reload_lighting()

    def reload_keymap(self) -> None:
        if self.has_layout:
            self.keymap = self.via.read_keymap(self.layer_count, self.rows, self.columns)
        else:
            self.keymap = []

    def reload_macros(self) -> None:
        try:
            count = self.via.macro_count()
            self.macro_buffer_size = self.via.macro_buffer_size()
            buffer = self.via.read_macro_buffer(self.macro_buffer_size)
            self.macros = macros.split_buffer(buffer, count)
        except (via.ViaError, macros.MacroError):
            self.macros = []
            self.macro_buffer_size = 0

    def reload_lighting(self) -> None:
        channel = self.lighting_channel
        if channel is None or self.variant is None:
            self.lighting = None
            return
        try:
            self.lighting = self.via.get_lighting(channel, self.variant.lighting.has_color)
        except via.ViaError:
            self.lighting = None

    # -- keymap ----------------------------------------------------------

    def keycode(self, layer: int, row: int, column: int) -> int:
        return self.keymap[layer][row][column]

    def default_keycode(self, layer: int, row: int, column: int) -> int | None:
        """What the firmware ships on this key, if the definition knows."""
        if self.definition is None or self.variant is None:
            return None
        grid = self.definition.default_keymap(self.variant)
        if layer >= len(grid):
            return None
        return grid[layer][row][column]

    def changed_cells(self, layer: int) -> set[tuple[int, int]]:
        """Cells on a layer that differ from the stock keymap."""
        if self.definition is None or self.variant is None or not self.keymap:
            return set()
        grid = self.definition.default_keymap(self.variant)
        if layer >= len(grid):
            return set()
        return {
            (row, column)
            for row in range(self.rows)
            for column in range(self.columns)
            if self.keymap[layer][row][column] != grid[layer][row][column]
        }

    def set_keycode(self, layer: int, row: int, column: int, keycode: int) -> None:
        """Remap one key, writing it through to the keyboard."""
        self.via.set_keycode(layer, row, column, keycode)
        self.keymap[layer][row][column] = keycode

    def reset_keymap(self) -> None:
        self.via.reset_keymap()
        self.reload_keymap()

    # -- macros ----------------------------------------------------------

    def set_macros(self, entries: list[list[macros.Action]]) -> None:
        """Write every macro slot at once; the buffer is stored as a whole."""
        buffer = macros.join_buffer(entries, self.macro_buffer_size)
        self.via.write_macro_buffer(buffer)
        self.macros = entries

    def reset_macros(self) -> None:
        self.via.reset_macros()
        self.reload_macros()

    # -- lighting --------------------------------------------------------

    def apply_lighting(self, state: via.LightingState, save: bool = True) -> None:
        """Push lighting settings to the keyboard, optionally persisting them."""
        channel = self.lighting_channel
        if channel is None:
            return
        current = self.lighting
        if current is None or state.brightness != current.brightness:
            self.via.set_brightness(channel, state.brightness)
        if current is None or state.effect != current.effect:
            self.via.set_effect(channel, state.effect)
        if current is None or state.speed != current.speed:
            self.via.set_speed(channel, state.speed)
        if state.has_color and (
            current is None
            or (state.hue, state.saturation) != (current.hue, current.saturation)
        ):
            self.via.set_color(channel, state.hue or 0, state.saturation or 0)
        if save:
            self.via.save_lighting(channel)
        self.lighting = state

    # -- key tester ------------------------------------------------------

    def matrix_state(self) -> list[list[bool]]:
        if not self.has_layout:
            return []
        return self.via.switch_matrix_state(self.rows, self.columns)

    # -- maintenance -----------------------------------------------------

    def indicate(self) -> None:
        self.via.indicate()

    def reset_eeprom(self) -> None:
        """Wipe every VIA setting and reload. Undoes all customisation."""
        self.via.reset_eeprom()
        self.refresh()

    # -- description -----------------------------------------------------

    @property
    def title(self) -> str:
        if self.definition and self.variant:
            return f"{self.definition.name} — {self.variant.title}"
        return self.info.product

    @property
    def firmware_text(self) -> str:
        if not self.firmware_version:
            return "unreported"
        major = (self.firmware_version >> 24) & 0xFF
        minor = (self.firmware_version >> 16) & 0xFF
        patch = self.firmware_version & 0xFFFF
        return f"{major}.{minor}.{patch}"
