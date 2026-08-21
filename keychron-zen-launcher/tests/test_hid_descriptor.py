"""HID report descriptor parsing, used to pick the right /dev/hidraw node."""

import unittest

from keychron_zen.protocol.hid_descriptor import find_raw_hid, parse_collections

# The raw HID interface QMK emits: usage page 0xFF60, usage 0x61, 32-byte reports.
RAW_HID = bytes([
    0x06, 0x60, 0xFF, 0x09, 0x61, 0xA1, 0x01,
    0x09, 0x62, 0x15, 0x00, 0x26, 0xFF, 0x00, 0x95, 0x20, 0x75, 0x08, 0x81, 0x02,
    0x09, 0x63, 0x15, 0x00, 0x26, 0xFF, 0x00, 0x95, 0x20, 0x75, 0x08, 0x91, 0x02,
    0xC0,
])

# A plain boot keyboard interface, which must never be mistaken for raw HID.
KEYBOARD = bytes([
    0x05, 0x01, 0x09, 0x06, 0xA1, 0x01,
    0x05, 0x07, 0x19, 0xE0, 0x29, 0xE7, 0x15, 0x00, 0x25, 0x01,
    0x95, 0x08, 0x75, 0x01, 0x81, 0x02,
    0xC0,
])


class DescriptorTests(unittest.TestCase):
    def test_finds_raw_hid(self):
        collection = find_raw_hid(RAW_HID)
        self.assertIsNotNone(collection)
        self.assertEqual(collection.usage_page, 0xFF60)
        self.assertEqual(collection.usage, 0x61)
        self.assertEqual(collection.report_bytes, 32)

    def test_ignores_the_keyboard_interface(self):
        self.assertIsNone(find_raw_hid(KEYBOARD))

    def test_picks_raw_hid_out_of_several_collections(self):
        collections = parse_collections(KEYBOARD + RAW_HID)
        self.assertEqual(len(collections), 2)
        self.assertTrue(find_raw_hid(KEYBOARD + RAW_HID).is_raw_hid)

    def test_survives_a_truncated_descriptor(self):
        for length in range(len(RAW_HID)):
            with self.subTest(length=length):
                parse_collections(RAW_HID[:length])  # must not raise

    def test_ignores_long_items(self):
        # 0xFE introduces a long item; its payload must be skipped whole.
        descriptor = bytes([0xFE, 0x02, 0x00, 0xAA, 0xBB]) + RAW_HID
        self.assertIsNotNone(find_raw_hid(descriptor))


if __name__ == "__main__":
    unittest.main()
