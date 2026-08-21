"""The application window: find a keyboard, then show the pages for it."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gio, GLib, Gtk  # noqa: E402

from .. import config_io  # noqa: E402
from ..model.device import Discovery, Keyboard, discover  # noqa: E402
from ..protocol.hidraw import PermissionDeniedError  # noqa: E402
from .keymap_page import KeymapPage  # noqa: E402
from .lighting_page import LightingPage  # noqa: E402
from .macros_page import MacrosPage  # noqa: E402
from .palette import current as current_palette  # noqa: E402
from .tester_page import TesterPage  # noqa: E402

UDEV_HINT = (
    "Keyboard plugged in but not listed? The udev rule is probably missing.\n"
    "<tt>sudo ./scripts/install-udev-rule.sh</tt>\n"
    "Then unplug and replug the keyboard."
)


class MainWindow(Adw.ApplicationWindow):
    """One window, one connected keyboard."""

    __gtype_name__ = "KeychronZenWindow"

    def __init__(self, application: Adw.Application, start_in_demo: bool = False):
        super().__init__(
            application=application,
            title="Keychron Zen Launcher",
            default_width=1180,
            default_height=760,
        )
        self._keyboard: Keyboard | None = None
        self._discoveries: list[Discovery] = []
        self._last_toast: Adw.Toast | None = None

        style = Adw.StyleManager.get_default()
        palette = current_palette(style.get_dark())
        style.connect("notify::dark", self._on_theme_changed)

        self._toasts = Adw.ToastOverlay()

        self._keymap_page = KeymapPage(palette, self.notify_user)
        self._macros_page = MacrosPage(self.notify_user)
        self._lighting_page = LightingPage(self.notify_user)
        self._tester_page = TesterPage(palette)

        self._pages = Adw.ViewStack()
        self._pages.add_titled_with_icon(
            self._keymap_page, "keymap", "Keys", "input-keyboard-symbolic"
        )
        self._pages.add_titled_with_icon(
            self._macros_page, "macros", "Macros", "media-playback-start-symbolic"
        )
        self._pages.add_titled_with_icon(
            self._lighting_page, "lighting", "Lighting", "display-brightness-symbolic"
        )
        self._pages.add_titled_with_icon(
            self._tester_page, "tester", "Key tester", "emblem-ok-symbolic"
        )
        self._pages.connect("notify::visible-child", self._on_page_changed)

        self._welcome = self._build_welcome()

        self._root = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE)
        self._root.add_named(self._welcome, "welcome")
        self._root.add_named(self._pages, "pages")

        self._switcher = Adw.ViewSwitcher(
            stack=self._pages, policy=Adw.ViewSwitcherPolicy.WIDE
        )
        self._header = Adw.HeaderBar()
        self._header.pack_start(self._build_device_button())
        self._header.pack_end(self._build_menu_button())

        view = Adw.ToolbarView()
        view.add_top_bar(self._header)
        view.set_content(self._root)
        self._toasts.set_child(view)
        self.set_content(self._toasts)

        self._install_actions()
        self.connect("close-request", self._on_close)

        if start_in_demo:
            self.use_demo_keyboard()
        else:
            self.rescan()

    # -- chrome ----------------------------------------------------------

    def _build_device_button(self) -> Gtk.Widget:
        self._device_button = Gtk.Button(icon_name="view-refresh-symbolic")
        self._device_button.set_tooltip_text("Look for keyboards again")
        self._device_button.connect("clicked", lambda *_: self.rescan())
        return self._device_button

    def _build_menu_button(self) -> Gtk.Widget:
        menu = Gio.Menu()

        configuration = Gio.Menu()
        configuration.append("Save configuration…", "win.export")
        configuration.append("Load configuration…", "win.import")
        menu.append_section(None, configuration)

        keyboard = Gio.Menu()
        keyboard.append("Identify keyboard", "win.identify")
        keyboard.append("Reset keys to default", "win.reset-keymap")
        keyboard.append("Erase all settings…", "win.factory-reset")
        menu.append_section(None, keyboard)

        about = Gio.Menu()
        about.append("Demo mode", "win.demo")
        about.append("About", "win.about")
        menu.append_section(None, about)

        button = Gtk.MenuButton(icon_name="open-menu-symbolic", menu_model=menu)
        button.set_tooltip_text("Main menu")
        return button

    def _build_welcome(self) -> Gtk.Widget:
        self._status = Adw.StatusPage(
            icon_name="input-keyboard-symbolic",
            title="No keyboard connected",
            description="Plug in a Keychron keyboard with the USB cable.",
        )
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12,
                      halign=Gtk.Align.CENTER)

        self._device_list = Gtk.ListBox(
            selection_mode=Gtk.SelectionMode.NONE,
            css_classes=["boxed-list"],
            visible=False,
        )
        box.append(self._device_list)

        buttons = Gtk.Box(spacing=12, halign=Gtk.Align.CENTER)
        rescan = Gtk.Button(label="Look again", css_classes=["pill", "suggested-action"])
        rescan.connect("clicked", lambda *_: self.rescan())
        buttons.append(rescan)

        demo = Gtk.Button(label="Try demo mode", css_classes=["pill"])
        demo.set_tooltip_text("Explore the app with a simulated K13 Max")
        demo.connect("clicked", lambda *_: self.use_demo_keyboard())
        buttons.append(demo)
        box.append(buttons)

        hint = Gtk.Label(
            use_markup=True,
            label=UDEV_HINT,
            wrap=True,
            justify=Gtk.Justification.CENTER,
            css_classes=["dim-label", "caption"],
        )
        box.append(hint)

        # Adw.StatusPage stretches its child to the window width, which would
        # leave the hint as one very long line. Clamp is the reliable way to
        # bound it: max-width-chars only affects the natural size request, and
        # a wrapping label wraps at whatever width it is actually given.
        self._status.set_child(Adw.Clamp(maximum_size=560, child=box))
        return self._status

    def _install_actions(self) -> None:
        for name, handler in (
            ("export", self._on_export),
            ("import", self._on_import),
            ("identify", self._on_identify),
            ("reset-keymap", self._on_reset_keymap),
            ("factory-reset", self._on_factory_reset),
            ("demo", lambda *_: self.use_demo_keyboard()),
            ("about", self._on_about),
        ):
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", handler)
            self.add_action(action)

    # -- device lifecycle ------------------------------------------------

    def rescan(self) -> None:
        """Look for keyboards and connect if exactly one is usable."""
        self._disconnect()
        self._discoveries = discover()
        usable = [item for item in self._discoveries if item.usable]

        if len(usable) == 1:
            self._connect(usable[0])
            return

        self._show_welcome()
        if not self._discoveries:
            self._status.set_title("No keyboard connected")
            self._status.set_description(
                "Plug in a Keychron keyboard with the USB cable. Keychron's "
                "firmware only accepts configuration over the cable, not over "
                "Bluetooth or the 2.4 GHz receiver."
            )
        elif not usable:
            self._status.set_title("Keyboard found, but not reachable")
            self._status.set_description("See below for what is in the way.")
        else:
            self._status.set_title("Choose a keyboard")
            self._status.set_description("More than one configurable keyboard is connected.")

    def _populate_device_list(self) -> None:
        child = self._device_list.get_first_child()
        while child is not None:
            following = child.get_next_sibling()
            self._device_list.remove(child)
            child = following

        for item in self._discoveries:
            row = Adw.ActionRow(
                title=item.title,
                subtitle=item.problem or f"{item.info.node} · ready",
                activatable=item.usable,
            )
            if item.usable:
                row.add_suffix(Gtk.Image(icon_name="go-next-symbolic"))
                row.connect("activated", lambda _row, target=item: self._connect(target))
            else:
                row.add_suffix(Gtk.Image(icon_name="dialog-warning-symbolic"))
            self._device_list.append(row)
        self._device_list.set_visible(bool(self._discoveries))

    def _connect(self, discovery: Discovery) -> None:
        try:
            keyboard = Keyboard.open(discovery)
        except PermissionDeniedError:
            self._show_welcome()
            self._status.set_title("Not allowed to open the keyboard")
            self._status.set_description(
                "The device node exists but this user may not use it. Install "
                "the udev rule, then unplug and replug the keyboard."
            )
            return
        except Exception as exc:  # noqa: BLE001 - any failure lands on the status page
            self._show_welcome()
            self._status.set_title("Could not talk to the keyboard")
            self._status.set_description(str(exc))
            return
        self._adopt(keyboard)

    def use_demo_keyboard(self) -> None:
        self._disconnect()
        self._adopt(Keyboard.demo())
        self.notify_user("Demo mode — nothing is written to real hardware")

    def _adopt(self, keyboard: Keyboard) -> None:
        self._keyboard = keyboard
        self._keymap_page.set_keyboard(keyboard)
        self._macros_page.set_keyboard(keyboard)
        self._lighting_page.set_keyboard(keyboard)
        self._tester_page.set_keyboard(keyboard)

        self._header.set_title_widget(self._switcher)
        self._root.set_visible_child_name("pages")
        self._device_button.set_tooltip_text(f"{keyboard.title} — click to look again")
        self.set_title(f"{keyboard.title} — Keychron Zen Launcher")
        if not keyboard.has_layout:
            self.notify_user(
                "No layout definition for this keyboard — macros and lighting only"
            )
        self._on_page_changed()

    def _disconnect(self) -> None:
        self._tester_page.stop()
        if self._keyboard is not None:
            self._keyboard.close()
            self._keyboard = None

    def _show_welcome(self) -> None:
        self._keymap_page.set_keyboard(None)
        self._macros_page.set_keyboard(None)
        self._lighting_page.set_keyboard(None)
        self._tester_page.set_keyboard(None)
        self._populate_device_list()
        self._header.set_title_widget(None)
        self.set_title("Keychron Zen Launcher")
        self._root.set_visible_child_name("welcome")

    # -- helpers ---------------------------------------------------------

    def notify_user(self, message: str) -> None:
        """Show a transient message, replacing any previous one.

        Dismissing the outgoing toast keeps them from queueing up: after a run
        of edits the newest message is the only one worth reading.
        """
        if self._last_toast is not None:
            self._last_toast.dismiss()
        self._last_toast = Adw.Toast(title=message, timeout=4)
        self._toasts.add_toast(self._last_toast)

    def _on_theme_changed(self, style: Adw.StyleManager, _param) -> None:
        palette = current_palette(style.get_dark())
        self._keymap_page.set_palette(palette)
        self._tester_page.set_palette(palette)

    def _on_page_changed(self, *_args) -> None:
        # The tester polls the keyboard continuously; only run it while visible.
        if self._pages.get_visible_child() is self._tester_page and self._keyboard:
            self._tester_page.start()
        else:
            self._tester_page.stop()

    def _on_close(self, *_args) -> bool:
        self._disconnect()
        return False

    def _confirm(self, heading: str, body: str, label: str, callback) -> None:
        dialog = Adw.AlertDialog(heading=heading, body=body)
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("confirm", label)
        dialog.set_response_appearance("confirm", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")
        dialog.set_close_response("cancel")
        dialog.connect(
            "response",
            lambda _dialog, response: callback() if response == "confirm" else None,
        )
        dialog.present(self)

    # -- actions ---------------------------------------------------------

    def _on_identify(self, *_args) -> None:
        if self._keyboard is None:
            return
        try:
            self._keyboard.indicate()
            self.notify_user("Asked the keyboard to flash its lights")
        except Exception as exc:  # noqa: BLE001
            self.notify_user(f"The keyboard would not do that: {exc}")

    def _on_reset_keymap(self, *_args) -> None:
        if self._keyboard is None:
            return
        self._confirm(
            "Reset every key?",
            "All four layers go back to the keymap the keyboard shipped with. "
            "Macros and lighting are left alone.",
            "Reset keys",
            self._do_reset_keymap,
        )

    def _do_reset_keymap(self) -> None:
        try:
            self._keyboard.reset_keymap()
        except Exception as exc:  # noqa: BLE001
            self.notify_user(f"Could not reset the keymap: {exc}")
            return
        self._keymap_page.refresh()
        self.notify_user("Keys restored to their defaults")

    def _on_factory_reset(self, *_args) -> None:
        if self._keyboard is None:
            return
        self._confirm(
            "Erase all settings?",
            "Clears the keymap, every macro and the lighting settings stored on "
            "the keyboard. This cannot be undone.",
            "Erase everything",
            self._do_factory_reset,
        )

    def _do_factory_reset(self) -> None:
        try:
            self._keyboard.reset_eeprom()
        except Exception as exc:  # noqa: BLE001
            self.notify_user(f"Could not erase the settings: {exc}")
            return
        self._adopt(self._keyboard)
        self.notify_user("Keyboard settings erased")

    def _on_export(self, *_args) -> None:
        if self._keyboard is None:
            return
        dialog = Gtk.FileDialog(
            title="Save configuration",
            initial_name=_suggested_filename(self._keyboard),
        )
        dialog.set_filters(_json_filters())
        dialog.save(self, None, self._on_export_ready)

    def _on_export_ready(self, dialog: Gtk.FileDialog, result) -> None:
        try:
            file = dialog.save_finish(result)
        except GLib.Error:
            return  # the user cancelled
        if file is None or self._keyboard is None:
            return
        try:
            text = config_io.dumps(self._keyboard)
            file.replace_contents(
                text.encode(), None, False, Gio.FileCreateFlags.REPLACE_DESTINATION, None
            )
        except Exception as exc:  # noqa: BLE001
            self.notify_user(f"Could not save: {exc}")
            return
        self.notify_user(f"Saved to {file.get_basename()}")

    def _on_import(self, *_args) -> None:
        if self._keyboard is None:
            return
        dialog = Gtk.FileDialog(title="Load configuration")
        dialog.set_filters(_json_filters())
        dialog.open(self, None, self._on_import_ready)

    def _on_import_ready(self, dialog: Gtk.FileDialog, result) -> None:
        try:
            file = dialog.open_finish(result)
        except GLib.Error:
            return  # the user cancelled
        if file is None or self._keyboard is None:
            return
        try:
            ok, contents, _etag = file.load_contents(None)
            if not ok:
                raise OSError("could not read the file")
            data = config_io.loads(contents.decode())
        except Exception as exc:  # noqa: BLE001
            self.notify_user(f"Could not read that file: {exc}")
            return

        self._confirm(
            "Apply this configuration?",
            f"{config_io.describe(data)}\n\nIt will overwrite what is on the "
            "keyboard now.",
            "Apply",
            lambda: self._do_import(data),
        )

    def _do_import(self, data: dict) -> None:
        try:
            applied = config_io.apply(self._keyboard, data)
        except Exception as exc:  # noqa: BLE001
            self.notify_user(str(exc))
            return
        self._adopt(self._keyboard)
        self.notify_user(
            "Applied " + ", ".join(applied) if applied else "Nothing to apply"
        )

    def _on_about(self, *_args) -> None:
        about = Adw.AboutDialog(
            application_name="Keychron Zen Launcher",
            application_icon="input-keyboard-symbolic",
            developer_name="Keychron Zen Launcher contributors",
            version=_version(),
            comments=(
                "Configure QMK/VIA Keychron keyboards on Linux, without a "
                "Chromium-based browser."
            ),
            license_type=Gtk.License.GPL_2_0,
        )
        if self._keyboard is not None:
            about.set_debug_info(
                f"{self._keyboard.title}\n"
                f"device: {self._keyboard.info}\n"
                f"VIA protocol: 0x{self._keyboard.protocol_version:04X}\n"
                f"firmware: {self._keyboard.firmware_text}\n"
                f"layers: {self._keyboard.layer_count}"
            )
        about.present(self)


def _version() -> str:
    from .. import __version__

    return __version__


def _suggested_filename(keyboard: Keyboard) -> str:
    name = keyboard.title.split("—")[0].strip().lower().replace(" ", "-")
    return f"{name or 'keyboard'}.json"


def _json_filters() -> Gio.ListStore:
    filters = Gio.ListStore.new(Gtk.FileFilter)
    json_filter = Gtk.FileFilter()
    json_filter.set_name("Keyboard configuration (*.json)")
    json_filter.add_pattern("*.json")
    filters.append(json_filter)
    return filters
