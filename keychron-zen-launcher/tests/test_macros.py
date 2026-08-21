"""VIA macro buffer encoding and the text form used by the editor."""

import unittest

from keychron_zen.protocol import macros


class TextRoundTripTests(unittest.TestCase):
    def test_round_trip(self):
        text = "Hello{+KC_LSFT}world{-KC_LSFT}{250}!{KC_ENT}"
        actions = macros.from_text(text)
        self.assertEqual(macros.to_text(actions), text)
        self.assertEqual(macros.to_text(macros.decode(macros.encode(actions))), text)

    def test_action_shapes(self):
        actions = macros.from_text("hi{KC_A}{+KC_LSFT}{-KC_LSFT}{75}")
        self.assertEqual(
            actions,
            [
                macros.Text("hi"),
                macros.Tap(0x04),
                macros.Down(0xE1),
                macros.Up(0xE1),
                macros.Delay(75),
            ],
        )

    def test_escapes(self):
        for text in ("brace \\{ here", "back \\\\ slash", "\\{\\\\"):
            with self.subTest(text=text):
                self.assertEqual(macros.to_text(macros.from_text(text)), text)


class WireFormatTests(unittest.TestCase):
    def test_matches_the_firmware_encoding(self):
        """Bytes must match what dynamic_keymap_macro_send expects."""
        self.assertEqual(macros.encode([macros.Tap(0x04)]), b"\x01\x01\x04")
        self.assertEqual(macros.encode([macros.Down(0xE1)]), b"\x01\x02\xe1")
        self.assertEqual(macros.encode([macros.Up(0xE1)]), b"\x01\x03\xe1")
        # Delays are decimal digits terminated by a pipe, not a binary value.
        self.assertEqual(macros.encode([macros.Delay(250)]), b"\x01\x04250|")
        self.assertEqual(macros.encode([macros.Text("ab")]), b"ab")

    def test_buffer_split_and_join(self):
        entries = [macros.from_text("one"), macros.from_text("two{50}"), []]
        buffer = macros.join_buffer(entries, 64)
        self.assertEqual(len(buffer), 64)
        self.assertEqual(
            [macros.to_text(macro) for macro in macros.split_buffer(buffer, 3)],
            ["one", "two{50}", ""],
        )

    def test_join_refuses_to_overflow(self):
        with self.assertRaises(macros.MacroError):
            macros.join_buffer([macros.from_text("x" * 40)], 16)

    def test_trailing_slots_decode_as_empty(self):
        buffer = macros.join_buffer([macros.from_text("only")], 32)
        self.assertEqual(
            [macros.to_text(macro) for macro in macros.split_buffer(buffer, 4)],
            ["only", "", "", ""],
        )


class ErrorTests(unittest.TestCase):
    def test_rejects_bad_text(self):
        for text in ("{", "{}", "{NOPE}", "{99999}", "{MO(1)}"):
            with self.subTest(text=text), self.assertRaises(macros.MacroError):
                macros.from_text(text)

    def test_rejects_unencodable_characters(self):
        with self.assertRaises(macros.MacroError):
            macros.encode([macros.Text("café")])

    def test_rejects_malformed_bytes(self):
        for data in (b"\x01", b"\x01\x01", b"\x01\x09\x04", b"\x01\x04250"):
            with self.subTest(data=data), self.assertRaises(macros.MacroError):
                macros.decode(data)


if __name__ == "__main__":
    unittest.main()
