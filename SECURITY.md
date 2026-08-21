# Security and failure model

Wayland intentionally does not let ordinary apps globally intercept a
physical mouse button and inject wheel events. HyperScroll therefore uses
the kernel evdev/uinput boundary, with the permissions narrowed to the task.

## Privileges

- The long-running daemon is **not root**. It runs as the dedicated,
  non-login `bazzite-hyperscroll` system account with no capabilities.
- A targeted udev rule adds a POSIX ACL to Razer pointer interfaces (USB
  vendor `1532`) and to any pointer interface named `Viper V3 Pro` on any
  transport, plus one to `/dev/uinput`. The pointer ACL is read/write
  because the kernel's evdev interface is opened `O_RDWR`; write access to
  an event node permits LED/force-feedback writes on that mouse, not reading
  any other device.
  Interfaces udev marks as keyboards (`ID_INPUT_KEYBOARD`) are excluded, so
  the mouse's connection mode can change without the feature breaking and
  without widening the rule to keyboards.
- It does not grant access to the Razer keyboard/control interface,
  keyboards, or the broad `input` group.
- Which node the daemon actually opens is decided separately by the
  root-owned `ONLY_DEVICES` list, and keyboard-class devices are refused
  before that list is consulted, so no config can point it at typing.
- ACLs are added without replacing Bazzite's existing device group or its
  Sunshine/uaccess permissions.
- The root-owned configuration is ignored if it is a symlink, not owned by
  root, group/world-writable, or unreasonably large.

Access to the selected evdev node reveals that mouse's movement and button
events, and permits writes to that one node. Access to `/dev/uinput` is inherently powerful: code that completely
compromised the service account could create synthetic keyboard or pointer
devices. The systemd sandbox reduces the surrounding impact with a closed
device policy, no network, no writable home/system tree, no capabilities,
no realtime scheduling, namespace and syscall restrictions, and memory/task
limits. This is still a trusted local input component and should be updated
only from reviewed source.

## GNOME sidecar and local socket

The unprivileged GNOME extension connects to a Unix socket under
`/run/bazzite-hyperscroll`. The daemon accepts reports only from a user that
logind considers logged in on a seat and accepts cursor offsets only from
the active user. Messages are bounded and contain app identity plus offset
from the anchor, never absolute pointer coordinates. The same active-user
check gates the on/off control verb, so a background session or a service
account cannot switch the feature on or off; the state it sets lives in the
runtime directory and is cleared by a reboot. Reports are advisory:
they can pause/resume eligibility but cannot change the root-owned device
selection or executable.

## Failure behavior

- The virtual mirror is created before the physical mouse is grabbed.
- Any setup failure closes the physical device without grabbing it.
- Unplug, cancellation, read/write failure, and unexpected pump errors all
  close the physical descriptor, which makes Linux release `EVIOCGRAB`.
- Forwarded held buttons are released during cleanup when the mirror still
  accepts writes.
- `SYN_DROPPED` input is discarded until the next complete report, then held
  state is reconciled.
- Transient uinput or competing-grab failures retry automatically.
- A systemd watchdog restarts a stalled event loop; process termination
  releases the physical grab before restart.
- If the GNOME focus/offset helper disappears, autoscroll fails safe rather
  than using stale focus or raw high-DPI distance.

Emergency stop:

```bash
hyperscrollctl kill
```
