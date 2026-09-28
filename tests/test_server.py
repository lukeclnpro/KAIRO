#!/usr/bin/env python3
"""Tests autonomes des fonctions pures du serveur web."""

from __future__ import annotations

import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import server


class ServerTest(unittest.TestCase):
    def test_extract_launch_tool_call(self):
        result = server.extract_tool_call(
            '<tool_call>{"name":"launch_application","arguments":{"name":"Calculator"}}</tool_call>'
        )
        self.assertEqual(result["name"], "launch_application")
        self.assertEqual(result["arguments"]["name"], "Calculator")

    def test_extract_command_tool_call(self):
        content = '<tool_call>{"name":"execute_command","arguments":{"argv":["echo","ok"]}}</tool_call>'
        result = server.extract_tool_call(content)
        self.assertEqual(result["name"], "execute_command")
        self.assertEqual(server.extract_command_tool(content), ["echo", "ok"])
        self.assertEqual(result["arguments"]["argv"], ["echo", "ok"])

    def test_rejects_invalid_tool_call(self):
        self.assertIsNone(server.extract_tool_call("<tool_call>{not json}</tool_call>"))

    def test_create_chat_uses_centralized_conversation_schema(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(server, "CHAT_DIR", Path(directory)):
            chat = server.create_chat()
        self.assertIn("summary_updated_at", chat)
        self.assertIn("messages", chat)

    def test_chat_agent_and_conversation_are_cached(self):
        chat_id = 987654321
        chat = {"id": chat_id, "topic": None, "messages": []}
        self.addCleanup(server.CHAT_AGENTS.pop, str(chat_id), None)
        with patch.object(server, "LocalAgent") as agent_class:
            agent_class.return_value.model = "cached-test-model"
            session = server.chat_agent(chat, "cached-test-model")
            cached_chat = server.get_chat(chat_id)
            cached_chat["messages"].append({"role": "user", "content": "Salut"})
            reused = server.chat_agent(cached_chat, "cached-test-model")
            self.assertIs(reused, session)
            self.assertIs(cached_chat, chat)
            self.assertEqual(cached_chat["messages"][0]["content"], "Salut")
            agent_class.assert_called_once_with(model="cached-test-model")
            session["agent"].prepare_chat.assert_called()
            server.close_chat_agent(chat_id)
            session["agent"].close.assert_called_once_with()
            self.assertNotIn(str(chat_id), server.CHAT_AGENTS)

    def test_chat_with_model_delegates_to_local_agent(self):
        chat = {"id": 17, "messages": [{"role": "user", "content": "lis app.py"}]}
        session = {"agent": Mock(), "lock": server.threading.RLock()}
        session["agent"].respond.return_value = "Réponse de l'agent"

        answer = server.chat_with_model(
            "test-model",
            chat,
            file_context="extrait du fichier",
            session=session,
        )

        self.assertEqual(answer, "Réponse de l'agent")
        history, message = session["agent"].respond.call_args.args
        self.assertEqual(history["messages"], [])
        self.assertEqual(message, "lis app.py\n\nextrait du fichier")
        self.assertEqual(
            session["agent"].respond.call_args.kwargs["allowed_tools"],
            {"memory", "context", "file", "write", "edit", "list", "search"},
        )

    def test_concurrent_new_chats_get_unique_ids(self):
        count = 12
        barrier = threading.Barrier(count)
        with tempfile.TemporaryDirectory() as directory, patch.object(server, "CHAT_DIR", Path(directory)):
            def create_chat():
                barrier.wait()
                return server.create_chat()["id"]

            with ThreadPoolExecutor(max_workers=count) as executor:
                chat_ids = list(executor.map(lambda _: create_chat(), range(count)))
        self.assertEqual(len(set(chat_ids)), count)

    def test_network_urls_contains_localhost(self):
        self.assertIn("http://127.0.0.1:8080", server.network_urls(8080))


if __name__ == "__main__":
    unittest.main()