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


if __name__ == "__main__":
    unittest.main()