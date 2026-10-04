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
from local_ia.tools import download as download_tool, write as write_tool


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

    def test_appended_chunks_can_grow_beyond_the_single_write_limit(self):
        path = Path(self.directory.name) / "large.txt"
        block = "x" * (file_commands.MAX_WRITE_BYTES // 2 + 1)
        file_commands.write_file(str(path), block)
        result = file_commands.append_file(str(path), block)

        self.assertGreater(result["size"], file_commands.MAX_WRITE_BYTES)
        self.assertEqual(result["appended_size"], len(block.encode("utf-8")))
        self.assertEqual(path.stat().st_size, len((block + block).encode("utf-8")))
        self.assertEqual(path.read_text(encoding="utf-8"), block + block)

    def test_append_rejects_paths_outside_allowed_root(self):
        with self.assertRaises(PermissionError):
            file_commands.append_file(str(Path(tempfile.gettempdir()) / "outside.txt"), "blocked")

    def test_append_rejects_an_oversized_block_without_changing_the_file(self):
        path = Path(self.directory.name) / "large.txt"
        file_commands.write_file(str(path), "original")

        with self.assertRaises(ValueError):
            file_commands.append_file(
                str(path), "x" * (file_commands.MAX_WRITE_BYTES + 1)
            )

        self.assertEqual(path.read_text(encoding="utf-8"), "original")

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

    def test_download_tool_creates_a_cache_artifact(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(
            download_tool, "CACHE_DIR", Path(directory)
        ), patch.object(download_tool, "GENERATED_FILES_DIR", Path(directory) / "generated"):
            artifact = download_tool.use("rapport", "résultat", "txt")
            cached_file = download_tool.resolve_cached_file(artifact["artifact_id"], "rapport.txt")
            persistent_file = download_tool.GENERATED_FILES_DIR / "rapport.txt"

            self.assertEqual(cached_file.read_text(encoding="utf-8"), "résultat")
            self.assertEqual(persistent_file.read_text(encoding="utf-8"), "résultat")
            self.assertEqual(artifact["size"], len("résultat".encode("utf-8")))

    def test_download_tool_rejects_a_path_as_filename(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(
            download_tool, "CACHE_DIR", Path(directory)
        ), patch.object(download_tool, "GENERATED_FILES_DIR", Path(directory) / "generated"), self.assertRaises(ValueError):
            download_tool.use("../outside.txt", "blocked")

    def test_download_tool_preserves_existing_generated_files(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(
            download_tool, "CACHE_DIR", Path(directory) / "cache"
        ), patch.object(download_tool, "GENERATED_FILES_DIR", Path(directory) / "generated"):
            first = download_tool.use("rapport.txt", "première version")
            second = download_tool.use("rapport.txt", "deuxième version")

            self.assertEqual(first["filename"], "rapport.txt")
            self.assertEqual(second["filename"], "rapport-2.txt")
            self.assertEqual((Path(directory) / "generated" / "rapport.txt").read_text(encoding="utf-8"), "première version")
            self.assertEqual((Path(directory) / "generated" / "rapport-2.txt").read_text(encoding="utf-8"), "deuxième version")


if __name__ == "__main__":
    unittest.main()