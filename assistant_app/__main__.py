"""Tray app for session context, task requests, and edit previews."""
import argparse
from datetime import datetime
from html import escape
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
from threading import Event, Thread
from urllib.parse import urlsplit


# Use the checkout's dependencies even when launched with an older system-Python command.
if __name__ == "__main__" and sys.prefix == sys.base_prefix:
    checkout_python = Path(__file__).resolve().parents[1] / ".venv/bin/python"
    if checkout_python.is_file() and os.access(checkout_python, os.X_OK):
        os.execv(str(checkout_python), [str(checkout_python), "-m", "assistant_app", *sys.argv[1:]])


from gi.repository import GLib
from PyQt5.QtCore import QSettings, QTimer, Qt, QUrl, pyqtSignal
from PyQt5.QtGui import QDesktopServices
from PyQt5.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QMainWindow, QMenu, QMessageBox, QPlainTextEdit, QPushButton, QSpinBox, QStyle, QSystemTrayIcon, QToolButton,
    QVBoxLayout, QWidget,
)

from .chats import ChatStore
from .desktop import Desktop
from .drafting import complete
from .ipc import LocalBridge
from .journal import ChatJournal
from .live import VoiceMeter
from .session import Session
from .speech import Microphone
from .theme import STYLE
from .tasks import next_task
from . import credentials, updates
from .voice import Speaker
from .window_view import CaptureCanceled, MONITOR, WINDOW, capture_frame, select_source


