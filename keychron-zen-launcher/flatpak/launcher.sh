#!/bin/sh
# Entry point inside the Flatpak sandbox.
#
# The package is installed to a fixed path rather than into site-packages so
# the manifest does not have to know the runtime's Python version.
PYTHONPATH="/app/lib/keychron-zen-launcher${PYTHONPATH:+:${PYTHONPATH}}"
export PYTHONPATH
exec python3 -m keychron_zen "$@"
