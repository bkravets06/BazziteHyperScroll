"""QMK keycode values, names and human labels.

The raw table in ``qmk_keycodes.json`` is generated from QMK's own
``quantum/keycodes.h`` (see ``tools/qmk_keycode_import.py``). This module adds
the parts that table cannot express: how QMK packs composite keycodes such as
``MO(1)`` or ``LCTL(KC_A)`` into 16 bits, how to render one as a keycap legend,
and how to parse the text form back.

Text forms round-trip, which is what makes the exported JSON config readable
and hand-editable.
"""

from __future__ import annotations

import functools
import json
import pathlib
import re
from dataclasses import dataclass

_TABLE_PATH = pathlib.Path(__file__).with_name("qmk_keycodes.json")

KC_NO = 0x0000
KC_TRANSPARENT = 0x0001

# Modifier bit mask used by every mod-carrying keycode (QMK's MOD_* values).
MOD_LCTL = 0x01
MOD_LSFT = 0x02
MOD_LALT = 0x04
MOD_LGUI = 0x08
MOD_RIGHT = 0x10

MOD_NAMES = (
    (MOD_LCTL, "CTL"),
    (MOD_LSFT, "SFT"),
    (MOD_LALT, "ALT"),
    (MOD_LGUI, "GUI"),
)

MOD_LABELS = {"CTL": "Ctrl", "SFT": "Shift", "ALT": "Alt", "GUI": "Super"}


@dataclass(frozen=True)
class Range:
    """One of QMK's keycode ranges, e.g. ``MO(layer)``."""

    name: str
    base: int
    limit: int

    def contains(self, keycode: int) -> bool:
        return self.base <= keycode <= self.limit


@functools.lru_cache(maxsize=1)
def _table() -> dict:
    return json.loads(_TABLE_PATH.read_text())


@functools.lru_cache(maxsize=1)
def keycode_values() -> dict[str, int]:
    """Every canonical QMK keycode name mapped to its value."""
    return dict(_table()["keycodes"])


@functools.lru_cache(maxsize=1)
def keycode_aliases() -> dict[str, str]:
    """QMK's short names (``KC_ESC``) mapped to canonical ones."""
    return dict(_table()["aliases"])


@functools.lru_cache(maxsize=1)
def ranges() -> dict[str, int]:
    return dict(_table()["ranges"])


# QMK's placeholder spellings for "nothing" and "same as the layer below".
# They are legal names but meaningless on their own, so never display them.
_PLACEHOLDERS = re.compile(r"^[_X]+$")


@functools.lru_cache(maxsize=1)
def _names_by_value() -> dict[int, str]:
    """Preferred display name per value.

    QMK gives most keycodes a long canonical name and a short alias
    (``KC_MEDIA_PLAY_PAUSE`` / ``KC_MPLY``). The short one is what keymaps and
    documentation actually use, so prefer the shortest spelling, breaking ties
    alphabetically to keep the choice stable across runs.
    """
    candidates: dict[int, set[str]] = {}
    for name, value in keycode_values().items():
        candidates.setdefault(value, set()).add(name)
    for alias, canonical in keycode_aliases().items():
        value = keycode_values().get(canonical)
        if value is not None and not _PLACEHOLDERS.match(alias):
            candidates[value].add(alias)
    return {
        value: min(names, key=lambda name: (len(name), name))
        for value, names in candidates.items()
    }


@functools.lru_cache(maxsize=1)
def _all_names_by_value() -> dict[int, tuple[str, ...]]:
    """Every spelling QMK has for each value, canonical names first."""
    names: dict[int, list[str]] = {}
    for name, value in keycode_values().items():
        names.setdefault(value, []).append(name)
    for alias, canonical in keycode_aliases().items():
        value = keycode_values().get(canonical)
        if value is not None and not _PLACEHOLDERS.match(alias):
            names[value].append(alias)
    return {value: tuple(entries) for value, entries in names.items()}


def names_for(keycode: int) -> tuple[str, ...]:
    """All QMK spellings of a keycode, for searching."""
    return _all_names_by_value().get(keycode, ())


def _range(name: str) -> Range:
    table = ranges()
    return Range(name, table[name], table[f"{name}_MAX"])


