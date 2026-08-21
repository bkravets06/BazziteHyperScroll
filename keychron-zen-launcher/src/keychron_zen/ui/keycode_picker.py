"""The dialog that chooses what a key should do.

Four ways in, because keycodes come in four flavours: pick a plain key from a
searchable catalogue, pick a layer action, pick a macro slot, or type an
expression for the combinations no button grid can cover (``LT(1,KC_SPC)``,
``LCTL(LSFT(KC_A))``, a raw ``0x....``).
"""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, GObject, Gtk  # noqa: E402

from ..model.definitions import CustomKeycode  # noqa: E402
from ..protocol import keycodes, labels  # noqa: E402


class KeycodePicker(Adw.Window):
    """Modal chooser. Emits ``keycode-chosen`` with the selected value."""

    __gtype_name__ = "KeychronZenKeycodePicker"

    __gsignals__ = {
        "keycode-chosen": (GObject.SignalFlags.RUN_FIRST, None, (int,)),
    }

    def __init__(
        self,
        parent: Gtk.Window,
        *,
        current: int,
        layer_count: int,
        macro_texts: list[str],
        custom_keycodes: tuple[CustomKeycode, ...] = (),
        subtitle: str = "",
    ):
        super().__init__(
            transient_for=parent,
            modal=True,
            title="Choose a key",
            default_width=760,
            default_height=580,
        )
        self._current = current
        self._layer_count = layer_count
        self._macro_texts = macro_texts
        self._custom_keycodes = custom_keycodes
        self._buttons: list[tuple[Gtk.FlowBoxChild, str]] = []
        self._sections: list[tuple[Gtk.Widget, Gtk.FlowBox]] = []

        stack = Adw.ViewStack()
        stack.add_titled_with_icon(
            self._keys_page(), "keys", "Keys", "input-keyboard-symbolic"
        )
        stack.add_titled_with_icon(
            self._layers_page(), "layers", "Layers", "view-paged-symbolic"
        )
        stack.add_titled_with_icon(
            self._macros_page(), "macros", "Macros", "media-playback-start-symbolic"
        )
        stack.add_titled_with_icon(
            self._advanced_page(), "advanced", "Advanced", "applications-engineering-symbolic"
        )

        header = Adw.HeaderBar()
        header.set_title_widget(Adw.ViewSwitcher(stack=stack, policy=Adw.ViewSwitcherPolicy.WIDE))

        clear = Gtk.Button(label="Nothing")
        clear.set_tooltip_text("Make this key do nothing (KC_NO)")
        clear.connect("clicked", lambda *_: self._choose(keycodes.KC_NO))
        header.pack_start(clear)

        view = Adw.ToolbarView()
        view.add_top_bar(header)
        view.set_content(stack)

        subtitle_label = Gtk.Label(
            label=subtitle,
            xalign=0,
            css_classes=["dim-label", "caption"],
            margin_start=12,
            margin_end=12,
            margin_top=6,
            margin_bottom=6,
            wrap=True,
        )
        if subtitle:
            view.add_bottom_bar(subtitle_label)

        self.set_content(view)

        escape = Gtk.EventControllerKey()
        escape.connect("key-pressed", self._on_key_pressed)
        self.add_controller(escape)

    # -- pages -----------------------------------------------------------

    def _keys_page(self) -> Gtk.Widget:
        self._search = Gtk.SearchEntry(
            placeholder_text="Search keys…", margin_start=12, margin_end=12, margin_top=12
        )
        self._search.connect("search-changed", self._on_search_changed)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18,
                          margin_start=12, margin_end=12, margin_top=12, margin_bottom=12)

        categories = list(labels.categories())
        if self._custom_keycodes:
            categories.insert(
                0,
                (
                    "This keyboard",
                    [(entry.value, entry.name) for entry in self._custom_keycodes],
                ),
            )
        for title, entries in categories:
            content.append(self._category(title, entries))

        self._empty = Adw.StatusPage(
            title="No matching keys",
            icon_name="edit-find-symbolic",
            visible=False,
        )
        content.append(self._empty)

        scroller = Gtk.ScrolledWindow(vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER)
        scroller.set_child(content)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        box.append(self._search)
        box.append(scroller)
        return box

    def _category(self, title: str, entries: list[tuple[int, str]]) -> Gtk.Widget:
        heading = Gtk.Label(label=title, xalign=0, css_classes=["heading"])
        flow = Gtk.FlowBox(
            selection_mode=Gtk.SelectionMode.NONE,
            max_children_per_line=10,
            min_children_per_line=3,
            homogeneous=True,
            row_spacing=6,
            column_spacing=6,
            valign=Gtk.Align.START,
            vexpand=False,
        )
        for value, name in entries:
            flow.append(self._key_button(value, name))

        group = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        group.append(heading)
        group.append(flow)
        self._sections.append((group, flow))
        return group

    def _key_button(self, value: int, name: str) -> Gtk.Widget:
        main, sub = labels.legend(value, {e.value: e.label for e in self._custom_keycodes})
        button = Gtk.Button(css_classes=["keycode-button"])
        button.set_tooltip_text(f"{main} {sub}".strip() + f"\n{name}")

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0,
                      valign=Gtk.Align.CENTER)
        box.append(Gtk.Label(label=main or "—", ellipsize=3, css_classes=["heading"]))
        if sub:
            box.append(Gtk.Label(label=sub, ellipsize=3, css_classes=["dim-label", "caption"]))
        button.set_child(box)
        button.connect("clicked", lambda *_: self._choose(value))
        if value == self._current:
            button.add_css_class("suggested-action")

        child = Gtk.FlowBoxChild(valign=Gtk.Align.START, vexpand=False)
        child.set_child(button)
        self._buttons.append((child, labels.search_text(value, name)))
        return child

    def _layers_page(self) -> Gtk.Widget:
        page = Adw.PreferencesPage()
        for function, title, description in labels.LAYER_FUNCTIONS:
            group = Adw.PreferencesGroup(title=f"{title} — {function}()", description=description)
            row = Adw.ActionRow(title="Layer")
            box = Gtk.Box(spacing=6, valign=Gtk.Align.CENTER)
            for layer in range(self._layer_count):
                keycode = keycodes.parse(f"{function}({layer})")
                button = Gtk.Button(label=str(layer))
                button.set_tooltip_text(f"{function}({layer})")
                if keycode == self._current:
                    button.add_css_class("suggested-action")
                button.connect("clicked", lambda _b, code=keycode: self._choose(code))
                box.append(button)
            row.add_suffix(box)
            group.add(row)
            page.add(group)
        return page

    def _macros_page(self) -> Gtk.Widget:
        page = Adw.PreferencesPage()
        group = Adw.PreferencesGroup(
            title="Macro slots",
            description="Pressing the key replays that slot. Edit the slots on the Macros page.",
        )
        if not self._macro_texts:
            group.add(Adw.ActionRow(title="This keyboard has no macro storage"))
        for index, text in enumerate(self._macro_texts):
            keycode = keycodes.parse(f"M{index}")
            row = Adw.ActionRow(
                title=f"Macro {index}",
                subtitle=text or "empty",
                activatable=True,
            )
            row.connect("activated", lambda _r, code=keycode: self._choose(code))
            if keycode == self._current:
                row.add_css_class("accent")
            group.add(row)
        page.add(group)
        return page

    def _advanced_page(self) -> Gtk.Widget:
        page = Adw.PreferencesPage()
        group = Adw.PreferencesGroup(
            title="Type a keycode",
            description=(
                "Anything QMK can express: LT(1,KC_SPC) for tap/hold layers, "
                "LCTL_T(KC_ESC) for tap/hold modifiers, LCTL(LSFT(KC_A)) for a "
                "combination, OSM(MOD_LSFT) for one-shot, or a raw 0x1234."
            ),
        )
        self._entry = Adw.EntryRow(title="Keycode")
        self._entry.set_text(keycodes.name_for(self._current))
        self._entry.connect("changed", self._on_entry_changed)
        self._entry.connect("entry-activated", lambda *_: self._apply_entry())
        group.add(self._entry)

        self._preview = Adw.ActionRow(title="—", subtitle="")
        group.add(self._preview)

        apply_button = Gtk.Button(label="Use this keycode", css_classes=["suggested-action", "pill"],
                                  halign=Gtk.Align.CENTER, margin_top=12)
        apply_button.connect("clicked", lambda *_: self._apply_entry())
        self._apply_button = apply_button

        page.add(group)
        wrapper = Adw.PreferencesGroup()
        wrapper.add(apply_button)
        page.add(wrapper)
        self._on_entry_changed(self._entry)
        return page

    # -- behaviour -------------------------------------------------------

    def _on_search_changed(self, entry: Gtk.SearchEntry) -> None:
        needle = entry.get_text().strip().lower()
        for child, haystack in self._buttons:
            child.set_visible(not needle or labels.matches(haystack, needle))
        any_visible = False
        for group, flow in self._sections:
            visible = any(
                child.get_visible()
                for child, _ in self._buttons
                if child.get_parent() is flow
            )
            group.set_visible(visible)
            any_visible = any_visible or visible
        self._empty.set_visible(not any_visible)

    def _on_entry_changed(self, entry: Adw.EntryRow) -> None:
        text = entry.get_text().strip()
        try:
            keycode = keycodes.parse(text)
        except ValueError as exc:
            entry.add_css_class("error")
            self._preview.set_title("Not a keycode")
            self._preview.set_subtitle(str(exc))
            if hasattr(self, "_apply_button"):
                self._apply_button.set_sensitive(False)
            return
        entry.remove_css_class("error")
        main, sub = labels.legend(keycode, {e.value: e.label for e in self._custom_keycodes})
        self._preview.set_title(f"{main} {sub}".strip() or "(nothing)")
        self._preview.set_subtitle(f"{keycodes.name_for(keycode)} · 0x{keycode:04X}")
        if hasattr(self, "_apply_button"):
            self._apply_button.set_sensitive(True)

    def _apply_entry(self) -> None:
        try:
            self._choose(keycodes.parse(self._entry.get_text().strip()))
        except ValueError:
            pass

    def _choose(self, keycode: int) -> None:
        self.emit("keycode-chosen", keycode)
        self.close()

    def _on_key_pressed(self, _controller, keyval, _keycode, _state) -> bool:
        from gi.repository import Gdk

        if keyval == Gdk.KEY_Escape:
            self.close()
            return True
        return False

