"""Read one frame from a user-selected Wayland ScreenCast portal source."""
import os
import shutil
import subprocess
from threading import Lock
from time import monotonic
from uuid import uuid4

from gi.repository import Gio, GLib


BUS_NAME = "org.freedesktop.portal.Desktop"
PORTAL = "/org/freedesktop/portal/desktop"
CAST = "org.freedesktop.portal.ScreenCast"
REMOTE = "org.freedesktop.portal.RemoteDesktop"
REQUEST = "org.freedesktop.portal.Request"
SESSION = "org.freedesktop.portal.Session"
WINDOW = 2
MONITOR = 1


class CaptureCanceled(Exception):
    pass


def close_object(bus, path, interface):
    bus.call(BUS_NAME, path, interface, "Close", None, None,
             Gio.DBusCallFlags.NONE, 1000, None, None, None)


def portal_request(bus, context, cancel, method, signature, args, options=None, *, interface=CAST):
    token = "work_" + uuid4().hex
    sender = bus.get_unique_name().lstrip(":").replace(".", "_")
    expected = f"{PORTAL}/request/{sender}/{token}"
    path = expected
    result = []

    def response(_bus, _sender, _path, _interface, _signal, params):
        result.append(params.unpack())

    def listen(object_path):
        return bus.signal_subscribe(BUS_NAME, REQUEST, "Response", object_path,
                                    None, Gio.DBusSignalFlags.NONE, response)

    subscription = listen(expected)
    try:
        values = {**(options or {}), "handle_token": GLib.Variant("s", token)}
        variant = GLib.Variant(signature, (*args, values))
        reply = bus.call_sync(BUS_NAME, PORTAL, interface, method, variant, GLib.VariantType.new("(o)"),
                              Gio.DBusCallFlags.NONE, 5000, None)
        path = reply.unpack()[0]
        if path != expected:
            bus.signal_unsubscribe(subscription)
            subscription = listen(path)
        deadline = monotonic() + 60
        while not result and not cancel.is_set() and monotonic() < deadline:
            while context.pending():
                context.iteration(False)
            if not result:
                cancel.wait(0.02)
        if not result:
            close_object(bus, path, REQUEST)
            if cancel.is_set():
                raise CaptureCanceled()
            raise RuntimeError("The desktop share picker timed out.")
        code, values = result[0]
        if code == 1:
            raise CaptureCanceled()
        if code:
            raise RuntimeError(f"The desktop denied {method}.")
        return values
    finally:
        bus.signal_unsubscribe(subscription)


def read_frame(descriptor, node, cancel):
    args = ["gst-launch-1.0", "-q", "pipewiresrc", f"fd={descriptor}", f"path={node}",
            "num-buffers=1", "!", "videoconvert", "!", "jpegenc", "quality=88", "!", "fdsink", "fd=1"]
    with subprocess.Popen(args, pass_fds=(descriptor,), stdout=subprocess.PIPE, stderr=subprocess.PIPE) as process:
        deadline = monotonic() + 8
        while not cancel.is_set() and monotonic() < deadline:
            try:
                image, _ = process.communicate(timeout=0.2)
            except subprocess.TimeoutExpired:
                continue
            if process.returncode or not image.startswith(b"\xff\xd8") or not image.endswith(b"\xff\xd9"):
                raise RuntimeError("The selected source returned no frame. Make it visible or try sharing the screen.")
            if len(image) > 12_000_000:
                raise RuntimeError("The selected frame is too large.")
            return image
        process.kill()
        process.communicate()
        if cancel.is_set():
            raise CaptureCanceled()
        raise RuntimeError("The selected source did not produce a frame in time.")


class SharedSource:
    def __init__(self, bus, session, nodes):
        self.bus, self.session, self.nodes = bus, session, nodes
        self.closed = False
        self.close_subscription = None
        self.lock = Lock()

    def watch_closed(self, on_closed):
        def closed(*_args):
            with self.lock:
                if self.closed:
                    return
                self.closed = True
                self.unwatch_closed()
            on_closed()

        with self.lock:
            if not self.closed and self.close_subscription is None:
                self.close_subscription = self.bus.signal_subscribe(
                    BUS_NAME, SESSION, "Closed", self.session, None, Gio.DBusSignalFlags.NONE, closed)

    def unwatch_closed(self):
        if self.close_subscription is not None:
            self.bus.signal_unsubscribe(self.close_subscription)
            self.close_subscription = None

    def close(self):
        with self.lock:
            self.unwatch_closed()
            if not self.closed:
                self.closed = True
                close_object(self.bus, self.session, SESSION)

    def frame(self, cancel):
        images = tuple(self.read_node(node, cancel) for node in self.nodes)
        return images[0] if len(images) == 1 else images

    def read_node(self, node, cancel):
        if self.closed or cancel.is_set():
            raise CaptureCanceled()
        response, fds = self.bus.call_with_unix_fd_list_sync(
            BUS_NAME, PORTAL, CAST, "OpenPipeWireRemote", GLib.Variant("(oa{sv})", (self.session, {})),
            GLib.VariantType.new("(h)"), Gio.DBusCallFlags.NONE, 5000, None, None)
        descriptor = fds.get(response.unpack()[0])
        try:
            return read_frame(descriptor, node, cancel)
        finally:
            os.close(descriptor)


