#!/usr/bin/env bash
set -euo pipefail

project_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
service_name=bazzite-hyperscroll.service
service_account=bazzite-hyperscroll
extension_uuid=bazzite-hyperscroll@local

if [[ $EUID -ne 0 ]]; then
    exec sudo --preserve-env=DISPLAY,WAYLAND_DISPLAY,XDG_RUNTIME_DIR,DBUS_SESSION_BUS_ADDRESS \
        "$0" "$@"
fi

target_user=${SUDO_USER:-}
if [[ -z $target_user || $target_user == root ]]; then
    echo "Run this installer from the desktop account with sudo." >&2
    exit 1
fi

target_uid=$(id -u "$target_user")
target_group=$(id -gn "$target_user")
target_home=$(getent passwd "$target_user" | cut -d: -f6)
runtime_dir=/run/user/$target_uid
extension_src="$project_dir/gnome-extension/$extension_uuid"
extension_dst="$target_home/.local/share/gnome-shell/extensions/$extension_uuid"

command -v python3 >/dev/null
command -v setfacl >/dev/null || {
    echo "setfacl is required for the least-privilege device ACLs." >&2
    exit 1
}
python3 -c 'import evdev' 2>/dev/null || {
    echo "python3-evdev is required and is not installed." >&2
    echo "On Bazzite (rpm-ostree), install it and reboot, then rerun this:" >&2
    echo "    rpm-ostree install python3-evdev && systemctl reboot" >&2
    exit 1
}

# Which mouse the daemon will grab, decided by the same code the daemon uses,
# so the installer never disagrees with it. The config being installed is the
# source of truth: an existing /etc config wins, exactly as at runtime.
config_source="$project_dir/config/bazzite-hyperscroll.conf"
[[ -e /etc/bazzite-hyperscroll.conf ]] && \
    config_source=/etc/bazzite-hyperscroll.conf

selected_mice() {
    python3 - "$project_dir/src/bazzite-hyperscroll" "$config_source" <<'PYTHON'
import importlib.machinery
import importlib.util
import sys

source, config = sys.argv[1], sys.argv[2]
loader = importlib.machinery.SourceFileLoader("bazzite_hyperscroll", source)
hs = importlib.util.module_from_spec(importlib.util.spec_from_loader(
    loader.name, loader))
loader.exec_module(hs)
hs.log.disabled = True
for line in open(config, encoding="utf-8", errors="replace"):
    line = line.split("#", 1)[0].strip()
    if "=" not in line:
        continue
    key, value = (part.strip() for part in line.split("=", 1))
    if key in hs.DEVICE_KEYS:
        setattr(hs, key, hs.parse_devices(value))
for path in sorted(hs.list_devices()):
    try:
        dev = hs.InputDevice(path)
    except OSError:
        continue
    try:
        if hs.decide_device(dev, path)[0]:
            print(f"{path}\t{(dev.name or '').strip()}")
    finally:
        dev.close()
PYTHON
}

