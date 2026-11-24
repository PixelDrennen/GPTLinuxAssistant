"""Microphone capture, turn detection, and transcription without audio files."""
import json
from http.client import HTTPException
import re
import subprocess
from threading import Event, Lock, Thread

from .transcription import FRAME_BYTES, RATE, SpeechTurn, speech_detector, transcribe
from .voice import level

from PyQt5.QtCore import QObject, pyqtSignal


class Microphone(QObject):
    ready = pyqtSignal(int)
    meter = pyqtSignal(int, float)
    partial = pyqtSignal(int, str)
    heard = pyqtSignal(int, str, float)
    failed = pyqtSignal(int, str)
    speech_started = pyqtSignal(int)
    decoding = pyqtSignal(int)
    transcription_failed = pyqtSignal(int, str)

    def __init__(self):
        super().__init__()
        self.generation = 0
        self.cancel = Event()
        self.process = None
        self.lock = Lock()
        self.model = None
        self.model_path = ""
        self.model_lock = Lock()

    def start(self, path, pause_seconds=3, api_key=None, vocabulary=""):
        self.stop()
        generation = self.generation
        cancel = Event()
        self.cancel = cancel
        Thread(target=self.read_audio, args=(path, generation, cancel, pause_seconds, api_key, vocabulary), daemon=True).start()
        return generation

    def stop(self):
        self.generation += 1
        self.cancel.set()
        with self.lock:
            if self.process is not None and self.process.poll() is None:
                self.process.terminate()

    def recognizer(self, path, cancel):
        from vosk import KaldiRecognizer, Model, SetLogLevel

        with self.model_lock:
            if cancel.is_set():
                return None
            if self.model is None or self.model_path != path:
                SetLogLevel(-1)
                self.model = Model(path)
                self.model_path = path
            recognizer = KaldiRecognizer(self.model, RATE)
        recognizer.SetWords(True)
        return recognizer

    def read_audio(self, path, generation, cancel, pause_seconds, api_key, vocabulary):
        try:
            recognizer = None
            if path:
                try:
                    recognizer = self.recognizer(path, cancel)
                except Exception as exc:
                    # Vosk is optional when OpenAI handles transcription.
                    if not api_key:
                        raise RuntimeError(str(exc)) from exc
            detector = speech_detector()
            turn = SpeechTurn(pause_seconds)
            segments = []
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
                    audio = process.stdout.read(FRAME_BYTES)
                    if len(audio) != FRAME_BYTES:
                        if not cancel.is_set():
                            raise RuntimeError("PipeWire recording ended. Check the microphone and pw-record.")
                        break
                    if not ready:
                        self.ready.emit(generation)
                        ready = True
                    amount = level(audio)
                    self.meter.emit(generation, amount)
                    was_speaking = bool(turn.frames)
                    frames, finished_audio = turn.accept(audio, detector(audio, amount, was_speaking))
                    if not was_speaking and frames:
                        self.speech_started.emit(generation)
                    partial = ""
                    if recognizer and frames:
                        for frame in frames:
                            if recognizer.AcceptWaveform(frame):
                                segments.append(json.loads(recognizer.Result()))
                        pending = json.loads(recognizer.PartialResult()).get("partial", "")
                        partial = " ".join(filter(None, [*(segment.get("text") for segment in segments), pending]))
                    if finished_audio is not None:
                        if recognizer:
                            segments.append(json.loads(recognizer.FinalResult()))
                            recognizer.Reset()
                        if not cancel.is_set():
                            self.finish_turn(generation, cancel, finished_audio, segments, api_key, vocabulary)
                        segments.clear()
                        partial = ""
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

    def finish_turn(self, generation, cancel, audio, segments, api_key, vocabulary):
        local = " ".join(filter(None, (segment.get("text") for segment in segments)))
        confidence = min((word["conf"] for segment in segments for word in segment.get("result", [])),
                         default=0.0)
        text = local
        if api_key:
            self.decoding.emit(generation)
            try:
                text = transcribe(audio, api_key, vocabulary)
                # A cloud transcript alone cannot authorize an action.
                if re.findall(r"[a-z0-9]+", text.casefold()) != re.findall(r"[a-z0-9]+", local.casefold()):
                    confidence = 0.0
            except (OSError, HTTPException, RuntimeError, ValueError) as exc:
                if not cancel.is_set():
                    self.transcription_failed.emit(generation, str(exc))
                return
        if not cancel.is_set():
            if text:
                self.heard.emit(generation, text, confidence)
            else:
                self.ready.emit(generation)
