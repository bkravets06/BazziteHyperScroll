"""Human-facing names for keycodes: keycap legends and picker categories.

QMK's own names (``KC_BACKSPACE``, ``KC_MEDIA_PLAY_PAUSE``) are precise but
unreadable on a 40-pixel keycap, so this module carries the curated legends and
the grouped catalogue the key picker presents. Only the entries that need a
nicer form are listed; everything else falls back to a cleaned-up QMK name.
"""

from __future__ import annotations

import functools
import re

from . import keycodes

TRANSPARENT_GLYPH = "▽"

# Keycap legends. Values are ``(main, sub)``; ``sub`` is the small second line.
LEGENDS: dict[str, tuple[str, str]] = {
    "KC_NO": ("", ""),
    "KC_TRNS": (TRANSPARENT_GLYPH, ""),
    "KC_GRV": ("`", "~"),
    "KC_1": ("1", "!"),
    "KC_2": ("2", "@"),
    "KC_3": ("3", "#"),
    "KC_4": ("4", "$"),
    "KC_5": ("5", "%"),
    "KC_6": ("6", "^"),
    "KC_7": ("7", "&"),
    "KC_8": ("8", "*"),
    "KC_9": ("9", "("),
    "KC_0": ("0", ")"),
    "KC_MINS": ("-", "_"),
    "KC_EQL": ("=", "+"),
    "KC_LBRC": ("[", "{"),
    "KC_RBRC": ("]", "}"),
    "KC_BSLS": ("\\", "|"),
    "KC_SCLN": (";", ":"),
    "KC_QUOT": ("'", '"'),
    "KC_COMM": (",", "<"),
    "KC_DOT": (".", ">"),
    "KC_SLSH": ("/", "?"),
    "KC_NUHS": ("#", "~"),
    "KC_NUBS": ("\\", "|"),
    "KC_ESC": ("Esc", ""),
    "KC_TAB": ("Tab", ""),
    "KC_CAPS": ("Caps", ""),
    "KC_ENT": ("Enter", ""),
    "KC_BSPC": ("Bksp", ""),
    "KC_SPC": ("Space", ""),
    "KC_DEL": ("Del", ""),
    "KC_INS": ("Ins", ""),
    "KC_HOME": ("Home", ""),
    "KC_END": ("End", ""),
    "KC_PGUP": ("PgUp", ""),
    "KC_PGDN": ("PgDn", ""),
    "KC_PSCR": ("PrtSc", ""),
    "KC_SCRL": ("ScrLk", ""),
    "KC_PAUS": ("Pause", ""),
    "KC_APP": ("Menu", ""),
    "KC_UP": ("↑", ""),
    "KC_DOWN": ("↓", ""),
    "KC_LEFT": ("←", ""),
    "KC_RGHT": ("→", ""),
    "KC_LCTL": ("Ctrl", "L"),
    "KC_RCTL": ("Ctrl", "R"),
    "KC_LSFT": ("Shift", "L"),
    "KC_RSFT": ("Shift", "R"),
    "KC_LALT": ("Alt", "L"),
    "KC_RALT": ("Alt", "R"),
    "KC_LGUI": ("Super", "L"),
    "KC_RGUI": ("Super", "R"),
    "KC_NUM": ("Num", ""),
    "KC_PSLS": ("/", "num"),
    "KC_PAST": ("*", "num"),
    "KC_PMNS": ("-", "num"),
    "KC_PPLS": ("+", "num"),
    "KC_PENT": ("Enter", "num"),
    "KC_PDOT": (".", "num"),
    "KC_PCMM": (",", "num"),
    "KC_PEQL": ("=", "num"),
    **{f"KC_P{digit}": (str(digit), "num") for digit in range(10)},
    "KC_MUTE": ("Mute", ""),
    "KC_VOLU": ("Vol +", ""),
    "KC_VOLD": ("Vol −", ""),
    "KC_MNXT": ("Next", "▶▶"),
    "KC_MPRV": ("Prev", "◀◀"),
    "KC_MPLY": ("Play", "▶⏸"),
    "KC_MSTP": ("Stop", "■"),
    "KC_MFFD": ("FFwd", ""),
    "KC_MRWD": ("Rew", ""),
    "KC_BRIU": ("Bright +", ""),
    "KC_BRID": ("Bright −", ""),
    "KC_MSEL": ("Media", ""),
    "KC_EJCT": ("Eject", ""),
    "KC_MAIL": ("Mail", ""),
    "KC_CALC": ("Calc", ""),
    "KC_MYCM": ("Files", ""),
    "KC_WSCH": ("Search", ""),
    "KC_WHOM": ("Home", "www"),
    "KC_WBAK": ("Back", "www"),
    "KC_WFWD": ("Fwd", "www"),
    "KC_WSTP": ("Stop", "www"),
    "KC_WREF": ("Reload", "www"),
    "KC_WFAV": ("Favs", "www"),
    "KC_PWR": ("Power", ""),
    "KC_SLEP": ("Sleep", ""),
    "KC_WAKE": ("Wake", ""),
    "KC_MCTL": ("Mission", "Control"),
    "KC_LPAD": ("Launch", "pad"),
    "KC_ASST": ("Assist", ""),
    "KC_CPNL": ("Control", "Panel"),
    "QK_BOOT": ("Boot", "loader"),
    "QK_RBT": ("Reboot", ""),
    "EE_CLR": ("Clear", "EEPROM"),
    "NK_TOGG": ("NKRO", "toggle"),
    "AG_TOGG": ("Alt/Gui", "swap"),
    "RGB_TOG": ("RGB", "on/off"),
    "RGB_MOD": ("RGB", "effect +"),
    "RGB_RMOD": ("RGB", "effect −"),
    "RGB_HUI": ("RGB", "hue +"),
    "RGB_HUD": ("RGB", "hue −"),
    "RGB_SAI": ("RGB", "sat +"),
    "RGB_SAD": ("RGB", "sat −"),
    "RGB_VAI": ("RGB", "bright +"),
    "RGB_VAD": ("RGB", "bright −"),
    "RGB_SPI": ("RGB", "speed +"),
    "RGB_SPD": ("RGB", "speed −"),
    "BL_TOGG": ("Backlight", "on/off"),
    "BL_UP": ("Backlight", "+"),
    "BL_DOWN": ("Backlight", "−"),
    "BL_STEP": ("Backlight", "step"),
    "KC_MS_U": ("Mouse", "↑"),
    "KC_MS_D": ("Mouse", "↓"),
    "KC_MS_L": ("Mouse", "←"),
    "KC_MS_R": ("Mouse", "→"),
    "KC_BTN1": ("Click", "left"),
    "KC_BTN2": ("Click", "right"),
    "KC_BTN3": ("Click", "middle"),
    "KC_BTN4": ("Click", "4"),
    "KC_BTN5": ("Click", "5"),
    "KC_WH_U": ("Wheel", "↑"),
    "KC_WH_D": ("Wheel", "↓"),
    "KC_WH_L": ("Wheel", "←"),
    "KC_WH_R": ("Wheel", "→"),
    "KC_ACL0": ("Mouse", "slow"),
    "KC_ACL1": ("Mouse", "med"),
    "KC_ACL2": ("Mouse", "fast"),
}

