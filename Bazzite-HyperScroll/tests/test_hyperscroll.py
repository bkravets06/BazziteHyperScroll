#!/usr/bin/env python3
import importlib.machinery
import importlib.util
import os
import pathlib
import tempfile
import time
import types
import unittest
from unittest import mock

from evdev import InputEvent, ecodes as e


SOURCE = pathlib.Path(__file__).parents[1] / "src" / "bazzite-hyperscroll"
loader = importlib.machinery.SourceFileLoader("bazzite_hyperscroll", str(SOURCE))
spec = importlib.util.spec_from_loader(loader.name, loader)
hs = importlib.util.module_from_spec(spec)
loader.exec_module(hs)


class FakeUI:
    def __init__(self):
        self.events = []

    def write(self, event_type, code, value):
        self.events.append((event_type, code, value))

    def syn(self):
        self.events.append((e.EV_SYN, e.SYN_REPORT, 0))


class FakeFocus:
    def __init__(self, blocked=False):
        self.blocked = blocked


class FakeInfo:
    vendor = 0x1532
    product = 0x00C1


class FakeDevice:
    def __init__(self, name, keyboard=False):
        self.name = name
        self.phys = "usb-test/input0"
        self.info = FakeInfo()
        keys = [e.BTN_LEFT, e.BTN_MIDDLE]
        if keyboard:
            keys += list(hs.KEYBOARD_KEYS)
        self._caps = {e.EV_KEY: keys, e.EV_REL: [e.REL_X, e.REL_Y]}

    def capabilities(self):
        return self._caps


class FakeActiveDevice:
    def __init__(self, active=()):
        self.active = set(active)

    def active_keys(self):
        return list(self.active)


