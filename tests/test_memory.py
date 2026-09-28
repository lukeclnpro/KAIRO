#!/usr/bin/env python3
"""Tests autonomes de la mémoire SQLite."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from local_ia.core.memory import (
    extract_memory_candidate,
    get_history,
    get_memories,
    init_database,
    save_memory,
    save_message,
)


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

    def test_get_memories_keeps_legacy_order_without_query(self):
        save_memory(self.connection, "premier")
        save_memory(self.connection, "second")
        self.assertEqual(get_memories(self.connection), ["second", "premier"])

    def test_get_memories_uses_embedding_similarity_when_query_is_present(self):
        save_memory(self.connection, "Le projet utilise un modèle local de chat dans Ollama.")
        save_memory(self.connection, "L'utilisateur aime les scripts Python.")

        with patch("local_ia.core.memory.compute_embedding") as mock_compute:
            vectors = {
                "Quel moteur de discussion est installé sur mon PC ?": [1.0, 0.0, 0.0],
                "Le projet utilise un modèle local de chat dans Ollama.": [1.0, 0.0, 0.1],
                "L'utilisateur aime les scripts Python.": [0.0, 1.0, 0.0],
            }

            def fake_embedding(text, model=None, timeout=None):
                return vectors[str(text)]

            mock_compute.side_effect = fake_embedding

            memories = get_memories(
                self.connection,
                query="Quel moteur de discussion est installé sur mon PC ?",
                limit=2,
            )

            self.assertTrue(mock_compute.called)
            self.assertIn("Le projet utilise un modèle local de chat dans Ollama.", memories)

    def test_memory_detector_catches_persistent_preferences_and_deduplicates(self):
        candidate = extract_memory_candidate("Je préfère Python à JavaScript pour les scripts de bureau.")
        self.assertIsNotNone(candidate)
        self.assertIn("Python", candidate["memory"])
        self.assertEqual(candidate["category"], "preference")

        save_memory(self.connection, "J'utilise Python pour les scripts de bureau.")
        self.assertFalse(extract_memory_candidate("J'utilise le langage Python pour les scripts de bureau.") is None)


if __name__ == "__main__":
    unittest.main()