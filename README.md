# Bazzite HyperScroll

Bazzite HyperScroll adds Windows-style, click-to-toggle middle-button
autoscroll to this Bazzite GNOME/Wayland desktop.

It is tailored to the connected **Razer Viper V3 Pro**. A middle click in
an enabled app starts scrolling, a small anchor appears, and moving the
pointer above or below that anchor controls direction and speed. Any mouse
button press stops it. The service starts automatically at boot; the GNOME
sidecar loads automatically with the desktop session.

## Defaults

- Enabled for Zen and other browsers, plus ordinary desktop apps.
- Native middle-button behavior is preserved over GNOME panels/docks and in
  configured CAD, slicer, game, and launcher apps.
- Vertical scrolling only. Set `HORIZONTAL_SCROLL = true` if diagonal
  panning is wanted.
- The speed curve uses GNOME's actual accelerated screen-pixel distance, so
  mouse DPI changes do not unexpectedly alter the ramp.
- If the GNOME sidecar is missing or stale, HyperScroll fails safe: it
  preserves native middle-button behavior or pauses scrolling.

## Requirements

- A GNOME session (Wayland or X11). The sidecar is a GNOME Shell extension,
  and by default HyperScroll keeps the middle button native whenever no
  sidecar is reporting, so it stays inactive on other desktops.
- `python3-evdev`. On Bazzite's immutable base, install it once with
  `rpm-ostree install python3-evdev` and reboot if the installer says it is
  missing.

## Install

Clone the repository and run the installer from its top level:

```bash
git clone https://github.com/bkravets06/bazzitehyperscroll.git
cd bazzitehyperscroll
./install.sh
```

The installer prints which mouse it selected before it changes anything, and
refuses to continue if none is connected or if the device ACL did not apply.

The installer requests sudo once, installs only persistent Bazzite-friendly
paths under `/usr/local` and `/etc`, enables the system service, and installs
the per-user GNOME extension. It does not layer an RPM.

A newly installed GNOME Shell extension requires **one logout/login** on a
Wayland session. After that, there is nothing to launch manually.

## Use

1. Middle-click once in Zen or another enabled app.
2. Move upward to scroll up or downward to scroll down. Greater distance
   means greater speed.
3. Press any mouse button to stop.

The middle button is dedicated to HyperScroll in enabled apps, so a plain
middle click no longer opens a browser link in a new tab there. Apps in the
blacklist receive native middle-button input unchanged.

The Linux input stack delivers injected wheel events to the app under the
current pointer, not permanently to the window where scrolling began. Keep
the pointer over the target app. Entering GNOME Shell UI or a blacklisted app
stops the active scroll.

## Status, tuning, and recovery

```bash
hyperscrollctl doctor
hyperscrollctl status
hyperscrollctl logs
hyperscrollctl edit
```

`hyperscrollctl doctor` prints the whole picture in one go: whether the
service is running, which mouse it grabbed, whether the GNOME sidecar is
loaded, the active configuration, and recent warnings. It is the first thing
to run when something does not behave.

`hyperscrollctl edit` opens `/etc/bazzite-hyperscroll.conf` and restarts the
service after editing. The most useful settings are:

- `SPEED_MULT`: overall acceleration; raise it for more speed.
- `SPEED_EXP`: how sharply speed ramps with distance.
- `DEADZONE_PX`: no-scroll radius around the anchor.
- `MAX_PX_PER_SEC`: top-speed safety cap.
- `PX_PER_NOTCH`: lower values produce more wheel motion.
- `HORIZONTAL_SCROLL`: opt-in horizontal panning.
- `BLACKLIST`: comma-separated GNOME app-ID or WM-class fragments that keep
  native middle-button behavior.
- `ONLY_DEVICES`: which mouse is used. It ships as the name fragment
  `Viper V3 Pro`, which matches that mouse over its 2.4 GHz dongle, its
  cable, and Bluetooth alike. `hyperscrollctl devices` lists every device
  with its identifier and what HyperScroll does with it.

If input ever behaves unexpectedly, the keyboard command below immediately
stops the daemon. Closing the process releases the kernel's exclusive mouse
grab automatically.

```bash
hyperscrollctl kill
```

## When nothing scrolls

Run `hyperscrollctl doctor` first; it answers most of this in one screen.

The usual cause is the GNOME sidecar not being loaded. HyperScroll keeps the
middle button native whenever no sidecar is reporting a focused window, so a
sidecar that never loaded looks exactly like a feature that does nothing. The
journal says so explicitly the first time a middle click is left native:

```bash
journalctl -u bazzite-hyperscroll.service -b | grep 'left native'
```

Things worth checking, in order:

1. `gnome-extensions info bazzite-hyperscroll@local` reports `ACTIVE`. If it
   reports `OUT OF DATE`, the running GNOME is newer than the version
   recorded in the extension. Rerun `./install.sh` - it stamps the running
   Shell version into the installed metadata - then log out and back in.
2. You logged out and back in once after installing. A new extension cannot
   load into a running Wayland session.
3. `hyperscrollctl doctor` shows a grabbed mouse. If not, `hyperscrollctl
   devices` shows what the daemon sees and why each device is or is not used.
4. The app is not in `BLACKLIST`, and the pointer is over an application
   window rather than a panel or the overview.

To remove the feature:

```bash
./uninstall.sh
```

The uninstaller leaves `/etc/bazzite-hyperscroll.conf` in place so personal
tuning is recoverable.

## How it works

The system service exclusively reads only the selected physical pointer,
mirrors its normal events through Linux `uinput`, and replaces the toggled
middle-click gesture with high-resolution wheel events. A small GNOME Shell
extension reports the app beneath the pointer, captures the anchor's screen
position, and renders its click-through badge. The core has no X11,
XWayland, browser, or compositor-injection dependency.

See [SECURITY.md](SECURITY.md) for the privilege boundary and failure model.

## Provenance and license

The input engine began from
[`gnhen/midscroll`](https://github.com/gnhen/midscroll), commit
`02bb4fb7e078494e0fa1820bb6302556e12ad334`, then was substantially adapted
for Bazzite, GNOME 50, this exact mouse, least-privilege startup, screen-pixel
tracking, and additional failure handling. Both the upstream and this
tailored package are released into the public domain under the Unlicense;
see [LICENSE](LICENSE).