class HyperScrollTests(unittest.TestCase):
    def setUp(self):
        mutable_names = (
            set(hs.FLOAT_KEYS) | set(hs.BOOL_KEYS) | set(hs.DEVICE_KEYS)
            | {"ALLOWLIST", "BLACKLIST"}
        )
        self.saved = {
            name: getattr(hs, name)
            for name in mutable_names
        }
        hs.ALLOWLIST = []
        hs.BLACKLIST = ["bambu-studio", "steam"]
        hs.DESKTOP_SCROLL = False
        hs.ONLY_DEVICES = []
        hs.EXTRA_DEVICES = []
        hs.IGNORE_DEVICES = []
        hs.REQUIRE_FOCUS_HELPER = True
        hs.TOGGLE_MODE = True
        hs.HORIZONTAL_SCROLL = False

    def tearDown(self):
        for name, value in self.saved.items():
            setattr(hs, name, value)

    def test_focus_helper_fails_safe_and_blacklist_wins(self):
        focus = hs.FocusFilter()
        self.assertTrue(focus.blocked)
        zen = object()
        focus.update(zen, "app.zen_browser.zen.desktop|zen")
        self.assertFalse(focus.blocked)
        cad = object()
        focus.update(cad, "com.bambulab.BambuStudio.desktop|bambu-studio")
        self.assertTrue(focus.blocked)
        focus.remove(cad)
        self.assertFalse(focus.blocked)
        focus.remove(zen)
        self.assertTrue(focus.blocked)

    def test_allowlist_is_optional_and_case_insensitive(self):
        hs.ALLOWLIST = ["app.zen_browser", "org.gnome"]
        focus = hs.FocusFilter()
        client = object()
        focus.update(client, "APP.ZEN_BROWSER.ZEN.desktop|zen")
        self.assertFalse(focus.blocked)
        focus.update(client, "com.example.Other.desktop")
        self.assertTrue(focus.blocked)

    def test_focus_report_is_bounded_sanitized_and_desktop_is_opt_in(self):
        focus = hs.FocusFilter()
        client = object()
        focus.update(client, "org.gnome.shell\n" + "x" * hs.MAX_FOCUS_LEN)
        identity = focus.by_client[client]
        self.assertNotIn("\n", identity)
        self.assertEqual(len(identity), hs.MAX_FOCUS_LEN)
        self.assertTrue(focus.blocked)

        hs.DESKTOP_SCROLL = True
        self.assertFalse(focus.blocked)

    def test_stale_focus_heartbeat_fails_safe(self):
        focus = hs.FocusFilter()
        client = object()
        focus.update(client, "app.zen_browser.zen.desktop|zen")
        self.assertFalse(focus.blocked)
        focus.focus_stamp_by_client[client] = (
            time.monotonic() - hs.FOCUS_TTL - 0.1)
        self.assertTrue(focus.blocked)

    def test_freshest_screen_offset_wins_and_disconnect_removes_it(self):
        focus = hs.FocusFilter()
        older = object()
        newer = object()
        now = time.monotonic()
        focus.offset_by_client[older] = (now - 0.20, 10.0, 20.0)
        focus.offset_by_client[newer] = (now - 0.05, 30.0, 40.0)
        self.assertEqual(focus.offset, (30.0, 40.0))
        focus.remove(newer)
        self.assertEqual(focus.offset, (10.0, 20.0))
        focus.remove(older)
        self.assertIsNone(focus.offset)

    def test_screen_offset_is_clamped_and_expires(self):
        focus = hs.FocusFilter()
        client = object()
        focus.update_offset(client, 999999, -999999)
        self.assertEqual(focus.offset, (hs.MAX_DRAG_PX, -hs.MAX_DRAG_PX))
        _, dx, dy = focus.offset_by_client[client]
        focus.offset_by_client[client] = (time.monotonic() - 1.0, dx, dy)
        self.assertIsNone(focus.offset)

    def test_numeric_config_bounds_reject_nonfinite_and_unsafe_values(self):
        invalid = {
            "DEADZONE_PX": (-1, 501, float("nan")),
            "TICK_HZ": (0, 9, 361, float("inf")),
            "SPEED_MULT": (0, 101),
            "SPEED_EXP": (0, 5.1),
            "MAX_PX_PER_SEC": (0, 100001),
            "PX_PER_NOTCH": (0, 1001),
            "MAX_DRAG_PX": (0, 9, 10001),
            "GHOST_SCALE": (0, 0.09, 10.1),
        }
        for key, values in invalid.items():
            for value in values:
                with self.subTest(key=key, value=value):
                    self.assertIsNotNone(hs.validate(key, value))

        for key, (low, high) in hs.VALUE_RANGES.items():
            with self.subTest(key=key, endpoint="low"):
                self.assertIsNone(hs.validate(key, low))
            with self.subTest(key=key, endpoint="high"):
                self.assertIsNone(hs.validate(key, high))

    def test_config_loader_keeps_defaults_for_rejected_numbers(self):
        old_tick = hs.TICK_HZ
        old_exp = hs.SPEED_EXP
        config = """
            TICK_HZ = 999
            SPEED_EXP = nan
            DEADZONE_PX = 0
            REQUIRE_FOCUS_HELPER = off
            BLACKLIST = Bambu-Studio, Steam
            ONLY_DEVICES = /etc/passwd, ab, 1532:00c1
        """
        with mock.patch.object(hs, "read_config_text", return_value=config):
            hs.load_config("unused")
        self.assertEqual(hs.TICK_HZ, old_tick)
        self.assertEqual(hs.SPEED_EXP, old_exp)
        self.assertEqual(hs.DEADZONE_PX, 0)
        self.assertFalse(hs.REQUIRE_FOCUS_HELPER)
        self.assertEqual(hs.BLACKLIST, ["bambu-studio", "steam"])
        self.assertEqual(hs.ONLY_DEVICES, ["1532:00c1"])

    def test_device_spec_parser_enforces_security_bounds(self):
        specs = hs.validate_devices([
            "/etc/passwd",
            "ab",
            "1532:00c1",
            "/dev/input/event7",
            "Razer Viper V3 Pro",
            "x" * (hs.MAX_SPEC_LEN + 1),
        ])
        self.assertEqual(specs, [
            "1532:00c1",
            "/dev/input/event7",
            "Razer Viper V3 Pro",
        ])
        many = hs.validate_devices(
            [f"mouse-device-{index}" for index in range(hs.MAX_SPECS + 5)])
        self.assertEqual(len(many), hs.MAX_SPECS)

    def test_config_reader_rejects_untrusted_metadata_and_symlinks(self):
        with tempfile.TemporaryDirectory() as directory:
            config = pathlib.Path(directory) / "config"
            config.write_text("TICK_HZ=90\n", encoding="utf-8")
            insecure = types.SimpleNamespace(st_uid=0, st_mode=0o100664)
            with mock.patch.object(hs.os, "fstat", return_value=insecure):
                self.assertIsNone(hs.read_config_text(str(config)))

            not_root = types.SimpleNamespace(st_uid=1234, st_mode=0o100644)
            with mock.patch.object(hs.os, "fstat", return_value=not_root):
                self.assertIsNone(hs.read_config_text(str(config)))

            secure = types.SimpleNamespace(st_uid=0, st_mode=0o100644)
            with mock.patch.object(hs.os, "fstat", return_value=secure):
                self.assertEqual(hs.read_config_text(str(config)),
                                 "TICK_HZ=90\n")

            link = pathlib.Path(directory) / "link"
            os.symlink(config, link)
            self.assertIsNone(hs.read_config_text(str(link)))

    def test_toggle_stop_click_is_consumed_as_a_pair(self):
        ui = FakeUI()
        state = hs.State(ui)
        state.begin_toggle()
        down = InputEvent(0, 0, e.EV_KEY, e.BTN_LEFT, 1)
        up = InputEvent(0, 0, e.EV_KEY, e.BTN_LEFT, 0)
        self.assertTrue(hs._toggle_key(down, state, ui, FakeFocus()))
        self.assertFalse(state.toggled)
        self.assertEqual(state.eat_release, e.BTN_LEFT)
        self.assertTrue(hs._toggle_key(up, state, ui, FakeFocus()))
        self.assertIsNone(state.eat_release)

    def test_middle_click_transitions_from_idle_to_toggle_on_release(self):
        ui = FakeUI()
        state = hs.State(ui)
        down = InputEvent(0, 0, e.EV_KEY, e.BTN_MIDDLE, 1)
        up = InputEvent(0, 0, e.EV_KEY, e.BTN_MIDDLE, 0)
        self.assertTrue(hs._toggle_key(down, state, ui, FakeFocus(False)))
        self.assertTrue(state.pending)
        self.assertFalse(state.toggled)
        self.assertTrue(hs._toggle_key(up, state, ui, FakeFocus(False)))
        self.assertFalse(state.pending)
        self.assertTrue(state.toggled)
        self.assertEqual(ui.events, [])

    def test_preexisting_button_release_is_not_swallowed(self):
        ui = FakeUI()
        state = hs.State(ui)
        state.begin_toggle()
        release = InputEvent(0, 0, e.EV_KEY, e.BTN_LEFT, 0)
        self.assertFalse(hs._toggle_key(release, state, ui, FakeFocus()))
        self.assertTrue(state.toggled)

    def test_blocked_app_gets_native_middle_button(self):
        ui = FakeUI()
        state = hs.State(ui)
        down = InputEvent(0, 0, e.EV_KEY, e.BTN_MIDDLE, 1)
        up = InputEvent(0, 0, e.EV_KEY, e.BTN_MIDDLE, 0)
        self.assertTrue(hs._toggle_key(down, state, ui, FakeFocus(True)))
        self.assertTrue(state.passthrough)
        self.assertTrue(hs._toggle_key(up, state, ui, FakeFocus(True)))
        self.assertFalse(state.passthrough)
        key_events = [event for event in ui.events if event[0] == e.EV_KEY]
        self.assertEqual(key_events, [
            (e.EV_KEY, e.BTN_MIDDLE, 1),
            (e.EV_KEY, e.BTN_MIDDLE, 0),
        ])

    def test_focus_change_cancels_scroll_and_clears_accumulators(self):
        ui = FakeUI()
        state = hs.State(ui)
        state.begin_toggle()
        state.dx = state.dy = 300
        state.acc_v = state.notch_v = 42
        hs.tick(state, 0.1, FakeFocus(True))
        self.assertFalse(state.scrolling)
        self.assertEqual((state.dx, state.dy), (0.0, 0.0))
        self.assertEqual((state.acc_v, state.notch_v), (0.0, 0.0))
        self.assertEqual(ui.events, [])

    def test_hold_mode_crossing_deadzone_starts_and_release_resets(self):
        hs.TOGGLE_MODE = False
        ui = FakeUI()
        state = hs.State(ui)
        state.press()
        state.dy = hs.DEADZONE_PX
        hs.tick(state, 0.1, FakeFocus(False))
        self.assertTrue(state.pending)
        self.assertFalse(state.active)

        state.dy += 1
        hs.tick(state, 0.1, FakeFocus(False))
        self.assertFalse(state.pending)
        self.assertTrue(state.active)
        self.assertFalse(state.release())
        self.assertFalse(state.scrolling)

    def test_resync_releases_only_buttons_missing_from_physical_state(self):
        ui = FakeUI()
        state = hs.State(ui)
        state.eat_release = e.BTN_LEFT
        held = {e.BTN_LEFT, e.BTN_RIGHT}
        hs._resync(ui, FakeActiveDevice({e.BTN_RIGHT}), held, state)
        self.assertEqual(held, {e.BTN_RIGHT})
        self.assertIsNone(state.eat_release)
        self.assertEqual(ui.events, [
            (e.EV_KEY, e.BTN_LEFT, 0),
            (e.EV_SYN, e.SYN_REPORT, 0),
        ])

    def test_resync_repairs_passthrough_middle_and_aborts_hold_drag(self):
        ui = FakeUI()
        passthrough = hs.State(ui)
        passthrough.passthrough = True
        hs._resync(ui, FakeActiveDevice(), set(), passthrough)
        self.assertFalse(passthrough.passthrough)
        self.assertEqual(ui.events, [
            (e.EV_KEY, e.BTN_MIDDLE, 0),
            (e.EV_SYN, e.SYN_REPORT, 0),
        ])

        ui.events.clear()
        dragging = hs.State(ui)
        dragging.pending = False
        dragging.active = True
        dragging.dx = dragging.dy = 200
        hs._resync(ui, FakeActiveDevice(), set(), dragging)
        self.assertFalse(dragging.scrolling)
        self.assertEqual((dragging.dx, dragging.dy), (0.0, 0.0))
        self.assertEqual(ui.events, [])

    def test_windows_curve_emits_hires_and_legacy_wheel(self):
        ui = FakeUI()
        state = hs.State(ui)
        state.begin_toggle()
        state.dy = 300
        hs.tick(state, 0.10, FakeFocus(False))
        hires = [v for t, c, v in ui.events if t == e.EV_REL and c == e.REL_WHEEL_HI_RES]
        legacy = [v for t, c, v in ui.events if t == e.EV_REL and c == e.REL_WHEEL]
        self.assertTrue(hires and hires[0] < 0)
        self.assertTrue(legacy and legacy[0] < 0)

    def test_horizontal_autoscroll_is_off_by_default_and_opt_in(self):
        ui = FakeUI()
        state = hs.State(ui)
        state.begin_toggle()
        state.dx = 300
        hs.tick(state, 0.10, FakeFocus(False))
        horizontal = [event for event in ui.events
                      if event[1] in (e.REL_HWHEEL, e.REL_HWHEEL_HI_RES)]
        self.assertEqual(horizontal, [])

        hs.HORIZONTAL_SCROLL = True
        hs.tick(state, 0.10, FakeFocus(False))
        horizontal = [event for event in ui.events
                      if event[1] in (e.REL_HWHEEL, e.REL_HWHEEL_HI_RES)]
        self.assertTrue(horizontal)

    def test_legacy_physical_wheel_gets_matching_hires_units(self):
        ui = FakeUI()
        state = hs.State(ui, source_rels=[e.REL_X, e.REL_Y, e.REL_WHEEL])
        detent = InputEvent(0, 0, e.EV_REL, e.REL_WHEEL, -2)
        hs._supplement_physical_wheel(state, ui, detent)
        self.assertIn(
            (e.EV_REL, e.REL_WHEEL_HI_RES, -2 * hs.HIRES_PER_LINE),
            ui.events,
        )

        ui.events.clear()
        state.source_hires_v = True
        hs._supplement_physical_wheel(state, ui, detent)
        self.assertEqual(ui.events, [])

    def test_vertical_and_horizontal_physical_hires_axes_are_independent(self):
        ui = FakeUI()
        state = hs.State(ui, source_rels=[e.REL_WHEEL_HI_RES])
        vertical = InputEvent(0, 0, e.EV_REL, e.REL_WHEEL, 1)
        horizontal = InputEvent(0, 0, e.EV_REL, e.REL_HWHEEL, -3)
        hs._supplement_physical_wheel(state, ui, vertical)
        hs._supplement_physical_wheel(state, ui, horizontal)
        self.assertEqual(ui.events, [
            (e.EV_REL, e.REL_HWHEEL_HI_RES, -3 * hs.HIRES_PER_LINE),
        ])

        ui.events.clear()
        state = hs.State(ui, source_rels=[e.REL_HWHEEL_HI_RES])
        hs._supplement_physical_wheel(state, ui, vertical)
        hs._supplement_physical_wheel(state, ui, horizontal)
        self.assertEqual(ui.events, [
            (e.EV_REL, e.REL_WHEEL_HI_RES, hs.HIRES_PER_LINE),
        ])

    def test_write_only_uinput_discovers_sysfs_without_opening_event_node(self):
        mirror = hs.MirrorUInput.__new__(hs.MirrorUInput)
        with (
            mock.patch.object(hs._uinput, "get_sysname", return_value="input42"),
            mock.patch.object(hs.os, "listdir", return_value=["event314"]),
            mock.patch("builtins.open", mock.mock_open(
                read_data=hs.PHYS_MARKER + "\n")),
        ):
            self.assertIsNone(mirror._find_device(9))
        self.assertEqual(mirror.event_path, "/dev/input/event314")
        self.assertEqual(mirror.reported_phys, hs.PHYS_MARKER)

        mirror.device = None
        mirror.fd = 9
        with mock.patch.object(hs._uinput, "close") as close:
            mirror.close()
        close.assert_called_once_with(9)
        self.assertEqual(mirror.fd, -1)

    def test_strict_device_allowlist_selects_only_razer(self):
        hs.ONLY_DEVICES = ["Razer Viper V3 Pro"]
        selected, reason = hs.decide_device(
            FakeDevice("Razer Razer Viper V3 Pro"), "/dev/input/event7")
        self.assertTrue(selected, reason)
        selected, reason = hs.decide_device(
            FakeDevice("Keychron Keychron K13 Max Mouse"), "/dev/input/event3")
        self.assertFalse(selected, reason)

    def test_keyboard_is_rejected_even_if_selected(self):
        hs.ONLY_DEVICES = ["Razer Viper V3 Pro"]
        selected, reason = hs.decide_device(
            FakeDevice("Razer Razer Viper V3 Pro", keyboard=True),
            "/dev/input/event8")
        self.assertFalse(selected)
        self.assertIn("keyboard", reason)


if __name__ == "__main__":
    unittest.main(verbosity=2)