mapfile -t selected < <(selected_mice)
if [[ ${#selected[@]} -eq 0 ]]; then
    echo "No mouse matching ONLY_DEVICES in $config_source is connected." >&2
    echo "Connect the mouse, or edit ONLY_DEVICES after listing devices:" >&2
    echo "    sudo python3 $project_dir/src/bazzite-hyperscroll --list-devices" >&2
    exit 1
fi
echo "HyperScroll will use:"
printf '  %s\n' "${selected[@]}"

# The sidecar is a GNOME Shell extension, and REQUIRE_FOCUS_HELPER keeps the
# middle button native while no sidecar reports a focused window. Say so now
# rather than leaving a silently inactive install behind.
session_id=$(loginctl show-user "$target_user" --value -p Display 2>/dev/null || true)
session_desktop=""
if [[ -n $session_id ]]; then
    session_desktop=$(loginctl show-session "$session_id" --value -p Desktop \
        2>/dev/null || true)
fi
if [[ -n $session_desktop && ${session_desktop,,} != *gnome* ]]; then
    echo
    echo "Warning: this session is '$session_desktop', not GNOME. The sidecar" >&2
    echo "extension only loads under GNOME Shell, so autoscroll will stay" >&2
    echo "inactive until a GNOME session is used." >&2
    echo
fi

getent group "$service_account" >/dev/null || groupadd --system "$service_account"
id "$service_account" >/dev/null 2>&1 || useradd --system \
    --gid "$service_account" --home-dir / --no-create-home \
    --shell /usr/sbin/nologin "$service_account"

install -Dm0755 "$project_dir/src/bazzite-hyperscroll" \
    /usr/local/bin/bazzite-hyperscroll
install -Dm0755 "$project_dir/src/hyperscrollctl" \
    /usr/local/bin/hyperscrollctl
install -Dm0644 "$project_dir/systemd/$service_name" \
    "/etc/systemd/system/$service_name"
install -Dm0644 "$project_dir/udev/99-bazzite-hyperscroll.rules" \
    /etc/udev/rules.d/99-bazzite-hyperscroll.rules
if [[ ! -e /etc/bazzite-hyperscroll.conf ]]; then
    install -Dm0644 "$project_dir/config/bazzite-hyperscroll.conf" \
        /etc/bazzite-hyperscroll.conf
else
    echo "Keeping existing /etc/bazzite-hyperscroll.conf"
fi

install -d -m0755 -o "$target_user" -g "$target_group" "$extension_dst"
for file in extension.js metadata.json stylesheet.css; do
    install -m0644 -o "$target_user" -g "$target_group" \
        "$extension_src/$file" "$extension_dst/$file"
done

# GNOME refuses to load an extension whose metadata does not list the running
# Shell version, and it refuses silently as far as this feature is concerned:
# with no sidecar reporting, the middle button just stays native. Record the
# version actually running here, so an OS upgrade to an unlisted GNOME only
# costs a rerun of this installer rather than a mystery.
shell_version=$(gnome-shell --version 2>/dev/null |
    sed -n 's/^GNOME Shell \([0-9]\+\).*/\1/p')
if [[ -n $shell_version ]]; then
    echo "GNOME Shell $shell_version detected."
    sudo -u "$target_user" python3 - \
        "$extension_dst/metadata.json" "$shell_version" <<'PYTHON'
import json
import sys

path, version = sys.argv[1], sys.argv[2]
with open(path, encoding="utf-8") as f:
    data = json.load(f)
versions = [str(v) for v in data.get("shell-version", [])]
if version not in versions:
    data["shell-version"] = sorted([*versions, version],
                                   key=lambda v: int(v.split(".")[0]))
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        f.write("\n")
PYTHON
else
    echo "Warning: gnome-shell was not found; the sidecar cannot load without" >&2
    echo "a GNOME session, and autoscroll stays inactive without the sidecar." >&2
fi

if command -v restorecon >/dev/null; then
    restorecon -F /usr/local/bin/bazzite-hyperscroll \
        /usr/local/bin/hyperscrollctl \
        "/etc/systemd/system/$service_name" \
        /etc/udev/rules.d/99-bazzite-hyperscroll.rules \
        /etc/bazzite-hyperscroll.conf >/dev/null 2>&1 || true
    restorecon -RF "$extension_dst" >/dev/null 2>&1 || true
fi

modprobe uinput
udevadm control --reload-rules
udevadm trigger --action=change --subsystem-match=input
udevadm trigger --action=change --subsystem-match=misc --sysname-match=uinput
udevadm settle

for entry in "${selected[@]}"; do
    node=${entry%%$'\t'*}
    if ! sudo -u "$service_account" test -r "$node"; then
        echo "The ACL for $node was not applied; refusing to start." >&2
        echo "Check /etc/udev/rules.d/99-bazzite-hyperscroll.rules against" >&2
        echo "    udevadm info --query=property --name=$node" >&2
        exit 1
    fi
done
if ! sudo -u "$service_account" test -w /dev/uinput; then
    echo "The targeted uinput ACL was not applied; refusing to start." >&2
    exit 1
fi

systemctl daemon-reload
systemctl enable "$service_name"
systemctl restart "$service_name"

# Type=notify proves the hotplug monitor is alive. This separate marker proves
# the selected Razer is actually mirrored, without making boot restart-loop
# when the receiver is temporarily disconnected.
grabbed=false
for _attempt in {1..50}; do
    if [[ -s /run/bazzite-hyperscroll/grabbed ]]; then
        grabbed=true
        break
    fi
    sleep 0.2
done
if [[ $grabbed != true ]]; then
    echo "The service started but did not grab the selected mouse." >&2
    journalctl -u "$service_name" -n 30 --no-pager >&2 || true
    exit 1
fi

extension_enabled=false
if [[ -S $runtime_dir/bus ]]; then
    # Write the enabled-extension setting directly as well as asking the
    # current Shell. A new Wayland extension cannot load code until the next
    # login, but this guarantees that it loads automatically then.
    if sudo -u "$target_user" env \
        XDG_RUNTIME_DIR="$runtime_dir" \
        DBUS_SESSION_BUS_ADDRESS="unix:path=$runtime_dir/bus" \
        python3 -c 'from gi.repository import Gio; import sys; s=Gio.Settings.new("org.gnome.shell"); u=sys.argv[1]; d=[x for x in s.get_strv("disabled-extensions") if x != u]; e=s.get_strv("enabled-extensions"); e=e if u in e else [*e, u]; ok=s.set_strv("disabled-extensions", d) and s.set_strv("enabled-extensions", e); Gio.Settings.sync(); raise SystemExit(0 if ok else 1)' \
        "$extension_uuid"; then
        extension_enabled=true
    fi
    sudo -u "$target_user" env \
        XDG_RUNTIME_DIR="$runtime_dir" \
        DBUS_SESSION_BUS_ADDRESS="unix:path=$runtime_dir/bus" \
        gnome-extensions enable "$extension_uuid" >/dev/null 2>&1 || true
fi

echo
echo "Bazzite HyperScroll is installed and enabled at every boot."
echo "Emergency stop:  hyperscrollctl kill"
echo "Status/logs:      hyperscrollctl status | hyperscrollctl logs"
if [[ $extension_enabled == true ]]; then
    echo "Log out and back in once so GNOME loads the new sidecar automatically."
else
    echo "Could not update GNOME's extension setting. After logging back in, run:"
    echo "  gnome-extensions enable $extension_uuid"
fi
