"""Keyboard definitions: matrix size, physical layout, lighting capabilities.

A definition is the piece VIA-style tools cannot get from the keyboard itself.
The firmware will happily tell you how many layers it has, but not how its
6x17 matrix maps onto the keys in front of you -- that lives in the QMK
metadata, which ``tools/qmk_layout_import.py`` converts into the JSON files
next to this module.
"""

from __future__ import annotations

import functools
import json
import pathlib
from dataclasses import dataclass, field

from ..protocol import keycodes

KEYBOARDS_DIR = pathlib.Path(__file__).with_name("keyboards")

# Definitions hold their stock keymaps as names; the parsed grids are cached
# here because Definition is frozen but not hashable.
_DEFAULT_KEYMAPS: dict[tuple[str, int], list[list[list[int]]]] = {}


@dataclass(frozen=True)
class KeyPosition:
    """One physical key: where it sits, and which matrix cell it reports."""

    row: int
    column: int
    x: float
    y: float
    width: float = 1.0
    height: float = 1.0

    @property
    def cell(self) -> tuple[int, int]:
        return self.row, self.column


@dataclass(frozen=True)
class Effect:
    value: int
    name: str


@dataclass(frozen=True)
class Lighting:
    """What kind of backlight a variant has, and which effects it supports."""

    kind: str
    effects: tuple[Effect, ...]

    @property
    def has_color(self) -> bool:
        # Single-colour boards expose brightness/effect/speed but no hue.
        return self.kind in ("rgb_matrix", "rgblight")

    def effect_name(self, value: int) -> str:
        for effect in self.effects:
            if effect.value == value:
                return effect.name
        return f"Effect {value}"


@dataclass(frozen=True)
class CustomKeycode:
    """A keyboard-specific keycode in QMK's ``QK_KB_*`` range."""

    value: int
    name: str
    label: str
    description: str


@dataclass(frozen=True)
class Variant:
    """One sellable configuration of a keyboard, identified by USB product id."""

    product_id: int
    physical: str
    layout: str
    lighting: Lighting
    custom_keycodes: tuple[CustomKeycode, ...] = ()
    # The keymap the firmware ships with, as keycode names in layout order.
    default_keymap: tuple[tuple[str, ...], ...] = ()

    @property
    def title(self) -> str:
        backlight = "RGB" if self.lighting.kind == "rgb_matrix" else "white"
        return f"{self.physical.upper()}, {backlight} backlight"


@dataclass(frozen=True)
class Definition:
    """Everything known about one keyboard model."""

    name: str
    vendor_id: int
    rows: int
    columns: int
    variants: tuple[Variant, ...]
    layouts: dict[str, tuple[KeyPosition, ...]]
    layer_names: tuple[str, ...] = ()
    source: dict = field(default_factory=dict)

    def variant_for(self, product_id: int) -> Variant | None:
        for variant in self.variants:
            if variant.product_id == product_id:
                return variant
        return None

    def keys(self, variant: Variant) -> tuple[KeyPosition, ...]:
        return self.layouts[variant.layout]

    def default_keymap(self, variant: Variant) -> list[list[list[int]]]:
        """The stock keymap as ``[layer][row][column]`` keycode values.

        Cells the physical layout does not use stay ``KC_NO``. Empty when the
        definition carries no stock keymap.
        """
        cache_key = (self.name, variant.product_id)
        cached = _DEFAULT_KEYMAPS.get(cache_key)
        if cached is not None:
            return cached

        grid: list[list[list[int]]] = []
        positions = self.keys(variant)
        for layer in variant.default_keymap:
            rows = [[keycodes.KC_NO] * self.columns for _ in range(self.rows)]
            for position, name in zip(positions, layer):
                try:
                    rows[position.row][position.column] = keycodes.parse(name)
                except (ValueError, IndexError):
                    continue
            grid.append(rows)
        _DEFAULT_KEYMAPS[cache_key] = grid
        return grid

    def layer_name(self, index: int) -> str:
        if index < len(self.layer_names):
            return f"{index} · {self.layer_names[index]}"
        return f"Layer {index}"


def _parse(data: dict) -> Definition:
    layouts = {
        name: tuple(
            KeyPosition(
                row=key["matrix"][0],
                column=key["matrix"][1],
                x=key["x"],
                y=key["y"],
                width=key.get("w", 1.0),
                height=key.get("h", 1.0),
            )
            for key in keys
        )
        for name, keys in data["layouts"].items()
    }
    variants = tuple(
        Variant(
            product_id=variant["product_id"],
            physical=variant["physical"],
            layout=variant["layout"],
            lighting=Lighting(
                kind=variant["lighting"]["kind"],
                effects=tuple(
                    Effect(effect["value"], effect["name"])
                    for effect in variant["lighting"]["effects"]
                ),
            ),
            custom_keycodes=tuple(
                CustomKeycode(
                    value=entry["value"],
                    name=entry["name"],
                    label=entry["label"],
                    description=entry["description"],
                )
                for entry in variant.get("custom_keycodes", ())
            ),
            default_keymap=tuple(
                tuple(layer) for layer in variant.get("default_keymap", ())
            ),
        )
        for variant in data["variants"]
    )
    return Definition(
        name=data["name"],
        vendor_id=data["vendor_id"],
        rows=data["matrix"]["rows"],
        columns=data["matrix"]["cols"],
        variants=variants,
        layouts=layouts,
        layer_names=tuple(data.get("layer_names", ())),
        source=data.get("source", {}),
    )


@functools.lru_cache(maxsize=1)
def load_all() -> tuple[Definition, ...]:
    """Load every bundled definition."""
    return tuple(
        _parse(json.loads(path.read_text()))
        for path in sorted(KEYBOARDS_DIR.glob("*.json"))
    )


def find(vendor_id: int, product_id: int) -> tuple[Definition, Variant] | None:
    """Look up the definition for a connected device."""
    for definition in load_all():
        if definition.vendor_id != vendor_id:
            continue
        variant = definition.variant_for(product_id)
        if variant is not None:
            return definition, variant
    return None

