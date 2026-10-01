#!/usr/bin/env python3
"""Tests autonomes du stockage des conversations."""

from __future__ import annotations

import sys
import json
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
        self.assertEqual(loaded["title"], "")
        self.assertEqual(len(conversation.list_chats()), 1)

    def test_title_uses_first_informative_message_and_stays_stable(self):
        chat = conversation.create_chat()
        conversation.add_chat_message(chat, "user", "Donne-moi plein d'infos sur macron")
        self.assertEqual(chat["title"], "Questions sur Macron")

        conversation.add_chat_message(chat, "assistant", "Voici les informations.")
        conversation.add_chat_message(chat, "user", "Quel âge a-t-il ?")
        self.assertEqual(chat["title"], "Questions sur Macron")

        conversation.add_chat_message(chat, "user", "Quelle est la météo à Metz aujourd'hui ?")
        self.assertEqual(chat["title"], "Questions sur Macron")

    def test_title_skips_greetings_and_cleans_request_openers(self):
        chat = conversation.create_chat()
        conversation.add_chat_message(chat, "user", "Bonjour !")
        self.assertEqual(chat["title"], "")

        conversation.add_chat_message(
            chat,
            "user",
            "Bonjour ! Peux-tu m'aider à réparer une fuite d'eau ?",
        )
        self.assertEqual(chat["title"], "Réparer une fuite d'eau")

    def test_derived_title_has_clean_french_capitalization(self):
        self.assertEqual(
            conversation.derive_chat_title("Quelle est la capitale de la France ?"),
            "Capitale de la France",
        )

    def test_manual_topic_is_not_replaced_by_generated_title(self):
        chat = conversation.create_chat()
        chat["topic"] = "Projet personnel"
        conversation.add_chat_message(chat, "user", "Parle-moi de Macron")
        self.assertEqual(chat["title"], "Questions sur Macron")
        self.assertEqual(chat["topic"], "Projet personnel")

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

    def test_weighted_history_decays_by_25_percent_without_changing_saved_messages(self):
        chat = {
            "messages": [
                {"role": "user", "content": f"message {index}"}
                for index in range(1, 6)
            ]
        }

        history = conversation.get_weighted_chat_history(chat)

        self.assertEqual(
            [message["content"].split("]", 1)[0] for message in history],
            [
                "[Importance: 31%",
                "[Importance: 42%",
                "[Importance: 56%",
                "[Importance: 75%",
                "[Importance: 100%",
            ],
        )
        self.assertEqual(chat["messages"][0]["content"], "message 1")

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
        self.assertEqual(cleared["title"], "")
        self.assertNotIn("pending_tool", cleared)

    def test_save_chat_supports_async_background_write(self):
        chat = conversation.create_chat()
        conversation.add_chat_message(chat, "user", "bonjour")
        conversation.save_chat(chat, async_mode=True)
        chat["messages"][-1]["content"] = "modifié après sauvegarde"
        conversation.flush_writes()
        loaded = conversation.load_chat(chat["id"])
        self.assertEqual(loaded["messages"][-1]["content"], "bonjour")

    def test_chat_files_are_written_as_compact_json(self):
        chat = conversation.create_chat()
        conversation.add_chat_message(chat, "user", "Bonjour")
        conversation.save_chat(chat, async_mode=False)

        saved_text = conversation.chat_path(chat["id"]).read_text(encoding="utf-8")

        self.assertNotIn("\n", saved_text)
        self.assertEqual(json.loads(saved_text)["messages"][0]["content"], "Bonjour")


if __name__ == "__main__":
    unittest.main()