"""Run on Qt offscreen with real widgets and simulated microphone/model results."""
import os
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import Mock, patch

from PyQt5.QtCore import QEventLoop, QTimer
from PyQt5.QtWidgets import QApplication

from assistant_app.__main__ import Window
from assistant_app.drafting import DraftResult
from assistant_app.session import Session


def settle():
    loop = QEventLoop()
    QTimer.singleShot(100, loop.quit)
    loop.exec_()


def main():
    scratch = TemporaryDirectory()
    os.environ["XDG_DATA_HOME"] = scratch.name
    os.environ["XDG_CONFIG_HOME"] = scratch.name
    app = QApplication([])
    session = Session()
    window = Window(session, SimpleNamespace(vosk_model="", ollama_model="test-model", openai_model=None))
    assert window.auto_view.isChecked() and window.window_access.isChecked()
    assert window.rider.isChecked() and window.unity.isChecked()
    window.spoken.setChecked(False)
    window.show()
    app.processEvents()
    window.start()

    def hear(text, confidence=1.0):
        window.heard(window.audio.generation, text, confidence)

    window.conversation.setChecked(False)
    hear("I'm wiring up a fallback dialogue line.")
    assert "fallback dialogue line" in window.journal.toPlainText()
    with patch("assistant_app.__main__.complete") as model:
        model.side_effect = [
            DraftResult("", "Which prefab?"),
            DraftResult("Open the Training prefab in Prefab Mode.", ""),
        ]
        hear("assistant")
        model.assert_not_called()
        hear("how do I edit this?")
        settle()
        hear("the Training prefab")
        settle()
        assert "My answer: the Training prefab" in model.call_args.args[2]
        assert not session.proposal
        journal = window.journal.toPlainText()
        assert "Open the Training prefab in Prefab Mode." in journal
        assert journal.count("how do I edit this?") == 1
        assert "Request  ·" not in journal
        assert "Preparing a reply" not in journal and "Reply ready" not in journal

    window.conversation.setChecked(True)
    with patch("assistant_app.__main__.complete", return_value=DraftResult("Hello!", "")) as model:
        hear("say hello")
        settle()
        assert model.call_args.args[2] == "say hello"
        assert window.journal.toPlainText().count("say hello") == 1

    with patch("assistant_app.__main__.capture_frame", return_value=b"frame") as capture, \
            patch("assistant_app.__main__.complete", return_value=DraftResult("A game inventory.", "")) as model:
        hear("Can you look at this game and tell me what's visible?")
        settle()
        assert capture.call_args.args[0] == 2
        assert model.call_args.kwargs["image"] == b"frame"
        assert not session.proposal
        assert window.last_reply == "A game inventory."

    monitor = Mock()
    monitor.frame.return_value = (b"left", b"right")
    with patch("assistant_app.__main__.select_source", return_value=monitor) as picker, \
            patch("assistant_app.__main__.complete", side_effect=[
                DraftResult("", "", True), DraftResult("Two monitors.", ""),
                DraftResult("", "", True), DraftResult("Same two monitors.", ""),
            ]) as model:
        hear("Which file is visible in Rider?")
        settle()
        hear("What is visible in my browser?")
        settle()
        picker.assert_called_once()
        assert monitor.frame.call_count == 2
        assert model.call_args.kwargs["image"] == (b"left", b"right")
        assert window.stop_monitor_button.isVisible()
        hear("stop sharing")
        monitor.close.assert_called_once()
        assert not window.stop_monitor_button.isVisible()
    window.last_reply = "A game inventory."

    window.mic_path.setText("simulated-model")
    window.audio.read_audio = lambda *args: None
    window.mic.setChecked(True)
    hear("copy that")
    assert session.proposal
    old_generation = window.audio.generation - 1
    hear("yes")
    hear("Assistant approve", 0.50)
    window.heard(old_generation, "Assistant approve", 1.0)
    assert not app.clipboard().text()
    hear("yes, apply it")
    assert app.clipboard().text() == "A game inventory."
    assert not session.proposal

    window.spoken.setChecked(True)
    with patch.object(window.speaker, "start") as synthesize:
        window.say("Hello")
        synthesize.assert_called_once_with("Hello", api_key=None, voice="marin")
        current = window.audio.generation
        window.heard(current, "Assistant copy that", 1.0)
        assert not session.proposal
        window.speaker_finished(window.speaker.generation, "")
    assert not window.speaking

    hear("pause")
    assert not session.active and "A game inventory." in window.journal.toPlainText()
    work_chat = window.history.chat.id
    window.new_chat()
    assert "A game inventory." not in window.journal.toPlainText()
    window.change_chat(work_chat)
    assert "A game inventory." in window.journal.toPlainText()
    assert window.last_reply == "Same two monitors."
    window.model.setText("work-model")
    window.profile_picker.setCurrentIndex(window.profile_picker.findData("play"))
    assert window.model.text() != "work-model"
    assert window.history.chat.id != work_chat
    assert "A game inventory." not in window.journal.toPlainText()
    window.profile_picker.setCurrentIndex(window.profile_picker.findData("work"))
    assert window.history.chat.id == work_chat
    assert window.model.text() == "work-model"
    initial_chat_geometry = window.journal.geometry()
    window.settings.show()
    app.processEvents()
    assert window.journal.geometry() == initial_chat_geometry
    window.settings.hide()

    window.key_field.setText("test-wallet-key")
    with patch("assistant_app.__main__.credentials.save_key") as save:
        window.store_api_key()
        settle()
        save.assert_called_once_with("test-wallet-key")
    assert window.current_provider == "openai"
    assert not window.key_field.text()
    window.history.close()

    restarted = Window(Session(), SimpleNamespace(vosk_model="", ollama_model=None, openai_model=None))
    with patch("assistant_app.__main__.credentials.read_key", return_value="test-wallet-key"):
        restarted.retrieve_api_key()
        settle()
    assert restarted.api_key == "test-wallet-key"
    assert restarted.current_provider == "openai"
    with open(restarted.profile_settings.fileName(), encoding="utf8") as config:
        assert "test-wallet-key" not in config.read()
    restarted.history.close()
    scratch.cleanup()
    print("Voice dashboard, clarification, window routing, playback isolation and voice approval passed.")


if __name__ == "__main__":
    main()