@functools.lru_cache(maxsize=1)
def _layer_ranges() -> dict[str, Range]:
    """Single-argument layer ranges, keyed by their VIA/QMK function name."""
    return {
        "TO": _range("QK_TO"),
        "MO": _range("QK_MOMENTARY"),
        "DF": _range("QK_DEF_LAYER"),
        "TG": _range("QK_TOGGLE_LAYER"),
        "OSL": _range("QK_ONE_SHOT_LAYER"),
        "TT": _range("QK_LAYER_TAP_TOGGLE"),
    }


def modifier_names(mods: int) -> list[str]:
    """Split a mod mask into QMK names such as ``LCTL``/``RSFT``."""
    side = "R" if mods & MOD_RIGHT else "L"
    return [f"{side}{name}" for bit, name in MOD_NAMES if mods & bit]


def modifier_label(mods: int) -> str:
    """Human wording for a mod mask, e.g. ``Ctrl+Shift``."""
    side = "Right " if mods & MOD_RIGHT else ""
    parts = [side + MOD_LABELS[name] for bit, name in MOD_NAMES if mods & bit]
    return "+".join(parts) if parts else "None"


def _mod_text(mods: int) -> str:
    """Render a mod mask as ``MOD_LCTL|MOD_LSFT``."""
    return "|".join("MOD_" + name for name in modifier_names(mods))


def parse_modifiers(text: str) -> int | None:
    """Parse ``LCTL|LSFT`` or ``MOD_LCTL|MOD_LSFT`` into a mod mask."""
    mods = 0
    for token in text.split("|"):
        token = token.strip().upper().removeprefix("MOD_")
        if len(token) != 4 or token[0] not in "LR":
            return None
        for bit, name in MOD_NAMES:
            if token[1:] == name:
                mods |= bit
                break
        else:
            return None
        if token[0] == "R":
            mods |= MOD_RIGHT
    return mods or None


def _has_modifier(mods: int) -> bool:
    """True when a mod mask names at least one real modifier.

    A mask of ``MOD_RIGHT`` alone -- or of nothing at all -- is a legal but
    degenerate encoding that no text form can express. Rendering those as hex
    keeps :func:`name_for` and :func:`parse` exact inverses.
    """
    return bool(mods & (MOD_LCTL | MOD_LSFT | MOD_LALT | MOD_LGUI))


def name_for(keycode: int) -> str:
    """Render a keycode as QMK/VIA text, e.g. ``MO(1)`` or ``LCTL(KC_A)``.

    Anything this build does not recognise comes back as a hex literal so a
    round-trip through export/import never silently rewrites a key.
    """
    keycode &= 0xFFFF

    macro = _range("QK_MACRO")
    if macro.contains(keycode):
        return f"M{keycode - macro.base}"

    simple = _names_by_value().get(keycode)
    if simple is not None:
        return simple

    for function, span in _layer_ranges().items():
        if span.contains(keycode):
            return f"{function}({keycode - span.base})"

    osm = _range("QK_ONE_SHOT_MOD")
    if osm.contains(keycode) and _has_modifier(keycode - osm.base):
        return f"OSM({_mod_text(keycode - osm.base)})"

    layer_mod = _range("QK_LAYER_MOD")
    if layer_mod.contains(keycode):
        offset = keycode - layer_mod.base
        layer, mods = (offset >> 5) & 0x0F, offset & 0x1F
        if _has_modifier(mods):
            return f"LM({layer},{_mod_text(mods)})"
        return f"0x{keycode:04X}"

    layer_tap = _range("QK_LAYER_TAP")
    if layer_tap.contains(keycode):
        layer = (keycode >> 8) & 0x0F
        return f"LT({layer},{name_for(keycode & 0xFF)})"

    mod_tap = _range("QK_MOD_TAP")
    if mod_tap.contains(keycode):
        mods = (keycode >> 8) & 0x1F
        if not _has_modifier(mods):
            return f"0x{keycode:04X}"
        names = modifier_names(mods)
        inner = name_for(keycode & 0xFF)
        if len(names) == 1:
            return f"{names[0]}_T({inner})"
        return f"MT({_mod_text(mods)},{inner})"

    if _range("QK_MODS").contains(keycode):
        mods = (keycode >> 8) & 0x1F
        if not _has_modifier(mods):
            return f"0x{keycode:04X}"
        result = name_for(keycode & 0xFF)
        for name in reversed(modifier_names(mods)):
            result = f"{name}({result})"
        return result

    return f"0x{keycode:04X}"