class Window(QMainWindow):
    drafted = pyqtSignal(object, object, str)
    viewed = pyqtSignal(object, object, str)
    monitor_selected = pyqtSignal(object, object)
    update_checked = pyqtSignal(object, str, bool)
    update_installed = pyqtSignal(str)
    key_finished = pyqtSignal(str, str, bool)

    def __init__(self, session, args):
        super().__init__()
        self.session = session
        self.api_key = os.environ.get("OPENAI_API_KEY", "").strip()
        self.key_pending = False
        self.key_finished.connect(self.key_result)
        data_home = Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local/share")))
        self.data_dir = data_home / "gpt-linux-assistant"
        self.profile_settings = QSettings("PixelDrennen", "GPT Linux Assistant")
        self.cli_provider = bool(args.openai_model or args.ollama_model)
        self.profile = self.profile_settings.value("profile", "work")
        if self.profile not in ("work", "play"):
            self.profile = "work"
        self.history = ChatStore(self.data_dir / self.profile)
        self.update_busy = False
        self.update_offered = None
        self.update_checked.connect(self.offer_update)
        self.update_installed.connect(self.finish_update)
        self.history_error = False
        self.history_timer = QTimer(self)
        self.history_timer.setSingleShot(True)
        self.history_timer.setInterval(500)
        self.history_timer.timeout.connect(self.save_chat)
        self.audio = Microphone()
        self.audio.ready.connect(self.audio_ready)
        self.audio.heard.connect(self.heard)
        self.audio.failed.connect(self.audio_failed)
        self.audio.speech_started.connect(self.audio_speech_started)
        self.audio.decoding.connect(self.audio_decoding)
        self.audio.transcription_failed.connect(self.audio_transcription_failed)
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
        self.drafted.connect(self.draft_finished)
        self.viewed.connect(self.view_finished)
        self.view_job = None
        self.watch_request = None
        self.watch_timer = QTimer(self)
        self.watch_timer.setInterval(5000)
        self.watch_timer.timeout.connect(self.check_watch)
        self.shared_monitor = None
        self.monitor_selected.connect(self.on_monitor_selected)
        self.mode = None
        self.model_job = None
        self.previewed = None
        self.hint_seen = -float("inf")
        self.last_tray_state = None
        self.audio_status = ""
        self.user_speaking = False
        self.partial_text = ""
        self.setWindowTitle("GPT Linux Assistant")
        self.setStyleSheet(STYLE)
        self.resize(1100, 760)
        surface = QWidget()
        shell = QHBoxLayout(surface)
        shell.setContentsMargins(0, 0, 0, 0)
        shell.setSpacing(0)
        self.setCentralWidget(surface)
        sidebar = QWidget()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(200)
        navigation = QVBoxLayout(sidebar)
        navigation.setContentsMargins(9, 11, 9, 10)
        navigation.setSpacing(6)
        sidebar_top = QHBoxLayout()
        self.profile_picker = QComboBox()
        self.profile_picker.setObjectName("profile")
        self.profile_picker.addItem("Work", "work")
        self.profile_picker.addItem("Play", "play")
        self.profile_picker.setAccessibleName("Work or Play profile")
        self.profile_picker.setCurrentIndex(self.profile_picker.findData(self.profile))
        sidebar_top.addWidget(self.profile_picker, 1)
        self.circle(sidebar_top, "+", "New chat", self.new_chat)
        navigation.addLayout(sidebar_top)
        self.chat_list = QListWidget()
        self.chat_list.setObjectName("chats")
        self.chat_list.setAccessibleName("Chats")
        self.chat_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.chat_list.setTextElideMode(Qt.ElideRight)
        self.chat_list.currentItemChanged.connect(self.select_chat)
        navigation.addWidget(self.chat_list, 1)
        self.history_note = self.label("")
        self.history_note.setObjectName("muted")
        navigation.addWidget(self.history_note)
        self.history_note.hide()
        self.voice_row = QWidget()
        signals = QHBoxLayout(self.voice_row)
        signals.setContentsMargins(4, 0, 4, 0)
        signals.setSpacing(8)
        self.mic_meter = VoiceMeter("Your microphone", "#d6d6d6", compact=True)
        self.ai_meter = VoiceMeter("Assistant voice", "#a3a3a3", compact=True)
        for meter in (self.mic_meter, self.ai_meter):
            meter.setToolTip(meter.accessibleName())
            signals.addWidget(meter)
        navigation.addWidget(self.voice_row)
        controls = QHBoxLayout()
        controls.setSpacing(5)
        self.listen_button = self.circle(controls, "▶", "Start listening", self.toggle_listening)
        self.state = self.label("")
        self.state.setObjectName("muted")
        self.state.setWordWrap(False)
        controls.addWidget(self.state, 1)
        menu_button = self.circle(controls, "⋯", "Assistant menu")
        navigation.addLayout(controls)
        shell.addWidget(sidebar)
        self.controls = QMenu(menu_button)
        menu_button.setMenu(self.controls)
        menu_button.setPopupMode(QToolButton.InstantPopup)
        self.controls.addAction("Ask by voice", self.ask_voice)
        share = self.controls.addMenu("Screen sharing")
        self.view_button = share.addAction("View a window", self.look_at_window)
        self.monitor_button = share.addAction("View monitors", lambda: self.look_at_window(source=MONITOR))
        self.stop_monitor_button = share.addAction("Stop monitor sharing", self.stop_monitor)
        self.stop_monitor_button.setVisible(False)
        self.stop_watch_button = share.addAction("Stop screen watch", self.stop_watch)
        self.stop_watch_button.setVisible(False)
        self.offer = self.controls.addAction("Review suggestion", self.follow_suggestion)
        self.offer.setVisible(False)
        self.controls.addSeparator()
        self.controls.addAction("Manual request…", lambda: self.manual.show())
        self.controls.addAction("Settings…", lambda: self.settings.show())
        self.controls.addAction("Check for updates", lambda: self.check_updates(manual=True))

        root = QWidget()
        root.setObjectName("workspace")
        shell.addWidget(root, 1)
        stack = QVBoxLayout(root)
        stack.setContentsMargins(24, 17, 24, 12)
        stack.setSpacing(10)
        self.chat_title = title = self.label("New chat")
        title_font = title.font()
        title_font.setPointSize(title_font.pointSize() + 3)
        title_font.setBold(True)
        title.setFont(title_font)
        stack.addWidget(title)

        self.journal = ChatJournal()
        stack.addWidget(self.journal, 1)
        self.settings = self.popup("Settings", 580, 520)
        form = QFormLayout(self.settings)
        self.mic = QCheckBox("Use microphone")
        default_path = Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local/share"))) / "gpt-linux-assistant/vosk-model"
        mic_path = args.vosk_model or (str(default_path) if default_path.is_dir() else "")
        self.mic_path = QLineEdit(mic_path)
        self.mic.setChecked(bool(mic_path))
        self.mic_path.setPlaceholderText("Path to the extracted Vosk model")
        self.mic.toggled.connect(self.refresh_audio)
        self.mic_path.editingFinished.connect(self.refresh_audio)
        form.addRow(self.mic, self.mic_path)
        self.cloud_transcription = QCheckBox("OpenAI transcription · sends completed utterances")
        form.addRow(self.cloud_transcription)
        self.thinking_pause = QSpinBox()
        self.thinking_pause.setRange(2, 8)
        self.thinking_pause.setValue(4)
        self.thinking_pause.setSuffix(" seconds")
        form.addRow("Wait after speech", self.thinking_pause)
        self.vocabulary = QLineEdit()
        self.vocabulary.setPlaceholderText("Names and terms, e.g. TradeSkillMaster, TSM, Hanami")
        self.vocabulary.setMaxLength(320)
        form.addRow("Recognition vocabulary", self.vocabulary)
        self.spoken = QCheckBox("Speak replies")
        self.spoken.setChecked(True)
        self.spoken.toggled.connect(self.speech_setting)
        self.voice_choice = QComboBox()
        for label, value in (("Follow reply provider", "auto"), ("OpenAI · Marin", "marin"),
                             ("OpenAI · Cedar", "cedar"), ("Local eSpeak NG", "local")):
            self.voice_choice.addItem(label, value)
        form.addRow(self.spoken, self.voice_choice)
        self.conversation = QCheckBox("Conversation mode · respond when I speak")
        self.conversation.setChecked(True)
        self.conversation.toggled.connect(self.update_cloud_notice)
        form.addRow(self.conversation)
        self.provider = QComboBox()
        self.provider.addItem("Local Ollama", "ollama")
        self.provider.addItem("OpenAI API", "openai")
        use_openai = args.openai_model or (self.api_key and not args.ollama_model)
        self.provider.setCurrentIndex(1 if use_openai else 0)
        self.models = {"ollama": args.ollama_model or "gemma4", "openai": args.openai_model or "gpt-4.1-mini"}
        self.model = QLineEdit(self.models[self.provider.currentData()])
        self.model.setMaxLength(100)
        self.current_provider = self.provider.currentData()
        self.provider.currentIndexChanged.connect(self.switch_provider)
        form.addRow(self.provider, self.model)
        key_row = QHBoxLayout()
        self.key_field = QLineEdit()
        self.key_field.setEchoMode(QLineEdit.Password)
        self.key_field.setPlaceholderText("Paste an OpenAI API key")
        self.key_field.returnPressed.connect(self.store_api_key)
        key_row.addWidget(self.key_field, 1)
        self.key_save = self.button(key_row, "Save to wallet", self.store_api_key)
        self.key_status = self.label("")
        form.addRow(key_row)
        form.addRow(self.key_status)
        self.include_narration = QCheckBox("Include recent narration and app focus in model requests")
        self.auto_view = QCheckBox("Let the assistant request monitor context when needed")
        self.auto_view.setChecked(True)
        form.addRow(self.auto_view)
        self.include_narration.setChecked(True)
        form.addRow(self.include_narration)
        self.cloud_notice = self.label("")
        form.addRow(self.cloud_notice)
        self.voice_choice.currentIndexChanged.connect(self.update_cloud_notice)
        self.cloud_transcription.toggled.connect(self.transcription_settings_changed)
        self.thinking_pause.valueChanged.connect(self.refresh_audio)
        self.vocabulary.editingFinished.connect(self.refresh_audio)
        self.update_cloud_notice()
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
        self.window_access.setChecked(True)
        self.rider.setChecked(True)
        self.unity.setChecked(True)

        self.manual = self.popup("Manual request", 570, 470)
        form = QFormLayout(self.manual)
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

        self.review = self.popup("Approve this action", 660, 280)
        self.review.rejected.connect(self.dismiss_review)
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
        menu.addAction("Check for updates", lambda: self.check_updates(manual=True))
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
        self.profile_defaults = {
            "provider": self.provider.currentData(), "ollama": self.models["ollama"], "openai": self.models["openai"],
            "microphonePath": self.mic_path.text(), "microphone": self.mic.isChecked(),
        }
        self.profile_boxes = {
            "microphone": self.mic, "speak": self.spoken, "conversation": self.conversation,
            "windows": self.window_access, "rider": self.rider, "unity": self.unity,
            "narration": self.include_narration, "autoView": self.auto_view, "quiet": self.quiet,
        }
        self.apply_profile()
        if args.vosk_model:
            self.mic_path.setText(args.vosk_model)
            self.mic.setChecked(True)
        if args.openai_model or args.ollama_model:
            self.provider.setCurrentIndex(1 if args.openai_model else 0)
            self.model.setText(args.openai_model or args.ollama_model)
        self.profile_picker.currentIndexChanged.connect(self.change_profile)
        self.load_chat()
        self.render()
        self.update_timer = QTimer(self)
        self.update_timer.setInterval(60 * 60 * 1000)
        self.update_timer.timeout.connect(self.check_updates)
        if getattr(args, "check_updates", False):
            self.update_timer.start()
            QTimer.singleShot(1800, self.check_updates)

    def popup(self, title, width, height):
        dialog = QDialog(self, Qt.Tool)
        dialog.setWindowTitle(title)
        dialog.resize(width, height)
        return dialog

    @staticmethod
    def circle(layout, symbol, title, callback=None):
        button = QToolButton()
        button.setObjectName("circle")
        button.setFixedSize(30, 30)
        button.setText(symbol)
        button.setToolTip(title)
        button.setAccessibleName(title)
        if callback:
            button.clicked.connect(callback)
        layout.addWidget(button)
        return button

    def toggle_listening(self):
        if self.session.active:
            self.pause()
        else:
            self.start()
        self.render()

    def dismiss_review(self):
        if self.previewed and self.session.proposal:
            self.respond(False, self.previewed)

    def retrieve_api_key(self):
        if self.key_pending:
            return
        env_key = self.api_key
        self.key_pending = True
        self.key_save.setEnabled(False)
        self.key_status.setText("Checking desktop wallet…")

        def lookup():
            try:
                saved = credentials.read_key()
                if not saved and env_key:
                    credentials.save_key(env_key)
                    saved = env_key
                self.key_finished.emit(saved, "", False)
            except (RuntimeError, ValueError) as exc:
                self.key_finished.emit("", str(exc), False)
        Thread(target=lookup, daemon=True).start()

    def store_api_key(self):
        key = self.key_field.text().strip()
        if not key or self.key_pending:
            return
        self.key_pending = True
        self.key_save.setEnabled(False)
        self.key_status.setText("Saving to desktop wallet…")

        def store():
            try:
                credentials.save_key(key)
                self.key_finished.emit(key, "", True)
            except (RuntimeError, ValueError) as exc:
                self.key_finished.emit("", str(exc), True)
        Thread(target=store, daemon=True).start()

    def key_result(self, key, error, explicit):
        self.key_pending = False
        self.key_save.setEnabled(True)
        if key:
            self.api_key = key
            self.key_field.clear()
            self.key_status.setText("OpenAI API key saved in the desktop wallet.")
            no_provider = not self.profile_settings.contains(self.profile + "/provider")
            if explicit or (no_provider and not self.cli_provider):
                self.provider.setCurrentIndex(self.provider.findData("openai"))
                self.save_profile()
            if self.session.active and self.cloud_transcription.isChecked():
                self.refresh_audio()
        else:
            self.key_status.setText(error or "No OpenAI API key saved.")

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
        self.stop_monitor()
        self.audio.stop()
        self.speaker.stop()
        self.speaking = False
        self.voice_approval = None
        self.clarification = None
        self.waiting_for_share = None
        self.last_reply = ""
        self.mode = None
        self.model_job = None
        self.audio_status = ""
        self.user_speaking = False
        self.last_status = ""
        self.last_focus = ""
        self.mic_meter.clear()
        self.ai_meter.clear()
        self.partial_text = ""
        if self.session.active:
            self.log("Session", "Listening paused.")
        self.save_chat()
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
        self.stop_monitor()
        self.models[self.current_provider] = self.model.text()
        self.current_provider = self.provider.currentData()
        self.model.setText(self.models[self.current_provider])
        self.update_cloud_notice()
        self.model_job = None
        self.clarification = None
        self.waiting_for_share = None

    def cloud_voice(self):
        voice = self.voice_choice.currentData()
        if voice == "auto":
            return "marin" if self.current_provider == "openai" else None
        return None if voice == "local" else voice

    def update_cloud_notice(self):
        notes = []
        if self.current_provider == "openai":
            notes.append("OpenAI receives spoken text in conversation mode, plus any shared draft or excerpt used in a request."
                         if self.conversation.isChecked() else
                         "OpenAI receives request text and any shared draft or excerpt used in the request.")
        if self.cloud_voice():
            notes.append("The OpenAI voice sends the assistant’s spoken text for synthesis.")
        if self.cloud_transcription.isChecked():
            notes.append("Completed utterance audio and vocabulary are sent to OpenAI for transcription.")
        elif notes:
            notes.append("Microphone audio stays local.")
        self.cloud_notice.setText(" ".join(notes))
        self.cloud_notice.setVisible(bool(notes))
        self.view_button.setToolTip("Share one frame with OpenAI." if self.current_provider == "openai"
                                    else "Share one frame with the local model.")

    def save_profile(self):
        prefix = self.profile + "/"
        self.models[self.current_provider] = self.model.text()
        values = {**self.models, "provider": self.current_provider,
                  "microphonePath": self.mic_path.text(), "excluded": self.exclude.text(),
                  "voice": self.voice_choice.currentData()}
        values.update(transcribeOnline=self.cloud_transcription.isChecked(),
                      thinkingPause=self.thinking_pause.value(), vocabulary=self.vocabulary.text())
        values.update({key: box.isChecked() for key, box in self.profile_boxes.items()})
        for key, value in values.items():
            self.profile_settings.setValue(prefix + key, value)
        self.profile_settings.sync()

    def apply_profile(self):
        prefix = self.profile + "/"
        for key, box in self.profile_boxes.items():
            default = self.profile_defaults.get(key, key != "quiet")
            box.setChecked(self.profile_settings.value(prefix + key, default, type=bool))
        self.mic_path.setText(self.profile_settings.value(prefix + "microphonePath",
                                                          self.profile_defaults["microphonePath"]))
        self.exclude.setText(self.profile_settings.value(prefix + "excluded", ""))
        self.cloud_transcription.setChecked(self.profile_settings.value(prefix + "transcribeOnline", False, type=bool))
        self.thinking_pause.setValue(self.profile_settings.value(prefix + "thinkingPause", 4, type=int))
        self.vocabulary.setText(self.profile_settings.value(prefix + "vocabulary", ""))
        provider = self.profile_settings.value(prefix + "provider", self.profile_defaults["provider"])
        index = self.provider.findData(provider)
        self.provider.setCurrentIndex(max(0, index))
        for key in ("ollama", "openai"):
            self.models[key] = self.profile_settings.value(prefix + key, self.profile_defaults[key])
        self.model.setText(self.models[self.current_provider])
        voice = self.voice_choice.findData(self.profile_settings.value(prefix + "voice", "auto"))
        self.voice_choice.setCurrentIndex(max(0, voice))

    def change_profile(self):
        other = self.profile_picker.currentData()
        if other == self.profile:
            return
        try:
            history = ChatStore(self.data_dir / other)
        except (OSError, sqlite3.Error):
            self.profile_picker.blockSignals(True)
            self.profile_picker.setCurrentIndex(self.profile_picker.findData(self.profile))
            self.profile_picker.blockSignals(False)
            self.history_note.setText("Could not open the other profile")
            self.history_note.show()
            return
        was_active = self.session.active
        self.pause()
        self.save_profile()
        self.history.close()
        self.profile = other
        self.history = history
        self.profile_settings.setValue("profile", other)
        self.apply_profile()
        self.load_chat()
        if was_active:
            self.start()

    def check_updates(self, manual=False):
        if self.update_busy:
            return
        self.update_busy = True

        def check():
            try:
                self.update_checked.emit(updates.check(), "", manual)
            except (OSError, subprocess.SubprocessError, IndexError):
                self.update_checked.emit(None, "Could not check for updates.", manual)

        Thread(target=check, daemon=True).start()

    def offer_update(self, revision, error, manual):
        self.update_busy = False
        if not revision:
            if manual:
                QMessageBox.information(self, "Updates", error or "No newer version is available for this checkout.")
            return
        if revision == self.update_offered and not manual:
            return
        self.update_offered = revision
        prompt = QMessageBox(QMessageBox.Information, "Update available",
                             "A new version of GPT Linux Assistant is available.",
                             QMessageBox.NoButton, self)
        install = prompt.addButton("Update and restart", QMessageBox.AcceptRole)
        prompt.addButton("Later", QMessageBox.RejectRole)
        prompt.exec_()
        if prompt.clickedButton() is not install:
            return
        self.pause()
        self.update_busy = True

        def apply():
            try:
                updates.install(revision)
                self.update_installed.emit("")
            except (OSError, ValueError, subprocess.SubprocessError) as exc:
                self.update_installed.emit(str(exc))

        Thread(target=apply, daemon=True).start()

    def finish_update(self, error):
        self.update_busy = False
        if error:
            QMessageBox.warning(self, "Update could not be installed", error)
        else:
            QApplication.instance().exit(updates.RESTART)

    def save_chat(self):
        self.history_timer.stop()
        try:
            self.history.save()
        except (OSError, sqlite3.Error):
            self.history_error = True
            self.history_note.setText("Could not save chat history")
            self.history_note.show()
        else:
            if self.history_error:
                self.history_note.hide()
            self.history_error = False

    def load_chat(self):
        chat = self.history.chat
        self.chat_title.setText(chat.title)
        self.journal.set_entries("".join(self.entry_html(*entry) for entry in chat.entries))
        self.chat_list.blockSignals(True)
        self.chat_list.clear()
        for chat_id, title, updated in self.history.index():
            item = QListWidgetItem(title)
            item.setData(Qt.UserRole, chat_id)
            item.setToolTip(f"{title} · {updated[:10]}")
            self.chat_list.addItem(item)
            if chat_id == chat.id:
                self.chat_list.setCurrentItem(item)
        self.chat_list.blockSignals(False)
        self.last_reply = chat.turns[-1][2] if len(chat.turns) > chat.task_start else ""

    def change_chat(self, chat_id=None):
        if chat_id == self.history.chat.id:
            return
        was_active = self.session.active
        self.pause()
        try:
            self.history.select(chat_id)
        except (OSError, ValueError, sqlite3.Error):
            self.history_note.setText("Could not open this chat")
            self.history_note.show()
        self.load_chat()
        if was_active:
            self.start()

    def new_chat(self):
        self.change_chat()

    def select_chat(self, item, _previous):
        if item:
            self.change_chat(item.data(Qt.UserRole))

    @staticmethod
    def entry_html(stamp, source, text):
        conversation = source in ("You", "Assistant")
        color = "#ececec" if conversation else "#ababab"
        label_color = "#eeeeee" if conversation else "#b0b0b0"
        return (f'<p style="margin-bottom:12px"><b style="color:{label_color}">{escape(source)}</b> &nbsp;'
                f'<span style="color:#a2a2a2">{escape(stamp)}</span><br>'
                f'<span style="color:{color}">{escape(text).replace(chr(10), "<br>")}</span></p>')

    def remember_turn(self, kind, request, answer):
        self.history.chat.turns.append([kind, request[:3000], answer[:24000]])
        self.history_timer.start()

    def log(self, source, text):
        if self.session.active and text:
            chat = self.history.chat
            if source == "You" and chat.title == "New chat":
                chat.title = " ".join(text.split())[:58]
                self.chat_title.setText(chat.title)
                item = self.chat_list.currentItem()
                if item:
                    item.setText(chat.title)
            entry = [datetime.now().strftime("%H:%M:%S"), source, text[:24000]]
            chat.entries.append(entry)
            self.journal.append_entry(self.entry_html(*entry))
            self.history_timer.start()

    def mic_sample(self, generation, amount):
        if generation == self.audio.generation and self.session.active:
            self.mic_meter.sample(amount)

    def mic_partial(self, generation, text):
        if generation == self.audio.generation and self.session.active:
            self.partial_text = text[:300]

    def speaker_sample(self, generation, amount):
        if generation == self.speaker.generation and self.speaking:
            self.audio_status = "Assistant speaking · microphone paused"
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
        voice = self.cloud_voice()
        api_key = self.api_key if voice else None
        if voice and not api_key:
            self.log("Audio", "Save an OpenAI API key in Settings to use this voice.")
            return
        self.audio.stop()
        self.mode = None
        self.voice_approval = None
        self.mic_meter.clear()
        self.partial_text = ""
        self.speaking = True
        self.audio_status = "Preparing speech · microphone paused"
        self.speaker.start(text[:420], api_key=api_key, voice=voice or "marin")

    def transcription_settings_changed(self, enabled):
        if enabled:
            self.mic.setChecked(True)
        self.update_cloud_notice()
        self.refresh_audio()

    def start_microphone(self):
        self.audio.start(self.mic_path.text().strip(), self.thinking_pause.value(),
                         self.api_key if self.cloud_transcription.isChecked() else None,
                         self.vocabulary.text().strip())

    def refresh_audio(self):
        if self.speaking:
            return
        self.audio.stop()
        self.voice_approval = None
        self.mode = None
        path = self.mic_path.text().strip()
        self.user_speaking = False
        if not self.session.active or not self.mic.isChecked():
            self.audio_status = ""
        elif self.cloud_transcription.isChecked() and not self.api_key:
            self.audio_status = "Save your OpenAI API key to use OpenAI transcription."
        elif not path and not self.cloud_transcription.isChecked():
            self.audio_status = "Set the Vosk model path to use the microphone."
        else:
            self.audio_status = "Starting microphone"
            self.start_microphone()

    def audio_ready(self, generation):
        if generation == self.audio.generation:
            self.user_speaking = False
            if self.mode is None:
                self.audio_status = "Microphone listening"

    def audio_speech_started(self, generation):
        if generation == self.audio.generation:
            self.user_speaking = True
            if self.view_job and self.view_job[5]:
                self.cancel_view()

    def audio_decoding(self, generation):
        if generation == self.audio.generation:
            self.audio_status = "Transcribing speech"

    def audio_transcription_failed(self, generation, message):
        if generation == self.audio.generation and self.session.active:
            self.user_speaking = False
            self.audio_status = "Microphone listening"
            self.log("Audio", message)

    def audio_failed(self, generation, message):
        if generation == self.audio.generation:
            self.mode = None
            self.user_speaking = False
            self.audio_status = "Microphone unavailable. " + message
            self.log("Audio", self.audio_status)

    def arm(self, action, proposal_id=""):
        if (not self.session.active or not self.mic.isChecked() or
                (not self.api_key if self.cloud_transcription.isChecked() else not self.mic_path.text().strip())):
            self.message("Start listening and enable the microphone first.")
            return
        if self.speaking:
            self.speaker.stop()
            self.speaking = False
            self.ai_meter.clear()
        self.start_microphone()
        self.voice_approval = None
        self.mode = (action, proposal_id, self.session.clock() + (75 if action == "ask" else 20))
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
        self.user_speaking = False
        self.audio_status = "Microphone listening"
        words = " ".join(re.findall(r"[a-z0-9]+", text.casefold()))
        if not words:
            return
        if words in ("assistant approve", "assistant decline", "approve it", "decline it",
                     "yes apply it", "no cancel it"):
            self.log("You", text)
            if (confidence >= 0.85 and self.voice_approval == (generation, self.previewed)
                    and self.review.isVisible() and self.session.proposal):
                self.respond(words in ("assistant approve", "approve it", "yes apply it"), self.previewed)
            else:
                self.log("Approval", "No matching spoken approval. Use the visible preview.")
            return
        if self.mode:
            action, proposal_id, expires = self.mode
            self.mode = None
            if expires >= self.session.clock():
                if action == "reply":
                    self.log("You", text)
                    if words in ("yes", "no") and confidence >= 0.85 and self.review.isVisible():
                        self.respond(words == "yes", proposal_id)
                    else:
                        self.message("Voice reply was unclear. Use the approval buttons.")
                    return
                if words != "assistant":
                    request = re.sub(r"^assistant[\W_]+", "", text, flags=re.IGNORECASE).strip()
                    self.request_from_speech(request)
                    return
        if words == "assistant":
            self.mode = ("ask", "", self.session.clock() + 8)
            self.audio_status = "Listening for your request"
        elif words.startswith("assistant "):
            request = re.sub(r"^assistant[\W_]+", "", text, flags=re.IGNORECASE).strip()
            self.request_from_speech(request)
        elif self.conversation.isChecked() or (self.clarification and self.clarification[0] > self.session.clock()):
            self.request_from_speech(text)
        else:
            self.log("You", text)
            self.session.narrate(text)

    def request_from_speech(self, request):
        self.log("You", request)
        self.ask(voice_request=request)

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
        if voice and words in ("stop watching", "stop the watch", "stop checking"):
            self.stop_watch()
            self.say("I stopped checking the screen.")
            return
        if voice and words in ("stop sharing", "stop screen sharing", "stop monitor sharing"):
            self.stop_monitor()
            self.say("Screen sharing stopped.")
            return
        if voice and words in ("repeat that", "say that again", "read the last reply"):
            self.say(self.last_reply or "There is no reply to repeat yet.")
            return
        if not self.session.active:
            self.message("Start listening before making a request.")
            return
        follow_up = next_task(request) if voice else None
        if follow_up is not None:
            self.discard_task()
            if follow_up:
                self.ask(voice_request=follow_up)
            else:
                self.say("Okay. What would you like to do next?")
            return
        if self.view_job and self.view_job[5]:
            self.cancel_view()
        if voice and self.watch_request and words in ("it is open", "it s open", "it s open now", "it is open now",
                                                      "check again", "take another look", "look again"):
            self.check_watch()
            return
        with self.session.lock:
            self.session.expire()
            blocked = bool(self.session.proposal or self.session.command)
            narration = [value for _, source, value in self.session.events if source == "speech"]
            focus = self.session.focus
            epoch = self.session.epoch
        if blocked:
            if voice:
                self.log("Approval", "Review the pending action or say decline it.")
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
        visual = re.match(r"^(?:please |can you |could you )?look at (?:this |the |my |a )?(window|screen|game)\b", request, re.IGNORECASE)
        if visual:
            self.look_at_window(request, MONITOR if visual[1].casefold() == "screen" else WINDOW)
            return
        if self.model_job or self.view_job:
            self.answer("A reply is already being prepared.", voice)
            return

        self.waiting_for_share = None
        kind = "general" if voice else self.workflow.currentData()
        has_app = True
        if re.search(r"\brider\b", words) and (not voice or
                re.search(r"\b(prompt|draft|selection|finish|rewrite|replace)\b", words)):
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
            api_key = self.api_key
            if not api_key:
                self.answer("OpenAI is selected. Save your API key in Settings.", voice)
                return
        original = target.data["text"] if target else self.input.toPlainText()
        if len(original) > 16000:
            self.answer("Share a shorter excerpt, up to 16,000 characters.", voice)
            return
        context = {"profile": self.profile}
        if self.include_narration.isChecked():
            context.update(narration=narration[-5:], focused_app=focus)
        chat = self.history.chat
        recent = chat.turns[max(chat.task_start, len(chat.turns) - 16):]
        history = [turn[1:] for turn in recent if turn[0] == kind][-4:]
        if history:
            context["previous_turns"] = [[request[:1200], reply[:1600]] for request, reply in history]
        job = (epoch, kind, target, self.output.toPlainText(), self.request.text(),
               self.input.toPlainText(), voice, request, model)
        self.model_job = job
        self.message("Preparing a reply.")

        may_view = self.auto_view.isChecked() and kind != "rider"

        def generate():
            try:
                result = complete(model, original, request, context, kind, api_key=api_key, may_view=may_view)
                self.drafted.emit(job, result, "")
            except (OSError, ValueError) as exc:
                self.drafted.emit(job, None, str(exc))

        Thread(target=generate, daemon=True).start()

    def cancel_view(self):
        if self.view_job is not None:
            self.view_job[0].set()
            self.view_job = None

    def discard_task(self):
        self.stop_watch()
        self.cancel_view()
        self.model_job = None
        self.clarification = None
        self.waiting_for_share = None
        self.last_reply = ""
        self.output.clear()
        self.input.clear()
        self.request.clear()
        self.url.clear()
        chat = self.history.chat
        chat.task_start = len(chat.turns)
        with self.session.lock:
            self.session.events.clear()
            self.session.suggestion = ""
            self.session.targets.clear()
            self.session.proposal = None
            if self.session.command and not self.session.command["claimed"]:
                self.session.command = None
            self.session.status = "Listening"
        self.log("Task", "Ready for a new task.")
        self.render()

    def stop_watch(self):
        self.watch_request = None
        self.watch_timer.stop()
        self.stop_watch_button.setVisible(False)
        if self.view_job and self.view_job[5]:
            self.cancel_view()

    def check_watch(self):
        if not self.watch_request or not self.session.active or not self.shared_monitor:
            self.stop_watch()
        elif not (self.speaking or self.model_job or self.view_job or self.mode
                  or self.session.proposal or self.session.command or self.user_speaking
                  or self.audio_status == "Transcribing speech"):
            self.look_at_window(self.watch_request, MONITOR, rechecking=True)

    def stop_monitor(self):
        self.stop_watch()
        self.cancel_view()
        if self.shared_monitor is not None:
            self.shared_monitor.close()
            self.shared_monitor = None
            self.log("Screen", "Monitor sharing stopped.")
        self.stop_monitor_button.setVisible(False)

    def on_monitor_selected(self, job, monitor):
        if self.view_job is job and self.session.active and not job[0].is_set():
            self.shared_monitor = monitor
            self.stop_monitor_button.setVisible(True)
            self.log("Screen", "Selected monitors are available for on-demand frames during this session.")
        else:
            monitor.close()

    def look_at_window(self, request=None, source=WINDOW, *, rechecking=False):
        if not rechecking:
            self.stop_watch()
        if not self.session.active:
            self.message("Start listening before sharing a window.")
            return
        with self.session.lock:
            self.session.expire()
            blocked = self.session.proposal or self.session.command
        if blocked or self.view_job or self.model_job:
            self.message("Finish the current request before sharing a window.")
            return
        model = self.model.text().strip()
        if not model:
            self.answer("Choose a vision-capable model under Setup first.", True)
            return
        cloud = self.current_provider == "openai"
        api_key = self.api_key if cloud else None
        if cloud and not api_key:
            self.answer("Save your OpenAI API key in Settings before sharing a window.", True)
            return
        if not isinstance(request, str):
            request = self.request.text().strip() or "Briefly describe what is visible and how you could help."
        target = "screen" if source == MONITOR else "window"
        destination = "OpenAI" if cloud else "the local model"
        if not rechecking:
            self.waiting_for_share = None
            self.clarification = None
        shared = self.shared_monitor if source == MONITOR else None
        if shared is not None:
            if not rechecking:
                self.message(f"Sharing fresh frames from the selected monitors with {destination}.")
        elif source == MONITOR:
            self.message(f"Choose monitors for this session. Requested frames go to {destination}.")
        else:
            self.message(f"Choose a {target} to share one frame with {destination}.")
        profile = self.profile
        job = (Event(), self.session.epoch, model, request, source, rechecking)
        self.view_job = job
        cancel = job[0]

        def inspect():
            try:
                if source == MONITOR:
                    monitor = shared or select_source(MONITOR, cancel)
                    if shared is None:
                        self.monitor_selected.emit(job, monitor)
                    frame = monitor.frame(cancel)
                else:
                    frame = capture_frame(source, cancel)
                if cancel.is_set():
                    return
                result = complete(model, "", request, {"profile": profile}, "general", api_key=api_key, image=frame,
                                  may_wait=source == MONITOR, rechecking=rechecking)
                self.viewed.emit(job, result, "")
            except CaptureCanceled:
                self.viewed.emit(job, None, "")
            except (GLib.Error, OSError, ValueError, RuntimeError, KeyError) as exc:
                self.viewed.emit(job, None, str(exc))

        Thread(target=inspect, daemon=True).start()

    def view_finished(self, job, result, error):
        if self.view_job is not job:
            return
        self.view_job = None
        if not self.session.active or job[1] != self.session.epoch:
            return
        if error:
            if job[4] == MONITOR:
                self.stop_monitor()
            self.message("Window view failed. " + error)
            self.say("I couldn't view that source. Check the activity log for details.")
        elif result is None:
            self.stop_watch()
            self.message("Window sharing canceled.")
        elif result.wait_for_view and self.shared_monitor:
            if not job[5]:
                self.watch_request = job[3]
                self.watch_timer.start()
                self.stop_watch_button.setVisible(True)
                self.log("Screen", "Waiting for the requested view. Say stop watching to end the checks.")
                self.answer(result.draft + " I’ll check again when it’s open.", True)
        elif result.question:
            self.stop_watch()
            self.answer(result.question, True)
        else:
            self.stop_watch()
            self.last_reply = result.draft
            self.remember_turn("general", job[3], result.draft)
            self.output.setPlainText(result.draft)
            self.message("Listening")
            self.log("Assistant", result.draft)
            spoken = result.draft if len(result.draft) <= 400 else "I reviewed the window. The full reply is in the activity log."
            self.say(spoken, record=False)

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
                self.say(error if error.startswith("Ollama is offline.") else
                         "The model request failed. Check the chat for details.")
            return
        if result.needs_view:
            if self.auto_view.isChecked():
                self.look_at_window(request, MONITOR)
            else:
                self.answer("Use View monitors to share the screen for this question.", voice)
            return
        if result.question:
            if voice:
                self.clarification = (self.session.clock() + 90, self.current_provider, kind, request, result.question)
                self.answer(result.question, True)
            else:
                self.message(result.question + "\nAdd the answer to the Task field.")
                self.request.setFocus()
            return
        self.output.setPlainText(result.draft)
        self.last_reply = result.draft
        self.remember_turn(kind, request, result.draft)
        if voice:
            if kind == "rider":
                self.show_panel()
            else:
                self.message("Listening")
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
            self.manual.show()
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
        self.state.setText("Transcribing" if active and self.audio_status == "Transcribing speech"
                           else "Listening" if active else "Paused")
        if active != self.last_tray_state:
            self.listen_button.setText("■" if active else "▶")
            label = "Pause listening" if active else "Start listening"
            self.listen_button.setToolTip(label)
            self.listen_button.setAccessibleName(label)
        self.voice_row.setVisible(active)
        self.tray.setToolTip("GPT Linux Assistant · " + ("Listening" if active else "Paused"))
        if active != self.last_tray_state:
            self.tray.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay if active else QStyle.SP_MediaPause))
            self.last_tray_state = active
        shared = [target.label for target in targets.values() if target.kind != "desktop"]
        detail = [status, self.audio_status, self.partial_text, summary if active else ""]
        if apps:
            detail.append("Open apps: " + apps)
        if shared:
            detail.append("Shared: " + ", ".join(shared))
        self.state.setToolTip("\n".join(filter(None, detail)))
        if focus != self.last_focus:
            self.last_focus = focus
            if focus:
                self.log("Focus", focus)
        now_status = status.split("\nShared:", 1)[0]
        if now_status != self.last_status:
            self.last_status = now_status
            if now_status not in ("Preparing a reply.", "Listening", "Review the proposed edit."):
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
                if not self.speaking and not self.user_speaking and not self.model_job and not self.view_job and not proposal:
                    command = "review suggestion" if self.conversation.isChecked() else "Assistant, review suggestion"
                    self.say(f"{message} Say {command}.", record=False)
        proposal_id = proposal.id if proposal else None
        if self.mode and (self.mode[2] < session.clock() or (self.mode[0] == "reply" and self.mode[1] != proposal_id)):
            self.mode = None
            if not self.speaking:
                self.audio_status = "Microphone listening"
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
                self.review.raise_()
                self.log("Approval", label)
                action = {"rider": "The Rider replacement", "unity": "The Unity connection",
                          "desktop": proposal.target.label}[proposal.target.kind]
                hint = (" Say approve it or decline it." if self.mic.isChecked()
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
    args.check_updates = True
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
        QTimer.singleShot(0, window.retrieve_api_key)
        result = app.exec_()
    except (OSError, sqlite3.Error) as exc:
        QMessageBox.critical(None, "Cannot open chat history", str(exc))
        return 1
    finally:
        session.pause()
        if "window" in locals():
            window.audio.stop()
            window.speaker.stop()
            window.stop_monitor()
            window.save_profile()
            try:
                window.history.close()
            except (OSError, sqlite3.Error):
                pass
        bridge.close()
    if result == updates.RESTART:
        os.execv(sys.executable, [sys.executable, "-m", "assistant_app", *sys.argv[1:]])
    return result


if __name__ == "__main__":
    sys.exit(main())
