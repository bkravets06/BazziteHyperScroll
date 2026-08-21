"""Device enumeration, against a stand-in for /sys/class/hidraw.

Enumeration is the step most likely to misbehave on a real machine, and the
one hardest to notice going wrong: picking the keyboard's HID interface instead
of its raw HID interface would fail in confusing ways rather than obviously.
"""

import pathlib
import tempfile
import unittest
from unittest import mock

from keychron_zen.protocol import hidraw
from keychron_zen.protocol.hid_descriptor import RAW_USAGE_ID, RAW_USAGE_PAGE

RAW_HID_DESCRIPTOR = bytes([
    0x06, 0x60, 0xFF, 0x09, 0x61, 0xA1, 0x01,
    0x09, 0x62, 0x15, 0x00, 0x26, 0xFF, 0x00, 0x95, 0x20, 0x75, 0x08, 0x81, 0x02,
    0xC0,
])

KEYBOARD_DESCRIPTOR = bytes([
    0x05, 0x01, 0x09, 0x06, 0xA1, 0x01,
    0x05, 0x07, 0x19, 0xE0, 0x29, 0xE7, 0x15, 0x00, 0x25, 0x01,
    0x95, 0x08, 0x75, 0x01, 0x81, 0x02, 0xC0,
])


class FakeSysfs:
    """Builds the two files enumeration reads for each hidraw node."""

    def __init__(self, root: pathlib.Path):
        self.sysfs = root / "sys"
        self.dev = root / "dev"
        self.sysfs.mkdir()
        self.dev.mkdir()

    def add(self, node, *, bus=0x03, vendor=0x3434, product=0x0AD0,
            name="Keychron Keychron K13 Max", descriptor=RAW_HID_DESCRIPTOR):
        device = self.sysfs / node / "device"
        device.mkdir(parents=True)
        (device / "uevent").write_text(
            "DRIVER=hid-generic\n"
            f"HID_ID={bus:04X}:{vendor:08X}:{product:08X}\n"
            f"HID_NAME={name}\n"
            "HID_PHYS=usb-0000:00:14.0-3/input1\n"
        )
        (device / "report_descriptor").write_bytes(descriptor)
        (self.dev / node).write_bytes(b"")


class EnumerationTests(unittest.TestCase):
    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp.cleanup)
        self.fake = FakeSysfs(pathlib.Path(self._temp.name))
        patcher = mock.patch.multiple(
            hidraw, SYSFS_ROOT=self.fake.sysfs, DEV_ROOT=self.fake.dev
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_finds_the_raw_hid_interface_only(self):
        # A real keyboard shows up as several nodes; only one takes VIA commands.
        self.fake.add("hidraw0", descriptor=KEYBOARD_DESCRIPTOR)
        self.fake.add("hidraw1", descriptor=RAW_HID_DESCRIPTOR)

        found = hidraw.enumerate_raw_hid()
        self.assertEqual([device.node for device in found], ["hidraw1"])

    def test_reads_identity_from_uevent(self):
        self.fake.add("hidraw3", vendor=0x3434, product=0x0AD1)
        device = hidraw.enumerate_raw_hid()[0]
        self.assertEqual((device.vendor_id, device.product_id), (0x3434, 0x0AD1))
        self.assertEqual(device.product, "Keychron Keychron K13 Max")
        self.assertEqual(device.report_bytes, 32)
        self.assertFalse(device.is_bluetooth)

    def test_reports_bluetooth_transport(self):
        self.fake.add("hidraw4", bus=0x05)
        self.assertTrue(hidraw.enumerate_raw_hid()[0].is_bluetooth)

    def test_filters_by_vendor(self):
        self.fake.add("hidraw0", vendor=0x3434)
        self.fake.add("hidraw1", vendor=0x1234)
        self.assertEqual(len(hidraw.enumerate_raw_hid(vendor_id=0x3434)), 1)
        self.assertEqual(len(hidraw.enumerate_raw_hid()), 2)

    def test_unreadable_devices_are_still_listed(self):
        """"Found it but cannot open it" must be distinguishable from "not there"."""
        self.fake.add("hidraw0")
        (self.fake.dev / "hidraw0").chmod(0o000)
        with mock.patch.object(hidraw.os, "access", return_value=False):
            device = hidraw.enumerate_raw_hid()[0]
        self.assertFalse(device.readable)

    def test_skips_nodes_with_unreadable_metadata(self):
        (self.fake.sysfs / "hidraw9").mkdir()
        self.fake.add("hidraw0")
        self.assertEqual([d.node for d in hidraw.enumerate_raw_hid()], ["hidraw0"])

    def test_opening_without_permission_raises_a_clear_error(self):
        self.fake.add("hidraw0")
        device = hidraw.enumerate_raw_hid()[0]
        with mock.patch.object(hidraw.os, "open", side_effect=PermissionError(13, "denied")):
            with self.assertRaises(hidraw.PermissionDeniedError):
                hidraw.HidRawDevice(device)


class IoctlTests(unittest.TestCase):
    def test_request_codes_match_linux_hidraw_h(self):
        """These constants are hand-encoded, so pin them to their known values."""
        self.assertEqual(hidraw.HIDIOCGRDESCSIZE, 0x80044801)
        self.assertEqual(hidraw.HIDIOCGRAWINFO, 0x80084803)

    def test_raw_hid_usage_constants(self):
        self.assertEqual((RAW_USAGE_PAGE, RAW_USAGE_ID), (0xFF60, 0x61))


if __name__ == "__main__":
    unittest.main()