_CALL = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\((.*)\)$", re.DOTALL)
_MACRO = re.compile(r"^M(\d{1,3})$")


def parse(text: str) -> int:
    """Parse the text form produced by :func:`name_for`.

    Raises :class:`ValueError` on anything unrecognised, so importing a
    hand-edited config fails loudly instead of writing a wrong key.
    """
    text = text.strip()
    if not text:
        raise ValueError("empty keycode")

    if text.lower().startswith("0x"):
        try:
            value = int(text, 16)
        except ValueError as exc:
            raise ValueError(f"bad hex keycode {text!r}") from exc
        if not 0 <= value <= 0xFFFF:
            raise ValueError(f"keycode {text!r} out of range")
        return value

    # A few QMK names are mixed case (the MIDI notes), so try verbatim first.
    for candidate in (text, text.upper()):
        if candidate in keycode_values():
            return keycode_values()[candidate]
        if candidate in keycode_aliases():
            return keycode_values()[keycode_aliases()[candidate]]
    upper = text.upper()

    if match := _MACRO.match(upper):
        index = int(match.group(1))
        macro = _range("QK_MACRO")
        if macro.base + index > macro.limit:
            raise ValueError(f"macro index {index} out of range")
        return macro.base + index

    match = _CALL.match(text)
    if not match:
        raise ValueError(f"unknown keycode {text!r}")
    function, argument = match.group(1).upper(), match.group(2).strip()

    if function in _layer_ranges():
        span = _layer_ranges()[function]
        layer = _parse_int(argument, function)
        if span.base + layer > span.limit:
            raise ValueError(f"{function}: layer {layer} out of range")
        return span.base + layer

    if function == "OSM":
        mods = parse_modifiers(argument)
        if mods is None:
            raise ValueError(f"OSM: bad modifiers {argument!r}")
        return _range("QK_ONE_SHOT_MOD").base + mods

    if function == "LM":
        layer_text, _, mod_text = argument.partition(",")
        mods = parse_modifiers(mod_text)
        if mods is None:
            raise ValueError(f"LM: bad modifiers {mod_text!r}")
        layer = _parse_int(layer_text, "LM")
        if layer > 0x0F:
            raise ValueError(f"LM: layer {layer} out of range")
        return _range("QK_LAYER_MOD").base + (layer << 5) + mods

    if function == "LT":
        layer_text, _, inner_text = argument.partition(",")
        layer = _parse_int(layer_text, "LT")
        if layer > 0x0F:
            raise ValueError(f"LT: layer {layer} out of range")
        return _range("QK_LAYER_TAP").base + (layer << 8) + _basic(inner_text)

    if function == "MT":
        mod_text, _, inner_text = argument.partition(",")
        mods = parse_modifiers(mod_text)
        if mods is None:
            raise ValueError(f"MT: bad modifiers {mod_text!r}")
        return _range("QK_MOD_TAP").base + (mods << 8) + _basic(inner_text)

    if function.endswith("_T"):
        mods = parse_modifiers(function[:-2])
        if mods is None:
            raise ValueError(f"unknown keycode {text!r}")
        return _range("QK_MOD_TAP").base + (mods << 8) + _basic(argument)

    mods = parse_modifiers(function)
    if mods is not None:
        inner = parse(argument)
        if _range("QK_MODS").contains(inner):
            # Nested modifiers stack, e.g. LCTL(LSFT(KC_A)).
            mods |= (inner >> 8) & 0x1F
            inner &= 0xFF
        elif inner > 0xFF:
            raise ValueError(f"{function}: {argument!r} is not a basic keycode")
        # The mod mask occupies bits 8-12; QK_MODS is simply mods==1, so unlike
        # the other ranges there is no base to add here.
        return (mods << 8) | inner

    raise ValueError(f"unknown keycode {text!r}")


def _parse_int(text: str, function: str) -> int:
    try:
        return int(text.strip(), 0)
    except ValueError as exc:
        raise ValueError(f"{function}: expected a number, got {text!r}") from exc


def _basic(text: str) -> int:
    keycode = parse(text)
    if keycode > 0xFF:
        raise ValueError(f"{text.strip()!r} is not a basic keycode")
    return keycode
