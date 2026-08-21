"""Saving and loading a configuration file."""

import json
import unittest

from keychron_zen import config_io
from keychron_zen.model.device import Keyboard
from keychron_zen.protocol import keycodes, macros


class ExportTests(unittest.TestCase):
    def setUp(self):
        self.keyboard = Keyboard.demo()

    def test_export_shape(self):
        data = config_io.export(self.keyboard)
        self.assertEqual(data["format"], config_io.FORMAT)
        self.assertEqual(data["keyboard"]["product_id"], "0x0AD0")
        self.assertEqual(len(data["layers"]), 4)
        self.assertEqual(len(data["macros"]), 16)
        self.assertIn("lighting", data)

    def test_keycodes_are_written_as_names(self):
        data = config_io.export(self.keyboard)
        self.assertEqual(data["layers"][0]["keys"][0][0], "KC_ESC")

    def test_describe(self):
        data = config_io.export(self.keyboard)
        self.assertIn("Keychron K13 Max", config_io.describe(data))
        self.assertIn("4 layers", config_io.describe(data))


class RoundTripTests(unittest.TestCase):
    def test_configuration_survives_a_round_trip(self):
        source = Keyboard.demo()
        source.set_keycode(0, 0, 0, keycodes.parse("MO(1)"))
        source.set_keycode(2, 3, 4, keycodes.parse("LT(1,KC_SPC)"))
        source.set_macros([macros.from_text("hello{250}world")] + [[]] * 15)

        target = Keyboard.demo()
        data = config_io.loads(config_io.dumps(source))
        applied = config_io.apply(target, data)

        self.assertEqual(target.keymap, source.keymap)
        self.assertEqual(target.macros, source.macros)
        self.assertEqual(target.lighting, source.lighting)
        self.assertIn("4 layers", applied)


class GuardTests(unittest.TestCase):
    def setUp(self):
        self.keyboard = Keyboard.demo()
        self.data = config_io.loads(config_io.dumps(self.keyboard))

    def test_rejects_a_file_for_another_model(self):
        self.data["keyboard"]["product_id"] = "0x0AD1"
        with self.assertRaises(config_io.ConfigError):
            config_io.apply(self.keyboard, self.data)

    def test_force_overrides_the_model_check(self):
        self.data["keyboard"]["product_id"] = "0x0AD1"
        config_io.apply(self.keyboard, self.data, force=True)

    def test_rejects_foreign_files(self):
        with self.assertRaises(config_io.ConfigError):
            config_io.loads(json.dumps({"format": "via", "version": 1}))

    def test_rejects_invalid_json(self):
        with self.assertRaises(config_io.ConfigError):
            config_io.loads("{not json")

    def test_rejects_a_newer_format_version(self):
        self.data["version"] = config_io.VERSION + 1
        with self.assertRaises(config_io.ConfigError):
            config_io.loads(json.dumps(self.data))

    def test_rejects_a_wrong_sized_keymap(self):
        self.data["layers"][0]["keys"] = [["KC_A"]]
        with self.assertRaises(config_io.ConfigError):
            config_io.apply(self.keyboard, self.data)

    def test_rejects_an_unparseable_keycode(self):
        self.data["layers"][0]["keys"][0][0] = "NOT_A_KEY"
        with self.assertRaises(config_io.ConfigError) as caught:
            config_io.apply(self.keyboard, self.data)
        self.assertIn("layer 0", str(caught.exception))

    def test_a_rejected_keymap_is_not_partially_written(self):
        """Validation happens before anything reaches the keyboard."""
        before = [[row[:] for row in layer] for layer in self.keyboard.keymap]
        self.data["layers"][0]["keys"][0][0] = "NOT_A_KEY"
        self.data["layers"][1]["keys"][0][0] = "KC_B"
        with self.assertRaises(config_io.ConfigError):
            config_io.apply(self.keyboard, self.data)
        self.assertEqual(self.keyboard.keymap, before)

    def test_selective_apply(self):
        self.data["layers"][0]["keys"][0][0] = "KC_B"
        config_io.apply(self.keyboard, self.data, keymap=False)
        self.assertNotEqual(self.keyboard.keycode(0, 0, 0), keycodes.parse("KC_B"))


if __name__ == "__main__":
    unittest.main()
