from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from assistant_app import updates


class UpdatesTests(unittest.TestCase):
    def test_fast_forward_install_preserves_dirty_checkout(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            origin = root / "origin"
            checkout = root / "checkout"

            def git(folder, *args):
                return subprocess.check_output(["git", "-C", str(folder), *args], text=True,
                                               stderr=subprocess.DEVNULL).strip()

            origin.mkdir()
            git(origin, "init", "-b", "main")
            git(origin, "config", "user.name", "Test")
            git(origin, "config", "user.email", "test@example.invalid")
            file = origin / "version"
            file.write_text("one")
            git(origin, "add", "version")
            git(origin, "commit", "-m", "First")
            git(root, "clone", str(origin), str(checkout))
            file.write_text("two")
            git(origin, "commit", "-am", "Second")

            with patch.object(updates, "ROOT", checkout), patch.object(updates, "REPOSITORY", str(origin)):
                available = updates.check()
                local = checkout / "version"
                local.write_text("local changes")
                with self.assertRaisesRegex(ValueError, "local changes"):
                    updates.install(available)
                self.assertEqual("local changes", local.read_text())
                git(checkout, "restore", "version")
                updates.install(available)
                self.assertEqual("two", local.read_text())
                self.assertIsNone(updates.check())
