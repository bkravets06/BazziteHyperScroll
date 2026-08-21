"""The VIA protocol, as spoken by QMK's ``quantum/via.c``.

Every exchange is a fixed 32-byte report: byte 0 is the command id, the rest is
the payload, and the keyboard replies with the same command id followed by its
answer. Commands the firmware does not implement come back as ``0xFF``.

Command and channel ids here match QMK protocol version 12, which is what the
Keychron Max boards ship.
"""

from __future__ import annotations

from dataclasses import dataclass

PROTOCOL_VERSION = 0x000C
PACKET_SIZE = 32

# The largest payload a buffer command can move in one packet: 32 bytes less
# the command id, the two offset bytes and the length byte.
CHUNK_SIZE = 28

# The command, value and channel enums below are transcribed in full from
# quantum/via.h so the protocol is documented in one place, even where this
# app has no use for a particular id.

# via_command_id
CMD_GET_PROTOCOL_VERSION = 0x01
CMD_GET_KEYBOARD_VALUE = 0x02
CMD_SET_KEYBOARD_VALUE = 0x03
CMD_DYNAMIC_KEYMAP_GET_KEYCODE = 0x04
CMD_DYNAMIC_KEYMAP_SET_KEYCODE = 0x05
CMD_DYNAMIC_KEYMAP_RESET = 0x06
CMD_CUSTOM_SET_VALUE = 0x07
CMD_CUSTOM_GET_VALUE = 0x08
CMD_CUSTOM_SAVE = 0x09
CMD_EEPROM_RESET = 0x0A
CMD_BOOTLOADER_JUMP = 0x0B
CMD_MACRO_GET_COUNT = 0x0C
CMD_MACRO_GET_BUFFER_SIZE = 0x0D
CMD_MACRO_GET_BUFFER = 0x0E
CMD_MACRO_SET_BUFFER = 0x0F
CMD_MACRO_RESET = 0x10
CMD_DYNAMIC_KEYMAP_GET_LAYER_COUNT = 0x11
CMD_DYNAMIC_KEYMAP_GET_BUFFER = 0x12
CMD_DYNAMIC_KEYMAP_SET_BUFFER = 0x13
CMD_UNHANDLED = 0xFF

# via_keyboard_value_id
VALUE_UPTIME = 0x01
VALUE_LAYOUT_OPTIONS = 0x02
VALUE_SWITCH_MATRIX_STATE = 0x03
VALUE_FIRMWARE_VERSION = 0x04
VALUE_DEVICE_INDICATION = 0x05

# via_channel_id
CHANNEL_BACKLIGHT = 1
CHANNEL_RGBLIGHT = 2
CHANNEL_RGB_MATRIX = 3
CHANNEL_AUDIO = 4
CHANNEL_LED_MATRIX = 5

CHANNEL_FOR_LIGHTING = {
    "rgb_matrix": CHANNEL_RGB_MATRIX,
    "led_matrix": CHANNEL_LED_MATRIX,
    "backlight": CHANNEL_BACKLIGHT,
    "rgblight": CHANNEL_RGBLIGHT,
}

# Lighting value ids. RGB and single-colour channels agree on 1-3; only the
# RGB channels have a colour.
LIGHTING_BRIGHTNESS = 1
LIGHTING_EFFECT = 2
LIGHTING_EFFECT_SPEED = 3
LIGHTING_COLOR = 4


class ViaError(Exception):
    """A VIA command failed or was rejected by the firmware."""


class UnsupportedCommandError(ViaError):
    """The firmware answered ``id_unhandled`` for this command."""


@dataclass(frozen=True)
class LightingState:
    """The lighting settings a keyboard currently has applied."""

    brightness: int
    effect: int
    speed: int
    hue: int | None = None
    saturation: int | None = None

    @property
    def has_color(self) -> bool:
        return self.hue is not None


