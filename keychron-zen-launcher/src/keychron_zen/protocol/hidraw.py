"""Linux ``hidraw`` transport.

Everything here talks to ``/dev/hidraw*`` directly. There is deliberately no
dependency on ``hidapi`` or any other C extension: the app targets Linux only,
the kernel already exposes the whole interface we need, and a pure-Python
transport keeps the Flatpak build to "copy some files in".

Enumeration reads ``/sys/class/hidraw`` rather than opening devices, because
sysfs is world-readable while the device nodes are not. That lets the app
distinguish "no keyboard plugged in" from "keyboard is there but you have no
permission to talk to it", which is the single most common way this kind of
tool fails on Linux.
"""

from __future__ import annotations

import array
import errno
import fcntl
import os
import pathlib
import select
from dataclasses import dataclass

from .hid_descriptor import find_raw_hid

SYSFS_ROOT = pathlib.Path("/sys/class/hidraw")
DEV_ROOT = pathlib.Path("/dev")

BUS_BLUETOOTH = 0x05

# ioctl request encoding, asm-generic/ioctl.h
_IOC_READ = 2
_HID_IOC_MAGIC = ord("H")


def _ior(number: int, size: int) -> int:
    return (_IOC_READ << 30) | (size << 16) | (_HID_IOC_MAGIC << 8) | number


HIDIOCGRDESCSIZE = _ior(0x01, 4)
HIDIOCGRDESC = _ior(0x02, 4 + 4096)
HIDIOCGRAWINFO = _ior(0x03, 8)


def _hidiocgrawname(length: int) -> int:
    return _ior(0x04, length)


class HidError(OSError):
    """Raised when a hidraw node cannot be used."""


class PermissionDeniedError(HidError):
    """The device exists but the user may not open it.

    Almost always means the udev rule has not been installed; the UI turns
    this into an actionable message rather than a stack trace.
    """


@dataclass(frozen=True)
class HidDeviceInfo:
    """A raw-HID capable interface discovered on the system."""

    path: str
    vendor_id: int
    product_id: int
    product: str
    bus: int
    report_bytes: int
    readable: bool

    @property
    def node(self) -> str:
        return pathlib.Path(self.path).name

    @property
    def is_bluetooth(self) -> bool:
        return self.bus == BUS_BLUETOOTH

    def __str__(self) -> str:
        return f"{self.product} ({self.vendor_id:04X}:{self.product_id:04X}) on {self.node}"


def _parse_uevent(text: str) -> dict[str, str]:
    values = {}
    for line in text.splitlines():
        key, _, value = line.partition("=")
        if value:
            values[key] = value
    return values


def _info_from_sysfs(entry: pathlib.Path) -> tuple[int, int, int, str] | None:
    """Return ``(bus, vid, pid, name)`` for a ``/sys/class/hidraw`` entry."""
    try:
        uevent = _parse_uevent((entry / "device" / "uevent").read_text())
    except OSError:
        return None
    # HID_ID is "bus:vendor:product", each field zero-padded hex.
    hid_id = uevent.get("HID_ID", "")
    parts = hid_id.split(":")
    if len(parts) != 3:
        return None
    try:
        bus, vendor, product = (int(part, 16) for part in parts)
    except ValueError:
        return None
    return bus, vendor & 0xFFFF, product & 0xFFFF, uevent.get("HID_NAME", "HID device")


def _descriptor_from_sysfs(entry: pathlib.Path) -> bytes | None:
    try:
        return (entry / "device" / "report_descriptor").read_bytes()
    except OSError:
        return None


def _descriptor_from_ioctl(fd: int) -> bytes:
    size = array.array("i", [0])
    fcntl.ioctl(fd, HIDIOCGRDESCSIZE, size, True)
    buffer = array.array("B", bytes(4 + 4096))
    buffer[0:4] = array.array("B", int(size[0]).to_bytes(4, "little"))
    fcntl.ioctl(fd, HIDIOCGRDESC, buffer, True)
    return bytes(buffer[4 : 4 + size[0]])


