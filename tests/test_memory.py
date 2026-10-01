#!/usr/bin/env python3
"""Tests autonomes de la mémoire SQLite."""

from __future__ import annotations

import sys
import json
import sqlite3
import tempfile
import unittest
import contextlib
import io
from urllib.error import HTTPError
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from local_ia.core.memory import (
    clear_memories,
    delete_memory,
    extract_memory_candidate,
    get_history,
    get_memories,
    init_database,
    list_memories,
    save_memory,
    save_message,
)
from local_ia.core import memory as memory_module
from local_ia.cli import interface


class MemoryTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.connection = init_database(Path(self.directory.name) / "memory.db")

    def tearDown(self):
        self.connection.close()
        self.directory.cleanup()

    def test_save_and_get_memory(self):
        save_memory(self.connection, "L'utilisateur préfère le français.")
        self.assertEqual(get_memories(self.connection), ["L'utilisateur préfère le français."])

    def test_memories_can_be_listed_and_deleted_by_id(self):
        save_memory(self.connection, "Premier souvenir.", async_mode=False)
        save_memory(self.connection, "Deuxième souvenir.", async_mode=False)
        memories = list_memories(self.connection)

        self.assertEqual([item["content"] for item in memories], ["Deuxième souvenir.", "Premier souvenir."])
        self.assertTrue(delete_memory(self.connection, memories[0]["id"]))
        self.assertFalse(delete_memory(self.connection, memories[0]["id"]))
        self.assertEqual(get_memories(self.connection), ["Premier souvenir."])

    def test_clearing_memories_flushes_pending_writes(self):
        save_memory(self.connection, "Souvenir en attente.", async_mode=True)
        save_memory(self.connection, "Autre souvenir.", async_mode=False)

        self.assertEqual(clear_memories(self.connection), 2)
        self.assertEqual(get_memories(self.connection), [])

    def test_cli_memory_commands_support_selective_and_confirmed_deletion(self):
        class FakeAgent:
            reload_count = 0

            def reload_memories(self):
                self.reload_count += 1

        agent = FakeAgent()
        save_memory(self.connection, "L'utilisateur préfère Python.", async_mode=False)
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertTrue(interface._handle_memory_command(self.connection, agent, "/memory"))
        self.assertIn("#1 - L'utilisateur préfère Python.", output.getvalue())

        with patch.object(interface.ui, "print_ok"):
            self.assertTrue(interface._handle_memory_command(self.connection, agent, "/forget 1"))
        self.assertEqual(list_memories(self.connection), [])
        self.assertEqual(agent.reload_count, 1)

        save_memory(self.connection, "Souvenir à effacer.", async_mode=False)
        with contextlib.redirect_stdout(io.StringIO()), patch.object(interface.ui, "print_ok"):
            interface._handle_memory_command(
                self.connection, agent, "/forget-all", input_fn=lambda prompt: "n"
            )
        self.assertEqual(len(list_memories(self.connection)), 1)

        with patch.object(interface.ui, "print_ok"):
            interface._handle_memory_command(
                self.connection, agent, "/forget-all", input_fn=lambda prompt: "oui"
            )
        self.assertEqual(list_memories(self.connection), [])
        self.assertEqual(agent.reload_count, 2)

    def test_save_and_get_conversation_history(self):
        save_message(self.connection, "chat-1", "user", "Bonjour")
        save_message(self.connection, "chat-1", "assistant", "Salut")
        self.assertEqual(get_history(self.connection, "chat-1"), [
            {"role": "user", "content": "Bonjour"},
            {"role": "assistant", "content": "Salut"},
        ])

    def test_conversations_are_isolated(self):
        save_message(self.connection, "chat-1", "user", "un")
        save_message(self.connection, "chat-2", "user", "deux")
        self.assertEqual(get_history(self.connection, "chat-1")[0]["content"], "un")

    def test_negative_limits_return_no_memory_or_history(self):
        save_memory(self.connection, "souvenir")
        save_message(self.connection, "chat-1", "user", "message")
        self.assertEqual(get_memories(self.connection, limit=-1), [])
        self.assertEqual(get_history(self.connection, "chat-1", limit=-1), [])

    def test_get_memories_can_sort_by_relevance_to_query(self):
        save_memory(self.connection, "L'utilisateur travaille sur Python et Ollama.")
        save_memory(self.connection, "L'utilisateur aime le café.")
        save_memory(self.connection, "Le projet utilise React.")
        memories = get_memories(self.connection, query="Python Ollama", limit=2)
        self.assertEqual(memories[0], "L'utilisateur travaille sur Python et Ollama.")
        self.assertIn("L'utilisateur aime le café.", memories)

    def test_embedding_http_errors_are_closed_before_lexical_fallback(self):
        error = HTTPError("https://ollama.test/api/embed", 404, "Not Found", {}, io.BytesIO(b"missing"))
        text = "fallback lexical vérifiable"

        with patch.object(memory_module, "load_config", return_value={"ollama": {"timeout": 5}}), \
             patch.object(memory_module, "ollama_base_url", return_value="https://ollama.test"), \
             patch.object(memory_module, "urlopen", side_effect=error):
            result = memory_module.compute_embedding(text, model="test-error-close")

        self.assertTrue(error.fp.closed)
        self.assertEqual(result, memory_module._lexical_embedding(text))

    def test_get_memories_keeps_legacy_order_without_query(self):
        save_memory(self.connection, "premier")
        save_memory(self.connection, "second")
        self.assertEqual(get_memories(self.connection), ["second", "premier"])

    def test_get_memories_uses_embedding_similarity_when_query_is_present(self):
        query = "Quel moteur de discussion est installé sur mon PC ?"
        ollama_memory = "Le projet utilise un modèle local de chat dans Ollama."
        python_memory = "L'utilisateur aime les scripts Python."
        with patch("local_ia.core.memory.compute_embedding") as mock_compute:
            vectors = {
                query: [1.0, 0.0, 0.0],
                ollama_memory: [1.0, 0.0, 0.1],
                python_memory: [0.0, 1.0, 0.0],
            }

            def fake_embedding(text, model=None, timeout=None):
                return vectors[str(text)]

            mock_compute.side_effect = fake_embedding
            save_memory(self.connection, ollama_memory, async_mode=False)
            save_memory(self.connection, python_memory, async_mode=False)
            mock_compute.reset_mock()

            memories = get_memories(
                self.connection,
                query=query,
                limit=2,
            )

            self.assertEqual(mock_compute.call_count, 1)
            self.assertEqual(mock_compute.call_args.args[0], query)
            self.assertEqual(memories[0], ollama_memory)

    def test_existing_memory_schema_is_migrated_and_legacy_embeddings_are_backfilled(self):
        database_path = Path(self.directory.name) / "legacy.db"
        legacy_connection = sqlite3.connect(database_path)
        legacy_connection.execute(
            "CREATE TABLE memories (id INTEGER PRIMARY KEY AUTOINCREMENT, content TEXT NOT NULL, created_at TEXT NOT NULL)"
        )
        legacy_connection.execute(
            "INSERT INTO memories (content, created_at) VALUES (?, ?)",
            ("Souvenir hérité sur Python", "2026-01-01T00:00:00"),
        )
        legacy_connection.commit()
        legacy_connection.close()

        migrated = init_database(database_path)
        self.addCleanup(migrated.close)
        calls = []

        def fake_embedding(text, model=None, timeout=None):
            calls.append(text)
            return [1.0, 0.0]

        with patch.object(memory_module, "compute_embedding", side_effect=fake_embedding):
            memories = get_memories(migrated, query="Python", limit=1)
            self.assertEqual(memories, ["Souvenir hérité sur Python"])
            self.assertEqual(calls, ["Python", "Souvenir hérité sur Python"])
            self.assertEqual(get_memories(migrated, query="Python", limit=1), memories)
            self.assertEqual(calls, ["Python", "Souvenir hérité sur Python", "Python"])

        columns = {row[1] for row in migrated.execute("PRAGMA table_info(memories)")}
        self.assertIn("embedding", columns)
        self.assertIn("embedding_model", columns)
        stored_embedding = migrated.execute("SELECT embedding FROM memories").fetchone()[0]
        self.assertEqual(json.loads(stored_embedding), [1.0, 0.0])

    def test_memory_detector_catches_persistent_preferences_and_deduplicates(self):
        candidate = extract_memory_candidate("Je préfère Python à JavaScript pour les scripts de bureau.")
        self.assertIsNotNone(candidate)
        self.assertIn("Python", candidate["memory"])
        self.assertEqual(candidate["category"], "preference")

        save_memory(self.connection, "J'utilise Python pour les scripts de bureau.")
        self.assertFalse(extract_memory_candidate("J'utilise le langage Python pour les scripts de bureau.") is None)


if __name__ == "__main__":
    unittest.main()