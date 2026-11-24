"""Collect a complete turn before dispatching speech for transcription."""
from collections import deque
from io import BytesIO
import sys
import wave


RATE = 16000
FRAME_MS = 30
FRAME_BYTES = RATE * FRAME_MS // 1000 * 2
PRE_ROLL = 10
TAIL = 10
MAX_TURN_MS = 90000


class SpeechTurn:
    def __init__(self, pause_seconds):
        self.pause_frames = round(pause_seconds * 1000 / FRAME_MS)
        self.leading = deque(maxlen=PRE_ROLL)
        self.frames = []
        self.voiced = 0
        self.quiet = 0

    def accept(self, frame, speech):
        if not self.frames:
            self.leading.append(frame)
            self.voiced = self.voiced + 1 if speech else 0
            if self.voiced < 2:
                return (), None
            self.frames = list(self.leading)
            return tuple(self.frames), None

        self.frames.append(frame)
        self.quiet = 0 if speech else self.quiet + 1
        if self.quiet < self.pause_frames and len(self.frames) * FRAME_MS < MAX_TURN_MS:
            return (frame,), None

        keep = len(self.frames) - max(0, self.quiet - TAIL)
        finished = b"".join(self.frames[:keep])
        self.leading.clear()
        self.frames.clear()
        self.voiced = self.quiet = 0
        return (frame,), finished


def speech_detector():
    try:
        from webrtcvad import Vad
    except ImportError:
        # Still work with existing installs. Learn a baseline from quieter frames.
        baseline = 0.008

        def energy_gate(_frame, amount, active):
            nonlocal baseline
            speech = amount >= max(0.037, baseline * 2.6)
            if not active and not speech:
                baseline = baseline * 0.95 + amount * 0.05
            return speech
        return energy_gate
    detector = Vad(2)
    return lambda frame, _amount, _active: detector.is_speech(frame, RATE)


def openai_sdk():
    try:
        from openai import APIError, OpenAI
    except ModuleNotFoundError as error:
        if error.name == "openai":
            raise RuntimeError(f"OpenAI SDK missing from {sys.executable}. "
                               "Launch with scripts/launch-assistant.sh to use the checkout’s virtual environment.") from None
        raise RuntimeError(f"OpenAI SDK dependency missing in {sys.executable}: {error}") from None
    except (ImportError, OSError) as error:
        raise RuntimeError(f"OpenAI SDK could not load in {sys.executable}: {error}") from None
    return APIError, OpenAI


def transcribe(audio, key, vocabulary=""):
    buffered = BytesIO()
    with wave.open(buffered, "wb") as wav:
        wav.setparams((1, 2, RATE, 0, "NONE", "not compressed"))
        wav.writeframes(audio)

    APIError, OpenAI = openai_sdk()
    prompt = "Transcribe the speaker verbatim. Preserve incomplete phrases."
    if vocabulary:
        prompt += " Only use these spellings if heard: " + vocabulary
    try:
        with OpenAI(api_key=key, base_url="https://api.openai.com/v1", timeout=20, max_retries=0) as client:
            transcript = client.audio.transcriptions.create(
                model="gpt-4o-transcribe", file=("utterance.wav", buffered.getvalue(), "audio/wav"),
                response_format="json", prompt=prompt)
    except APIError as error:
        status = getattr(error, "status_code", None)
        detail = f" (HTTP {status})" if status else ". Check your connection."
        raise RuntimeError("OpenAI transcription failed" + detail) from None
    return transcript.text.strip()
