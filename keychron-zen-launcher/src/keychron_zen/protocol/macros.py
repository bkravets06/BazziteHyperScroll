"""VIA dynamic macro encoding.

The keyboard stores all macros in one flat buffer of null-terminated strings.
Plain bytes are typed literally; ``0x01`` introduces a directive:

===============================  ====================================
``01 01 <keycode>``              tap a key
``01 02 <keycode>``              hold a key down
``01 03 <keycode>``              release a key
``01 04 <digits> '|'``           wait, in milliseconds
===============================  ====================================

This matches ``dynamic_keymap_macro_send`` in QMK, which is what actually
replays the buffer, so the encoding here is checked against the firmware
rather than against VIA's UI.

The text form (``Hello{+KC_LSFT}a{-KC_LSFT}{250}``) is the same shape VIA and
Keychron Launcher use, so muscle memory carries over.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from . import keycodes

SS_QMK_PREFIX = 0x01
SS_TAP_CODE = 0x01
SS_DOWN_CODE = 0x02
SS_UP_CODE = 0x03
SS_DELAY_CODE = 0x04

# QMK's replay loop gives up if a delay runs past four digits.
MAX_DELAY_MS = 9999

# Bytes that may appear literally: printable ASCII plus tab and newline.
_LITERAL = set(range(0x20, 0x7F)) | {0x09, 0x0A}


class MacroError(ValueError):
    """Raised when a macro cannot be encoded or decoded."""


@dataclass(frozen=True)
class Text:
    """Literal characters, typed via QMK's ``send_string``."""

    value: str


@dataclass(frozen=True)
class Tap:
    keycode: int


@dataclass(frozen=True)
class Down:
    keycode: int


@dataclass(frozen=True)
class Up:
    keycode: int


@dataclass(frozen=True)
class Delay:
    milliseconds: int


Action = Text | Tap | Down | Up | Delay

_CODES: dict[int, type] = {SS_TAP_CODE: Tap, SS_DOWN_CODE: Down, SS_UP_CODE: Up}
_PREFIXES: dict[type, int] = {Tap: SS_TAP_CODE, Down: SS_DOWN_CODE, Up: SS_UP_CODE}


def decode(data: bytes) -> list[Action]:
    """Decode one macro's bytes (without its null terminator)."""
    actions: list[Action] = []
    literal: list[str] = []
    index = 0

    def flush() -> None:
        if literal:
            actions.append(Text("".join(literal)))
            literal.clear()

    while index < len(data):
        byte = data[index]
        if byte != SS_QMK_PREFIX:
            literal.append(chr(byte))
            index += 1
            continue

        flush()
        if index + 1 >= len(data):
            raise MacroError("macro ends in the middle of a directive")
        code = data[index + 1]
        if code in _CODES:
            if index + 2 >= len(data):
                raise MacroError("macro ends before its keycode")
            actions.append(_CODES[code](data[index + 2]))
            index += 3
        elif code == SS_DELAY_CODE:
            end = data.find(b"|", index + 2)
            if end < 0:
                raise MacroError("delay is missing its '|' terminator")
            digits = data[index + 2 : end].decode("ascii", "replace")
            if not digits.isdigit():
                raise MacroError(f"delay {digits!r} is not a number")
            actions.append(Delay(int(digits)))
            index = end + 1
        else:
            raise MacroError(f"unknown macro directive 0x{code:02X}")

    flush()
    return actions


