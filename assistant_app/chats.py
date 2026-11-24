"""Local chat history. Only the selected chat has an uncompressed payload."""
from dataclasses import dataclass, field
from datetime import datetime
import json
import os
from pathlib import Path
import sqlite3
from uuid import uuid4
import zlib


@dataclass
class Chat:
    id: str
    title: str = "New chat"
    entries: list = field(default_factory=list)
    turns: list = field(default_factory=list)
    task_start: int = 0


class ChatStore:
    def __init__(self, directory):
        directory = Path(directory)
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.db = sqlite3.connect(directory / "chats.sqlite3")
        os.chmod(directory / "chats.sqlite3", 0o600)
        self.db.execute("PRAGMA auto_vacuum = FULL")
        self.db.execute("PRAGMA secure_delete = ON")
        self.db.execute("""CREATE TABLE IF NOT EXISTS chats
                        (id TEXT PRIMARY KEY, title TEXT, updated TEXT, archived INTEGER, payload BLOB)""")
        active = self.db.execute("SELECT id FROM chats WHERE archived = 0 ORDER BY updated DESC LIMIT 1").fetchone()
        self.chat = self.read(active[0]) if active else Chat(uuid4().hex)
        self.save()

    def read(self, chat_id):
        row = self.db.execute("SELECT title, archived, payload FROM chats WHERE id = ?", (chat_id,)).fetchone()
        if row is None:
            raise ValueError("This chat is no longer available.")
        title, archived, payload = row
        contents = json.loads(zlib.decompress(payload) if archived else payload)
        return Chat(chat_id, title, contents["entries"], contents["turns"], contents.get("task_start", 0))

    def index(self):
        return self.db.execute("SELECT id, title, updated FROM chats ORDER BY archived, updated DESC, rowid DESC").fetchall()

    def write(self, chat, archive):
        data = json.dumps({"entries": chat.entries, "turns": chat.turns, "task_start": chat.task_start}, ensure_ascii=False).encode()
        payload = zlib.compress(data, level=6) if archive else data
        self.db.execute("""INSERT INTO chats VALUES (?, ?, ?, ?, ?)
                        ON CONFLICT(id) DO UPDATE SET title=excluded.title,
                        updated=excluded.updated, archived=excluded.archived, payload=excluded.payload""",
                        (chat.id, chat.title, datetime.now().isoformat(timespec="seconds"), int(archive), payload))

    def save(self):
        with self.db:
            self.write(self.chat, False)

    def select(self, chat_id=None):
        if chat_id == self.chat.id:
            return
        selected = self.read(chat_id) if chat_id else Chat(uuid4().hex)
        with self.db:
            self.write(self.chat, True)
            self.write(selected, False)
        self.chat = selected

    def close(self):
        self.save()
        self.db.close()
