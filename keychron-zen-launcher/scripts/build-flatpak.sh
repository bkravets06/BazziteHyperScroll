#!/usr/bin/env bash
# Build the Flatpak and install it for the current user.
#
# Needs flatpak and org.flatpak.Builder, which Bazzite can install with:
#   flatpak install -y flathub org.flatpak.Builder
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_ID="io.github.bkravets06.KeychronZenLauncher"
MANIFEST="${ROOT}/flatpak/${APP_ID}.yml"
BUILD_DIR="${ROOT}/.flatpak-builder/build"

if ! command -v flatpak >/dev/null; then
  echo "flatpak is not installed." >&2
  exit 1
fi

builder=(flatpak run org.flatpak.Builder)
if command -v flatpak-builder >/dev/null; then
  builder=(flatpak-builder)
fi

echo "Making sure the GNOME 48 runtime and SDK are available…"
flatpak install --user --or-update --noninteractive flathub \
  org.gnome.Platform//48 org.gnome.Sdk//48

echo "Building…"
cd "${ROOT}/flatpak"
"${builder[@]}" --force-clean --user --install "${BUILD_DIR}" "${MANIFEST}"

cat <<MESSAGE

Installed. Launch it from the app grid, or run:
  flatpak run ${APP_ID}

Remember the udev rule, or the app will not be allowed to open the keyboard:
  sudo ${ROOT}/scripts/install-udev-rule.sh

To remove the app completely:
  flatpak uninstall --user ${APP_ID}
MESSAGE
