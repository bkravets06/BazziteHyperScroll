"""Keycode encoding, naming and parsing."""

import unittest

from keychron_zen.protocol import keycodes, labels


class RoundTripTests(unittest.TestCase):
    def test_every_keycode_round_trips(self):
        """name_for and parse must be exact inverses across the 16-bit space.

        Export/import writes names, so a single asymmetric value would quietly
        rewrite someone's keymap.
        """
        failures = []
        for value in range(0x10000):
            name = keycodes.name_for(value)
            try:
                parsed = keycodes.parse(name)
            except ValueError as exc:
                failures.append((value, name, str(exc)))
                continue
            if parsed != value:
                failures.append((value, name, parsed))
        self.assertEqual(failures[:8], [], f"{len(failures)} keycodes did not round-trip")


class EncodingTests(unittest.TestCase):
    def test_basic_keycodes(self):
        self.assertEqual(keycodes.parse("KC_A"), 0x0004)
        self.assertEqual(keycodes.parse("KC_NO"), 0x0000)
        self.assertEqual(keycodes.parse("KC_TRNS"), 0x0001)
        self.assertEqual(keycodes.parse("KC_LCTL"), 0x00E0)

    def test_modifier_combinations(self):
        # QK_MODS packs the mod mask into bits 8-12 of the keycode itself.
        self.assertEqual(keycodes.parse("LCTL(KC_A)"), 0x0104)
        self.assertEqual(keycodes.parse("LSFT(KC_A)"), 0x0204)
        self.assertEqual(keycodes.parse("RCTL(KC_A)"), 0x1104)
        self.assertEqual(keycodes.parse("LCTL(LSFT(KC_A))"), 0x0304)
        self.assertEqual(keycodes.name_for(0x0304), "LCTL(LSFT(KC_A))")

    def test_layer_functions(self):
        self.assertEqual(keycodes.parse("MO(1)"), 0x5221)
        self.assertEqual(keycodes.parse("TO(2)"), 0x5202)
        self.assertEqual(keycodes.parse("TG(3)"), 0x5263)
        self.assertEqual(keycodes.parse("OSL(1)"), 0x5281)
        self.assertEqual(keycodes.parse("TT(3)"), 0x52C3)
        self.assertEqual(keycodes.parse("DF(0)"), 0x5240)

    def test_tap_hold(self):
        self.assertEqual(keycodes.parse("LT(1,KC_SPC)"), 0x412C)
        self.assertEqual(keycodes.parse("LCTL_T(KC_A)"), 0x2104)
        self.assertEqual(keycodes.parse("MT(MOD_LCTL|MOD_LSFT,KC_A)"), 0x2304)
        self.assertEqual(keycodes.name_for(0x2104), "LCTL_T(KC_A)")

    def test_one_shot_and_layer_mod(self):
        self.assertEqual(keycodes.parse("OSM(MOD_LSFT)"), 0x52A2)
        self.assertEqual(keycodes.parse("LM(1,MOD_LCTL|MOD_LSFT)"), 0x5023)

    def test_macros(self):
        self.assertEqual(keycodes.parse("M0"), 0x7700)
        self.assertEqual(keycodes.parse("M15"), 0x770F)
        self.assertEqual(keycodes.name_for(0x7703), "M3")

    def test_raw_hex(self):
        self.assertEqual(keycodes.parse("0x7E0B"), 0x7E0B)
        self.assertEqual(keycodes.parse("0x1234"), 0x1234)

    def test_short_aliases_are_preferred(self):
        """People read KC_MPLY, not KC_MEDIA_PLAY_PAUSE."""
        self.assertEqual(keycodes.name_for(keycodes.parse("KC_MEDIA_PLAY_PAUSE")), "KC_MPLY")
        self.assertEqual(keycodes.name_for(keycodes.parse("RGB_MODE_FORWARD")), "RGB_MOD")

    def test_placeholder_names_are_never_displayed(self):
        # "_______" and "XXXXXXX" are keymap.c formatting, not key names.
        self.assertNotIn(keycodes.name_for(0x0001), ("_______", "XXXXXXX"))
        self.assertNotIn(keycodes.name_for(0x0000), ("_______", "XXXXXXX"))


class ParseErrorTests(unittest.TestCase):
    def test_rejects_nonsense(self):
        for text in ("", "NOPE", "MO(", "MO(x)", "LT(1)", "0xZZZZ", "0x10000",
                     "MT(,KC_A)", "LCTL(MO(1))"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                keycodes.parse(text)

    def test_rejects_out_of_range_layer(self):
        with self.assertRaises(ValueError):
            keycodes.parse("MO(99)")


class ModifierTests(unittest.TestCase):
    def test_names_and_labels(self):
        self.assertEqual(keycodes.modifier_names(0x03), ["LCTL", "LSFT"])
        self.assertEqual(keycodes.modifier_names(0x11), ["RCTL"])
        self.assertEqual(keycodes.modifier_label(0x03), "Ctrl+Shift")
        self.assertEqual(keycodes.modifier_label(0x12), "Right Shift")

    def test_parse_modifiers(self):
        self.assertEqual(keycodes.parse_modifiers("MOD_LCTL|MOD_LSFT"), 0x03)
        self.assertEqual(keycodes.parse_modifiers("RSFT"), 0x12)
        self.assertIsNone(keycodes.parse_modifiers("NOPE"))


class LabelTests(unittest.TestCase):
    def test_legends(self):
        self.assertEqual(labels.legend(keycodes.parse("KC_A")), ("A", ""))
        self.assertEqual(labels.legend(keycodes.parse("KC_ESC")), ("Esc", ""))
        self.assertEqual(labels.legend(keycodes.parse("MO(1)")), ("MO", "Layer 1"))
        self.assertEqual(labels.legend(keycodes.parse("LCTL_T(KC_A)")), ("A", "Ctrl"))
        self.assertEqual(labels.legend(keycodes.parse("M3")), ("Macro 3", ""))

    def test_custom_labels_win(self):
        legend = labels.legend(0x7E0B, {0x7E0B: "BT 1"})
        self.assertEqual(legend, ("BT 1", ""))

    def test_every_catalogue_entry_is_a_real_keycode(self):
        for title, entries in labels.categories():
            for value, name in entries:
                with self.subTest(category=title, name=name):
                    self.assertEqual(keycodes.parse(name), value)

    def test_search_finds_keys_by_plain_words(self):
        for query, expected in (
            ("volume", "KC_VOLU"),
            ("windows", "KC_LGUI"),
            ("escape", "KC_ESC"),
            ("numpad 5", "KC_P5"),
            ("bootloader", "QK_BOOT"),
        ):
            with self.subTest(query=query):
                hits = [
                    name
                    for _title, entries in labels.categories()
                    for value, name in entries
                    if labels.matches(labels.search_text(value, name), query)
                ]
                self.assertIn(expected, hits)


if __name__ == "__main__":
    unittest.main()
