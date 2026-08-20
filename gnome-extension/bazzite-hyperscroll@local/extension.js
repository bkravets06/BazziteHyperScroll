import Clutter from 'gi://Clutter';
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import Shell from 'gi://Shell';
import St from 'gi://St';

import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';

const SOCKET_PATH = '/run/bazzite-hyperscroll/state.sock';
const RECONNECT_SECONDS = 2;
const CONTEXT_POLL_MS = 100;
const OFFSET_POLL_MS = 16;
const FOCUS_HEARTBEAT_USEC = 1_000_000;
const MAX_IDENTITY_CHARS = 240;
const ANCHOR_SIZE = 38;
const ENCODER = new TextEncoder();

export default class BazziteHyperScrollExtension extends Extension {
    enable() {
        this._enabled = true;
        this._retryId = 0;
        this._contextPollId = 0;
        this._contextIdleId = 0;
        this._offsetPollId = 0;
        this._focusSignalId = 0;
        this._stageEventId = 0;

        this._client = null;
        this._connection = null;
        this._input = null;
        this._output = null;
        this._cancellable = null;
        this._writing = false;
        this._pendingFocus = null;
        this._pendingOffset = null;

        this._lastFocusIdentity = null;
        this._lastFocusQueueUsec = 0;
        this._overShellChrome = true;
        this._pointerWindow = null;
        this._scrollActive = false;
        this._anchorX = 0;
        this._anchorY = 0;
        this._watchedWindow = null;
        this._windowSignalIds = [];

        const glyph = new St.Label({
            text: '↕',
            style_class: 'bazzite-hyperscroll-anchor-glyph',
            x_align: Clutter.ActorAlign.CENTER,
            y_align: Clutter.ActorAlign.CENTER,
            reactive: false,
            can_focus: false,
            track_hover: false,
        });

        this._anchor = new St.Bin({
            child: glyph,
            style_class: 'bazzite-hyperscroll-anchor',
            width: ANCHOR_SIZE,
            height: ANCHOR_SIZE,
            reactive: false,
            can_focus: false,
            track_hover: false,
            visible: false,
        });
        Main.layoutManager.addTopChrome(this._anchor, {
            affectsStruts: false,
            trackFullscreen: false,
        });

        this._refreshPointerContext();
        this._focusSignalId = global.display.connect(
            'notify::focus-window', () => this._focusChanged());
        this._focusChanged();

        this._stageEventId = global.stage.connect(
            'captured-event', (_stage, event) => {
                const type = event.type();
                if (type === Clutter.EventType.MOTION ||
                    type === Clutter.EventType.ENTER ||
                    type === Clutter.EventType.LEAVE)
                    this._requestContextRefresh();
                return Clutter.EVENT_PROPAGATE;
            });

        this._contextPollId = GLib.timeout_add(
            GLib.PRIORITY_DEFAULT, CONTEXT_POLL_MS, () => {
                if (!this._enabled)
                    return GLib.SOURCE_REMOVE;
                this._refreshPointerContext();
                if (GLib.get_monotonic_time() - this._lastFocusQueueUsec >=
                    FOCUS_HEARTBEAT_USEC)
                    this._queueFocus(true);
                return GLib.SOURCE_CONTINUE;
            });

        this._connectSocket();
    }

    disable() {
        this._enabled = false;

        if (this._focusSignalId)
            global.display.disconnect(this._focusSignalId);
        if (this._stageEventId)
            global.stage.disconnect(this._stageEventId);
        this._focusSignalId = 0;
        this._stageEventId = 0;

        for (const id of [
            this._contextPollId,
            this._contextIdleId,
            this._retryId,
        ]) {
            if (id)
                GLib.source_remove(id);
        }
        this._contextPollId = 0;
        this._contextIdleId = 0;
        this._retryId = 0;

        this._unwatchFocusedWindow();
        this._closeSocket();

        if (this._anchor) {
            Main.layoutManager.removeChrome(this._anchor);
            this._anchor.destroy();
            this._anchor = null;
        }
    }

    _requestContextRefresh() {
        if (!this._enabled || this._contextIdleId)
            return;
        this._contextIdleId = GLib.idle_add(
            GLib.PRIORITY_DEFAULT_IDLE, () => {
                this._contextIdleId = 0;
                if (this._enabled)
                    this._refreshPointerContext();
                return GLib.SOURCE_REMOVE;
            });
    }