# Layer functions, with the wording the picker shows next to each.
LAYER_FUNCTIONS: list[tuple[str, str, str]] = [
    ("MO", "Momentary", "Activate the layer while the key is held"),
    ("TG", "Toggle", "Switch the layer on or off"),
    ("TO", "Go to", "Make this the only active layer"),
    ("OSL", "One-shot", "Activate the layer for the next key press only"),
    ("TT", "Tap-toggle", "Hold to activate, tap several times to lock on"),
    ("DF", "Default", "Change which layer is the base layer"),
]

_CATEGORY_SPECS: list[tuple[str, tuple[str, ...]]] = [
    (
        "Letters & numbers",
        (
            "KC_A KC_B KC_C KC_D KC_E KC_F KC_G KC_H KC_I KC_J KC_K KC_L KC_M "
            "KC_N KC_O KC_P KC_Q KC_R KC_S KC_T KC_U KC_V KC_W KC_X KC_Y KC_Z "
            "KC_1 KC_2 KC_3 KC_4 KC_5 KC_6 KC_7 KC_8 KC_9 KC_0"
        ).split(),
    ),
    (
        "Punctuation",
        "KC_GRV KC_MINS KC_EQL KC_LBRC KC_RBRC KC_BSLS KC_SCLN KC_QUOT "
        "KC_COMM KC_DOT KC_SLSH KC_NUHS KC_NUBS".split(),
    ),
    (
        "Editing",
        "KC_ESC KC_TAB KC_CAPS KC_ENT KC_BSPC KC_SPC KC_DEL KC_INS "
        "KC_UNDO KC_CUT KC_COPY KC_PSTE KC_AGIN KC_FIND".split(),
    ),
    (
        "Modifiers",
        "KC_LCTL KC_LSFT KC_LALT KC_LGUI KC_RCTL KC_RSFT KC_RALT KC_RGUI KC_APP".split(),
    ),
    (
        "Navigation",
        "KC_UP KC_DOWN KC_LEFT KC_RGHT KC_HOME KC_END KC_PGUP KC_PGDN "
        "KC_PSCR KC_SCRL KC_PAUS".split(),
    ),
    (
        "Function keys",
        (
            "KC_F1 KC_F2 KC_F3 KC_F4 KC_F5 KC_F6 KC_F7 KC_F8 KC_F9 KC_F10 KC_F11 KC_F12 "
            "KC_F13 KC_F14 KC_F15 KC_F16 KC_F17 KC_F18 KC_F19 KC_F20 KC_F21 KC_F22 "
            "KC_F23 KC_F24"
        ).split(),
    ),
    (
        "Numpad",
        "KC_NUM KC_PSLS KC_PAST KC_PMNS KC_PPLS KC_PENT KC_PDOT KC_PCMM KC_PEQL "
        "KC_P0 KC_P1 KC_P2 KC_P3 KC_P4 KC_P5 KC_P6 KC_P7 KC_P8 KC_P9".split(),
    ),
    (
        "Media & system",
        "KC_MUTE KC_VOLU KC_VOLD KC_MPLY KC_MNXT KC_MPRV KC_MSTP KC_MFFD KC_MRWD "
        "KC_MSEL KC_EJCT KC_BRIU KC_BRID KC_PWR KC_SLEP KC_WAKE KC_MAIL KC_CALC "
        "KC_MYCM KC_WSCH KC_WHOM KC_WBAK KC_WFWD KC_WSTP KC_WREF KC_WFAV "
        "KC_MCTL KC_LPAD KC_ASST KC_CPNL".split(),
    ),
    (
        "Mouse",
        "KC_MS_U KC_MS_D KC_MS_L KC_MS_R KC_BTN1 KC_BTN2 KC_BTN3 KC_BTN4 KC_BTN5 "
        "KC_WH_U KC_WH_D KC_WH_L KC_WH_R KC_ACL0 KC_ACL1 KC_ACL2".split(),
    ),
    (
        "International",
        "KC_INT1 KC_INT2 KC_INT3 KC_INT4 KC_INT5 KC_INT6 KC_INT7 KC_INT8 KC_INT9 "
        "KC_LNG1 KC_LNG2 KC_LNG3 KC_LNG4 KC_LNG5 KC_LNG6 KC_LNG7 KC_LNG8 KC_LNG9".split(),
    ),
    (
        "Lighting",
        "RGB_TOG RGB_MOD RGB_RMOD RGB_HUI RGB_HUD RGB_SAI RGB_SAD RGB_VAI RGB_VAD "
        "RGB_SPI RGB_SPD BL_TOGG BL_UP BL_DOWN BL_STEP".split(),
    ),
    (
        "Keyboard",
        "KC_NO KC_TRNS QK_BOOT QK_RBT EE_CLR NK_TOGG AG_TOGG".split(),
    ),
]


