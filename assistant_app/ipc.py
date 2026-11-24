"""Authenticated loopback transport for the explicitly enabled editor bridges."""
import fcntl
from hmac import compare_digest
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
from pathlib import Path
import re
import secrets
from threading import Thread
from urllib.request import ProxyHandler, build_opener, HTTPRedirectHandler


MAX_BODY = 160_000


class LocalBridge:
    def __init__(self, session):
        self.session = session
        runtime = Path(os.environ["XDG_RUNTIME_DIR"])
        info = runtime.stat()
        if not runtime.is_absolute() or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise PermissionError("XDG_RUNTIME_DIR must be private to the current user.")
        self.endpoint = runtime / "gpt-linux-assistant.endpoint"
        self.lease = os.open(runtime / "gpt-linux-assistant.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(self.lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            os.close(self.lease)
            raise OSError("GPT Linux Assistant is already running in this session.") from exc
        token = secrets.token_hex(32)
        server = None
        try:
            server = HTTPServer(("127.0.0.1", 0), self.handler(token))
            self.endpoint.unlink(missing_ok=True)
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
            with os.fdopen(os.open(self.endpoint, flags, 0o600), "w") as handle:
                handle.write(f"{server.server_port}\n{token}\n")
        except Exception:
            if server is not None:
                server.server_close()
            os.close(self.lease)
            raise
        self.server = server
        self.thread = Thread(target=server.serve_forever, daemon=True)
        self.thread.start()

    def close(self):
        self.endpoint.unlink(missing_ok=True)
        self.server.shutdown()
        self.server.server_close()
        os.close(self.lease)

    def handler(self, token):
        session = self.session

        class Handler(BaseHTTPRequestHandler):
            def setup(self):
                self.request.settimeout(1)
                super().setup()

            def log_message(self, *_):
                pass

            def do_POST(self):
                header = self.headers.get("Authorization", "").encode("utf-8")
                if not compare_digest(header, f"Bearer {token}".encode()) or self.headers.get("Origin"):
                    self.reply(403, {"error": "Unauthorized editor bridge."})
                    return
                try:
                    size = int(self.headers.get("Content-Length", "0"))
                    if not 0 < size <= MAX_BODY:
                        raise ValueError("Invalid request size.")
                    data = json.loads(self.rfile.read(size))
                    if not isinstance(data, dict):
                        raise ValueError("Invalid editor message.")
                    kind, capture = data.get("kind"), data.get("capture")
                    if kind not in ("rider", "unity") or not isinstance(capture, str) or not re.fullmatch(r"[a-f0-9]{32}", capture):
                        raise ValueError("Invalid editor target.")
                    if self.path == "/capture":
                        label, fields = data.get("label"), data.get("data")
                        if not isinstance(label, str) or not isinstance(fields, dict):
                            raise ValueError("Invalid editor capture.")
                        session.capture(kind, capture, label, fields)
                        result = {"waiting": True}
                    elif self.path == "/poll":
                        result = session.poll(kind, capture)
                    elif self.path == "/finish" and data.get("outcome") in ("applied", "stale", "failed"):
                        session.finish(kind, capture, data.get("id"), data["outcome"])
                        result = {"ok": True}
                    else:
                        raise ValueError("Unknown editor message.")
                    self.reply(200, result)
                except (ValueError, TypeError, UnicodeError, RecursionError) as exc:
                    self.reply(400, {"error": str(exc)})

            def reply(self, status, result):
                raw = json.dumps(result).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

        return Handler


class NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def loopback_opener():
    return build_opener(ProxyHandler({}), NoRedirects())
