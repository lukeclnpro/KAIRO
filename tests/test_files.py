#!/usr/bin/env python3
"""Tests autonomes du gestionnaire de fichiers."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import file_commands
from local_ia.tools import write as write_tool


class FileCommandsTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        file_commands.set_access_roots([self.directory.name])

    def tearDown(self):
        file_commands.set_access_roots([ROOT])
        self.directory.cleanup()

    def test_write_and_read_text_file(self):
        path = str(Path(self.directory.name) / "note.txt")
        result = file_commands.write_file(path, "bonjour")
        loaded = file_commands.read_file(path)
        self.assertEqual(result["size"], len("bonjour".encode()))
        self.assertEqual(loaded["content"], "bonjour")
        self.assertEqual(loaded["kind"], "text")

    def test_utf8_bom_is_removed_from_decoded_text(self):
        path = Path(self.directory.name) / "bom.txt"
        path.write_bytes(b"\xef\xbb\xbftexte\n")
        self.assertEqual(file_commands.read_file(str(path))["content"], "texte\n")

    def test_oversized_text_is_rejected_before_reading_contents(self):
        path = Path(self.directory.name) / "large.txt"
        with path.open("wb") as output:
            output.truncate(file_commands.MAX_READ_BYTES + 1)
        with patch.object(Path, "read_bytes", side_effect=AssertionError("file contents were read")):
            with self.assertRaises(ValueError):
                file_commands.read_file(str(path))

    def test_rejects_path_outside_allowed_root(self):
        with self.assertRaises(PermissionError):
            file_commands.read_file(str(Path(tempfile.gettempdir()) / "outside.txt"))

    def test_parses_create_command(self):
        command = file_commands.parse_command('/fichier create "demo.md"\ncontenu')
        self.assertEqual(command["action"], "create")
        self.assertEqual(command["path"], "demo.md")

    def test_write_tool_adds_missing_extension(self):
        with patch("local_ia.tools.write.write_file", return_value={}) as write_file:
            write_tool.use("/home/luke/Telechargements/mon_dossier", "12345", "txt")
        written_path = write_file.call_args.args[0]
        self.assertTrue(written_path.endswith("mon_dossier.txt"))


if __name__ == "__main__":
    unittest.main()