@functools.lru_cache(maxsize=1)
def categories() -> list[tuple[str, list[tuple[int, str]]]]:
    """The picker catalogue: ``[(title, [(keycode, name), ...]), ...]``.

    Names that a given QMK build does not define are dropped rather than
    raising, so the catalogue degrades gracefully against another firmware.
    """
    result = []
    for title, names in _CATEGORY_SPECS:
        entries = []
        for name in names:
            try:
                entries.append((keycodes.parse(name), name))
            except ValueError:
                continue
        if entries:
            result.append((title, entries))
    return result


# Words people search for that appear nowhere in QMK's own naming. Without
# these, "volume" finds nothing because the keycode is spelled KC_VOLU.
SEARCH_SYNONYMS: dict[str, str] = {
    "KC_VOLU": "volume louder",
    "KC_VOLD": "volume quieter softer",
    "KC_MUTE": "volume silence",
    "KC_BRIU": "brightness screen backlight",
    "KC_BRID": "brightness screen backlight",
    "KC_LGUI": "windows command super meta cmd",
    "KC_RGUI": "windows command super meta cmd",
    "KC_LALT": "option meta",
    "KC_RALT": "option meta altgr",
    "KC_LCTL": "control",
    "KC_RCTL": "control",
    "KC_LSFT": "shift",
    "KC_RSFT": "shift",
    "KC_ESC": "escape",
    "KC_ENT": "return newline",
    "KC_BSPC": "backspace delete",
    "KC_DEL": "delete forward",
    "KC_APP": "menu context right-click",
    "KC_PSCR": "print screen screenshot",
    "KC_CAPS": "caps lock",
    "KC_NUM": "num lock numlock",
    "KC_SCRL": "scroll lock",
    "KC_MPLY": "media play pause",
    "KC_MNXT": "media next track skip",
    "KC_MPRV": "media previous track back",
    "KC_MSTP": "media stop",
    "KC_GRV": "grave tilde backtick",
    "KC_MINS": "minus hyphen dash underscore",
    "KC_EQL": "equals plus",
    "KC_LBRC": "left bracket brace",
    "KC_RBRC": "right bracket brace",
    "KC_BSLS": "backslash pipe",
    "KC_SCLN": "semicolon colon",
    "KC_QUOT": "quote apostrophe",
    "KC_COMM": "comma less than",
    "KC_DOT": "period full stop greater than",
    "KC_SLSH": "slash question mark",
    "KC_SPC": "space bar spacebar",
    "KC_NO": "nothing none disable blank",
    "KC_TRNS": "transparent pass through fall through",
    "QK_BOOT": "bootloader dfu flash firmware",
    "EE_CLR": "factory reset clear eeprom",
    "KC_MCTL": "mission control expose macos",
    "KC_LPAD": "launchpad macos",
    "KC_PSLS": "numpad keypad divide slash",
    "KC_PAST": "numpad keypad multiply asterisk star",
    "KC_PMNS": "numpad keypad minus subtract",
    "KC_PPLS": "numpad keypad plus add",
    "KC_PENT": "numpad keypad enter return",
    "KC_PDOT": "numpad keypad period decimal",
    **{f"KC_P{digit}": f"numpad keypad {digit}" for digit in range(10)},
}


