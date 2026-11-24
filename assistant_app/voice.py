"""Speech synthesis and metering from the PCM sent to PipeWire."""
from array import array
from contextlib import contextmanager
from http.client import HTTPException
from io import BytesIO
from itertools import chain, islice
import json
import math
from queue import Empty, Full, Queue
import subprocess
import sys
from threading import Event, Lock, Thread
from time import monotonic
import wave
from urllib.error import HTTPError
from urllib.request import Request

from .ipc import loopback_opener

from PyQt5.QtCore import QObject, pyqtSignal


BLOCKS_PER_SECOND = 25
PREBUFFER_BLOCKS = 8
QUEUE_BLOCKS = 48


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

    def start(self, text, *, api_key=None, voice="marin"):
        self.stop()
        cancel = self.cancel = Event()
        Thread(target=self.play, args=(self.generation, cancel, text, api_key, voice), daemon=True).start()

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

    @contextmanager
    def audio_source(self, cancel, text, api_key, voice):
        if api_key is not None:
            request = Request("https://api.openai.com/v1/audio/speech", data=json.dumps({
                "model": "gpt-4o-mini-tts",
                "voice": voice,
                "input": text,
                "instructions": "Speak conversationally, with natural intonation and a brisk, clear pace.",
                "response_format": "pcm",
            }).encode(), headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"})
            try:
                with loopback_opener().open(request, timeout=12) as stream:
                    yield 24000, stream.read
            except HTTPError as error:
                raise RuntimeError(f"OpenAI speech request failed (HTTP {error.code}).") from None
            return

        synthesizer = self.spawn(cancel, ["espeak-ng", "--stdin", "--stdout", "-s", "180"],
                                 stdout=subprocess.PIPE)
        if synthesizer is None:
            yield 0, None
            return
        try:
            audio, _ = synthesizer.communicate(text.encode("utf-8"), timeout=8)
        except subprocess.TimeoutExpired:
            synthesizer.kill()
            synthesizer.communicate()
            raise RuntimeError("Speech synthesis timed out.")
        if cancel.is_set():
            yield 0, None
            return
        if synthesizer.returncode:
            raise RuntimeError("Speech synthesis failed.")
        with wave.open(BytesIO(audio), "rb") as wav:
            yield wav.getframerate(), lambda size: wav.readframes(size // 2)

    def fill_buffer(self, pending, stop_buffer, cancel, text, api_key, voice):
        def put(item):
            while not (cancel.is_set() or stop_buffer.is_set()):
                try:
                    pending.put(item, timeout=0.1)
                    return True
                except Full:
                    pass
            return False

        try:
            with self.audio_source(cancel, text, api_key, voice) as (rate, read):
                if not rate or not put(rate):
                    return
                size = 2 * (rate // BLOCKS_PER_SECOND)
                while not (cancel.is_set() or stop_buffer.is_set()):
                    block = read(size)
                    if not block:
                        break
                    if len(block) % 2:
                        raise RuntimeError("The voice returned an incomplete PCM sample.")
                    if not put(block):
                        return
        except (OSError, RuntimeError, EOFError, ValueError, HTTPException, wave.Error) as exc:
            put(exc)
        finally:
            put(None)

    @staticmethod
    def buffered_items(pending, cancel):
        while not cancel.is_set():
            try:
                item = pending.get(timeout=0.1)
            except Empty:
                continue
            if item is None:
                return
            if isinstance(item, Exception):
                raise item
            yield item

    def play(self, generation, cancel, text, api_key=None, voice="marin"):
        error = ""
        pending = Queue(maxsize=QUEUE_BLOCKS)
        stop_buffer = Event()
        Thread(target=self.fill_buffer,
               args=(pending, stop_buffer, cancel, text, api_key, voice), daemon=True).start()
        try:
            items = self.buffered_items(pending, cancel)
            rate = next(items, None)
            initial = list(islice(items, PREBUFFER_BLOCKS))
            if cancel.is_set():
                return
            if not initial:
                raise RuntimeError("The voice returned no audio.")
            player = self.spawn(cancel, ["pw-play", "--raw", f"--rate={rate}", "--channels=1",
                                         "--format=s16", "--latency=100ms", "-"])
            if player is None:
                return
            try:
                next_meter = 0.0
                for block in chain(initial, items):
                    if cancel.is_set():
                        break
                    # Let PipeWire set the playback pace through pipe backpressure.
                    player.stdin.write(block)
                    player.stdin.flush()
                    now = monotonic()
                    if now >= next_meter:
                        self.meter.emit(generation, level(block))
                        next_meter = now + 1 / BLOCKS_PER_SECOND
                player.stdin.close()
                if player.wait(timeout=3) and not cancel.is_set():
                    raise RuntimeError("PipeWire playback failed.")
            finally:
                if player.poll() is None:
                    player.kill()
                    player.wait()
                if not player.stdin.closed:
                    player.stdin.close()
        except (OSError, RuntimeError, EOFError, ValueError, HTTPException, wave.Error, subprocess.TimeoutExpired) as exc:
            error = f"Speech output unavailable. {exc}"
        finally:
            stop_buffer.set()
        if not cancel.is_set():
            self.finished.emit(generation, error)
