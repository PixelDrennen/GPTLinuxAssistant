"""Local microphone capture and Vosk transcription, with no audio files."""
import json
import subprocess
from threading import Event, Lock, Thread

from .voice import level

from PyQt5.QtCore import QObject, pyqtSignal


class Microphone(QObject):
    ready = pyqtSignal(int)
    meter = pyqtSignal(int, float)
    partial = pyqtSignal(int, str)
    heard = pyqtSignal(int, str, float)
    failed = pyqtSignal(int, str)

    def __init__(self):
        super().__init__()
        self.generation = 0
        self.cancel = Event()
        self.process = None
        self.lock = Lock()
        self.model = None
        self.model_path = ""
        self.model_lock = Lock()

    def start(self, path):
        self.stop()
        generation = self.generation
        cancel = Event()
        self.cancel = cancel
        Thread(target=self.read_audio, args=(path, generation, cancel), daemon=True).start()
        return generation

    def stop(self):
        self.generation += 1
        self.cancel.set()
        with self.lock:
            if self.process is not None and self.process.poll() is None:
                self.process.terminate()

    def read_audio(self, path, generation, cancel):
        try:
            from vosk import KaldiRecognizer, Model, SetLogLevel

            with self.model_lock:
                if cancel.is_set():
                    return
                if self.model is None or self.model_path != path:
                    SetLogLevel(-1)
                    self.model = Model(path)
                    self.model_path = path
                recognizer = KaldiRecognizer(self.model, 16000)
            recognizer.SetWords(True)
            with self.lock:
                if cancel.is_set():
                    return
                process = subprocess.Popen(
                    ["pw-record", "--raw", "--rate=16000", "--channels=1", "--format=s16", "-"],
                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
                self.process = process
            try:
                ready = False
                last_partial = ""
                while not cancel.is_set():
                    audio = process.stdout.read(3200)
                    if not audio:
                        if not cancel.is_set():
                            raise RuntimeError("PipeWire recording ended. Check the microphone and pw-record.")
                        break
                    if not ready and not cancel.is_set():
                        self.ready.emit(generation)
                        ready = True
                    self.meter.emit(generation, level(audio))
                    if recognizer.AcceptWaveform(audio):
                        if last_partial:
                            last_partial = ""
                            self.partial.emit(generation, "")
                        result = json.loads(recognizer.Result())
                        if result.get("text") and not cancel.is_set():
                            confidence = min((word["conf"] for word in result.get("result", [])), default=0.0)
                            self.heard.emit(generation, result["text"], confidence)
                    else:
                        partial = json.loads(recognizer.PartialResult()).get("partial", "")
                        if partial != last_partial:
                            last_partial = partial
                            self.partial.emit(generation, partial)
            finally:
                if process.poll() is None:
                    process.terminate()
                process.stdout.close()
                process.wait()
        except (ImportError, OSError, RuntimeError, ValueError) as exc:
            if not cancel.is_set():
                self.failed.emit(generation, str(exc))
