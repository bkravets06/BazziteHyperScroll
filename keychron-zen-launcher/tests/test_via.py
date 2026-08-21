"""The VIA client, driven against the in-process simulated keyboard."""

import unittest

from keychron_zen.protocol import keycodes, macros, via
from keychron_zen.protocol.simulator import SimulatedKeyboard


class ViaProtocolTests(unittest.TestCase):
    def setUp(self):
        self.sim = SimulatedKeyboard()
        self.kb = via.ViaKeyboard(self.sim)

    def test_identification(self):
        self.assertEqual(self.kb.protocol_version(), via.PROTOCOL_VERSION)
        self.assertEqual(self.kb.layer_count(), 4)
        self.assertEqual(self.kb.firmware_version(), 0x00010000)

    def test_command_framing(self):
        """Byte 0 is the command id and the payload starts at byte 1."""
        self.kb.command(via.CMD_GET_PROTOCOL_VERSION)
        packet = self.sim.written[-1]
        self.assertEqual(len(packet), via.PACKET_SIZE)
        self.assertEqual(packet[0], via.CMD_GET_PROTOCOL_VERSION)

    def test_single_keycode_write(self):
        self.kb.set_keycode(1, 2, 3, keycodes.parse("MO(2)"))
        self.assertEqual(self.kb.get_keycode(1, 2, 3), keycodes.parse("MO(2)"))
        self.assertEqual(self.sim.keycode_at(1, 2, 3), keycodes.parse("MO(2)"))

    def test_keymap_bulk_read_and_write(self):
        keymap = self.kb.read_keymap(4, 6, 17)
        self.assertEqual((len(keymap), len(keymap[0]), len(keymap[0][0])), (4, 6, 17))

        keymap[2][3][4] = keycodes.parse("LT(1,KC_SPC)")
        keymap[0][0][0] = keycodes.parse("KC_ESC")
        self.kb.write_keymap(keymap)
        self.assertEqual(self.kb.read_keymap(4, 6, 17), keymap)

    def test_buffer_commands_are_chunked_to_28_bytes(self):
        """VIA moves at most 28 payload bytes per 32-byte packet."""
        self.kb.read_keymap(4, 6, 17)
        requests = [p for p in self.sim.written if p[0] == via.CMD_DYNAMIC_KEYMAP_GET_BUFFER]
        self.assertTrue(requests)
        self.assertTrue(all(packet[3] <= via.CHUNK_SIZE for packet in requests))
        # 4 layers x 6 rows x 17 columns x 2 bytes, in 28-byte chunks.
        self.assertEqual(len(requests), -(-4 * 6 * 17 * 2 // via.CHUNK_SIZE))

    def test_macro_buffer(self):
        self.assertEqual(self.kb.macro_count(), 16)
        size = self.kb.macro_buffer_size()
        buffer = macros.join_buffer([macros.from_text("hi{250}there")] + [[]] * 15, size)
        self.kb.write_macro_buffer(buffer)
        self.assertEqual(self.kb.read_macro_buffer(size), buffer)

    def test_lighting(self):
        state = self.kb.get_lighting(via.CHANNEL_RGB_MATRIX, True)
        self.assertTrue(state.has_color)

        self.kb.set_effect(via.CHANNEL_RGB_MATRIX, 7)
        self.kb.set_brightness(via.CHANNEL_RGB_MATRIX, 99)
        self.kb.set_color(via.CHANNEL_RGB_MATRIX, 20, 200)
        self.kb.save_lighting(via.CHANNEL_RGB_MATRIX)

        state = self.kb.get_lighting(via.CHANNEL_RGB_MATRIX, True)
        self.assertEqual((state.effect, state.brightness, state.hue, state.saturation),
                         (7, 99, 20, 200))
        self.assertEqual(self.sim.saved_channels, [via.CHANNEL_RGB_MATRIX])

    def test_switch_matrix_state(self):
        self.sim.press(0, 16)
        self.sim.press(2, 5)
        state = self.kb.switch_matrix_state(6, 17)
        pressed = {
            (row, column)
            for row, columns in enumerate(state)
            for column, down in enumerate(columns)
            if down
        }
        self.assertEqual(pressed, {(0, 16), (2, 5)})

    def test_releasing_a_key_clears_it(self):
        self.sim.press(1, 1)
        self.assertTrue(self.kb.switch_matrix_state(6, 17)[1][1])
        self.sim.release(1, 1)
        self.assertFalse(self.kb.switch_matrix_state(6, 17)[1][1])

    def test_switch_matrix_covers_every_row(self):
        state = self.kb.switch_matrix_state(6, 17)
        self.assertEqual(len(state), 6)
        self.assertTrue(all(len(row) == 17 for row in state))

    def test_unsupported_command_raises(self):
        with self.assertRaises(via.UnsupportedCommandError):
            self.kb.command(0x7E)

    def test_stale_replies_do_not_desynchronise(self):
        """A leftover reply must be read past, not returned as the answer."""

        class NoisyTransport:
            def __init__(self, inner):
                self.inner = inner
                self.pending = [bytes([0x42]).ljust(via.PACKET_SIZE, b"\x00")]

            def write(self, payload):
                self.inner.write(payload)

            def read(self):
                if self.pending:
                    return self.pending.pop()
                return self.inner.read()

        keyboard = via.ViaKeyboard(NoisyTransport(self.sim))
        self.assertEqual(keyboard.protocol_version(), via.PROTOCOL_VERSION)

    def test_eeprom_reset_clears_everything(self):
        self.kb.set_keycode(0, 0, 0, keycodes.parse("MO(3)"))
        self.kb.write_macro_buffer(macros.join_buffer([macros.from_text("x")], 896))
        self.kb.reset_eeprom()
        self.assertNotEqual(self.kb.get_keycode(0, 0, 0), keycodes.parse("MO(3)"))
        self.assertEqual(self.kb.read_macro_buffer(16), bytes(16))

    def test_indicate(self):
        self.kb.indicate()
        self.assertEqual(self.sim.indicated, 1)


if __name__ == "__main__":
    unittest.main()
