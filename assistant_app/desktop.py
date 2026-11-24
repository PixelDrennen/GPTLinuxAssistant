"""KWin and screen-lock signals from the current desktop session."""
import json
from pathlib import Path

from gi.repository import Gio, GLib
from PyQt5.QtCore import QTimer


SERVICE = "io.github.PixelDrennen.WorkAssistant"
PATH = "/io/github/PixelDrennen/WorkAssistant"
XML = f"""
<node><interface name="{SERVICE}">
<method name="WantsWindows"><arg type="b" direction="out"/></method>
<method name="Observe"><arg type="s" direction="in"/></method>
</interface></node>
"""
SCREEN = "org.freedesktop.ScreenSaver"


class Desktop:
    def __init__(self, session, on_lock, parent):
        self.session = session
        self.on_lock = on_lock
        self.locked = False
        self.kwin_owner = ""
        self.bus = Gio.bus_get_sync(Gio.BusType.SESSION)
        self.interface = Gio.DBusNodeInfo.new_for_xml(XML)
        self.bus.register_object(PATH, self.interface.interfaces[0], self.method, None, None)
        self.ownership = Gio.bus_own_name_on_connection(self.bus, SERVICE, Gio.BusNameOwnerFlags.NONE, None, None)
        self.watch = Gio.bus_watch_name_on_connection(
            self.bus, "org.kde.KWin", Gio.BusNameWatcherFlags.NONE,
            self.kwin_appeared, self.kwin_gone)
        self.bus.signal_subscribe(SCREEN, SCREEN, "ActiveChanged", None, None,
                                  Gio.DBusSignalFlags.NONE, self.lock_changed)
        self.timer = QTimer(parent)
        self.timer.timeout.connect(self.pump)
        self.timer.start(35)
        try:
            state = self.bus.call_sync(SCREEN, "/ScreenSaver", SCREEN, "GetActive", None,
                                       GLib.VariantType.new("(b)"), Gio.DBusCallFlags.NO_AUTO_START, 300, None)
            self.locked = state.unpack()[0]
        except GLib.Error:
            pass

    @staticmethod
    def pump():
        context = GLib.MainContext.default()
        for _ in range(20):
            if not context.pending():
                break
            context.iteration(False)

    def kwin_appeared(self, _bus, _name, owner):
        self.kwin_owner = owner

    def kwin_gone(self, *_):
        self.kwin_owner = ""
        self.session.clear_windows()

    def lock_changed(self, _bus, _sender, _path, _interface, _signal, params):
        self.locked = bool(params.unpack()[0])
        if self.locked:
            self.on_lock()

    def method(self, _bus, sender, _path, _interface, method, params, call):
        allowed = bool(sender == self.kwin_owner and self.session.active and
                       self.session.windows_enabled and not self.locked)
        if method == "WantsWindows":
            call.return_value(GLib.Variant("(b)", (allowed,)))
            return
        if allowed:
            raw = params.unpack()[0]
            if len(raw) <= 30000:
                try:
                    packet = json.loads(raw)
                    focused = self.identity(packet["focus"])
                    windows = [self.identity(item) for item in packet["windows"][:100]]
                    self.session.observe(focused, windows)
                except (ValueError, TypeError, KeyError, RecursionError):
                    pass
        call.return_value(None)

    @staticmethod
    def identity(window):
        if not isinstance(window, dict):
            return ""
        app_id = window.get("app")
        if isinstance(app_id, str) and app_id.strip():
            return app_id[:128]
        pid = window.get("pid")
        if type(pid) is int and 0 < pid < 2**31:
            try:
                return Path(f"/proc/{pid}/comm").read_text(errors="replace").strip()[:128]
            except OSError:
                pass
        return ""
