#!/usr/bin/env bash
# Run the launcher straight from a checkout, without installing anything.
#
# Needs GTK 4, libadwaita and PyGObject on the system. Bazzite's GNOME image
# already has all three.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
exec env PYTHONPATH="${ROOT}/src${PYTHONPATH:+:${PYTHONPATH}}" \
  python3 -m keychron_zen "$@"
