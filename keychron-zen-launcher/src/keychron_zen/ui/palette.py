"""Colours for the drawn keyboard.

The keycaps are painted with Cairo rather than built from themed widgets, so
the palette lives here explicitly. Both variants are tuned to sit correctly on
libadwaita's window backgrounds, and the accent matches the GNOME default so
the drawing does not look pasted in from another app.
"""

from __future__ import annotations

from dataclasses import dataclass

RGBA = tuple[float, float, float, float]


def _hex(value: str, alpha: float = 1.0) -> RGBA:
    value = value.lstrip("#")
    return (
        int(value[0:2], 16) / 255,
        int(value[2:4], 16) / 255,
        int(value[4:6], 16) / 255,
        alpha,
    )


@dataclass(frozen=True)
class Palette:
    """Every colour the keyboard view needs."""

    surface: RGBA
    cap: RGBA
    cap_border: RGBA
    cap_empty: RGBA
    text: RGBA
    text_dim: RGBA
    selected: RGBA
    selected_text: RGBA
    hover: RGBA
    pressed: RGBA
    pressed_text: RGBA
    tested: RGBA
    modified: RGBA


LIGHT = Palette(
    surface=_hex("#fafafa"),
    cap=_hex("#ffffff"),
    cap_border=_hex("#d0cfcc"),
    cap_empty=_hex("#f0f0ef"),
    text=_hex("#241f31"),
    text_dim=_hex("#77767b"),
    selected=_hex("#3584e4"),
    selected_text=_hex("#ffffff"),
    hover=_hex("#3584e4", 0.14),
    pressed=_hex("#2ec27e"),
    pressed_text=_hex("#ffffff"),
    tested=_hex("#2ec27e", 0.30),
    modified=_hex("#e5a50a"),
)

DARK = Palette(
    surface=_hex("#1d1d20"),
    cap=_hex("#36363a"),
    cap_border=_hex("#48484d"),
    cap_empty=_hex("#28282b"),
    text=_hex("#ffffff"),
    text_dim=_hex("#9a9996"),
    selected=_hex("#3584e4"),
    selected_text=_hex("#ffffff"),
    hover=_hex("#62a0ea", 0.20),
    pressed=_hex("#2ec27e"),
    pressed_text=_hex("#13141a"),
    tested=_hex("#2ec27e", 0.35),
    modified=_hex("#f5c211"),
)


def current(dark: bool) -> Palette:
    return DARK if dark else LIGHT
