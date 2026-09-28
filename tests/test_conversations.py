#!/usr/bin/env python3
"""Tests autonomes du stockage des conversations."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from local_ia.core import conversation


class ConversationTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.chat_dir = Path(self.directory.name) / "chats"
        self.chat_dir.mkdir()
        self.patch = patch.object(conversation, "CHAT_DIR", self.chat_dir)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.directory.cleanup()

    def test_create_save_load_and_list(self):
        chat = conversation.create_chat()
        conversation.add_chat_message(chat, "user", "Bonjour")
        loaded = conversation.load_chat(chat["id"])
        self.assertEqual(loaded["messages"][0]["content"], "Bonjour")
        self.assertEqual(len(conversation.list_chats()), 1)

    def test_load_chat_rejects_path_traversal_ids(self):
        outside = self.chat_dir.parent / "outside.json"
        outside.write_text('{"messages": []}', encoding="utf-8")
        self.assertIsNone(conversation.load_chat("../outside"))

    def test_load_chat_repairs_invalid_field_types(self):
        path = conversation.chat_path(7)
        path.write_text(
            '{"id":"invalid","summary":[],"messages":"not a list","files":{}}',
            encoding="utf-8",
        )
        chat = conversation.load_chat(7)
        self.assertEqual(chat["id"], 7)
        self.assertEqual(chat["summary"], "")
        self.assertEqual(chat["messages"], [])
        self.assertEqual(chat["files"], [])

    def test_history_is_limited_to_user_and_assistant(self):
        chat = conversation.create_chat()
        chat["messages"] = [
            {"role": "system", "content": "ignore"},
            {"role": "user", "content": "question"},
            {"role": "assistant", "content": "réponse"},
        ]
        history = conversation.get_chat_history(chat)
        self.assertEqual(history, [
            {"role": "user", "content": "question"},
            {"role": "assistant", "content": "réponse"},
        ])

    def test_zero_history_limit_returns_no_messages(self):
        chat = {"messages": [{"role": "user", "content": "secret"}]}
        self.assertEqual(conversation.get_chat_history(chat, limit=0), [])

    def test_history_ignores_malformed_entries(self):
        chat = {"messages": [None, "invalid", {"role": "user", "content": "ok"}]}
        self.assertEqual(
            conversation.get_chat_history(chat),
            [{"role": "user", "content": "ok"}],
        )

    def test_clear_chat(self):
        chat = conversation.create_chat()
        conversation.add_chat_message(chat, "user", "à effacer")
        chat["pending_tool"] = {"tool": "command", "arguments": {"argv": ["rm", "-rf", "important"]}}
        conversation.clear_chat(chat)
        cleared = conversation.load_chat(chat["id"])
        self.assertEqual(cleared["messages"], [])
        self.assertNotIn("pending_tool", cleared)

    def test_save_chat_supports_async_background_write(self):
        chat = conversation.create_chat()
        conversation.add_chat_message(chat, "user", "bonjour")
        conversation.save_chat(chat, async_mode=True)
        conversation.flush_writes()
        loaded = conversation.load_chat(chat["id"])
        self.assertEqual(loaded["messages"][-1]["content"], "bonjour")


if __name__ == "__main__":
    unittest.main()