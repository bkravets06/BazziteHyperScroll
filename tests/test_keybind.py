#!/usr/bin/env python3
"""Tests for the GNOME shortcut helper.

PyGObject is a session dependency, so the helper is exercised against a
stand-in that records every settings write. What matters here is not that
GNOME accepts the values - it is that the helper adds exactly one entry, at
its own path, and never disturbs shortcuts the user set up themselves.
"""
import importlib.machinery
import importlib.util
import pathlib
import sys
import types
import unittest


class FakeSettings:
    """One dconf schema (optionally at a path), backed by a dict."""

    def __init__(self, store):
        self.store = store

    def get_strv(self, key):
        return list(self.store.get(key, []))

    def set_strv(self, key, value):
        self.store[key] = list(value)
        return True

    def get_string(self, key):
        return self.store.get(key, "")

    def set_string(self, key, value):
        self.store[key] = value
        return True

    def reset(self, key):
        self.store.pop(key, None)


class FakeGio:
    def __init__(self):
        self.stores = {}

    def _settings(self, name):
        return FakeSettings(self.stores.setdefault(name, {}))

    # The Gio.Settings surface the helper uses.
    @property
    def Settings(self):
        gio = self

        class Settings:
            @staticmethod
            def new(schema):
                return gio._settings(schema)

            @staticmethod
            def new_with_path(schema, path):
                return gio._settings(f"{schema}:{path}")

            @staticmethod
            def sync():
                gio.synced = True

        return Settings


def load_helper(gio):
    """Import the helper with a stand-in gi.repository.Gio in place."""
    source = pathlib.Path(__file__).parents[1] / "src" / "hyperscroll-keybind"
    repository = types.ModuleType("gi.repository")
    repository.Gio = gio
    gi = types.ModuleType("gi")
    gi.repository = repository
    saved = {name: sys.modules.get(name)
             for name in ("gi", "gi.repository")}
    sys.modules["gi"] = gi
    sys.modules["gi.repository"] = repository
    try:
        loader = importlib.machinery.SourceFileLoader(
            "hyperscroll_keybind", str(source))
        module = importlib.util.module_from_spec(
            importlib.util.spec_from_loader(loader.name, loader))
        loader.exec_module(module)
        return module
    finally:
        for name, value in saved.items():
            if value is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = value


class KeybindTests(unittest.TestCase):
    def setUp(self):
        self.gio = FakeGio()
        self.kb = load_helper(self.gio)
        self.media = self.gio.stores.setdefault(self.kb.MEDIA_KEYS, {})
        self.entry = self.gio.stores.setdefault(
            f"{self.kb.CUSTOM_SCHEMA}:{self.kb.CUSTOM_PATH}", {})

    def test_set_registers_one_entry_that_runs_the_toggle(self):
        self.assertEqual(self.kb.set_accel("<Ctrl><Alt>m"), 0)
        self.assertEqual(self.media["custom-keybindings"],
                         [self.kb.CUSTOM_PATH])
        self.assertEqual(self.entry["binding"], "<Ctrl><Alt>m")
        self.assertEqual(self.entry["command"], self.kb.COMMAND)
        self.assertIn("toggle", self.kb.COMMAND)

    def test_existing_user_shortcuts_are_preserved(self):
        mine = "/org/gnome/settings-daemon/plugins/media-keys/" \
               "custom-keybindings/custom0/"
        self.media["custom-keybindings"] = [mine]
        self.kb.set_accel("<Super><Shift>m")
        self.assertEqual(self.media["custom-keybindings"],
                         [mine, self.kb.CUSTOM_PATH])
        self.kb.clear()
        self.assertEqual(self.media["custom-keybindings"], [mine])

    def test_rebinding_does_not_add_a_second_entry(self):
        self.kb.set_accel("<Super><Shift>m")
        self.kb.set_accel("<Ctrl><Alt>m")
        self.assertEqual(self.media["custom-keybindings"],
                         [self.kb.CUSTOM_PATH])
        self.assertEqual(self.entry["binding"], "<Ctrl><Alt>m")

    def test_clear_is_safe_when_nothing_is_bound(self):
        self.assertEqual(self.kb.clear(), 0)
        self.assertEqual(self.media["custom-keybindings"], [])

    def test_an_empty_shortcut_is_refused(self):
        self.assertEqual(self.kb.set_accel("  "), 2)
        self.assertEqual(self.media.get("custom-keybindings", []), [])

    def test_unknown_action_reports_usage(self):
        self.assertEqual(self.kb.main(["hyperscroll-keybind", "wat"]), 2)

    def test_set_without_an_accel_uses_the_default(self):
        self.assertEqual(self.kb.main(["hyperscroll-keybind", "set"]), 0)
        self.assertEqual(self.entry["binding"], self.kb.DEFAULT_ACCEL)


if __name__ == "__main__":
    unittest.main(verbosity=2)