class ControlledSource(SharedSource):
    def __init__(self, bus, session, node, logical_size):
        super().__init__(bus, session, (node,))
        self.logical_size = logical_size

    def notify(self, name, types, *values):
        if self.closed:
            raise CaptureCanceled()
        self.bus.call_sync(BUS_NAME, PORTAL, REMOTE, name,
                           GLib.Variant("(oa{sv}" + types + ")", (self.session, {}, *values)),
                           None, Gio.DBusCallFlags.NONE, 2500, None)

    def move(self, x, y, width, height):
        logical_width, logical_height = self.logical_size
        self.notify("NotifyPointerMotionAbsolute", "udd", self.nodes[0],
                    x * logical_width / width, y * logical_height / height)


def select_source(source_type, cancel, *, control=False):
    if source_type not in (WINDOW, MONITOR):
        raise ValueError("Unknown desktop capture type.")
    if not shutil.which("gst-launch-1.0"):
        raise RuntimeError("Install the Fedora GStreamer capture packages listed in Setup.")
    context = GLib.MainContext.new()
    context.push_thread_default()
    session = None
    try:
        if cancel.is_set():
            raise CaptureCanceled()
        bus = Gio.bus_get_sync(Gio.BusType.SESSION)
        supported = bus.call_sync(BUS_NAME, PORTAL, "org.freedesktop.DBus.Properties", "Get",
                                  GLib.Variant("(ss)", (CAST, "AvailableSourceTypes")), None,
                                  Gio.DBusCallFlags.NONE, 5000, None).unpack()[0]
        if not supported & source_type:
            raise RuntimeError("This desktop does not offer that share source. Enable the KDE ScreenCast portal or try screen sharing.")
        interface = REMOTE if control else CAST
        session = portal_request(
            bus, context, cancel, "CreateSession", "(a{sv})", (),
            {"session_handle_token": GLib.Variant("s", "work_" + uuid4().hex)},
            interface=interface)["session_handle"]
        if cancel.is_set():
            raise CaptureCanceled()
        if control:
            portal_request(bus, context, cancel, "SelectDevices", "(oa{sv})", (session,),
                           {"types": GLib.Variant("u", 3)}, interface=REMOTE)
        portal_request(bus, context, cancel, "SelectSources", "(oa{sv})", (session,), {
            "types": GLib.Variant("u", source_type),
            "multiple": GLib.Variant("b", source_type == MONITOR and not control),
        })
        if cancel.is_set():
            raise CaptureCanceled()
        result = portal_request(bus, context, cancel, "Start", "(osa{sv})", (session, ""), interface=interface)
        if cancel.is_set():
            raise CaptureCanceled()
        streams = result.get("streams", [])
        if not streams or (source_type == WINDOW and len(streams) != 1):
            raise RuntimeError("Choose the window or monitors you want to share.")
        if control:
            if len(streams) != 1 or result.get("devices", 0) & 3 != 3:
                raise RuntimeError("Select one display and grant both keyboard and pointer control.")
            node, properties = streams[0]
            logical_size = properties.get("logical_size") or properties.get("size")
            if not logical_size or min(logical_size) <= 0:
                raise RuntimeError("The desktop did not provide coordinates for the selected display.")
            shared = ControlledSource(bus, session, node, logical_size)
        else:
            shared = SharedSource(bus, session, tuple(stream[0] for stream in streams))
        session = None
        return shared
    finally:
        if session:
            close_object(bus, session, SESSION)
        context.pop_thread_default()


def capture_frame(source_type, cancel):
    shared = select_source(source_type, cancel)
    try:
        if cancel.wait(0.3):
            raise CaptureCanceled()
        return shared.frame(cancel)
    finally:
        shared.close()