    _refreshPointerContext() {
        if (!this._enabled)
            return;

        let overShellChrome = true;
        let pointerWindow = null;
        try {
            const [x, y] = global.get_pointer();
            const picked = global.stage.get_actor_at_pos(
                Clutter.PickMode.REACTIVE, x, y);
            const overWindow = picked !== null &&
                picked !== global.window_group &&
                global.window_group.contains(picked);
            overShellChrome = !overWindow;

            if (overWindow)
                pointerWindow = this._windowForActor(picked);
        } catch {
            // A failed pick must preserve native Shell UI behavior.
            overShellChrome = true;
            pointerWindow = null;
        }

        if (overShellChrome !== this._overShellChrome ||
            pointerWindow !== this._pointerWindow) {
            this._overShellChrome = overShellChrome;
            this._pointerWindow = pointerWindow;
            this._queueFocus();
        }
    }

    _windowForActor(actor) {
        while (actor && actor !== global.window_group) {
            try {
                const win = actor.get_meta_window?.() ||
                    actor.meta_window || null;
                if (win)
                    return win;
            } catch {
                // The actor can disappear while a pointer pick is examined.
            }
            actor = actor.get_parent?.() || null;
        }
        return null;
    }

    _focusChanged() {
        this._unwatchFocusedWindow();
        const win = global.display.focus_window;
        this._watchedWindow = win;

        if (win) {
            const changed = () => this._queueFocus();
            for (const property of [
                'notify::gtk-application-id',
                'notify::wm-class',
                'notify::title',
            ]) {
                try {
                    this._windowSignalIds.push(win.connect(property, changed));
                } catch {
                    // Backends do not expose every optional property.
                }
            }
        }
        this._queueFocus();
    }

    _unwatchFocusedWindow() {
        if (this._watchedWindow) {
            for (const id of this._windowSignalIds) {
                try {
                    this._watchedWindow.disconnect(id);
                } catch {
                    // The window may already have been unmanaged.
                }
            }
        }
        this._windowSignalIds = [];
        this._watchedWindow = null;
    }

    _focusedIdentity() {
        if (this._overShellChrome)
            return 'org.gnome.shell';

        const win = this._pointerWindow || global.display.focus_window;
        if (!win)
            return 'org.gnome.shell';

        const values = [];
        const add = value => {
            if (value && !values.includes(String(value)))
                values.push(String(value));
        };

        try {
            const app = Shell.WindowTracker.get_default().get_window_app(win);
            add(app?.get_id?.());
        } catch {
            // WindowTracker may not know a just-mapped window yet.
        }
        add(win.get_sandboxed_app_id?.());
        add(win.get_gtk_application_id?.());
        add(win.get_wm_class?.());
        add(win.get_wm_class_instance?.());
        if (values.length === 0)
            add(win.get_title?.());

        const clean = values.join('|')
            .replace(/[\u0000-\u001f\u007f-\u009f]/g, ' ')
            .replace(/\s+/g, ' ')
            .trim()
            .slice(0, MAX_IDENTITY_CHARS);
        return clean || 'unknown';
    }

    _queueFocus(force = false) {
        const identity = this._focusedIdentity();
        if (!force && identity === this._lastFocusIdentity)
            return;
        this._lastFocusIdentity = identity;
        this._lastFocusQueueUsec = GLib.get_monotonic_time();
        this._pendingFocus = `focus ${identity}\n`;
        this._flushOutput();
    }

    _queueOffset() {
        if (!this._scrollActive)
            return;
        const [x, y] = global.get_pointer();
        const dx = Math.round(x - this._anchorX);
        const dy = Math.round(y - this._anchorY);
        this._pendingOffset = `offset ${dx} ${dy}\n`;
        this._flushOutput();
    }

    _flushOutput() {
        if (!this._output || this._writing)
            return;

        let text = null;
        if (this._pendingFocus !== null) {
            text = this._pendingFocus;
            this._pendingFocus = null;
        } else if (this._pendingOffset !== null) {
            text = this._pendingOffset;
            this._pendingOffset = null;
        }
        if (text === null)
            return;

        const output = this._output;
        const cancellable = this._cancellable;
        this._writing = true;
        try {
            output.write_all_async(
                ENCODER.encode(text), GLib.PRIORITY_DEFAULT, cancellable,
                (_stream, result) => {
                    try {
                        output.write_all_finish(result);
                    } catch {
                        if (output === this._output)
                            this._connectionLost();
                        return;
                    }
                    if (output !== this._output)
                        return;
                    this._writing = false;
                    this._flushOutput();
                });
        } catch {
            if (output === this._output) {
                this._writing = false;
                this._connectionLost();
            }
        }
    }

