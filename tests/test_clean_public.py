#!/usr/bin/env python3
"""Tests du nettoyeur autonome de préparation à la publication."""

from __future__ import annotations

import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import clean_public


class CleanPublicTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.accounts_dir = tempfile.TemporaryDirectory()
        self.accounts_file = Path(self.accounts_dir.name) / "accounts.json"
        self.accounts_file.write_text('{"Alice": {}}', encoding="utf-8")
        (self.root / "setup.py").write_text("", encoding="utf-8")
        (self.root / "chats").mkdir()
        (self.root / "chats" / "12.json").write_text("{}", encoding="utf-8")
        (self.root / "chats" / "keep.txt").write_text("keep", encoding="utf-8")
        (self.root / "src" / "__pycache__").mkdir(parents=True)
        (self.root / "src" / "__pycache__" / "module.pyc").write_bytes(b"cache")
        (self.root / "src" / "loose.pyo").write_bytes(b"cache")
        (self.root / ".venv" / "bin").mkdir(parents=True)
        (self.root / ".venv" / "bin" / "python").write_text("", encoding="utf-8")
        (self.root / ".git" / "__pycache__").mkdir(parents=True)
        (self.root / ".git" / "__pycache__" / "keep.pyc").write_bytes(b"keep")

    def tearDown(self):
        self.temp_dir.cleanup()
        self.accounts_dir.cleanup()

    def test_dry_run_lists_targets_without_deleting(self):
        output = io.StringIO()
        with patch.dict("os.environ", {"LOCAL_IA_ACCOUNTS_FILE": str(self.accounts_file)}):
            with contextlib.redirect_stdout(output):
                result = clean_public.main(["--root", str(self.root)])

        self.assertEqual(result, 0)
        self.assertIn("chats/12.json", output.getvalue())
        self.assertIn(str(self.accounts_file), output.getvalue())
        self.assertTrue((self.root / "chats" / "12.json").exists())
        self.assertTrue(self.accounts_file.exists())
        self.assertTrue((self.root / ".venv").exists())

    def test_apply_removes_targets_and_preserves_unrelated_files(self):
        with patch.dict("os.environ", {"LOCAL_IA_ACCOUNTS_FILE": str(self.accounts_file)}):
            result = clean_public.main(["--root", str(self.root), "--apply", "--yes"])

        self.assertEqual(result, 0)
        self.assertFalse((self.root / "chats" / "12.json").exists())
        self.assertFalse((self.root / "src" / "__pycache__").exists())
        self.assertFalse((self.root / "src" / "loose.pyo").exists())
        self.assertFalse((self.root / ".venv").exists())
        self.assertFalse(self.accounts_file.exists())
        self.assertTrue((self.root / "setup.py").exists())
        self.assertTrue((self.root / "chats" / "keep.txt").exists())
        self.assertTrue((self.root / ".git" / "__pycache__" / "keep.pyc").exists())


if __name__ == "__main__":
    unittest.main()