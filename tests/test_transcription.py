from io import BytesIO
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch
import wave

from assistant_app.tasks import next_task
from assistant_app.transcription import FRAME_BYTES, RATE, SpeechTurn, transcribe


class TranscriptionTests(unittest.TestCase):
    def test_thinking_pause_stays_within_the_same_turn(self):
        speech = b"\x10" * FRAME_BYTES
        silence = b"\0" * FRAME_BYTES
        turn = SpeechTurn(4)
        for frame, voiced in [(speech, True)] * 10 + [(silence, False)] * 100 + [(speech, True)] * 9:
            _, completed = turn.accept(frame, voiced)
            self.assertIsNone(completed)
        for _ in range(133):
            _, completed = turn.accept(silence, False)
        self.assertIsNotNone(completed)
        self.assertEqual(completed.count(speech), 19)
        self.assertEqual(len(completed) // FRAME_BYTES, 129)
        self.assertIsNone(turn.accept(silence, False)[1])

    def test_short_noise_does_not_start_a_turn(self):
        turn = SpeechTurn(4)
        frame = bytes(FRAME_BYTES)
        for index in range(200):
            self.assertEqual(turn.accept(frame, index == 5), ((), None))

    def test_sdk_receives_a_wav_and_only_requested_vocabulary(self):
        sdk = MagicMock()
        client = sdk.OpenAI.return_value.__enter__.return_value
        client.audio.transcriptions.create.return_value = SimpleNamespace(text="TradeSkillMaster ledger.")
        audio = b"\x05" * FRAME_BYTES
        with patch.dict(sys.modules, {"openai": sdk}):
            self.assertEqual(transcribe(audio, "key", "TradeSkillMaster, TSM"), "TradeSkillMaster ledger.")
        args = client.audio.transcriptions.create.call_args.kwargs
        self.assertEqual(args["model"], "gpt-4o-transcribe")
        self.assertIn("TradeSkillMaster, TSM", args["prompt"])
        with wave.open(BytesIO(args["file"][1])) as wav:
            self.assertEqual(wav.getframerate(), RATE)
            self.assertEqual(wav.readframes(wav.getnframes()), audio)

    def test_task_switches_are_distinct_from_normal_requests(self):
        self.assertEqual(next_task("nevermind"), "")
        self.assertEqual(next_task("Let's move past that and do something else."), "")
        self.assertEqual(next_task("Never mind, can you look at my inventory?"), "can you look at my inventory?")
        self.assertIsNone(next_task("Never mind the colors for now."))
