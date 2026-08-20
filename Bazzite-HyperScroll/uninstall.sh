#!/usr/bin/env bash
set -euo pipefail

service_name=bazzite-hyperscroll.service
service_account=bazzite-hyperscroll
extension_uuid=bazzite-hyperscroll@local

if [[ $EUID -ne 0 ]]; then
    exec sudo --preserve-env=XDG_RUNTIME_DIR,DBUS_SESSION_BUS_ADDRESS "$0" "$@"
fi

target_user=${SUDO_USER:-}
if [[ -n $target_user && $target_user != root ]]; then
    target_uid=$(id -u "$target_user")
    target_home=$(getent passwd "$target_user" | cut -d: -f6)
    runtime_dir=/run/user/$target_uid
    if [[ -S $runtime_dir/bus ]]; then
        sudo -u "$target_user" env XDG_RUNTIME_DIR="$runtime_dir" \
            DBUS_SESSION_BUS_ADDRESS="unix:path=$runtime_dir/bus" \
            gnome-extensions disable "$extension_uuid" 2>/dev/null || true
        sudo -u "$target_user" env XDG_RUNTIME_DIR="$runtime_dir" \
            DBUS_SESSION_BUS_ADDRESS="unix:path=$runtime_dir/bus" \
            python3 -c 'from gi.repository import Gio; import sys; s=Gio.Settings.new("org.gnome.shell"); u=sys.argv[1]; ok=s.set_strv("enabled-extensions", [x for x in s.get_strv("enabled-extensions") if x != u]) and s.set_strv("disabled-extensions", [x for x in s.get_strv("disabled-extensions") if x != u]); Gio.Settings.sync(); raise SystemExit(0 if ok else 1)' \
            "$extension_uuid" 2>/dev/null || true
    fi
    extension_dir="$target_home/.local/share/gnome-shell/extensions/$extension_uuid"
    rm -f "$extension_dir/extension.js" "$extension_dir/metadata.json" \
        "$extension_dir/stylesheet.css"
    rmdir "$extension_dir" 2>/dev/null || true
fi

systemctl disable "$service_name" 2>/dev/null || true
systemctl stop "$service_name" 2>/dev/null || true
if systemctl is-active --quiet "$service_name"; then
    echo "HyperScroll is still running; refusing to remove its files or device ACLs." >&2
    exit 1
fi

# Remove only the named ACL entries installed for this service. Existing
# Sunshine/input/uaccess permissions and device ownership are left intact.
mouse_link=/dev/input/by-id/usb-Razer_Razer_Viper_V3_Pro-event-mouse
if [[ -e $mouse_link ]]; then
    setfacl -x "g:$service_account" "$mouse_link" 2>/dev/null || true
fi
if [[ -e /dev/uinput ]]; then
    setfacl -x "g:$service_account" /dev/uinput 2>/dev/null || true
fi
rm -f "/etc/systemd/system/$service_name" \
    /etc/udev/rules.d/99-bazzite-hyperscroll.rules \
    /usr/local/bin/bazzite-hyperscroll \
    /usr/local/bin/hyperscrollctl
systemctl daemon-reload
udevadm control --reload-rules
udevadm trigger --action=change --subsystem-match=input
udevadm trigger --action=change --subsystem-match=misc --sysname-match=uinput
udevadm settle

if id "$service_account" >/dev/null 2>&1; then
    userdel "$service_account"
fi
if getent group "$service_account" >/dev/null; then
    groupdel "$service_account"
fi

echo "Bazzite HyperScroll was removed. Configuration remains at /etc/bazzite-hyperscroll.conf."