class ViaKeyboard:
    """Talks VIA over an open raw-HID transport.

    ``transport`` only has to provide ``write(bytes)`` and ``read() -> bytes``,
    which keeps the simulated keyboard in :mod:`keychron_zen.protocol.simulator`
    a drop-in replacement for real hardware.
    """

    # If the keyboard sends something unexpected, read past it rather than
    # failing: a stale reply from a previous timed-out command must not
    # desynchronise every command after it.
    _MAX_RESYNC_READS = 4

    def __init__(self, transport):
        self.transport = transport

    # -- framing ---------------------------------------------------------

    def command(self, command_id: int, payload: bytes = b"") -> bytes:
        """Send one command and return the payload of its reply."""
        request = bytes([command_id]) + payload
        if len(request) > PACKET_SIZE:
            raise ViaError(f"command 0x{command_id:02X} payload is too long")
        self.transport.write(request)

        for _ in range(self._MAX_RESYNC_READS):
            reply = self.transport.read()
            if not reply:
                continue
            if reply[0] == CMD_UNHANDLED:
                raise UnsupportedCommandError(
                    f"the keyboard does not support command 0x{command_id:02X}"
                )
            if reply[0] == command_id:
                return reply[1:]
        raise ViaError(f"no reply to command 0x{command_id:02X}")

    # -- identification --------------------------------------------------

    def protocol_version(self) -> int:
        reply = self.command(CMD_GET_PROTOCOL_VERSION)
        return int.from_bytes(reply[:2], "big")

    def firmware_version(self) -> int:
        reply = self.command(CMD_GET_KEYBOARD_VALUE, bytes([VALUE_FIRMWARE_VERSION]))
        return int.from_bytes(reply[1:5], "big")

    def indicate(self) -> None:
        """Ask the keyboard to flash its LEDs, so you can tell which one it is."""
        self.command(CMD_SET_KEYBOARD_VALUE, bytes([VALUE_DEVICE_INDICATION, 0]))

    # -- keymap ----------------------------------------------------------

    def layer_count(self) -> int:
        return self.command(CMD_DYNAMIC_KEYMAP_GET_LAYER_COUNT)[0]

    def get_keycode(self, layer: int, row: int, column: int) -> int:
        reply = self.command(
            CMD_DYNAMIC_KEYMAP_GET_KEYCODE, bytes([layer, row, column])
        )
        return int.from_bytes(reply[3:5], "big")

    def set_keycode(self, layer: int, row: int, column: int, keycode: int) -> None:
        self.command(
            CMD_DYNAMIC_KEYMAP_SET_KEYCODE,
            bytes([layer, row, column]) + keycode.to_bytes(2, "big"),
        )

    def read_keymap(self, layers: int, rows: int, columns: int) -> list[list[list[int]]]:
        """Read the whole keymap as ``keymap[layer][row][column]``."""
        raw = self._read_buffer(CMD_DYNAMIC_KEYMAP_GET_BUFFER, layers * rows * columns * 2)
        keymap = []
        offset = 0
        for _ in range(layers):
            layer = []
            for _ in range(rows):
                layer.append(
                    [
                        int.from_bytes(raw[offset + i * 2 : offset + i * 2 + 2], "big")
                        for i in range(columns)
                    ]
                )
                offset += columns * 2
            keymap.append(layer)
        return keymap

    def write_keymap(self, keymap: list[list[list[int]]]) -> None:
        """Write a whole keymap in one pass, chunked over the buffer command."""
        raw = bytearray()
        for layer in keymap:
            for row in layer:
                for keycode in row:
                    raw += keycode.to_bytes(2, "big")
        self._write_buffer(CMD_DYNAMIC_KEYMAP_SET_BUFFER, bytes(raw))

    def reset_keymap(self) -> None:
        """Restore the keymap the firmware was built with."""
        self.command(CMD_DYNAMIC_KEYMAP_RESET)

    # -- macros ----------------------------------------------------------

    def macro_count(self) -> int:
        return self.command(CMD_MACRO_GET_COUNT)[0]

    def macro_buffer_size(self) -> int:
        reply = self.command(CMD_MACRO_GET_BUFFER_SIZE)
        return int.from_bytes(reply[:2], "big")

    def read_macro_buffer(self, size: int) -> bytes:
        return self._read_buffer(CMD_MACRO_GET_BUFFER, size)

    def write_macro_buffer(self, data: bytes) -> None:
        self._write_buffer(CMD_MACRO_SET_BUFFER, data)

    def reset_macros(self) -> None:
        self.command(CMD_MACRO_RESET)

    # -- lighting --------------------------------------------------------

    def get_lighting(self, channel: int, with_color: bool) -> LightingState:
        brightness = self._get_lighting_value(channel, LIGHTING_BRIGHTNESS)[0]
        effect = self._get_lighting_value(channel, LIGHTING_EFFECT)[0]
        speed = self._get_lighting_value(channel, LIGHTING_EFFECT_SPEED)[0]
        hue = saturation = None
        if with_color:
            color = self._get_lighting_value(channel, LIGHTING_COLOR)
            hue, saturation = color[0], color[1]
        return LightingState(brightness, effect, speed, hue, saturation)

    def set_brightness(self, channel: int, value: int) -> None:
        self._set_lighting_value(channel, LIGHTING_BRIGHTNESS, bytes([value & 0xFF]))

    def set_effect(self, channel: int, value: int) -> None:
        self._set_lighting_value(channel, LIGHTING_EFFECT, bytes([value & 0xFF]))

    def set_speed(self, channel: int, value: int) -> None:
        self._set_lighting_value(channel, LIGHTING_EFFECT_SPEED, bytes([value & 0xFF]))

    def set_color(self, channel: int, hue: int, saturation: int) -> None:
        self._set_lighting_value(
            channel, LIGHTING_COLOR, bytes([hue & 0xFF, saturation & 0xFF])
        )

    def save_lighting(self, channel: int) -> None:
        """Persist the channel's live settings to EEPROM."""
        self.command(CMD_CUSTOM_SAVE, bytes([channel]))

    def _get_lighting_value(self, channel: int, value_id: int) -> bytes:
        reply = self.command(CMD_CUSTOM_GET_VALUE, bytes([channel, value_id]))
        return reply[2:]

    def _set_lighting_value(self, channel: int, value_id: int, data: bytes) -> None:
        self.command(CMD_CUSTOM_SET_VALUE, bytes([channel, value_id]) + data)

    # -- key tester ------------------------------------------------------

    def switch_matrix_state(self, rows: int, columns: int) -> list[list[bool]]:
        """Read which switches are physically down, straight from the matrix.

        This is how the key tester sees presses without needing window focus or
        caring what the key is mapped to.
        """
        row_bytes = (columns + 7) // 8
        per_request = CHUNK_SIZE // row_bytes
        state: list[list[bool]] = []
        for offset in range(0, rows, per_request):
            reply = self.command(
                CMD_GET_KEYBOARD_VALUE, bytes([VALUE_SWITCH_MATRIX_STATE, offset])
            )
            payload = reply[2:]
            for index in range(min(per_request, rows - offset)):
                chunk = payload[index * row_bytes : (index + 1) * row_bytes]
                if len(chunk) < row_bytes:
                    break
                bits = int.from_bytes(chunk, "big")
                state.append([bool(bits >> column & 1) for column in range(columns)])
        return state

    # -- maintenance -----------------------------------------------------

    def reset_eeprom(self) -> None:
        """Clear all VIA settings and restore the firmware defaults."""
        self.command(CMD_EEPROM_RESET)

    # -- chunked buffers -------------------------------------------------

    def _read_buffer(self, command_id: int, size: int) -> bytes:
        out = bytearray()
        while len(out) < size:
            length = min(CHUNK_SIZE, size - len(out))
            reply = self.command(
                command_id, len(out).to_bytes(2, "big") + bytes([length])
            )
            chunk = reply[3 : 3 + length]
            if len(chunk) < length:
                raise ViaError(
                    f"short reply for command 0x{command_id:02X} at offset {len(out)}"
                )
            out += chunk
        return bytes(out)

    def _write_buffer(self, command_id: int, data: bytes) -> None:
        for offset in range(0, len(data), CHUNK_SIZE):
            chunk = data[offset : offset + CHUNK_SIZE]
            self.command(
                command_id,
                offset.to_bytes(2, "big") + bytes([len(chunk)]) + chunk,
            )
