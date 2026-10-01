#!/usr/bin/env python3
"""Tests autonomes des fonctions pures du serveur web."""

from __future__ import annotations

import sys
import tempfile
import threading
import unittest
import base64
import http.client
import json
from concurrent.futures import ThreadPoolExecutor
from http.server import ThreadingHTTPServer
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
        self.assertEqual(chat["title"], "")
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
            {"memory", "context", "file", "write", "edit", "list", "search", "web", "launch", "open_page"},
        )
        self.assertNotIn("command", session["agent"].respond.call_args.kwargs["allowed_tools"])
        self.assertNotIn("system", session["agent"].respond.call_args.kwargs["allowed_tools"])

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

    def test_server_authenticates_remote_bind_with_constant_time_token_check(self):
        self.assertTrue(server.is_loopback_host("127.0.0.1"))
        self.assertFalse(server.is_loopback_host("0.0.0.0"))

        httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        httpd.auth_token = "a" * 32
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(httpd.server_close)
        self.addCleanup(httpd.shutdown)
        self.addCleanup(thread.join, 2)

        connection = http.client.HTTPConnection("127.0.0.1", httpd.server_port)
        self.addCleanup(connection.close)
        connection.request("GET", "/app.js")
        response = connection.getresponse()
        self.assertEqual(response.status, 401)
        response.read()

        credentials = base64.b64encode(b"kairo:" + b"a" * 32).decode("ascii")
        connection.request("GET", "/app.js", headers={"Authorization": f"Basic {credentials}"})
        response = connection.getresponse()
        self.assertEqual(response.status, 200)
        response.read()

    def test_remote_client_cannot_execute_direct_command(self):
        handler = object.__new__(server.Handler)
        with patch.object(server.Handler, "_is_local_client", return_value=False), \
             patch.object(server.command_commands, "execute_command") as execute:
            result = handler._execute_local_command("python -c pass", {})

        self.assertIsNone(result)
        execute.assert_not_called()

    def test_post_route_table_dispatches_chat_lifecycle_and_chat_message(self):
        chat = {"id": 77, "messages": []}
        httpd = server.KairoHTTPServer(("127.0.0.1", 0), server.Handler)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(httpd.server_close)
        self.addCleanup(httpd.shutdown)
        self.addCleanup(thread.join, 2)

        connection = http.client.HTTPConnection("127.0.0.1", httpd.server_port)
        self.addCleanup(connection.close)
        headers = {"Content-Type": "application/json"}
        with patch.object(server, "create_chat", return_value=chat) as create_chat, \
             patch.object(server, "chat_agent") as chat_agent, \
             patch.object(server, "close_chat_agent") as close_chat_agent:
            connection.request("POST", "/api/chats/new", body="{}", headers=headers)
            response = connection.getresponse()
            self.assertEqual(response.status, 200)
            self.assertEqual(json.loads(response.read())["chat"]["id"], 77)

            connection.request("POST", "/api/chats/77/close", body="{}", headers=headers)
            response = connection.getresponse()
            self.assertEqual(response.status, 200)
            self.assertTrue(json.loads(response.read())["ok"])

        create_chat.assert_called_once_with()
        chat_agent.assert_called_once_with(chat)
        close_chat_agent.assert_called_once_with("77")

        with patch.object(server, "get_chat", return_value=chat), \
             patch.object(server, "command_execution_config", return_value={}), \
             patch.object(server.program_commands, "execute_command", return_value=None), \
             patch.object(server.Handler, "_execute_local_command", return_value=None), \
             patch.object(server, "model_from_config", return_value="test-model"), \
             patch.object(server, "installed_models", return_value={"models": [{"name": "test-model"}]}), \
             patch.object(server.file_commands, "execute_command", return_value=None), \
             patch.object(server, "chat_agent", return_value=object()), \
             patch.object(server, "chat_with_model", return_value="Réponse de test"), \
             patch.object(server, "save_chat"):
            payload = json.dumps({"chat_id": 77, "message": "Bonjour"})
            connection.request("POST", "/api/chat", body=payload, headers=headers)
            response = connection.getresponse()
            self.assertEqual(response.status, 200)
            self.assertEqual(json.loads(response.read())["answer"], "Réponse de test")


if __name__ == "__main__":
    unittest.main()