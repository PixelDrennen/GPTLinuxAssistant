from tempfile import TemporaryDirectory
import unittest

from assistant_app.chats import ChatStore


class ChatsTests(unittest.TestCase):
    def test_inactive_chat_is_compressed_and_restored_with_context(self):
        with TemporaryDirectory() as root:
            store = ChatStore(root)
            first = store.chat.id
            text = "The dialogue connection is missing. " * 100
            store.chat.title = "Prefab notes"
            store.chat.entries.append(["10:30:00", "Assistant", text])
            store.chat.turns.append(["general", "What needs fixing?", text])
            store.select()
            row = store.db.execute("SELECT archived, length(payload) FROM chats WHERE id = ?", (first,)).fetchone()
            self.assertEqual(1, row[0])
            self.assertLess(row[1], len(text))
            store.select(first)
            self.assertEqual(text, store.chat.turns[-1][2])
            self.assertEqual(text, store.chat.entries[-1][2])
            self.assertEqual(1, sum(row[0] == 0 for row in store.db.execute("SELECT archived FROM chats")))
            store.close()
            reopened = ChatStore(root)
            self.assertEqual(first, reopened.chat.id)
            self.assertEqual("Prefab notes", reopened.chat.title)
            reopened.close()