def encode(actions: list[Action]) -> bytes:
    """Encode one macro. The caller adds the null terminator."""
    out = bytearray()
    for action in actions:
        if isinstance(action, Text):
            for character in action.value:
                point = ord(character)
                if point not in _LITERAL:
                    raise MacroError(
                        f"{character!r} cannot be stored in a macro; "
                        "use a {KC_...} directive instead"
                    )
                out.append(point)
        elif isinstance(action, Delay):
            if not 0 <= action.milliseconds <= MAX_DELAY_MS:
                raise MacroError(f"delay must be 0-{MAX_DELAY_MS} ms")
            out += bytes([SS_QMK_PREFIX, SS_DELAY_CODE])
            out += str(action.milliseconds).encode("ascii") + b"|"
        else:
            prefix = _PREFIXES[type(action)]
            if not 0 < action.keycode <= 0xFF:
                raise MacroError(
                    f"{keycodes.name_for(action.keycode)} is not a basic keycode"
                )
            out += bytes([SS_QMK_PREFIX, prefix, action.keycode])
    return bytes(out)


def split_buffer(buffer: bytes, count: int) -> list[list[Action]]:
    """Split the keyboard's macro buffer into ``count`` macros."""
    macros: list[list[Action]] = []
    start = 0
    for _ in range(count):
        end = buffer.find(b"\x00", start)
        if end < 0:
            macros.append([])
            continue
        macros.append(decode(buffer[start:end]))
        start = end + 1
    return macros


def join_buffer(macros: list[list[Action]], size: int) -> bytes:
    """Pack macros back into a buffer of exactly ``size`` bytes."""
    out = bytearray()
    for macro in macros:
        out += encode(macro) + b"\x00"
    if len(out) > size:
        raise MacroError(
            f"macros need {len(out)} bytes but the keyboard only has {size}"
        )
    return bytes(out).ljust(size, b"\x00")


_DIRECTIVE = re.compile(r"\{([^{}]*)\}")


def to_text(actions: list[Action]) -> str:
    """Render a macro in the ``Hi{+KC_LSFT}a{-KC_LSFT}{250}`` form."""
    parts: list[str] = []
    for action in actions:
        if isinstance(action, Text):
            parts.append(action.value.replace("\\", "\\\\").replace("{", "\\{"))
        elif isinstance(action, Delay):
            parts.append(f"{{{action.milliseconds}}}")
        elif isinstance(action, Tap):
            parts.append(f"{{{keycodes.name_for(action.keycode)}}}")
        elif isinstance(action, Down):
            parts.append(f"{{+{keycodes.name_for(action.keycode)}}}")
        else:
            parts.append(f"{{-{keycodes.name_for(action.keycode)}}}")
    return "".join(parts)


def from_text(text: str) -> list[Action]:
    """Parse the text form back into actions."""
    actions: list[Action] = []
    literal: list[str] = []
    index = 0

    def flush() -> None:
        if literal:
            actions.append(Text("".join(literal)))
            literal.clear()

    while index < len(text):
        character = text[index]
        if character == "\\" and index + 1 < len(text):
            literal.append(text[index + 1])
            index += 2
            continue
        if character == "{":
            match = _DIRECTIVE.match(text, index)
            if not match:
                raise MacroError("unclosed '{' in macro; write '\\{' for a literal brace")
            flush()
            actions.append(_parse_directive(match.group(1)))
            index = match.end()
            continue
        literal.append(character)
        index += 1

    flush()
    return actions


def _parse_directive(body: str) -> Action:
    body = body.strip()
    if not body:
        raise MacroError("empty {} in macro")
    if body.isdigit():
        delay = int(body)
        if delay > MAX_DELAY_MS:
            raise MacroError(f"delay must be 0-{MAX_DELAY_MS} ms")
        return Delay(delay)
    if body[0] in "+-":
        keycode = _basic(body[1:])
        return Down(keycode) if body[0] == "+" else Up(keycode)
    return Tap(_basic(body))


def _basic(name: str) -> int:
    try:
        keycode = keycodes.parse(name)
    except ValueError as exc:
        # Surface every macro problem as a MacroError so the editor can show
        # one consistent message.
        raise MacroError(str(exc)) from exc
    if not 0 < keycode <= 0xFF:
        raise MacroError(
            f"{name.strip()} cannot be used inside a macro; macros can only "
            "tap, hold and release basic keys"
        )
    return keycode
