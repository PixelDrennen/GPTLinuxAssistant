"""Simulate PCM arriving in bursts and PipeWire consuming it through a real pipe."""
from contextlib import contextmanager
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
from time import monotonic, sleep
from unittest.mock import patch

from assistant_app.voice import PREBUFFER_BLOCKS, Speaker


def main():
    block = bytes.fromhex("0010") * 960
    with TemporaryDirectory() as folder:
        root = Path(folder)
        started = root / "started"
        rendered = root / "rendered"
        player = root / "pw-play"
        player.write_text(
            "#!/usr/bin/python3\n"
            "import pathlib, sys\n"
            "assert '--latency=100ms' in sys.argv\n"
            "first = sys.stdin.buffer.read(1920)\n"
            f"pathlib.Path({str(started)!r}).touch()\n"
            f"pathlib.Path({str(rendered)!r}).write_bytes(first + sys.stdin.buffer.read())\n"
        )
        player.chmod(0o700)
        speaker = Speaker()
        finished = []
        speaker.finished.connect(lambda _, status: finished.append(status))
        reads = 0

        def read(size):
            nonlocal reads
            assert size == len(block)
            reads += 1
            if reads == PREBUFFER_BLOCKS + 1:
                deadline = monotonic() + 2
                while not started.exists() and monotonic() < deadline:
                    sleep(0.01)
                assert started.exists(), "Playback should start before the whole stream arrives."
            return block if reads <= PREBUFFER_BLOCKS + 2 else b""

        @contextmanager
        def source(*_args):
            yield 24000, read

        with patch.dict(os.environ, {"PATH": folder + ":" + os.environ["PATH"]}):
            with patch.object(speaker, "audio_source", source):
                speaker.play(0, Event(), "test speech")
        assert finished == [""], finished
        assert rendered.read_bytes() == block * (PREBUFFER_BLOCKS + 2)
    print("Buffered playback starts while synthesis is still streaming and sends all PCM samples.")


if __name__ == "__main__":
    main()
