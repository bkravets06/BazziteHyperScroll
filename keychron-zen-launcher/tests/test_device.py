"""The session layer that the window and the CLI both use."""

import unittest

from keychron_zen.model.device import Discovery, Keyboard
from keychron_zen.protocol import keycodes
from keychron_zen.protocol.hidraw import HidDeviceInfo


def info(**overrides) -> HidDeviceInfo:
    defaults = dict(
        path="/dev/hidraw3",
        vendor_id=0x3434,
        product_id=0x0AD0,
        product="Keychron K13 Max",
        bus=0x03,
        report_bytes=32,
        readable=True,
    )
    defaults.update(overrides)
    return HidDeviceInfo(**defaults)


class DiscoveryTests(unittest.TestCase):
    def test_a_readable_wired_device_is_usable(self):
        discovery = Discovery(info(), None, None)
        self.assertTrue(discovery.usable)
        self.assertIsNone(discovery.problem)

    def test_permission_problem_is_explained(self):
        discovery = Discovery(info(readable=False), None, None)
        self.assertFalse(discovery.usable)
        self.assertIn("udev", discovery.problem)

    def test_bluetooth_is_explained(self):
        # Keychron's firmware only accepts VIA over the cable.
        discovery = Discovery(info(bus=0x05), None, None)
        self.assertFalse(discovery.usable)
        self.assertIn("Bluetooth", discovery.problem)


class KeyboardTests(unittest.TestCase):
    def setUp(self):
        self.keyboard = Keyboard.demo()

    def test_demo_keyboard_loads_the_real_definition(self):
        self.assertTrue(self.keyboard.is_demo)
        self.assertTrue(self.keyboard.has_layout)
        self.assertEqual(self.keyboard.title, "Keychron K13 Max — ANSI, RGB backlight")
        self.assertEqual((self.keyboard.rows, self.keyboard.columns), (6, 17))
        self.assertEqual(self.keyboard.layer_count, 4)

    def test_demo_keyboard_starts_from_the_stock_keymap(self):
        self.assertEqual(self.keyboard.keycode(0, 0, 0), keycodes.parse("KC_ESC"))
        self.assertEqual(self.keyboard.changed_cells(0), set())

    def test_remapping_marks_the_cell_as_changed(self):
        self.keyboard.set_keycode(0, 0, 0, keycodes.parse("MO(1)"))
        self.assertEqual(self.keyboard.changed_cells(0), {(0, 0)})
        self.assertEqual(self.keyboard.default_keycode(0, 0, 0), keycodes.parse("KC_ESC"))

    def test_reset_restores_the_stock_keymap(self):
        self.keyboard.set_keycode(0, 0, 0, keycodes.parse("MO(1)"))
        self.keyboard.reset_keymap()
        self.assertEqual(self.keyboard.changed_cells(0), set())

    def test_lighting_channel_follows_the_variant(self):
        self.assertEqual(self.keyboard.lighting_channel, 3)  # QMK RGB matrix channel
        self.assertIsNotNone(self.keyboard.lighting)

    def test_custom_keycode_labels(self):
        self.assertEqual(self.keyboard.custom_keycode_labels[0x7E0B], "BT 1")

    def test_firmware_text(self):
        self.assertEqual(self.keyboard.firmware_text, "0.1.0")


if __name__ == "__main__":
    unittest.main()
