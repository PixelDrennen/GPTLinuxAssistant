"""Read one frame from a user-selected Wayland ScreenCast portal source."""
import os
import shutil
import subprocess
from time import monotonic
from uuid import uuid4

from gi.repository import Gio, GLib


BUS_NAME = "org.freedesktop.portal.Desktop"
PORTAL = "/org/freedesktop/portal/desktop"
CAST = f"{BUS_NAME}.ScreenCast"
REQUEST = f"{BUS_NAME}.Request"
SESSION = f"{BUS_NAME}.Session"
WINDOW = 2
MONITOR = 1


class CaptureCanceled(Exception):
    pass


def close_object(bus, path, interface):
    bus.call(BUS_NAME, path, interface, "Close", None, None,
             Gio.DBusCallFlags.NONE, 1000, None, None, None)


def portal_request(bus, context, cancel, method, signature, args, options=None):
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
        reply = bus.call_sync(BUS_NAME, PORTAL, CAST, method, variant, GLib.VariantType.new("(o)"),
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


def capture_frame(source_type, cancel):
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
        session = portal_request(
            bus, context, cancel, "CreateSession", "(a{sv})", (),
            {"session_handle_token": GLib.Variant("s", "work_" + uuid4().hex)})["session_handle"]
        if cancel.is_set():
            raise CaptureCanceled()
        portal_request(bus, context, cancel, "SelectSources", "(oa{sv})", (session,), {
            "types": GLib.Variant("u", source_type),
            "multiple": GLib.Variant("b", False),
        })
        if cancel.is_set():
            raise CaptureCanceled()
        result = portal_request(bus, context, cancel, "Start", "(osa{sv})", (session, ""))
        if cancel.is_set():
            raise CaptureCanceled()
        streams = result.get("streams", [])
        if len(streams) != 1:
            raise RuntimeError("Choose one window or screen.")
        node = streams[0][0]
        response, fds = bus.call_with_unix_fd_list_sync(
            BUS_NAME, PORTAL, CAST, "OpenPipeWireRemote", GLib.Variant("(oa{sv})", (session, {})),
            GLib.VariantType.new("(h)"), Gio.DBusCallFlags.NONE, 5000, None, None)
        descriptor = fds.get(response.unpack()[0])
        try:
            return read_frame(descriptor, node, cancel)
        finally:
            os.close(descriptor)
    finally:
        if session:
            close_object(bus, session, SESSION)
        context.pop_thread_default()