def _info_from_ioctl(path: pathlib.Path) -> HidDeviceInfo | None:
    """Fall back to ioctls when sysfs is unavailable (some sandboxes)."""
    try:
        fd = os.open(path, os.O_RDWR)
    except OSError:
        return None
    try:
        info = array.array("B", bytes(8))
        fcntl.ioctl(fd, HIDIOCGRAWINFO, info, True)
        raw = bytes(info)
        bus = int.from_bytes(raw[0:4], "little")
        vendor = int.from_bytes(raw[4:6], "little")
        product = int.from_bytes(raw[6:8], "little")
        name = array.array("B", bytes(256))
        fcntl.ioctl(fd, _hidiocgrawname(256), name, True)
        label = bytes(name).split(b"\x00", 1)[0].decode("utf-8", "replace")
        collection = find_raw_hid(_descriptor_from_ioctl(fd))
        if collection is None:
            return None
        return HidDeviceInfo(
            path=str(path),
            vendor_id=vendor,
            product_id=product,
            product=label,
            bus=bus,
            report_bytes=collection.report_bytes or 32,
            readable=True,
        )
    except OSError:
        return None
    finally:
        os.close(fd)


def _readable(path: pathlib.Path) -> bool:
    return os.access(path, os.R_OK | os.W_OK)


def enumerate_raw_hid(vendor_id: int | None = None) -> list[HidDeviceInfo]:
    """List every interface that speaks VIA's raw HID protocol.

    Devices the user cannot open are still returned, with ``readable`` unset,
    so callers can explain what to do about it.
    """
    found: list[HidDeviceInfo] = []
    if SYSFS_ROOT.is_dir():
        for entry in sorted(SYSFS_ROOT.iterdir()):
            identity = _info_from_sysfs(entry)
            if identity is None:
                continue
            bus, vendor, product, name = identity
            if vendor_id is not None and vendor != vendor_id:
                continue
            descriptor = _descriptor_from_sysfs(entry)
            if descriptor is None:
                continue
            collection = find_raw_hid(descriptor)
            if collection is None:
                continue
            node = DEV_ROOT / entry.name
            found.append(
                HidDeviceInfo(
                    path=str(node),
                    vendor_id=vendor,
                    product_id=product,
                    product=name,
                    bus=bus,
                    report_bytes=collection.report_bytes or 32,
                    readable=_readable(node),
                )
            )
    else:  # pragma: no cover - only hit where sysfs is not mounted
        for node in sorted(DEV_ROOT.glob("hidraw*")):
            info = _info_from_ioctl(node)
            if info is not None and (vendor_id is None or info.vendor_id == vendor_id):
                found.append(info)
    return found


class HidRawDevice:
    """An open raw-HID interface.

    QMK's raw HID uses unnumbered reports, so writes are prefixed with a zero
    report ID and reads come back without one.
    """

    def __init__(self, info: HidDeviceInfo, timeout: float = 1.0):
        self.info = info
        self.timeout = timeout
        self.report_bytes = info.report_bytes or 32
        try:
            self._fd = os.open(info.path, os.O_RDWR | os.O_NONBLOCK)
        except PermissionError as exc:
            raise PermissionDeniedError(
                exc.errno,
                f"cannot open {info.path}: permission denied",
                info.path,
            ) from exc
        except OSError as exc:
            raise HidError(exc.errno, f"cannot open {info.path}: {exc.strerror}", info.path) from exc

    def close(self) -> None:
        if self._fd >= 0:
            os.close(self._fd)
            self._fd = -1

    def __enter__(self) -> "HidRawDevice":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    @property
    def closed(self) -> bool:
        return self._fd < 0

    def write(self, payload: bytes) -> None:
        if self.closed:
            raise HidError(errno.EBADF, "device is closed")
        packet = bytes([0x00]) + payload.ljust(self.report_bytes, b"\x00")
        written = 0
        while True:
            try:
                written = os.write(self._fd, packet)
                break
            except BlockingIOError:
                self._wait(select_write=True)
        if written != len(packet):
            raise HidError(errno.EIO, f"short write ({written} of {len(packet)} bytes)")

    def read(self) -> bytes:
        if self.closed:
            raise HidError(errno.EBADF, "device is closed")
        while True:
            try:
                return os.read(self._fd, self.report_bytes)
            except BlockingIOError:
                self._wait(select_write=False)

    def _wait(self, select_write: bool) -> None:
        readable, writable, _ = select.select(
            [] if select_write else [self._fd],
            [self._fd] if select_write else [],
            [],
            self.timeout,
        )
        if not readable and not writable:
            raise TimeoutError(f"no response from {self.info.node} within {self.timeout:g}s")
