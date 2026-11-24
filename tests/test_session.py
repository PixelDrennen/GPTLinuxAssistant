import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request

from assistant_app.ipc import LocalBridge, loopback_opener
from assistant_app.session import Session


class SessionTests(unittest.TestCase):
    def setUp(self):
        self.now = 5.0
        self.session = Session(lambda: self.now)
        self.session.start()
        self.session.bridges.add("rider")

    def capture(self, identifier="a" * 32):
        self.session.capture("rider", identifier, "Scratch", {"text": "Draft", "start": 0, "end": 5})
        return self.session.targets["rider"]

    def test_approve_requires_exact_id_and_dispatches_once(self):
        target = self.capture()
        proposal = self.session.propose(target, "Completed")
        with self.assertRaises(ValueError):
            self.session.respond("some other proposal", True)
        self.assertEqual({"waiting": True}, self.session.poll("rider", target.capture))
        self.session.respond(proposal.id, True)
        self.assertEqual({"waiting": False}, self.session.poll("rider", "b" * 32))
        self.assertEqual({"id": proposal.id, "replacement": "Completed"},
                         self.session.poll("rider", target.capture))
        self.assertEqual({"waiting": False}, self.session.poll("rider", target.capture))
        self.session.finish("rider", target.capture, proposal.id, "applied")
        self.assertIn("Applied", self.session.status)

    def test_new_capture_and_pause_invalidate_approval(self):
        target = self.capture()
        proposal = self.session.propose(target, "Completed")
        self.capture("b" * 32)
        with self.assertRaises(ValueError):
            self.session.respond(proposal.id, True)
        other = self.session.propose(self.session.targets["rider"], "New")
        self.session.respond(other.id, True)
        self.session.pause()
        self.session.start()
        self.assertEqual({"waiting": False}, self.session.poll("rider", "b" * 32))

    def test_expired_and_declined_edits_never_dispatch(self):
        target = self.capture()
        proposal = self.session.propose(target, "Completed")
        self.now += 46
        with self.assertRaises(ValueError):
            self.session.respond(proposal.id, True)
        proposal = self.session.propose(target, "Completed")
        self.session.respond(proposal.id, False)
        self.assertEqual({"waiting": True}, self.session.poll("rider", target.capture))

    def test_narration_offers_unity_without_consent_to_edit(self):
        self.session.windows_enabled = True
        self.session.exclusions = {"private-app"}
        self.session.observe("Rider", ["unity", "Private-App", "Rider"])
        self.session.narrate("Reconnect the dialogue fallback lines.")
        self.session.narrate("yes")
        self.assertEqual("unity", self.session.suggestion)
        self.assertEqual(["Rider", "unity"], self.session.windows)
        self.assertIsNone(self.session.command)
        self.assertIsNone(self.session.proposal)

    def test_desktop_preview_uses_same_single_proposal(self):
        desktop = self.session.propose_desktop("copy", "Slack reply")
        self.assertEqual("Slack reply", desktop.after)
        with self.assertRaises(ValueError):
            self.session.propose(self.capture(), "Completed")
        self.session.respond(desktop.id, False)
        self.assertIsNone(self.session.command)

    def test_revoke_removes_pending_edit(self):
        target = self.capture()
        self.session.respond(self.session.propose(target, "Completed").id, True)
        self.session.revoke("rider")
        with self.assertRaises(ValueError):
            self.session.poll("rider", target.capture)
        self.assertIsNone(self.session.command)


class TransportTests(unittest.TestCase):
    def test_auth_scope_and_loopback_round_trip(self):
        with TemporaryDirectory() as folder, patch.dict(os.environ, {"XDG_RUNTIME_DIR": folder}):
            session = Session()
            endpoint = Path(folder) / "gpt-linux-assistant.endpoint"
            endpoint.write_text("left behind by a prior process")
            bridge = LocalBridge(session)
            try:
                self.assertEqual(0o600, endpoint.stat().st_mode & 0o777)
                with self.assertRaises(OSError):
                    LocalBridge(session)
                port, token = endpoint.read_text().splitlines()
                capture = "e" * 32
                body = {"kind": "rider", "capture": capture, "label": "Draft",
                        "data": {"text": "Old", "start": 0, "end": 3}}

                def send(route, message, auth=token, extra=None):
                    request = Request(f"http://127.0.0.1:{port}{route}", data=json.dumps(message).encode(),
                                      headers={"Authorization": f"Bearer {auth}", **(extra or {})})
                    with loopback_opener().open(request, timeout=3) as response:
                        return json.load(response)

                with self.assertRaises(HTTPError) as unauthenticated:
                    send("/capture", body, "invalid")
                self.assertEqual(403, unauthenticated.exception.code)
                with self.assertRaises(HTTPError) as paused:
                    send("/capture", body)
                self.assertEqual(400, paused.exception.code)
                session.start()
                session.bridges.add("rider")
                with self.assertRaises(HTTPError) as webpage:
                    send("/capture", body, extra={"Origin": "https://example.com"})
                self.assertEqual(403, webpage.exception.code)
                self.assertTrue(send("/capture", body)["waiting"])
                proposal = session.propose(session.targets["rider"], "New")
                session.respond(proposal.id, True)
                self.assertEqual("New", send("/poll", body)["replacement"])
                send("/finish", {**body, "id": proposal.id, "outcome": "stale"})
                self.assertIn("Skipped", session.status)
            finally:
                bridge.close()
            self.assertFalse(endpoint.exists())


if __name__ == "__main__":
    unittest.main()
