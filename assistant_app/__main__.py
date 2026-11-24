"""Tray app for session context, task requests, and edit previews."""
import argparse
import sys
from threading import Thread
from urllib.parse import urlsplit

from gi.repository import GLib
from PyQt5.QtCore import QTimer, Qt, QUrl, pyqtSignal
from PyQt5.QtGui import QDesktopServices
from PyQt5.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
    QMainWindow, QMenu, QMessageBox, QPlainTextEdit, QPushButton, QScrollArea, QStyle, QSystemTrayIcon,
    QVBoxLayout, QWidget,
)

from .desktop import Desktop
from .drafting import complete
from .ipc import LocalBridge
from .session import Session
from .speech import Microphone


class Window(QMainWindow):
    drafted = pyqtSignal(object, str, str)

    def __init__(self, session, args):
        super().__init__()
        self.session = session
        self.audio = Microphone()
        self.audio.heard.connect(self.heard)
        self.audio.failed.connect(self.audio_failed)
        self.drafted.connect(self.draft_finished)
        self.mode = None
        self.model_job = None
        self.previewed = None
        self.hint_seen = -float("inf")
        self.last_tray_state = None
        self.audio_status = ""
        self.setWindowTitle("GPT Linux Assistant")
        self.resize(760, 760)
        root = QWidget()
        scroller = QScrollArea()
        scroller.setWidgetResizable(True)
        scroller.setWidget(root)
        self.setCentralWidget(scroller)
        stack = QVBoxLayout(root)

        self.state = self.label("")
        self.audio_note = self.label("")
        self.summary = self.label("")
        self.apps = self.label("")
        self.status = self.label("")
        for label in (self.state, self.audio_note, self.summary, self.apps, self.status):
            stack.addWidget(label)
        row = QHBoxLayout()
        stack.addLayout(row)
        self.button(row, "Start listening", self.start)
        self.button(row, "Pause", self.pause)
        self.button(row, "Ask by voice", self.ask_voice)
        self.offer = self.button(row, "Review suggestion", self.follow_suggestion)
        self.offer.hide()

        settings = QGroupBox("Context and permissions")
        form = QFormLayout(settings)
        stack.addWidget(settings)
        self.mic = QCheckBox("Use microphone (Vosk)")
        self.mic_path = QLineEdit(args.vosk_model or "")
        self.mic_path.setPlaceholderText("Path to the extracted Vosk model")
        self.mic.toggled.connect(self.refresh_audio)
        self.mic_path.editingFinished.connect(self.refresh_audio)
        form.addRow(self.mic, self.mic_path)
        self.window_access = QCheckBox("Use KWin app identities")
        self.window_access.toggled.connect(self.set_windows)
        self.exclude = QLineEdit()
        self.exclude.setPlaceholderText("Excluded application IDs, comma separated")
        self.exclude.textChanged.connect(self.set_windows)
        form.addRow(self.window_access, self.exclude)
        self.rider = QCheckBox("Enable Rider")
        self.unity = QCheckBox("Enable Unity")
        self.quiet = QCheckBox("Quiet mode")
        for box, kind in ((self.rider, "rider"), (self.unity, "unity")):
            box.toggled.connect(lambda enabled, kind=kind: self.enable_bridge(kind, enabled))
        modes = QHBoxLayout()
        for box in (self.rider, self.unity, self.quiet):
            modes.addWidget(box)
        form.addRow(modes)

        work = QGroupBox("Request")
        form = QFormLayout(work)
        stack.addWidget(work)
        self.workflow = QComboBox()
        for label, value in (("Rider", "rider"), ("Unity", "unity"), ("Web browser", "browser"),
                             ("Slack", "slack"), ("Other app", "general")):
            self.workflow.addItem(label, value)
        self.workflow.currentIndexChanged.connect(self.switch_workflow)
        self.request = QLineEdit()
        self.request.setPlaceholderText("Finish writing this prompt for me")
        self.request.setMaxLength(1500)
        self.request.returnPressed.connect(self.ask)
        self.model = QLineEdit(args.ollama_model or "")
        self.model.setPlaceholderText("Local Ollama model name")
        self.model.setMaxLength(100)
        self.include_narration = QCheckBox("Include recent narration with local model requests")
        self.input = QPlainTextEdit()
        self.input.setPlaceholderText("Paste selected page, conversation, or app context")
        self.input.setMaximumHeight(70)
        self.output = QPlainTextEdit()
        self.output.setPlaceholderText("Generated draft or your own replacement text")
        self.output.setMaximumHeight(100)
        self.url = QLineEdit()
        self.url.setPlaceholderText("https://…")
        self.url.setMaxLength(2000)
        self.url.returnPressed.connect(self.open_preview)
        form.addRow("App", self.workflow)
        form.addRow("Task", self.request)
        form.addRow("Local model", self.model)
        form.addRow(self.include_narration)
        form.addRow("Shared context", self.input)
        form.addRow("Draft", self.output)
        row = QHBoxLayout()
        self.button(row, "Generate draft", self.ask)
        self.apply = self.button(row, "Preview Rider edit", self.preview_draft)
        form.addRow(row)
        self.link_button = QPushButton("Preview open link")
        self.link_button.clicked.connect(self.open_preview)
        form.addRow(self.url, self.link_button)

        self.review = QGroupBox("Approve this action")
        stack.addWidget(self.review)
        layout = QVBoxLayout(self.review)
        self.target_label = self.label("")
        layout.addWidget(self.target_label)
        previews = QHBoxLayout()
        layout.addLayout(previews)
        self.before = self.preview(previews, "Before")
        self.after = self.preview(previews, "Proposed")
        row = QHBoxLayout()
        layout.addLayout(row)
        self.button(row, "Approve once", lambda: self.respond(True))
        self.button(row, "Decline", lambda: self.respond(False))
        self.voice_ack = self.button(row, "Answer by voice", self.arm_reply)
        self.review.hide()
        stack.addStretch()

        self.tray = QSystemTrayIcon(self)
        self.tray.setIcon(self.style().standardIcon(QStyle.SP_MediaPause))
        menu = QMenu(self)
        menu.addAction("Show assistant", self.show_panel)
        menu.addAction("Start listening", self.start)
        menu.addAction("Pause", self.pause)
        menu.addAction("Ask assistant", self.show_panel)
        menu.addAction("Quit", QApplication.instance().quit)
        self.tray.setContextMenu(menu)
        self.tray.messageClicked.connect(self.show_panel)
        self.tray.activated.connect(lambda reason: self.show_panel() if reason == QSystemTrayIcon.Trigger else None)
        if self.tray.isSystemTrayAvailable():
            self.tray.show()
        try:
            self.desktop = Desktop(session, self.pause, self)
        except GLib.Error:
            self.desktop = None
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.render)
        self.timer.start(200)
        self.switch_workflow()
        self.render()

    @staticmethod
    def label(value):
        label = QLabel(value)
        label.setWordWrap(True)
        label.setTextFormat(Qt.PlainText)
        return label

    @staticmethod
    def button(row, name, callback):
        button = QPushButton(name)
        button.clicked.connect(callback)
        row.addWidget(button)
        return button

    def preview(self, row, name):
        box = QGroupBox(name)
        stack = QVBoxLayout(box)
        text = QPlainTextEdit()
        text.setReadOnly(True)
        text.setMinimumHeight(90)
        stack.addWidget(text)
        row.addWidget(box)
        return text

    def show_panel(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()
        self.request.setFocus()

    def closeEvent(self, event):
        if self.tray.isVisible():
            self.hide()
            event.ignore()
        else:
            event.accept()

    def start(self):
        if self.desktop is not None and self.desktop.locked:
            return
        if not self.session.active:
            self.session.start()
            self.refresh_audio()

    def pause(self):
        self.audio.stop()
        self.mode = None
        self.model_job = None
        self.audio_status = ""
        self.session.pause()
        for field in (self.input, self.output, self.request, self.url, self.before, self.after):
            field.clear()
        self.render()

    def set_windows(self):
        with self.session.lock:
            self.session.windows_enabled = self.window_access.isChecked()
            self.session.exclusions = {name.strip().casefold() for name in self.exclude.text().split(",") if name.strip()}
            self.session.clear_windows()
            self.session.suggestion = ""

    def enable_bridge(self, kind, enabled):
        with self.session.lock:
            if enabled:
                self.session.bridges.add(kind)
            else:
                self.session.revoke(kind)

    def switch_workflow(self):
        kind = self.workflow.currentData()
        self.apply.setText("Preview Rider edit" if kind == "rider" else
                           "Preview Unity connection" if kind == "unity" else "Preview copy")
        self.output.clear()

    def refresh_audio(self):
        self.audio.stop()
        self.mode = None
        path = self.mic_path.text().strip()
        if not self.session.active or not self.mic.isChecked():
            self.audio_status = ""
        elif not path:
            self.audio_status = "Set the Vosk model path to use the microphone."
        else:
            self.audio_status = "Starting microphone"
            self.audio.start(path)

    def audio_failed(self, generation, message):
        if generation == self.audio.generation:
            self.mode = None
            self.audio_status = "Microphone unavailable. " + message

    def arm(self, action, proposal_id=""):
        if not self.session.active or not self.mic.isChecked() or not self.mic_path.text().strip():
            self.message("Start listening and enable the microphone first.")
            return
        self.audio.start(self.mic_path.text().strip())
        self.mode = (action, proposal_id, self.session.clock() + 12)
        self.audio_status = "Say your request." if action == "ask" else "Say yes or no to this proposal."

    def ask_voice(self):
        self.show_panel()
        self.arm("ask")

    def arm_reply(self):
        if self.previewed and self.review.isVisible():
            self.arm("reply", self.previewed)

    def heard(self, generation, text, confidence):
        if not self.session.active or generation != self.audio.generation:
            return
        self.audio_status = "Microphone listening"
        if self.mode:
            action, proposal_id, expires = self.mode
            self.refresh_audio()
            if expires < self.session.clock():
                return
            if action == "reply":
                if text in ("yes", "no") and confidence >= 0.85 and self.review.isVisible():
                    self.respond(text == "yes", proposal_id)
                else:
                    self.message("Voice reply was unclear. Use the approval buttons.")
                return
            self.request.setText(text)
            self.ask()
        elif text.casefold().startswith("assistant "):
            self.show_panel()
            self.request.setText(text[len("assistant "):])
            self.ask()
        else:
            self.session.narrate(text)

    def message(self, text):
        with self.session.lock:
            self.session.status = text

    def ask(self):
        if not self.session.active:
            self.message("Start listening before making a request.")
            return
        if self.session.proposal or self.session.command:
            self.message("Resolve the current proposal first.")
            return
        request = self.request.text().strip()
        kind = self.workflow.currentData()
        words = request.casefold()
        if "rider" in words:
            kind = "rider"
        elif "unity" in words and ("prefab" in words or "dialog" in words):
            kind = "unity"
        elif "slack" in words:
            kind = "slack"
        elif "browser" in words or "web page" in words:
            kind = "browser"
        index = self.workflow.findData(kind)
        if index != self.workflow.currentIndex():
            self.workflow.setCurrentIndex(index)
        if kind == "unity":
            self.unity_preview()
            return
        with self.session.lock:
            self.session.expire()
            target = self.session.targets.get("rider") if kind == "rider" else None
            narration = [value for _, source, value in self.session.events if source == "speech"]
            epoch = self.session.epoch
        if kind == "rider" and not target:
            self.message("Which draft should I finish? Select it in Rider and run Share Selection with Work Assistant.")
            return
        if not request:
            self.message("What should I do with this draft or context?")
            return
        model = self.model.text().strip()
        if not model:
            self.message("Enter a local Ollama model, or write the replacement in the Draft box.")
            return
        if self.model_job:
            self.message("A draft is already generating.")
            return
        original = target.data["text"] if target else self.input.toPlainText()
        if len(original) > 16000:
            self.message("Share a shorter excerpt, up to 16,000 characters.")
            return
        context = narration[-5:] if self.include_narration.isChecked() else []
        job = (epoch, kind, target, self.output.toPlainText(), request, self.input.toPlainText())
        self.model_job = job
        self.message("Generating a draft with the configured Ollama model.")

        def generate():
            try:
                result = complete(model, original, request, context, kind)
                self.drafted.emit(job, result, "")
            except (OSError, ValueError, AttributeError) as exc:
                self.drafted.emit(job, "", str(exc))

        Thread(target=generate, daemon=True).start()

    def draft_finished(self, job, result, error):
        if self.model_job is not job:
            return
        self.model_job = None
        epoch, kind, target, original_output, request, original_context = job
        with self.session.lock:
            self.session.expire()
            if (epoch != self.session.epoch or self.workflow.currentData() != kind or
                    (kind == "rider" and self.session.targets.get("rider") is not target) or
                    self.output.toPlainText() != original_output or self.request.text().strip() != request or
                    (kind != "rider" and self.input.toPlainText() != original_context)):
                self.message("Draft discarded because the target or request view changed.")
                return
        if error:
            self.message("Draft generation failed. " + error)
            return
        self.output.setPlainText(result)
        self.message("Draft ready to preview.")
        self.preview_draft()

    def preview_draft(self):
        kind = self.workflow.currentData()
        if kind == "unity":
            self.unity_preview()
            return
        replacement = self.output.toPlainText()
        try:
            if not replacement.strip() or len(replacement) > 24000:
                raise ValueError("Enter a draft of up to 24,000 characters.")
            if kind == "rider":
                with self.session.lock:
                    target = self.session.targets.get("rider")
                    if not target:
                        raise ValueError("Share the selected draft from Rider first.")
                    self.session.propose(target, replacement)
            else:
                self.session.propose_desktop("copy", replacement)
        except ValueError as exc:
            self.message(str(exc))
        self.render()

    def follow_suggestion(self):
        with self.session.lock:
            self.session.expire()
            kind = self.session.suggestion
        if kind == "unity":
            self.workflow.setCurrentIndex(self.workflow.findData("unity"))
            self.unity_preview()
        elif kind in ("slack", "browser"):
            self.workflow.setCurrentIndex(self.workflow.findData(kind))
            self.show_panel()
            self.input.setFocus()
            self.message("Paste the relevant excerpt and tell me what you need.")

    def unity_preview(self):
        try:
            with self.session.lock:
                target = self.session.targets.get("unity")
                if not target:
                    raise ValueError("Which links should I finish? Open the prefab and share a source field and destination from Unity.")
                self.session.propose(target)
        except ValueError as exc:
            self.message(str(exc))
        self.show_panel()
        self.render()

    def open_preview(self):
        value = self.url.text().strip()
        try:
            if any(char.isspace() or ord(char) < 32 for char in value) or "\\" in value:
                raise ValueError("Enter a valid HTTP or HTTPS link.")
            parsed = urlsplit(value)
            if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username is not None:
                raise ValueError("Enter an HTTP or HTTPS link without credentials.")
            url = QUrl(value, QUrl.StrictMode)
            if not url.isValid() or not url.host():
                raise ValueError("Enter a valid HTTP or HTTPS link.")
            self.session.propose_desktop("open", url.toString(QUrl.FullyEncoded))
        except ValueError as exc:
            self.message(str(exc))
        self.render()

    def respond(self, approve, proposal_id=None):
        proposal_id = proposal_id or self.previewed
        try:
            with self.session.lock:
                proposal = self.session.proposal
                self.session.respond(proposal_id, approve)
                if approve and proposal.target.kind == "desktop":
                    action = proposal.target.data["action"]
                    value = proposal.target.data["value"]
                    if action == "copy":
                        QApplication.clipboard().setText(value)
                        self.message("Draft copied. Paste it in the destination app.")
                    else:
                        opened = QDesktopServices.openUrl(QUrl(value, QUrl.StrictMode))
                        self.message("Link handed to the default browser." if opened else "Could not open the link.")
                    self.session.command = None
        except ValueError as exc:
            self.message(str(exc))
        self.render()

    def render(self):
        session = self.session
        with session.lock:
            summary = session.summary()
            active, proposal = session.active, session.proposal
            status, apps = session.status, ", ".join(session.windows)
            suggestion = session.suggestion if not self.quiet.isChecked() else ""
            targets = dict(session.targets)
            hint_time = session.last_hint
        self.state.setText("Listening session active" if active else "Paused")
        self.tray.setToolTip("GPT Linux Assistant · " + ("Listening" if active else "Paused"))
        if active != self.last_tray_state:
            self.tray.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay if active else QStyle.SP_MediaPause))
            self.last_tray_state = active
        self.audio_note.setText(self.audio_status)
        self.audio_note.setVisible(bool(self.audio_status))
        self.summary.setText(summary if active else "")
        self.apps.setText("Open apps: " + apps if apps else "")
        self.apps.setVisible(bool(apps))
        shared = [target.label for target in targets.values() if target.kind != "desktop"]
        if shared:
            status += "\nShared: " + ", ".join(shared)
        self.status.setText(status)
        self.offer.setVisible(bool(suggestion))
        if suggestion:
            title, message = {
                "unity": ("Review Unity handoff", "I can help finish a dialogue connection."),
                "slack": ("Draft with Slack context", "Share the Slack excerpt and I can draft a reply or summary."),
                "browser": ("Summarize a web page", "Share the page text and I can summarize it."),
            }[suggestion]
            self.offer.setText(title)
            if self.hint_seen != hint_time:
                self.hint_seen = hint_time
                if self.tray.isVisible() and not self.isVisible():
                    self.tray.showMessage(title, message)
        proposal_id = proposal.id if proposal else None
        if self.mode and (self.mode[2] < session.clock() or (self.mode[0] == "reply" and self.mode[1] != proposal_id)):
            self.refresh_audio()
        if proposal_id != self.previewed:
            self.previewed = proposal_id
            self.review.setVisible(bool(proposal))
            self.before.setPlainText(proposal.before if proposal else "")
            self.after.setPlainText(proposal.after if proposal else "")
            label = proposal.target.label if proposal else ""
            if proposal and proposal.target.kind == "rider":
                span = proposal.target.data
                label += f' · Selected range {span["start"]}–{span["end"]}'
            self.target_label.setText(label)
        self.voice_ack.setEnabled(self.mic.isChecked())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--vosk-model")
    parser.add_argument("--ollama-model")
    args = parser.parse_args()
    app = QApplication([sys.argv[0]])
    app.setApplicationName("GPT Linux Assistant")
    app.setDesktopFileName("gpt-linux-assistant")
    session = Session()
    try:
        bridge = LocalBridge(session)
    except (OSError, KeyError) as exc:
        QMessageBox.critical(None, "Cannot start GPT Linux Assistant", str(exc))
        return 1
    try:
        window = Window(session, args)
        window.show()
        return app.exec_()
    finally:
        session.pause()
        if "window" in locals():
            window.audio.stop()
        bridge.close()


if __name__ == "__main__":
    sys.exit(main())
