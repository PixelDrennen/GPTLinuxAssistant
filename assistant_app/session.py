"""In-memory observation and one-use approval state."""
from collections import deque
from dataclasses import dataclass
import re
from threading import RLock
from time import monotonic
from uuid import uuid4


CAPTURE_TTL = 180
APPROVAL_TTL = 45
COMMAND_TTL = 10


@dataclass(frozen=True)
class Target:
    kind: str
    capture: str
    label: str
    data: dict
    expires: float


@dataclass(frozen=True)
class Proposal:
    id: str
    target: Target
    before: str
    after: str
    payload: str
    expires: float


class Session:
    def __init__(self, clock=monotonic):
        self.clock = clock
        self.lock = RLock()
        self.active = False
        self.epoch = 0
        self.windows_enabled = False
        self.exclusions = set()
        self.bridges = set()
        self.focus = ""
        self.windows = []
        self.events = deque(maxlen=20)
        self.targets = {}
        self.proposal = None
        self.command = None
        self.status = "Paused"
        self.suggestion = ""
        self.last_hint = -float("inf")

    def start(self):
        with self.lock:
            if not self.active:
                self.active = True
                self.epoch += 1
                self.status = "Listening"

    def pause(self):
        with self.lock:
            self.active = False
            self.epoch += 1
            self.clear_windows()
            self.events.clear()
            self.targets.clear()
            self.proposal = None
            self.command = None
            self.suggestion = ""
            self.last_hint = -float("inf")
            self.status = "Paused"

    def clear_windows(self):
        with self.lock:
            self.focus = ""
            self.windows = []
            self.events = deque((item for item in self.events if item[1] == "speech"), maxlen=20)

    def observe(self, focused, windows):
        with self.lock:
            if not self.active or not self.windows_enabled:
                return
            names = [name[:128].strip() for name in windows[:100] if isinstance(name, str)]
            self.windows = sorted({name for name in names if name and name.casefold() not in self.exclusions})
            focused = focused[:128].strip()
            focused = "" if focused.casefold() in self.exclusions else focused
            if focused != self.focus and focused:
                self.events.append((self.clock(), "focus", focused))
            self.focus = focused

    def narrate(self, text):
        with self.lock:
            if not self.active:
                return
            self.events.append((self.clock(), "speech", text[:1000]))
            recent = " ".join(value for ts, kind, value in self.events
                              if kind == "speech" and ts >= self.clock() - 45).casefold()
            if self.clock() - self.last_hint < 60:
                return
            applications = " ".join(self.windows + [self.focus]).casefold()
            if ("unity" in applications and re.search(r"\b(dialog(?:ue)?|voicelines?|fallback)\b", recent)
                    and re.search(r"\b(link\w*|connect\w*|reconnect\w*|wir\w*)\b", recent)):
                self.suggestion = "unity"
            elif ("slack" in applications and re.search(r"\b(reply|respond|draft|write|summari[sz]e)\b", recent)
                  and re.search(r"\b(slack|thread|message|update)\b", recent)):
                self.suggestion = "slack"
            elif (re.search(r"firefox|chrome|chromium|brave|vivaldi|librewolf|microsoft-edge", applications)
                  and re.search(r"\b(summari[sz]e|summary|take notes)\b", recent)
                  and re.search(r"\b(page|article|documentation|website)\b", recent)):
                self.suggestion = "browser"
            else:
                return
            self.last_hint = self.clock()

    def summary(self):
        with self.lock:
            self.expire()
            speech = next((value for _, kind, value in reversed(self.events) if kind == "speech"), "")
            if self.suggestion:
                task = {"unity": "connecting dialogue in Unity", "slack": "preparing a Slack message or summary",
                        "browser": "summarizing a web page"}[self.suggestion]
                return f"Likely task: {task}\nFrom your narration and open apps."
            details = []
            if self.focus:
                details.append(f"Focused app: {self.focus}")
            if speech:
                details.append(f'Recent narration: “{speech}”')
            return "\n".join(details) or "Waiting for narration or window context"

    def capture(self, kind, capture, label, data):
        with self.lock:
            self.expire()
            self.require_bridge(kind)
            if kind == "rider":
                text = data.get("text")
                start, end = data.get("start"), data.get("end")
                if (not isinstance(text, str) or not text.strip() or len(text) > 16000
                        or type(start) is not int or type(end) is not int or not 0 <= start < end):
                    raise ValueError("Select a nonempty draft of at most 16,000 characters.")
                data = {"text": text, "start": start, "end": end}
            else:
                field, source, destination = (data.get(key) for key in ("field", "source", "destination"))
                if not all(isinstance(value, str) and 0 < len(value) <= 1000
                           for value in (field, source, destination)):
                    raise ValueError("Choose a source, reference field, and destination in Unity.")
                data = {"field": field, "source": source, "destination": destination}
            if self.proposal and self.proposal.target.kind == kind:
                self.proposal = None
            if self.command and self.command["kind"] == kind and not self.command["claimed"]:
                self.command = None
            self.targets[kind] = Target(kind, capture, label[:400], data, self.clock() + CAPTURE_TTL)
            self.status = f"{kind.title()} target shared."

    def require_bridge(self, kind):
        if not self.active or (kind != "desktop" and kind not in self.bridges):
            raise ValueError("Start listening and enable this editor integration.")

    def revoke(self, kind):
        with self.lock:
            self.bridges.discard(kind)
            self.targets.pop(kind, None)
            if self.proposal and self.proposal.target.kind == kind:
                self.proposal = None
            if self.command and self.command["kind"] == kind:
                self.command = None

    def expire(self):
        with self.lock:
            now = self.clock()
            while self.events and now - self.events[0][0] >= 90:
                self.events.popleft()
            if now - self.last_hint >= 90:
                self.suggestion = ""
            for kind, target in tuple(self.targets.items()):
                if target.expires <= now:
                    del self.targets[kind]
            if self.proposal and (self.proposal.expires <= now or
                                  self.targets.get(self.proposal.target.kind) is not self.proposal.target):
                self.proposal = None
                self.status = "Proposal expired."
            if self.command and self.command["expires"] <= now:
                self.status = ("No confirmation from the editor. Check the target before retrying."
                               if self.command["claimed"] else "Approved edit expired before the editor received it.")
                self.command = None

    def propose_desktop(self, action, value):
        with self.lock:
            self.expire()
            self.require_bridge("desktop")
            if self.proposal or self.command:
                raise ValueError("Resolve the current edit before proposing another.")
            if not value.strip() or len(value) > 24000:
                raise ValueError("The action needs a valid preview.")
            label = {"copy": "Copy draft to clipboard", "open": "Open link in browser"}[action]
            target = Target("desktop", uuid4().hex, label, {"action": action, "value": value},
                            self.clock() + APPROVAL_TTL)
            self.targets["desktop"] = target
            return self.propose(target)

    def propose(self, target, replacement=""):
        with self.lock:
            self.expire()
            self.require_bridge(target.kind)
            if self.targets.get(target.kind) is not target:
                raise ValueError("The target changed. Share it again.")
            if self.proposal or self.command:
                raise ValueError("Resolve the current edit before proposing another.")
            if target.kind == "rider":
                before = target.data["text"]
                if not replacement.strip() or len(replacement) > 24000 or replacement == before:
                    raise ValueError("The replacement must differ from the selected draft and fit the preview.")
                after = replacement
                payload = replacement
            elif target.kind == "desktop":
                before = ""
                after = target.data["value"]
                payload = ""
            else:
                before = f'{target.data["source"]}.{target.data["field"]} → (unassigned)'
                after = f'{target.data["source"]}.{target.data["field"]} → {target.data["destination"]}'
                payload = ""
            self.proposal = Proposal(uuid4().hex, target, before, after, payload, self.clock() + APPROVAL_TTL)
            self.status = "Review the proposed edit."
            return self.proposal

    def respond(self, proposal_id, approve):
        with self.lock:
            self.expire()
            proposal = self.proposal
            if not self.active or not proposal or proposal.id != proposal_id:
                raise ValueError("This proposal is no longer active.")
            self.proposal = None
            if not approve:
                self.status = "Declined."
                return
            self.require_bridge(proposal.target.kind)
            self.command = dict(id=proposal.id, kind=proposal.target.kind, capture=proposal.target.capture,
                                replacement=proposal.payload, claimed=False, expires=self.clock() + COMMAND_TTL)
            self.targets.pop(proposal.target.kind, None)
            self.status = "Approved. Waiting for the editor."

    def poll(self, kind, capture):
        with self.lock:
            self.expire()
            self.require_bridge(kind)
            command = self.command
            if command and command["kind"] == kind and command["capture"] == capture and not command["claimed"]:
                command["claimed"] = True
                return {key: command[key] for key in ("id", "replacement")}
            target = self.targets.get(kind)
            alive = target is not None and target.capture == capture
            return {"waiting": alive}

    def finish(self, kind, capture, command_id, outcome):
        with self.lock:
            self.expire()
            if (self.command and self.command["kind"] == kind and self.command["capture"] == capture
                    and self.command["id"] == command_id and self.command["claimed"]):
                self.command = None
                self.status = {"applied": "Applied in the editor. Use Undo to revert.",
                               "stale": "Skipped. The editor target changed or became read-only.",
                               "failed": "The editor reported a failure. Check the target."}[outcome]