def search_text(keycode: int, extra: str = "") -> str:
    """Everything a key can be found by: names, legend, and plain-word synonyms."""
    names = keycodes.names_for(keycode) or (keycodes.name_for(keycode),)
    main, sub = legend(keycode)
    synonyms = " ".join(SEARCH_SYNONYMS.get(name, "") for name in names)
    return " ".join((*names, main, sub, synonyms, extra)).lower()


def matches(haystack: str, query: str) -> bool:
    """True when every word of the query appears in the haystack."""
    return all(token in haystack for token in query.lower().split())


_WORDS = re.compile(r"[_\s]+")


def _fallback_legend(name: str) -> tuple[str, str]:
    """Turn a bare QMK name into something readable on a keycap."""
    if name.startswith("0x"):
        return name, ""
    stripped = name.removeprefix("KC_")
    words = [word.capitalize() for word in _WORDS.split(stripped.lower()) if word]
    if len(words) <= 1:
        return " ".join(words) or name, ""
    return words[0], " ".join(words[1:])


def legend(keycode: int, custom: dict[int, str] | None = None) -> tuple[str, str]:
    """Return ``(main, sub)`` text for drawing ``keycode`` on a keycap."""
    if custom and keycode in custom:
        return custom[keycode], ""

    name = keycodes.name_for(keycode)
    if name in LEGENDS:
        return LEGENDS[name]

    # Composite keycodes read best as the function on top, its target below.
    if match := re.match(r"^(MO|TG|TO|OSL|TT|DF)\((\d+)\)$", name):
        return match.group(1), f"Layer {match.group(2)}"
    if match := re.match(r"^LT\((\d+),(.*)\)$", name):
        inner, _ = legend(keycodes.parse(match.group(2)), custom)
        return inner, f"LT {match.group(1)}"
    if match := re.match(r"^(\w+)_T\((.*)\)$", name):
        inner, _ = legend(keycodes.parse(match.group(2)), custom)
        return inner, keycodes.modifier_label(keycodes.parse_modifiers(match.group(1)) or 0)
    if match := re.match(r"^MT\((.*),(.*)\)$", name):
        inner, _ = legend(keycodes.parse(match.group(2)), custom)
        return inner, keycodes.modifier_label(keycodes.parse_modifiers(match.group(1)) or 0)
    if match := re.match(r"^M(\d+)$", name):
        return f"Macro {match.group(1)}", ""
    if match := re.match(r"^OSM\((.*)\)$", name):
        return keycodes.modifier_label(keycodes.parse_modifiers(match.group(1)) or 0), "one-shot"
    if match := re.match(r"^LM\((\d+),(.*)\)$", name):
        return keycodes.modifier_label(keycodes.parse_modifiers(match.group(2)) or 0), \
            f"Layer {match.group(1)}"
    if match := re.match(r"^(\w+)\((.*)\)$", name):
        mods = keycodes.parse_modifiers(match.group(1))
        if mods is not None:
            inner, _ = legend(keycodes.parse(match.group(2)), custom)
            return inner, keycodes.modifier_label(mods)

    return _fallback_legend(name)

