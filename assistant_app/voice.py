"""Local speech output and metering from the PCM sent to PipeWire."""
from array import array
from io import BytesIO
import math
import subprocess
import sys
from threading import Event, Lock, Thread
from time import monotonic
import wave

from PyQt5.QtCore import QObject, pyqtSignal


def level(pcm):
    samples = array("h")
    samples.frombytes(pcm[:len(pcm) & ~1])
    if not samples:
        return 0.0
    if sys.byteorder != "little":
        samples.byteswap()
    rms = math.sqrt(sum(sample * sample for sample in samples) / len(samples)) / 32768
    return min(1.0, rms * 4)


class Speaker(QObject):
    meter = pyqtSignal(int, float)
    finished = pyqtSignal(int, str)

    def __init__(self):
        super().__init__()
        self.generation = 0
        self.cancel = Event()
        self.lock = Lock()
        self.process = None

    def start(self, text):
        self.stop()
        cancel = self.cancel = Event()
        Thread(target=self.play, args=(self.generation, cancel, text), daemon=True).start()

    def stop(self):
        self.generation += 1
        self.cancel.set()
        with self.lock:
            if self.process is not None and self.process.poll() is None:
                self.process.terminate()

    def spawn(self, cancel, args, **kwargs):
        with self.lock:
            if cancel.is_set():
                return None
            process = subprocess.Popen(args, stderr=subprocess.DEVNULL, stdin=subprocess.PIPE, **kwargs)
            self.process = process
            return process

    def play(self, generation, cancel, text):
        error = ""
        try:
            synthesizer = self.spawn(cancel, ["espeak-ng", "--stdin", "--stdout", "-s", "180"],
                                     stdout=subprocess.PIPE)
            if synthesizer is None:
                return
            try:
                audio, _ = synthesizer.communicate(text.encode("utf-8"), timeout=8)
            except subprocess.TimeoutExpired:
                synthesizer.kill()
                synthesizer.communicate()
                raise RuntimeError("Speech synthesis timed out.")
            if cancel.is_set():
                return
            if synthesizer.returncode:
                raise RuntimeError("Speech synthesis failed.")
            with wave.open(BytesIO(audio), "rb") as wav:
                rate = wav.getframerate()
                player = self.spawn(cancel, ["pw-play", "--raw", f"--rate={rate}", "--channels=1",
                                             "--format=s16", "--latency=50ms", "-"])
                if player is None:
                    return
                try:
                    start = monotonic()
                    frames = 0
                    while not cancel.is_set():
                        block = wav.readframes(rate // 25)
                        if not block:
                            break
                        # Keep the displayed envelope close to the audible signal.
                        if cancel.wait(max(0, start + frames / rate - monotonic())):
                            break
                        player.stdin.write(block)
                        player.stdin.flush()
                        frames += len(block) // 2
                        self.meter.emit(generation, level(block))
                    player.stdin.close()
                    if player.wait(timeout=3) and not cancel.is_set():
                        raise RuntimeError("PipeWire playback failed.")
                finally:
                    if player.poll() is None:
                        player.kill()
                        player.wait()
                    if not player.stdin.closed:
                        player.stdin.close()
        except (OSError, RuntimeError, EOFError, wave.Error, subprocess.TimeoutExpired) as exc:
            error = f"Speech output unavailable. {exc}"
        if not cancel.is_set():
            self.finished.emit(generation, error)
