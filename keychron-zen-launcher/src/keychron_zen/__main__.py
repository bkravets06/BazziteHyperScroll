"""Entry point: ``keychron-zen-launcher`` and ``python -m keychron_zen``."""

from __future__ import annotations

import argparse
import sys

from . import __version__


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="keychron-zen-launcher",
        description=(
            "Configure QMK/VIA Keychron keyboards. Opens a window; nothing runs "
            "in the background once it is closed."
        ),
    )
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument(
        "--demo",
        action="store_true",
        help="start with a simulated keyboard, without touching real hardware",
    )
    parser.add_argument(
        "--list-devices",
        action="store_true",
        help="print the keyboards this app can see, then exit",
    )
    arguments = parser.parse_args(argv)

    if arguments.list_devices:
        return _list_devices()

    from .ui.application import Application

    return Application(demo=arguments.demo).run([])


def _list_devices() -> int:
    """Report what is visible, and why anything unusable is unusable.

    Kept out of the GUI import path so it still works on a machine with no
    display and no GTK installed.
    """
    from .model.device import discover

    found = discover()
    if not found:
        print("No VIA-capable keyboards found.")
        print(
            "Plug the keyboard in with its USB cable — Keychron's firmware does "
            "not accept configuration over Bluetooth or the 2.4 GHz receiver."
        )
        return 1

    for item in found:
        print(f"{item.info.node}: {item.title}")
        print(f"  usb {item.info.vendor_id:04X}:{item.info.product_id:04X}")
        if item.definition is None:
            print("  no layout definition — macros and lighting only")
        if item.problem:
            print(f"  unusable: {item.problem}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
