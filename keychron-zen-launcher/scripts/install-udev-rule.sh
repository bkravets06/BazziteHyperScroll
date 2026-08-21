#!/usr/bin/env bash
# Give the logged-in user permission to talk to Keychron keyboards.
#
# This writes one file to /etc/udev/rules.d. It installs no service, adds no
# autostart entry, and survives Bazzite image updates because /etc is preserved.
set -euo pipefail

RULE_NAME="99-keychron-zen-launcher.rules"
SOURCE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/data/${RULE_NAME}"
TARGET="/etc/udev/rules.d/${RULE_NAME}"

if [[ $EUID -ne 0 ]]; then
  echo "This needs root to write ${TARGET}." >&2
  echo "Run: sudo $0" >&2
  exit 1
fi

if [[ ! -f "$SOURCE" ]]; then
  echo "Cannot find ${SOURCE}" >&2
  exit 1
fi

install -Dm644 "$SOURCE" "$TARGET"
udevadm control --reload-rules
udevadm trigger --subsystem-match=hidraw

echo "Installed ${TARGET}."
echo "Unplug and replug the keyboard for the new permissions to take effect."