    _connectSocket() {
        if (!this._enabled || this._connection || this._client)
            return;

        const cancellable = new Gio.Cancellable();
        const client = new Gio.SocketClient({timeout: 2});
        const address = new Gio.UnixSocketAddress({path: SOCKET_PATH});
        this._cancellable = cancellable;
        this._client = client;

        client.connect_async(address, cancellable, (_source, result) => {
            let connection;
            try {
                connection = client.connect_finish(result);
            } catch {
                if (!this._enabled || this._cancellable !== cancellable)
                    return;
                this._client = null;
                this._cancellable = null;
                this._scheduleReconnect();
                return;
            }

            if (!this._enabled || this._cancellable !== cancellable) {
                try {
                    connection.close(null);
                } catch {
                    // A cancelled connect can complete during disable().
                }
                return;
            }

            this._client = null;
            this._connection = connection;
            // Gio.SocketClient's timeout is not a connect timeout: it arms an
            // inactivity timeout on the socket it creates, and every later
            // operation inherits it. This connection is idle by design - the
            // daemon speaks only when the scroll state changes - so the
            // pending read would fail with TIMED_OUT every two seconds and
            // take the connection, and any scroll in progress, with it.
            try {
                connection.get_socket()?.set_timeout(0);
            } catch {
                // Older Gio, or a connection without an exposed socket: the
                // reconnect path already handles a dropped connection.
            }
            this._output = connection.get_output_stream();
            this._input = new Gio.DataInputStream({
                base_stream: connection.get_input_stream(),
                close_base_stream: false,
            });
            this._lastFocusIdentity = null;
            this._queueFocus(true);
            this._readNextLine();
        });
    }

    _readNextLine() {
        const input = this._input;
        const cancellable = this._cancellable;
        if (!input)
            return;

        try {
            input.read_line_async(
                GLib.PRIORITY_DEFAULT, cancellable, (_stream, result) => {
                    let line;
                    try {
                        [line] = input.read_line_finish_utf8(result);
                    } catch {
                        if (input === this._input)
                            this._connectionLost();
                        return;
                    }
                    if (!this._enabled || input !== this._input)
                        return;
                    if (line === null) {
                        this._connectionLost();
                        return;
                    }
                    this._handleDaemonLine(line);
                    this._readNextLine();
                });
        } catch {
            if (input === this._input)
                this._connectionLost();
        }
    }

    _handleDaemonLine(raw) {
        const line = raw.trim();
        if (line === '1')
            this._startScrollTracking();
        else if (line === '0')
            this._stopScrollTracking();
    }

    _startScrollTracking() {
        if (this._scrollActive)
            return;
        this._scrollActive = true;
        [this._anchorX, this._anchorY] = global.get_pointer();
        this._anchor.set_position(
            Math.round(this._anchorX - ANCHOR_SIZE / 2),
            Math.round(this._anchorY - ANCHOR_SIZE / 2));
        this._anchor.show();
        this._queueOffset();
        this._offsetPollId = GLib.timeout_add(
            GLib.PRIORITY_DEFAULT, OFFSET_POLL_MS, () => {
                if (!this._enabled || !this._scrollActive)
                    return GLib.SOURCE_REMOVE;
                this._queueOffset();
                return GLib.SOURCE_CONTINUE;
            });
    }

    _stopScrollTracking() {
        this._scrollActive = false;
        this._pendingOffset = null;
        if (this._offsetPollId) {
            GLib.source_remove(this._offsetPollId);
            this._offsetPollId = 0;
        }
        this._anchor?.hide();
    }

    _connectionLost() {
        if (!this._enabled)
            return;
        this._closeSocket();
        this._scheduleReconnect();
    }

    _closeSocket() {
        this._stopScrollTracking();
        const cancellable = this._cancellable;
        const connection = this._connection;
        this._client = null;
        this._connection = null;
        this._input = null;
        this._output = null;
        this._cancellable = null;
        this._writing = false;
        this._pendingFocus = null;
        this._pendingOffset = null;
        this._lastFocusIdentity = null;
        this._lastFocusQueueUsec = 0;
        cancellable?.cancel();
        try {
            connection?.close(null);
        } catch {
            // Already closed.
        }
    }

    _scheduleReconnect() {
        if (!this._enabled || this._retryId)
            return;
        this._retryId = GLib.timeout_add_seconds(
            GLib.PRIORITY_DEFAULT, RECONNECT_SECONDS, () => {
                this._retryId = 0;
                if (this._enabled)
                    this._connectSocket();
                return GLib.SOURCE_REMOVE;
            });
    }
}
