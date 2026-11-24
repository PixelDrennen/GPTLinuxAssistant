"""Tray app for session context, task requests, and edit previews."""
import argparse
from datetime import datetime
import os
from pathlib import Path
import re
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
from .live import VoiceMeter
from .session import Session
from .speech import Microphone
from .voice import Speaker


class Window(QMainWindow):
    drafted = pyqtSignal(object, object, str)

    def __init__(self, session, args):
        super().__init__()
        self.session = session
        self.audio = Microphone()
        self.audio.ready.connect(self.audio_ready)
        self.audio.heard.connect(self.heard)
        self.audio.failed.connect(self.audio_failed)
        self.audio.meter.connect(self.mic_sample)
        self.audio.partial.connect(self.mic_partial)
        self.speaker = Speaker()
        self.speaker.meter.connect(self.speaker_sample)
        self.speaker.finished.connect(self.speaker_finished)
        self.speaking = False
        self.voice_approval = None
        self.clarification = None
        self.waiting_for_share = None
        self.last_status = ""
        self.last_focus = ""
        self.last_reply = ""
        self.last_turn = None
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
        self.scroller = QScrollArea()
        self.scroller.setWidgetResizable(True)
        self.scroller.setWidget(root)
        self.setCentralWidget(self.scroller)
        stack = QVBoxLayout(root)
        stack.setContentsMargins(18, 16, 18, 16)
        stack.setSpacing(9)

        header = QHBoxLayout()
        title = self.label("Work assistant")
        title_font = title.font()
        title_font.setPointSize(title_font.pointSize() + 7)
        title_font.setBold(True)
        title.setFont(title_font)
        header.addWidget(title, 1)
        stack.addLayout(header)
        self.state = self.label("")
        self.audio_note = self.label("")
        self.summary = self.label("")
        self.apps = self.label("")
        self.status = self.label("")
        header.addWidget(self.state)
        for label in (self.audio_note, self.summary, self.apps, self.status):
            stack.addWidget(label)
        row = QHBoxLayout()
        stack.addLayout(row)
        self.start_button = self.button(row, "Start listening", self.start)
        self.pause_button = self.button(row, "Pause", self.pause)
        self.button(row, "Ask by voice", self.ask_voice)
        self.offer = self.button(row, "Review suggestion", self.follow_suggestion)
        self.offer.hide()

        signals = QHBoxLayout()
        for label, color in (("You", "#16b8b1"), ("Assistant voice", "#8a70e0")):
            column = QVBoxLayout()
            column.addWidget(self.label(label))
            meter = VoiceMeter(label, color)
            column.addWidget(meter)
            signals.addLayout(column)
            if label == "You":
                self.mic_meter = meter
            else:
                self.ai_meter = meter
        stack.addLayout(signals)
        self.partial = self.label("")
        stack.addWidget(self.partial)
        self.journal = QPlainTextEdit()
        self.journal.setReadOnly(True)
        self.journal.setAccessibleName("Activity log")
        self.journal.setPlaceholderText("Activity log")
        self.journal.setMinimumHeight(170)
        self.journal.document().setMaximumBlockCount(240)
        stack.addWidget(self.label("Activity log"))
        stack.addWidget(self.journal, 1)
        self.settings_button = QPushButton("Setup")
        self.settings_button.setCheckable(True)
        stack.addWidget(self.settings_button)
        settings = QGroupBox("Voice, context and permissions")
        self.settings_button.toggled.connect(settings.setVisible)
        form = QFormLayout(settings)
        stack.addWidget(settings)
        self.mic = QCheckBox("Use microphone (Vosk)")
        default_path = Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local/share"))) / "gpt-linux-assistant/vosk-model"
        mic_path = args.vosk_model or (str(default_path) if default_path.is_dir() else "")
        self.mic_path = QLineEdit(mic_path)
        self.mic.setChecked(bool(mic_path))
        self.mic_path.setPlaceholderText("Path to the extracted Vosk model")
        self.mic.toggled.connect(self.refresh_audio)
        self.mic_path.editingFinished.connect(self.refresh_audio)
        form.addRow(self.mic, self.mic_path)
        self.spoken = QCheckBox("Speak replies")
        self.spoken.setChecked(True)
        self.spoken.toggled.connect(self.speech_setting)
        form.addRow(self.spoken)
        self.provider = QComboBox()
        self.provider.addItem("Local Ollama", "ollama")
        self.provider.addItem("OpenAI API", "openai")
        self.provider.setCurrentIndex(1 if args.openai_model else 0)
        self.models = {"ollama": args.ollama_model or "", "openai": args.openai_model or "gpt-4.1-mini"}
        self.model = QLineEdit(self.models[self.provider.currentData()])
        self.model.setMaxLength(100)
        self.current_provider = self.provider.currentData()
        self.provider.currentIndexChanged.connect(self.switch_provider)
        form.addRow(self.provider, self.model)
        self.include_narration = QCheckBox("Include recent narration and app focus in model requests")
        form.addRow(self.include_narration)
        self.cloud_notice = self.label("OpenAI receives request text and the selected draft or excerpt. Microphone audio stays local.")
        form.addRow(self.cloud_notice)
        self.cloud_notice.setVisible(self.current_provider == "openai")
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

        self.settings_button.setChecked(not (mic_path and self.model.text()))
        settings.setVisible(self.settings_button.isChecked())
        self.manual_button = QPushButton("Manual controls")
        self.manual_button.setCheckable(True)
        stack.addWidget(self.manual_button)
        work = QGroupBox("Request and draft")
        self.manual_button.toggled.connect(work.setVisible)
        work.hide()
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
        self.state.setFocus()

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
            self.log("Session", "Listening started.")
            self.last_status = "Listening"

    def pause(self):
        self.audio.stop()
        self.speaker.stop()
        self.speaking = False
        self.voice_approval = None
        self.clarification = None
        self.waiting_for_share = None
        self.last_turn = None
        self.last_reply = ""
        self.mode = None
        self.model_job = None
        self.audio_status = ""
        self.last_status = ""
        self.last_focus = ""
        self.mic_meter.clear()
        self.ai_meter.clear()
        self.partial.clear()
        self.journal.clear()
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

    def switch_provider(self):
        self.models[self.current_provider] = self.model.text()
        self.current_provider = self.provider.currentData()
        self.model.setText(self.models[self.current_provider])
        self.cloud_notice.setVisible(self.current_provider == "openai")
        self.model_job = None
        self.clarification = None
        self.waiting_for_share = None
        self.last_turn = None

    def log(self, source, text):
        if self.session.active and text:
            text = " ".join(text.split())
            self.journal.appendPlainText(f"{datetime.now():%H:%M:%S}  {source}  ·  {text[:2000]}")

    def mic_sample(self, generation, amount):
        if generation == self.audio.generation and self.session.active:
            self.mic_meter.sample(amount)

    def mic_partial(self, generation, text):
        if generation == self.audio.generation and self.session.active:
            self.partial.setText(text[:300])

    def speaker_sample(self, generation, amount):
        if generation == self.speaker.generation and self.speaking:
            self.ai_meter.sample(amount)

    def speech_setting(self, enabled):
        if not enabled and self.speaking:
            self.speaker.stop()
            self.end_speech()

    def end_speech(self):
        self.speaking = False
        self.ai_meter.clear()
        self.refresh_audio()
        self.arm_spoken_approval()

    def speaker_finished(self, generation, error):
        if generation == self.speaker.generation and self.session.active:
            self.end_speech()
            if error:
                self.log("Audio", error)

    def say(self, text, *, record=True):
        if not self.session.active or not text:
            return
        if record:
            self.log("Assistant", text)
        if not self.spoken.isChecked():
            return
        self.audio.stop()
        self.mode = None
        self.voice_approval = None
        self.mic_meter.clear()
        self.partial.clear()
        self.speaking = True
        self.audio_status = "Assistant speaking · microphone paused"
        self.speaker.start(text[:420])

    def refresh_audio(self):
        if self.speaking:
            return
        self.audio.stop()
        self.voice_approval = None
        self.mode = None
        path = self.mic_path.text().strip()
        if not self.session.active or not self.mic.isChecked():
            self.audio_status = ""
        elif not path:
            self.audio_status = "Set the Vosk model path to use the microphone."
        else:
            self.audio_status = "Starting microphone"
            self.audio.start(path)

    def audio_ready(self, generation):
        if generation == self.audio.generation and self.mode is None:
            self.audio_status = "Microphone listening"

    def audio_failed(self, generation, message):
        if generation == self.audio.generation:
            self.mode = None
            self.audio_status = "Microphone unavailable. " + message

    def arm(self, action, proposal_id=""):
        if not self.session.active or not self.mic.isChecked() or not self.mic_path.text().strip():
            self.message("Start listening and enable the microphone first.")
            return
        if self.speaking:
            self.speaker.stop()
            self.speaking = False
            self.ai_meter.clear()
        self.audio.start(self.mic_path.text().strip())
        self.voice_approval = None
        self.mode = (action, proposal_id, self.session.clock() + 12)
        self.audio_status = "Say your request." if action == "ask" else "Say yes or no to this proposal."

    def ask_voice(self):
        self.show_panel()
        self.arm("ask")

    def arm_reply(self):
        if self.previewed and self.review.isVisible():
            self.arm("reply", self.previewed)

    def arm_spoken_approval(self):
        if self.previewed and self.review.isVisible() and self.mic.isChecked() and self.mic_path.text().strip():
            self.voice_approval = (self.audio.generation, self.previewed)

    def heard(self, generation, text, confidence):
        if not self.session.active or self.speaking or generation != self.audio.generation:
            return
        self.audio_status = "Microphone listening"
        words = " ".join(re.findall(r"[a-z0-9]+", text.casefold()))
        self.log("You", text)
        if words in ("assistant approve", "assistant decline"):
            if (confidence >= 0.85 and self.voice_approval == (generation, self.previewed)
                    and self.review.isVisible() and self.session.proposal):
                self.respond(words.endswith("approve"), self.previewed)
            else:
                self.log("Approval", "No matching spoken approval. Use the visible preview.")
            return
        if self.mode:
            action, proposal_id, expires = self.mode
            self.refresh_audio()
            if expires < self.session.clock():
                return
            if action == "reply":
                if words in ("yes", "no") and confidence >= 0.85 and self.review.isVisible():
                    self.respond(words == "yes", proposal_id)
                else:
                    self.message("Voice reply was unclear. Use the approval buttons.")
                return
            self.ask(voice_request=text)
        elif words.startswith("assistant "):
            request = re.sub(r"^assistant[\W_]*", "", text, flags=re.IGNORECASE).strip()
            self.ask(voice_request=request)
        else:
            self.session.narrate(text)

    def message(self, text):
        with self.session.lock:
            self.session.status = text

    def answer(self, text, spoken):
        self.message(text)
        if spoken:
            self.last_status = text
            self.say(text)

    def ask(self, *, voice_request=None):
        voice = voice_request is not None
        request = voice_request.strip()[:1500] if voice else self.request.text().strip()
        words = " ".join(re.findall(r"[a-z0-9]+", request.casefold()))
        if voice and words in ("pause", "stop listening", "pause listening"):
            self.pause()
            return
        if voice and words in ("repeat that", "say that again", "read the last reply"):
            self.say(self.last_reply or "There is no reply to repeat yet.")
            return
        if not self.session.active:
            self.message("Start listening before making a request.")
            return
        with self.session.lock:
            self.session.expire()
            blocked = bool(self.session.proposal or self.session.command)
            narration = [value for _, source, value in self.session.events if source == "speech"]
            focus = self.session.focus
            epoch = self.session.epoch
        if blocked:
            if voice:
                self.log("Approval", "Review the pending action or say Assistant decline.")
            else:
                self.message("Resolve the current proposal first.")
            return
        if voice and words in ("what am i doing", "what am i working on"):
            self.say(self.session.summary())
            return
        if voice and words in ("copy that", "copy the last reply", "copy the draft"):
            if not self.last_reply:
                self.say("There is no reply to copy yet.")
                return
            self.show_panel()
            self.session.propose_desktop("copy", self.last_reply)
            self.render()
            return
        if voice and words in ("review suggestion", "take the suggestion"):
            self.follow_suggestion()
            return
        if voice and words in ("cancel", "cancel request"):
            self.clarification = None
            self.waiting_for_share = None
            self.model_job = None
            self.say("Request canceled.")
            return
        if self.model_job:
            self.answer("A reply is already being prepared.", voice)
            return

        self.waiting_for_share = None
        kind = "general" if voice else self.workflow.currentData()
        has_app = True
        if re.search(r"\brider\b", words):
            kind = "rider"
        elif "unity" in words and any(value in words for value in ("prefab", "dialog", "connect")):
            kind = "unity"
        elif "slack" in words:
            kind = "slack"
        elif "browser" in words or "web page" in words:
            kind = "browser"
        else:
            has_app = False
        clarification, self.clarification = self.clarification, None
        continued = (voice and not has_app and clarification and clarification[0] > self.session.clock()
                     and clarification[1] == self.current_provider)
        if continued:
            _, _, kind, original_request, question = clarification
            request = f"{original_request}\nClarifying question: {question}\nMy answer: {request}"[:3000]
        elif voice and not has_app and re.search(r"\b(prompt|selection)\b", words):
            kind = "rider"
        index = self.workflow.findData(kind)
        if index != self.workflow.currentIndex():
            self.workflow.setCurrentIndex(index)
        if kind == "unity":
            self.unity_preview(spoken=voice)
            return

        with self.session.lock:
            target = self.session.targets.get("rider") if kind == "rider" else None
        if kind == "rider" and not target:
            if voice:
                self.waiting_for_share = ("rider", request, self.session.clock() + 90)
            self.answer("Select the draft in Rider and choose Share Selection with Work Assistant.", voice)
            return
        if not request:
            self.answer("What should I do with this draft or context?", voice)
            return
        model = self.model.text().strip()
        if not model:
            self.answer("Choose a model under Setup to start voice conversations.", voice)
            return
        api_key = None
        if self.current_provider == "openai":
            api_key = os.environ.get("OPENAI_API_KEY", "").strip()
            if not api_key:
                self.answer("OpenAI is selected. Launch the assistant with your OpenAI API key set.", voice)
                return
        original = target.data["text"] if target else self.input.toPlainText()
        if len(original) > 16000:
            self.answer("Share a shorter excerpt, up to 16,000 characters.", voice)
            return
        context = {}
        if self.include_narration.isChecked():
            context = {"narration": narration[-5:], "focused_app": focus}
        if voice and self.last_turn and self.last_turn[0] == kind:
            context["previous_turn"] = self.last_turn[1:]
        job = (epoch, kind, target, self.output.toPlainText(), self.request.text(),
               self.input.toPlainText(), voice, request, model)
        self.model_job = job
        self.message("Preparing a reply.")
        if voice:
            self.log("Request", request)

        def generate():
            try:
                result = complete(model, original, request, context, kind, api_key=api_key)
                self.drafted.emit(job, result, "")
            except (OSError, ValueError) as exc:
                self.drafted.emit(job, None, str(exc))

        Thread(target=generate, daemon=True).start()

    def draft_finished(self, job, result, error):
        if self.model_job is not job:
            return
        self.model_job = None
        epoch, kind, target, original_output, typed_request, original_context, voice, request, model = job
        with self.session.lock:
            self.session.expire()
            changed = (epoch != self.session.epoch or self.workflow.currentData() != kind or
                       (kind == "rider" and self.session.targets.get("rider") is not target) or
                       self.output.toPlainText() != original_output or self.request.text() != typed_request or
                       self.model.text().strip() != model or
                       (kind != "rider" and self.input.toPlainText() != original_context))
        if changed:
            self.answer("The target or request changed. Please ask again.", voice)
            return
        if error:
            self.message("Model request failed. " + error)
            if voice:
                self.say("The model request failed. Check the activity log for details.")
            return
        if result.question:
            if voice:
                self.clarification = (self.session.clock() + 90, self.current_provider, kind, request, result.question)
                self.answer(result.question + " Start your answer with Assistant.", True)
            else:
                self.message(result.question + "\nAdd the answer to the Task field.")
                self.request.setFocus()
            return
        self.output.setPlainText(result.draft)
        self.last_reply = result.draft
        self.last_turn = (kind, request[:1200], result.draft[:1600]) if voice else None
        if voice:
            if kind == "rider":
                self.show_panel()
            else:
                self.message("Reply ready. Say Assistant copy that to use it in another app.")
                self.log("Assistant", result.draft)
                spoken = result.draft if len(result.draft) <= 400 else "I prepared a longer reply. It is in the activity log and Draft box."
                self.say(spoken, record=False)
                return
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
            self.unity_preview(spoken=True)
        elif kind in ("slack", "browser"):
            self.workflow.setCurrentIndex(self.workflow.findData(kind))
            self.show_panel()
            self.manual_button.setChecked(True)
            self.input.setFocus()
            self.answer("Share the relevant excerpt, then tell me what you need.", True)

    def unity_preview(self, *, spoken=False):
        try:
            with self.session.lock:
                target = self.session.targets.get("unity")
                if not target:
                    if spoken:
                        self.waiting_for_share = ("unity", "Finish this Unity prefab connection", self.session.clock() + 90)
                    raise ValueError("Open the prefab and share the source field and destination from Unity.")
                self.session.propose(target)
        except ValueError as exc:
            self.answer(str(exc), spoken)
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
        self.voice_approval = None
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
            status, focus, apps = session.status, session.focus, ", ".join(session.windows)
            suggestion = session.suggestion if not self.quiet.isChecked() else ""
            targets = dict(session.targets)
            hint_time = session.last_hint
        self.state.setText("Listening" if active else "Paused")
        self.start_button.setEnabled(not active)
        self.pause_button.setEnabled(active)
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
        self.status.setVisible(status not in ("Listening", "Paused"))
        if focus != self.last_focus:
            self.last_focus = focus
            if focus:
                self.log("Focus", focus)
        now_status = status.split("\nShared:", 1)[0]
        if now_status != self.last_status:
            self.last_status = now_status
            self.log("Session", now_status)
            if active and (now_status.startswith(("Applied ", "Skipped.", "The editor reported",
                                                  "Draft copied.", "Link handed", "Could not open",
                                                  "No confirmation")) or now_status == "Declined."):
                self.say(now_status, record=False)
        self.offer.setVisible(bool(suggestion))
        if suggestion:
            title, message = {
                "unity": ("Review Unity handoff", "It sounds like you are wiring dialogue in Unity. I can help finish a connection."),
                "slack": ("Draft with Slack context", "It sounds like you are writing a Slack message. Share the excerpt and I can help draft it."),
                "browser": ("Summarize a web page", "It sounds like you are summarizing a web page. Share its text and I can help."),
            }[suggestion]
            self.offer.setText(title)
            if self.hint_seen != hint_time:
                self.hint_seen = hint_time
                if self.tray.isVisible() and not self.isVisible():
                    self.tray.showMessage(title, message)
                self.log("Suggestion", message)
                if not self.speaking and not self.model_job and not proposal:
                    self.say(message + " Say Assistant, review suggestion.", record=False)
        proposal_id = proposal.id if proposal else None
        if self.mode and (self.mode[2] < session.clock() or (self.mode[0] == "reply" and self.mode[1] != proposal_id)):
            self.refresh_audio()
        if proposal_id != self.previewed:
            self.voice_approval = None
            self.previewed = proposal_id
            self.review.setVisible(bool(proposal))
            self.before.setPlainText(proposal.before if proposal else "")
            self.after.setPlainText(proposal.after if proposal else "")
            label = proposal.target.label if proposal else ""
            if proposal and proposal.target.kind == "rider":
                span = proposal.target.data
                label += f' · Selected range {span["start"]}–{span["end"]}'
            self.target_label.setText(label)
            if proposal:
                QTimer.singleShot(0, lambda: self.scroller.ensureWidgetVisible(self.review, 0, 0))
                self.log("Approval", f"{label} · {proposal.after}")
                action = {"rider": "The Rider replacement", "unity": "The Unity connection",
                          "desktop": proposal.target.label}[proposal.target.kind]
                hint = (" Say Assistant approve or Assistant decline." if self.mic.isChecked()
                        and self.mic_path.text().strip() else "")
                self.say(action + " is ready to review." + hint)
                if not self.speaking:
                    self.refresh_audio()
                    self.arm_spoken_approval()
        self.voice_ack.setEnabled(self.mic.isChecked())
        if self.waiting_for_share:
            kind, request, expires = self.waiting_for_share
            if expires <= session.clock():
                self.waiting_for_share = None
            elif not self.speaking and not proposal and kind in targets:
                self.waiting_for_share = None
                epoch = session.epoch
                QTimer.singleShot(0, lambda: self.ask(voice_request=request)
                                  if session.active and session.epoch == epoch else None)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--vosk-model")
    parser.add_argument("--ollama-model")
    parser.add_argument("--openai-model", help="Select OpenAI API drafting, using OPENAI_API_KEY.")
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
            window.speaker.stop()
        bridge.close()


if __name__ == "__main__":
    sys.exit(main())
