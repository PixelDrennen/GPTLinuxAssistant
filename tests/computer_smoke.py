"""Test the reviewed-input and chat screenshot paths with simulated desktop devices."""
import os
from tempfile import TemporaryDirectory
from threading import Event
from types import SimpleNamespace
from unittest.mock import Mock, patch

from PyQt5.QtCore import QBuffer, QEventLoop, QIODevice, QTimer, QUrl
from PyQt5.QtGui import QColor, QImage, QTextDocument
from PyQt5.QtWidgets import QApplication

from assistant_app.__main__ import Window
from assistant_app.computer import execute, keysym, parse_action
from assistant_app.session import Session


def settle(milliseconds=650):
    event = QEventLoop()
    QTimer.singleShot(milliseconds, event.quit)
    event.exec_()


def jpeg(color):
    image = QImage(250, 200, QImage.Format_RGB32)
    image.fill(QColor(color))
    buffer = QBuffer()
    buffer.open(QIODevice.WriteOnly)
    assert image.save(buffer, "JPEG")
    return bytes(buffer.data())


def main():
    with TemporaryDirectory() as root:
        os.environ["XDG_DATA_HOME"] = root
        os.environ["XDG_CONFIG_HOME"] = root
        app = QApplication([])
        frame = jpeg("#aabbcc")
        source = Mock()
        source.frame.return_value = frame
        action = parse_action(SimpleNamespace(type="keypress", keys=["CTRL", "a"]), 250, 200, (30, 40))
        execute(source, action, frame, Event())
        input_events = [item.args for item in source.notify.call_args_list]
        assert input_events == [
            ("NotifyPointerButton", "iu", 272, 1), ("NotifyPointerButton", "iu", 272, 0),
            ("NotifyKeyboardKeysym", "iu", keysym("CTRL"), 1), ("NotifyKeyboardKeysym", "iu", keysym("a"), 1),
            ("NotifyKeyboardKeysym", "iu", keysym("a"), 0), ("NotifyKeyboardKeysym", "iu", keysym("CTRL"), 0),
        ]
        source.reset_mock()
        source.frame.return_value = jpeg("#000000")
        try:
            execute(source, action, frame, Event())
        except ValueError as error:
            assert "changed" in str(error)
        else:
            raise AssertionError("Input was not refused after a screen change.")
        source.notify.assert_not_called()

        window = Window(Session(), SimpleNamespace(vosk_model="", ollama_model="local", openai_model=None))
        window.api_key = "mock-key"
        window.show()
        window.start()
        window.spoken.setChecked(False)
        source.frame.return_value = frame
        click = parse_action(SimpleNamespace(type="click", button="left", x=30, y=40, keys=[]), 250, 200)
        with patch("assistant_app.desktop_control.select_source", return_value=source), \
                patch("assistant_app.desktop_control.plan", side_effect=[click, "The Accounting tab is open."]):
            window.ask(voice_request="Use my computer to open Accounting")
            settle()
            assert window.desktop_control.pending[0] == click
            assert window.desktop_control.dialog.isVisible()
            source.notify.assert_not_called()
            window.desktop_control.approve()
            settle(1050)
            source.notify.assert_called()
            source.close.assert_called_once()
            assert window.last_reply == "The Accounting tab is open."
            assert len(window.journal.snapshots) == 2
            window.save_chat()
            window.load_chat()
            assert len(window.journal.snapshots) == 2
            image_id = next(iter(window.journal.snapshots))
            url = QUrl("assistant-snapshot:" + image_id)
            assert url.path() == image_id
            assert window.journal.document().resource(QTextDocument.ImageResource, url) is not None

        window.spoken.setChecked(True)
        with patch.object(window.speaker, "start"):
            window.say("Here is the requested result.")
            assert not window.speech_overlay.isVisible()
            window.speaker_sample(window.speaker.generation, 0.7)
            app.processEvents()
            assert window.speech_overlay.isVisible()
            assert window.speech_overlay.text == "Here is the requested result."
            window.speaker_finished(window.speaker.generation, "")
            assert not window.speech_overlay.isVisible()
        window.history.close()
    print("Verified approval, keystrokes, stale-screen rejection, in-chat screenshots, and speech overlay.")


if __name__ == "__main__":
    main()
