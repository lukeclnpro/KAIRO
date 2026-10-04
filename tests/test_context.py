#!/usr/bin/env python3
"""Tests autonomes du contexte permanent et du prompt système."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from local_ia.core.context import build_system_prompt, load_context
from local_ia.core.context_compiler import ContextCompiler


class ContextTest(unittest.TestCase):
    def test_load_context_merges_defaults(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "context.json"
            path.write_text(json.dumps({"langue": "anglais"}), encoding="utf-8")
            context = load_context(path)
        self.assertEqual(context["langue"], "anglais")
        self.assertIn("role", context)
        self.assertIn("instructions", context)

    def test_build_prompt_contains_context_and_memory(self):
        context = load_context()
        context["langue"] = "français"
        prompt = build_system_prompt(["Nom: Alex"], "tests", context)
        self.assertIn("français", prompt)
        self.assertIn("Nom: Alex", prompt)
        self.assertIn("tests", prompt)

    def test_invalid_context_uses_defaults(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "context.json"
            path.write_text("{invalide", encoding="utf-8")
            context = load_context(path)
        self.assertEqual(context["langue"], "français")

    def test_code_artifact_prompt_requires_a_complete_usable_program(self):
        prompt = ContextCompiler().compile(
            {"messages": []},
            load_context(),
            [],
            message="Crée un script Python qui permet de créer des fichiers texte",
            route={
                "mode": "code",
                "action": "code_artifact",
                "tools": ("write", "edit", "file"),
            },
            allow_tools={"write", "edit", "file"},
        )

        self.assertIn("implémentation complète, directement utilisable", prompt)
        self.assertIn("example.txt", prompt)
        self.assertIn("point d'entrée", prompt)
        self.assertIn("gestion des erreurs courantes", prompt)

    def test_relevant_course_is_added_without_loading_unrelated_courses(self):
        prompt = ContextCompiler().compile(
            {"messages": []},
            load_context(),
            [],
            message="Explique les bases de Python",
            route={"mode": "chat", "action": "chat", "tools": ()},
        )

        self.assertIn("PYTHON — FICHE DE RÉFÉRENCE", prompt)
        self.assertNotIn("RÉSEAUX — FICHE DE RÉFÉRENCE", prompt)

        prompt = ContextCompiler().compile(
            {"messages": []},
            load_context(),
            [],
            message="Explique les principes de Python",
            route={"mode": "chat", "action": "chat", "tools": ()},
        )
        self.assertNotIn("RÉSEAUX — FICHE DE RÉFÉRENCE", prompt)

    def test_generic_course_request_loads_the_course_corpus(self):
        prompt = ContextCompiler().compile(
            {"messages": []},
            load_context(),
            [],
            message="Montre-moi les cours disponibles",
            route={"mode": "chat", "action": "chat", "tools": ()},
        )

        self.assertIn("PYTHON — FICHE DE RÉFÉRENCE", prompt)
        self.assertIn("RÉSEAUX — FICHE DE RÉFÉRENCE", prompt)
        self.assertIn("GIT — FICHE DE RÉFÉRENCE", prompt)


if __name__ == "__main__":
    unittest.main()