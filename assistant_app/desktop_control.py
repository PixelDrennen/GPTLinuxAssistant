"""Review and run a desktop task through a single approved display."""
from dataclasses import dataclass, field
from threading import Event, Thread

from gi.repository import GLib
from PyQt5.QtCore import QObject, Qt, pyqtSignal
from PyQt5.QtGui import QColor, QImage, QPainter, QPen, QPixmap
from PyQt5.QtWidgets import QDialogButtonBox, QLabel, QVBoxLayout

from .computer import execute, plan
from .window_view import CaptureCanceled, MONITOR, select_source


@dataclass
class Task:
    request: str
    key: str
    cancel: Event = field(default_factory=Event)
    source: object = None
    actions: list = field(default_factory=list)
    anchor: tuple | None = None


class DesktopControl(QObject):
    permitted = pyqtSignal(object, object)
    planned = pyqtSignal(object, object, object, str)
    captured = pyqtSignal(object, object)

    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.task = None
        self.pending = None
        self.dialog = window.popup("Review desktop input", 790, 570)
        self.dialog.setAttribute(Qt.WA_QuitOnClose, False)
        layout = QVBoxLayout(self.dialog)
        self.summary = window.label("")
        layout.addWidget(self.summary)
        self.preview = QLabel(alignment=Qt.AlignCenter)
        layout.addWidget(self.preview)
        controls = QDialogButtonBox()
        approve = controls.addButton("Send this input", QDialogButtonBox.AcceptRole)
        stop = controls.addButton("Stop task", QDialogButtonBox.RejectRole)
        approve.clicked.connect(self.approve)
        stop.clicked.connect(self.dialog.reject)
        self.dialog.rejected.connect(self.denied)
        layout.addWidget(controls)
        self.permitted.connect(self.set_source)
        self.planned.connect(self.show_step)
        self.captured.connect(self.record_view)

    def start(self, request):
        if not self.window.session.active or not self.window.api_key:
            self.window.message("Start listening and save an OpenAI API key before using desktop control.")
            return
        if self.task or self.window.session.proposal or self.window.session.command or self.window.model_job:
            self.window.message("Finish or cancel the current task before starting desktop control.")
            return
        self.window.stop_monitor()
        task = Task(request, self.window.api_key)
        self.task = task
        self.window.log("Control", "Select one display and grant mouse and keyboard access. Screenshots go to OpenAI.")
        self.window.hide()
        self.next_step(task)

    def set_source(self, task, source):
        if task is self.task:
            task.source = source
        else:
            source.close()

    def stop(self, *, show=False):
        if self.task:
            self.task.cancel.set()
            if self.task.source:
                self.task.source.close()
        self.task = self.pending = None
        self.dialog.hide()
        self.preview.clear()
        if show:
            self.window.show_panel()

    def denied(self):
        if self.task:
            self.stop(show=True)
            self.window.log("Control", "Desktop task stopped. The proposed input was declined.")

    def next_step(self, task, approved=None):
        def run():
            try:
                source = task.source
                if source is None:
                    source = select_source(MONITOR, task.cancel, control=True)
                    self.permitted.emit(task, source)
                    if task.cancel.wait(0.4):
                        source.close()
                        return
                if approved is not None:
                    action, frame = approved
                    if task.cancel.wait(0.3):
                        return
                    execute(source, action, frame, task.cancel)
                    task.actions.append(action.label)
                    if action.kind == "click" and action.button == 272:
                        task.anchor = action.points[0]
                    if task.cancel.wait(0.4):
                        return
                if len(task.actions) >= 15:
                    raise RuntimeError("Done with this batch. Start another task to continue.")
                frame = source.frame(task.cancel)
                if task.cancel.is_set():
                    return
                self.captured.emit(task, frame)
                result = plan(frame, task.request, task.actions, task.key, task.anchor)
                self.planned.emit(task, frame, result, "")
            except CaptureCanceled:
                self.planned.emit(task, None, None, "Desktop control canceled.")
            except (GLib.Error, OSError, RuntimeError, ValueError, KeyError) as error:
                self.planned.emit(task, None, None, str(error))

        Thread(target=run, daemon=True).start()

    def record_view(self, task, frame):
        if task is self.task:
            self.window.record_frames("Desktop control view sent to OpenAI", frame)

    def show_step(self, task, frame, result, error):
        if task is not self.task:
            return
        if error or isinstance(result, str):
            self.stop(show=True)
            if error:
                self.window.log("Control", error)
                self.window.say("I stopped the desktop task. Check the chat for details.")
            else:
                self.window.remember_turn("general", task.request, result)
                self.window.last_reply = result
                self.window.say(result)
            return
        self.pending = result, frame
        self.summary.setText(result.label)
        image = QImage.fromData(frame)
        painter = QPainter(image)
        painter.setPen(QPen(QColor("#2df3b0"), max(3, image.width() // 500)))
        if len(result.points) > 1:
            for start, end in zip(result.points, result.points[1:]):
                painter.drawLine(*start, *end)
        for x, y in (result.points[0], result.points[-1]):
            radius = max(12, image.width() // 120)
            painter.drawEllipse(x - radius, y - radius, 2 * radius, 2 * radius)
        painter.end()
        self.preview.setPixmap(QPixmap.fromImage(image).scaled(760, 440, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        self.dialog.show()
        self.dialog.raise_()

    def approve(self):
        if self.task and self.pending:
            action = self.pending
            self.pending = None
            self.dialog.hide()
            self.preview.clear()
            self.window.log("Control", "Approved: " + action[0].label)
            self.next_step(self.task, action)
