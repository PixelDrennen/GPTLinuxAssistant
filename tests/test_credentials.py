from subprocess import CompletedProcess
import unittest
from unittest.mock import patch

from assistant_app import credentials


class CredentialsTests(unittest.TestCase):
    @patch("assistant_app.credentials.subprocess.run")
    def test_wallet_uses_stdin_for_key_and_reads_saved_value(self, run):
        run.return_value = CompletedProcess([], 0, "", "")
        credentials.save_key("test-key")
        self.assertNotIn("test-key", run.call_args.args[0])
        self.assertEqual("test-key", run.call_args.kwargs["input"])
        run.return_value = CompletedProcess([], 0, "test-key\n", "")
        self.assertEqual("test-key", credentials.read_key())
        self.assertEqual("lookup", run.call_args.args[0][1])

    @patch("assistant_app.credentials.subprocess.run")
    def test_missing_or_locked_wallet_is_reported(self, run):
        run.side_effect = FileNotFoundError()
        with self.assertRaisesRegex(RuntimeError, "Install libsecret"):
            credentials.read_key()
        run.side_effect = None
        run.return_value = CompletedProcess([], 1, "", "locked")
        with self.assertRaisesRegex(RuntimeError, "Unlock"):
            credentials.save_key("test-key")
