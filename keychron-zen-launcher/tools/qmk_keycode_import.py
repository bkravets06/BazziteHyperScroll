#!/usr/bin/env python3
"""Generate the QMK keycode table from ``quantum/keycodes.h``.

QMK generates that header from its own keycode specification, so parsing it is
the most reliable way to get the ~700 keycode values and their aliases without
transcribing them by hand. The result is committed as
``src/keychron_zen/protocol/qmk_keycodes.json``; re-run this only when tracking
a newer QMK.

Usage::

    tools/qmk_keycode_import.py --out src/keychron_zen/protocol/qmk_keycodes.json
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import urllib.request

DEFAULT_URL = (
    "https://raw.githubusercontent.com/Keychron/qmk_firmware/"
    "wireless_playground/quantum/keycodes.h"
)

_NAME = r"[A-Za-z_][A-Za-z0-9_]*"
ENUM = re.compile(rf"^\s*({_NAME})\s*=\s*(0x[0-9A-Fa-f]+|{_NAME})\s*,?\s*$")


def parse(source: str) -> tuple[dict[str, int], dict[str, int], dict[str, str]]:
    ranges: dict[str, int] = {}
    keycodes: dict[str, int] = {}
    aliases: dict[str, str] = {}
    section = None
    skipped: list[str] = []

    for line in source.splitlines():
        if line.startswith("enum qk_keycode_ranges"):
            section = "ranges"
            continue
        if line.startswith("enum qk_keycode_defines"):
            section = "keycodes"
            continue
        if section and line.startswith("};"):
            section = None
            continue
        if section is None:
            continue

        stripped = line.strip()
        if not stripped or stripped.startswith("//"):
            continue
        match = ENUM.match(line)
        if not match:
            skipped.append(stripped)
            continue

        name, value = match.groups()
        target = ranges if section == "ranges" else keycodes
        if value.startswith("0x"):
            target[name] = int(value, 16)
        elif value in target:
            # QMK writes its short names as aliases of the canonical name.
            if section == "keycodes":
                aliases[name] = value
            else:
                target[name] = target[value]
        else:
            skipped.append(stripped)

    if skipped:
        raise SystemExit("unparsed enum entries:\n  " + "\n  ".join(skipped[:20]))
    return ranges, keycodes, aliases


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--out", required=True, type=pathlib.Path)
    args = parser.parse_args()

    with urllib.request.urlopen(args.url, timeout=30) as response:
        source = response.read().decode()

    ranges, keycodes, aliases = parse(source)
    args.out.write_text(
        json.dumps(
            {
                "source": args.url,
                "ranges": ranges,
                "keycodes": keycodes,
                "aliases": aliases,
            },
            indent=1,
            sort_keys=False,
        )
        + "\n"
    )
    print(f"wrote {args.out}: {len(keycodes)} keycodes, {len(aliases)} aliases, "
          f"{len(ranges)} ranges")


if __name__ == "__main__":
    main()
