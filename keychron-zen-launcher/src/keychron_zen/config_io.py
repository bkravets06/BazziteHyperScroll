"""Export and import a keyboard's whole configuration as readable JSON.

Keycodes are stored by name (``LT(1,KC_SPC)``, not ``0x412C``) so a saved
config is worth putting in version control and can be edited by hand. Names
round-trip exactly; anything this build cannot name is written as ``0x....``
rather than being silently dropped.
"""

from __future__ import annotations

import json
from typing import Any

from .model.device import Keyboard
from .protocol import keycodes, macros, via

FORMAT = "keychron-zen-launcher"
VERSION = 1


class ConfigError(ValueError):
    """The config file is malformed or does not fit the connected keyboard."""


def export(keyboard: Keyboard) -> dict[str, Any]:
    """Capture everything about the keyboard's current configuration."""
    data: dict[str, Any] = {
        "format": FORMAT,
        "version": VERSION,
        "keyboard": {
            "name": keyboard.title,
            "vendor_id": f"0x{keyboard.info.vendor_id:04X}",
            "product_id": f"0x{keyboard.info.product_id:04X}",
            "matrix": {"rows": keyboard.rows, "cols": keyboard.columns},
        },
    }
    if keyboard.definition and keyboard.variant:
        data["keyboard"]["layout"] = keyboard.variant.layout

    if keyboard.keymap:
        data["layers"] = [
            {
                "name": keyboard.definition.layer_name(index)
                if keyboard.definition
                else f"Layer {index}",
                "keys": [[keycodes.name_for(code) for code in row] for row in layer],
            }
            for index, layer in enumerate(keyboard.keymap)
        ]

    if keyboard.macros:
        data["macros"] = [macros.to_text(macro) for macro in keyboard.macros]

    if keyboard.lighting and keyboard.variant:
        state = keyboard.lighting
        lighting: dict[str, Any] = {
            "kind": keyboard.variant.lighting.kind,
            "brightness": state.brightness,
            "effect": state.effect,
            "effect_name": keyboard.variant.lighting.effect_name(state.effect),
            "speed": state.speed,
        }
        if state.has_color:
            lighting["hue"] = state.hue
            lighting["saturation"] = state.saturation
        data["lighting"] = lighting

    return data


def dumps(keyboard: Keyboard) -> str:
    return json.dumps(export(keyboard), indent=2) + "\n"


def loads(text: str) -> dict[str, Any]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ConfigError(f"not valid JSON: {exc}") from exc
    if not isinstance(data, dict) or data.get("format") != FORMAT:
        raise ConfigError("this file was not written by Keychron Zen Launcher")
    if data.get("version", 0) > VERSION:
        raise ConfigError(
            f"the file is version {data['version']}, but this build only understands "
            f"version {VERSION}"
        )
    return data


def describe(data: dict[str, Any]) -> str:
    """A one-line summary of what a config file contains."""
    parts = [data.get("keyboard", {}).get("name", "unknown keyboard")]
    if layers := data.get("layers"):
        parts.append(f"{len(layers)} layers")
    if macro_list := data.get("macros"):
        used = sum(1 for macro in macro_list if macro)
        parts.append(f"{used} of {len(macro_list)} macros")
    if "lighting" in data:
        parts.append("lighting")
    return ", ".join(parts)


def apply(
    keyboard: Keyboard,
    data: dict[str, Any],
    *,
    keymap: bool = True,
    macro_slots: bool = True,
    lighting: bool = True,
    force: bool = False,
) -> list[str]:
    """Write a config onto a keyboard. Returns a list of what changed.

    Refuses a file captured from a different model unless ``force`` is set,
    because matrix positions mean different things on different boards.
    """
    applied: list[str] = []
    saved = data.get("keyboard", {})
    if not force:
        expected = _product_id(saved.get("product_id"))
        if expected is not None and expected != keyboard.info.product_id:
            raise ConfigError(
                f"this file is for product 0x{expected:04X}, but the connected "
                f"keyboard is 0x{keyboard.info.product_id:04X}. Import it anyway "
                "only if you know the layouts match."
            )

    if keymap and "layers" in data:
        applied.append(_apply_keymap(keyboard, data["layers"]))
    if macro_slots and "macros" in data:
        applied.append(_apply_macros(keyboard, data["macros"]))
    if lighting and "lighting" in data:
        message = _apply_lighting(keyboard, data["lighting"])
        if message:
            applied.append(message)
    return applied


def _product_id(value: Any) -> int | None:
    """Read a product id written as ``"0x0AD0"`` or as a plain number."""
    if value is None:
        return None
    try:
        return int(value, 16) if isinstance(value, str) else int(value)
    except ValueError as exc:
        raise ConfigError(f"bad product id {value!r}") from exc


def _apply_keymap(keyboard: Keyboard, layers: list[dict]) -> str:
    if not keyboard.has_layout:
        raise ConfigError("no layout definition for this keyboard, so its keymap cannot be written")
    if len(layers) > keyboard.layer_count:
        raise ConfigError(
            f"the file has {len(layers)} layers but the keyboard only has "
            f"{keyboard.layer_count}"
        )

    keymap = [[row[:] for row in layer] for layer in keyboard.keymap]
    for index, layer in enumerate(layers):
        rows = layer.get("keys", [])
        if len(rows) != keyboard.rows:
            raise ConfigError(
                f"layer {index} has {len(rows)} rows, expected {keyboard.rows}"
            )
        for row_index, row in enumerate(rows):
            if len(row) != keyboard.columns:
                raise ConfigError(
                    f"layer {index} row {row_index} has {len(row)} keys, "
                    f"expected {keyboard.columns}"
                )
            for column, name in enumerate(row):
                try:
                    keymap[index][row_index][column] = keycodes.parse(name)
                except ValueError as exc:
                    raise ConfigError(
                        f"layer {index}, row {row_index}, key {column}: {exc}"
                    ) from exc

    keyboard.via.write_keymap(keymap)
    keyboard.keymap = keymap
    return f"{len(layers)} layers"


def _apply_macros(keyboard: Keyboard, entries: list[str]) -> str:
    if not keyboard.macro_buffer_size:
        raise ConfigError("this keyboard did not report any macro storage")
    slots = len(keyboard.macros) or len(entries)
    if len(entries) > slots:
        raise ConfigError(
            f"the file has {len(entries)} macros but the keyboard has {slots} slots"
        )
    parsed = [macros.from_text(text) for text in entries]
    parsed += [[] for _ in range(slots - len(parsed))]
    try:
        keyboard.set_macros(parsed)
    except macros.MacroError as exc:
        raise ConfigError(str(exc)) from exc
    return f"{sum(1 for macro in parsed if macro)} macros"


def _apply_lighting(keyboard: Keyboard, settings: dict[str, Any]) -> str | None:
    if keyboard.lighting_channel is None or keyboard.variant is None:
        return None
    kind = settings.get("kind")
    if kind and kind != keyboard.variant.lighting.kind:
        raise ConfigError(
            f"the file's lighting is for a {kind} keyboard, but this one is "
            f"{keyboard.variant.lighting.kind}"
        )
    current = keyboard.lighting
    state = via.LightingState(
        brightness=int(settings.get("brightness", current.brightness if current else 0)),
        effect=int(settings.get("effect", current.effect if current else 0)),
        speed=int(settings.get("speed", current.speed if current else 0)),
        hue=settings.get("hue"),
        saturation=settings.get("saturation"),
    )
    keyboard.apply_lighting(state)
    return "lighting"
