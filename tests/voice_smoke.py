"""Run on Qt offscreen with real widgets and simulated microphone/model results."""
from types import SimpleNamespace
from unittest.mock import patch

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
    app = QApplication([])
    session = Session()
    window = Window(session, SimpleNamespace(vosk_model="", ollama_model="test-model", openai_model=None))
    window.spoken.setChecked(False)
    window.show()
    app.processEvents()
    window.start()

    def hear(text, confidence=1.0):
        window.heard(window.audio.generation, text, confidence)

    hear("I'm wiring up a fallback dialogue line.")
    assert "fallback dialogue line" in window.journal.toPlainText()
    with patch("assistant_app.__main__.complete") as model:
        model.side_effect = [
            DraftResult("", "Which prefab?"),
            DraftResult("Open the Training prefab in Prefab Mode.", ""),
        ]
        hear("Assistant, how do I edit this?")
        settle()
        hear("Assistant, the Training prefab")
        settle()
        assert "My answer: the Training prefab" in model.call_args.args[2]
        assert not session.proposal
        assert "Open the Training prefab in Prefab Mode." in window.journal.toPlainText()

    window.mic_path.setText("simulated-model")
    window.audio.read_audio = lambda *args: None
    window.mic.setChecked(True)
    hear("Assistant copy that")
    assert session.proposal
    old_generation = window.audio.generation - 1
    hear("yes")
    hear("Assistant approve", 0.50)
    window.heard(old_generation, "Assistant approve", 1.0)
    assert not app.clipboard().text()
    hear("Assistant approve")
    assert app.clipboard().text() == "Open the Training prefab in Prefab Mode."
    assert not session.proposal

    window.spoken.setChecked(True)
    with patch.object(window.speaker, "start") as synthesize:
        window.say("Hello")
        synthesize.assert_called_once_with("Hello")
        current = window.audio.generation
        window.heard(current, "Assistant copy that", 1.0)
        assert not session.proposal
        window.speaker_finished(window.speaker.generation, "")
    assert not window.speaking

    hear("Assistant pause")
    assert not session.active and not window.journal.toPlainText()
    print("Voice dashboard, clarification, playback isolation and voice approval passed.")


if __name__ == "__main__":
    main()
