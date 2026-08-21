#!/usr/bin/env bash
# Remove the udev rule installed by install-udev-rule.sh.
set -euo pipefail

TARGET="/etc/udev/rules.d/99-keychron-zen-launcher.rules"

if [[ $EUID -ne 0 ]]; then
  echo "This needs root to remove ${TARGET}." >&2
  echo "Run: sudo $0" >&2
  exit 1
fi

rm -f "$TARGET"
udevadm control --reload-rules
udevadm trigger --subsystem-match=hidraw
echo "Removed ${TARGET}."
