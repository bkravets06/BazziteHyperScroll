"""An in-process keyboard that speaks VIA.

Two jobs. It lets the tests drive the real :class:`~keychron_zen.protocol.via.ViaKeyboard`
client end to end without hardware, and it backs ``--demo`` mode so the window
can be opened, explored and screenshotted with nothing plugged in.

It implements the subset of ``via.c`` this app uses, with the same framing and
the same 32-byte packets.
"""

from __future__ import annotations

from . import via
from .hidraw import HidDeviceInfo


class SimulatedKeyboard:
    """A transport that answers VIA commands from in-memory state."""

    def __init__(
        self,
        *,
        rows: int = 6,
        columns: int = 17,
        layers: int = 4,
        macro_count: int = 16,
        macro_buffer_size: int = 896,
        with_color: bool = True,
        firmware_version: int = 0x00010000,
    ):
        self.rows = rows
        self.columns = columns
        self.layers = layers
        self.macro_count = macro_count
        self.with_color = with_color
        self.firmware_version = firmware_version

        self.keymap = bytearray(layers * rows * columns * 2)
        self.macro_buffer = bytearray(macro_buffer_size)
        self.layout_options = 0
        self.pressed: set[tuple[int, int]] = set()
        self.indicated = 0
        self.saved_channels: list[int] = []
        self.lighting: dict[int, dict[int, list[int]]] = {}

        self._reply = b""
        self.written: list[bytes] = []

        self.load_default_keymap()
        self.reset_lighting()
        self._factory_keymap = bytearray(self.keymap)

    # -- state helpers ---------------------------------------------------

    def load_default_keymap(self) -> None:
        """Fill layer 0 with letters and the rest with transparent keys.

        The exact keycodes do not matter; what matters is that demo mode shows
        a keyboard with something on it rather than a grid of blanks.
        """
        self.keymap = bytearray(self.layers * self.rows * self.columns * 2)
        for row in range(self.rows):
            for column in range(self.columns):
                keycode = 0x04 + (row * self.columns + column) % 26
                self._poke(0, row, column, keycode)
        for layer in range(1, self.layers):
            for row in range(self.rows):
                for column in range(self.columns):
                    self._poke(layer, row, column, 0x0001)

    def load_keymap(self, keymap: list[list[list[int]]]) -> None:
        """Replace the stored keymap with ``keymap[layer][row][column]``.

        This also becomes what a keymap reset restores, mirroring real
        firmware, where the reset target is whatever the keyboard was built
        with rather than whatever happens to be in EEPROM.
        """
        for layer, rows in enumerate(keymap[: self.layers]):
            for row, columns in enumerate(rows[: self.rows]):
                for column, keycode in enumerate(columns[: self.columns]):
                    self._poke(layer, row, column, keycode)
        self._factory_keymap = bytearray(self.keymap)

    def restore_factory_keymap(self) -> None:
        self.keymap = bytearray(self._factory_keymap)

    def reset_lighting(self) -> None:
        for channel in (via.CHANNEL_RGB_MATRIX, via.CHANNEL_LED_MATRIX):
            self.lighting[channel] = {
                via.LIGHTING_BRIGHTNESS: [180],
                via.LIGHTING_EFFECT: [4],
                via.LIGHTING_EFFECT_SPEED: [128],
                via.LIGHTING_COLOR: [140, 255],
            }

    def press(self, row: int, column: int) -> None:
        self.pressed.add((row, column))

    def release(self, row: int, column: int) -> None:
        self.pressed.discard((row, column))

    def keycode_at(self, layer: int, row: int, column: int) -> int:
        offset = self._offset(layer, row, column)
        return int.from_bytes(self.keymap[offset : offset + 2], "big")

    def _offset(self, layer: int, row: int, column: int) -> int:
        return ((layer * self.rows + row) * self.columns + column) * 2

    def _poke(self, layer: int, row: int, column: int, keycode: int) -> None:
        offset = self._offset(layer, row, column)
        self.keymap[offset : offset + 2] = keycode.to_bytes(2, "big")

    # -- transport interface ---------------------------------------------

    @property
    def info(self) -> HidDeviceInfo:
        return HidDeviceInfo(
            path="simulated",
            vendor_id=0x3434,
            product_id=0x0AD0,
            product="Keychron K13 Max (demo)",
            bus=0x03,
            report_bytes=via.PACKET_SIZE,
            readable=True,
        )

    def close(self) -> None:
        return None

    def write(self, payload: bytes) -> None:
        packet = payload.ljust(via.PACKET_SIZE, b"\x00")
        self.written.append(bytes(packet))
        self._reply = self._handle(packet)

    def read(self) -> bytes:
        reply, self._reply = self._reply, b""
        return reply

    # -- command dispatch -------------------------------------------------

    def _handle(self, packet: bytes) -> bytes:
        command = packet[0]
        data = bytearray(packet)

        if command == via.CMD_GET_PROTOCOL_VERSION:
            data[1:3] = via.PROTOCOL_VERSION.to_bytes(2, "big")
        elif command == via.CMD_GET_KEYBOARD_VALUE:
            self._get_keyboard_value(data)
        elif command == via.CMD_SET_KEYBOARD_VALUE:
            self._set_keyboard_value(data)
        elif command == via.CMD_DYNAMIC_KEYMAP_GET_LAYER_COUNT:
            data[1] = self.layers
        elif command == via.CMD_DYNAMIC_KEYMAP_GET_KEYCODE:
            keycode = self.keycode_at(data[1], data[2], data[3])
            data[4:6] = keycode.to_bytes(2, "big")
        elif command == via.CMD_DYNAMIC_KEYMAP_SET_KEYCODE:
            self._poke(data[1], data[2], data[3], int.from_bytes(data[4:6], "big"))
        elif command == via.CMD_DYNAMIC_KEYMAP_RESET:
            self.restore_factory_keymap()
        elif command == via.CMD_DYNAMIC_KEYMAP_GET_BUFFER:
            self._get_buffer(data, self.keymap)
        elif command == via.CMD_DYNAMIC_KEYMAP_SET_BUFFER:
            self._set_buffer(data, self.keymap)
        elif command == via.CMD_MACRO_GET_COUNT:
            data[1] = self.macro_count
        elif command == via.CMD_MACRO_GET_BUFFER_SIZE:
            data[1:3] = len(self.macro_buffer).to_bytes(2, "big")
        elif command == via.CMD_MACRO_GET_BUFFER:
            self._get_buffer(data, self.macro_buffer)
        elif command == via.CMD_MACRO_SET_BUFFER:
            self._set_buffer(data, self.macro_buffer)
        elif command == via.CMD_MACRO_RESET:
            self.macro_buffer = bytearray(len(self.macro_buffer))
        elif command == via.CMD_CUSTOM_GET_VALUE:
            self._get_lighting(data)
        elif command == via.CMD_CUSTOM_SET_VALUE:
            self._set_lighting(data)
        elif command == via.CMD_CUSTOM_SAVE:
            self.saved_channels.append(data[1])
        elif command == via.CMD_EEPROM_RESET:
            self.restore_factory_keymap()
            self.macro_buffer = bytearray(len(self.macro_buffer))
            self.reset_lighting()
        else:
            return bytes([via.CMD_UNHANDLED]).ljust(via.PACKET_SIZE, b"\x00")

        return bytes(data)

    def _get_keyboard_value(self, data: bytearray) -> None:
        value_id = data[1]
        if value_id == via.VALUE_FIRMWARE_VERSION:
            data[2:6] = self.firmware_version.to_bytes(4, "big")
        elif value_id == via.VALUE_UPTIME:
            data[2:6] = (12345).to_bytes(4, "big")
        elif value_id == via.VALUE_LAYOUT_OPTIONS:
            data[2:6] = self.layout_options.to_bytes(4, "big")
        elif value_id == via.VALUE_SWITCH_MATRIX_STATE:
            self._switch_matrix_state(data)

    def _switch_matrix_state(self, data: bytearray) -> None:
        offset = data[2]
        row_bytes = (self.columns + 7) // 8
        index = 3
        for row in range(offset, self.rows):
            if index + row_bytes > via.PACKET_SIZE:
                break
            bits = 0
            for column in range(self.columns):
                if (row, column) in self.pressed:
                    bits |= 1 << column
            data[index : index + row_bytes] = bits.to_bytes(row_bytes, "big")
            index += row_bytes

    def _set_keyboard_value(self, data: bytearray) -> None:
        if data[1] == via.VALUE_LAYOUT_OPTIONS:
            self.layout_options = int.from_bytes(data[2:6], "big")
        elif data[1] == via.VALUE_DEVICE_INDICATION:
            self.indicated += 1

    def _get_buffer(self, data: bytearray, source: bytearray) -> None:
        offset = int.from_bytes(data[1:3], "big")
        length = min(data[3], via.CHUNK_SIZE)
        data[4 : 4 + length] = source[offset : offset + length].ljust(length, b"\x00")

    def _set_buffer(self, data: bytearray, target: bytearray) -> None:
        offset = int.from_bytes(data[1:3], "big")
        length = min(data[3], via.CHUNK_SIZE)
        target[offset : offset + length] = data[4 : 4 + length]

    def _get_lighting(self, data: bytearray) -> None:
        channel, value_id = data[1], data[2]
        values = self.lighting.get(channel, {}).get(value_id, [0])
        data[3 : 3 + len(values)] = bytes(values)

    def _set_lighting(self, data: bytearray) -> None:
        channel, value_id = data[1], data[2]
        stored = self.lighting.setdefault(channel, {}).get(value_id, [0])
        self.lighting[channel][value_id] = list(data[3 : 3 + len(stored)])
