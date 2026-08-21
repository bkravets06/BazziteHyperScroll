"""The GTK application object."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gdk, Gio, Gtk  # noqa: E402

from .. import APP_ID  # noqa: E402
from .window import MainWindow  # noqa: E402


class Application(Adw.Application):
    """Runs one window. Nothing is registered to start on login."""

    __gtype_name__ = "KeychronZenApplication"

    def __init__(self, demo: bool = False):
        super().__init__(
            application_id=APP_ID,
            flags=Gio.ApplicationFlags.DEFAULT_FLAGS,
        )
        self._demo = demo
        self._window: MainWindow | None = None

        quit_action = Gio.SimpleAction.new("quit", None)
        quit_action.connect("activate", lambda *_: self.quit())
        self.add_action(quit_action)
        self.set_accels_for_action("app.quit", ["<Control>q", "<Control>w"])

    def do_startup(self) -> None:
        Adw.Application.do_startup(self)
        self._load_css()

    def do_activate(self) -> None:
        if self._window is None:
            self._window = MainWindow(self, start_in_demo=self._demo)
        self._window.present()

    def _load_css(self) -> None:
        from importlib.resources import files

        provider = Gtk.CssProvider()
        provider.load_from_string(
            files("keychron_zen.ui").joinpath("style.css").read_text()
        )
        display = Gdk.Display.get_default()
        if display is not None:
            Gtk.StyleContext.add_provider_for_display(
                display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
            )
