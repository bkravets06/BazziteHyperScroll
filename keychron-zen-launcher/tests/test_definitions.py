"""Sanity checks on the bundled keyboard definitions.

These guard the generated JSON: a definition with an out-of-range matrix cell
or overlapping keys would render a broken keyboard and write keys to the wrong
place, and neither failure is obvious by eye.
"""

import unittest

from keychron_zen.model import definitions
from keychron_zen.protocol import keycodes


class DefinitionTests(unittest.TestCase):
    def setUp(self):
        self.definitions = definitions.load_all()

    def test_at_least_one_definition_is_bundled(self):
        self.assertTrue(self.definitions)

    def test_matrix_cells_are_in_range_and_unique(self):
        for definition in self.definitions:
            for name, keys in definition.layouts.items():
                with self.subTest(keyboard=definition.name, layout=name):
                    cells = [key.cell for key in keys]
                    self.assertEqual(len(cells), len(set(cells)), "duplicate matrix cell")
                    for key in keys:
                        self.assertLess(key.row, definition.rows)
                        self.assertLess(key.column, definition.columns)

    def test_keys_do_not_overlap(self):
        """Two caps sharing space means the layout data is wrong."""
        for definition in self.definitions:
            for name, keys in definition.layouts.items():
                with self.subTest(keyboard=definition.name, layout=name):
                    for index, first in enumerate(keys):
                        for second in keys[index + 1:]:
                            overlap = (
                                first.x < second.x + second.width
                                and second.x < first.x + first.width
                                and first.y < second.y + second.height
                                and second.y < first.y + first.height
                            )
                            self.assertFalse(
                                overlap, f"{first.cell} overlaps {second.cell}"
                            )

    def test_every_variant_points_at_a_real_layout(self):
        for definition in self.definitions:
            for variant in definition.variants:
                with self.subTest(keyboard=definition.name, product=variant.product_id):
                    self.assertIn(variant.layout, definition.layouts)

    def test_product_ids_are_unique(self):
        seen = set()
        for definition in self.definitions:
            for variant in definition.variants:
                key = (definition.vendor_id, variant.product_id)
                self.assertNotIn(key, seen)
                seen.add(key)

    def test_lighting_effects_are_indexed_from_zero(self):
        """The value a keyboard reports is an index into this list."""
        for definition in self.definitions:
            for variant in definition.variants:
                with self.subTest(keyboard=definition.name, product=variant.product_id):
                    values = [effect.value for effect in variant.lighting.effects]
                    self.assertEqual(values, list(range(len(values))))
                    self.assertEqual(variant.lighting.effects[0].name, "None")

    def test_custom_keycodes_sit_in_the_qk_kb_range(self):
        for definition in self.definitions:
            for variant in definition.variants:
                for entry in variant.custom_keycodes:
                    with self.subTest(name=entry.name):
                        self.assertGreaterEqual(entry.value, 0x7E00)
                        self.assertLessEqual(entry.value, 0x7E3F)

    def test_default_keymaps_are_parseable_and_complete(self):
        for definition in self.definitions:
            for variant in definition.variants:
                if not variant.default_keymap:
                    continue
                with self.subTest(keyboard=definition.name, product=variant.product_id):
                    keys = definition.keys(variant)
                    for layer in variant.default_keymap:
                        self.assertEqual(len(layer), len(keys))
                        for name in layer:
                            keycodes.parse(name)  # must not raise

    def test_default_keymap_grid_matches_the_matrix(self):
        for definition in self.definitions:
            for variant in definition.variants:
                if not variant.default_keymap:
                    continue
                grid = definition.default_keymap(variant)
                with self.subTest(keyboard=definition.name, product=variant.product_id):
                    self.assertEqual(len(grid), len(variant.default_keymap))
                    for layer in grid:
                        self.assertEqual(len(layer), definition.rows)
                        self.assertTrue(all(len(row) == definition.columns for row in layer))


class K13MaxTests(unittest.TestCase):
    """The board this project was written for."""

    def setUp(self):
        found = definitions.find(0x3434, 0x0AD0)
        self.assertIsNotNone(found, "the K13 Max ANSI RGB definition is missing")
        self.definition, self.variant = found

    def test_shape(self):
        self.assertEqual(self.definition.name, "Keychron K13 Max")
        self.assertEqual((self.definition.rows, self.definition.columns), (6, 17))
        self.assertEqual(len(self.definition.keys(self.variant)), 90)

    def test_iso_variant_has_one_more_key(self):
        _definition, iso = definitions.find(0x3434, 0x0AD1)
        self.assertEqual(len(self.definition.keys(iso)), 91)

    def test_rgb_and_white_variants_differ(self):
        _definition, white = definitions.find(0x3434, 0x0AD3)
        self.assertTrue(self.variant.lighting.has_color)
        self.assertFalse(white.lighting.has_color)
        self.assertEqual(white.lighting.kind, "led_matrix")

    def test_layers_are_named_for_the_mac_windows_switch(self):
        self.assertEqual(self.definition.layer_names,
                         ("Mac", "Mac Fn", "Windows", "Windows Fn"))
        self.assertEqual(self.definition.layer_name(0), "0 · Mac")

    def test_stock_keymap_matches_the_shipped_firmware(self):
        """Spot-check against keychron/k13_max keymaps/via/keymap.c."""
        grid = self.definition.default_keymap(self.variant)
        self.assertEqual(grid[0][0][0], keycodes.parse("KC_ESC"))
        self.assertEqual(grid[2][0][0], keycodes.parse("KC_ESC"))
        # Layer 1 is the Mac Fn layer: F-keys along the top, Bluetooth on 1-3.
        self.assertEqual(grid[1][0][2], keycodes.parse("KC_F1"))
        self.assertEqual(grid[1][1][1], 0x7E0B)  # BT_HST1


if __name__ == "__main__":
    unittest.main()
