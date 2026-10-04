from __future__ import annotations

import csv
import importlib.util
import sqlite3
import tempfile
import unittest
import zipfile
from pathlib import Path

import file_commands
from local_ia.core.tool_manager import ToolManager
from local_ia.tools import documents


class DocumentToolTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name).resolve()
        file_commands.set_access_roots([self.root])

    def tearDown(self):
        file_commands.set_access_roots([Path(__file__).resolve().parents[1]])
        self.directory.cleanup()

    def test_csv_analysis_and_sort_write_a_new_table(self):
        source = self.root / "scores.csv"
        source.write_text("name,score\nAda,10\nLin,7\n", encoding="utf-8")

        summary = documents.use({"action": "analyze_table", "path": str(source)})
        result = documents.use({
            "action": "transform_table",
            "path": str(source),
            "destination": str(self.root / "sorted.csv"),
            "operation": "sort",
            "column": "score",
        })

        self.assertEqual(summary["row_count"], 2)
        self.assertEqual(summary["columns"], ["name", "score"])
        with Path(result["path"]).open(encoding="utf-8", newline="") as source_file:
            rows = list(csv.DictReader(source_file))
        self.assertEqual([row["name"] for row in rows], ["Lin", "Ada"])

    def test_sqlite_tool_is_read_only(self):
        database = self.root / "data.sqlite"
        connection = sqlite3.connect(database)
        connection.execute("CREATE TABLE items (name TEXT)")
        connection.execute("INSERT INTO items VALUES ('keep')")
        connection.commit()
        connection.close()

        result = documents.use({"action": "sqlite_query", "path": str(database), "query": "SELECT name FROM items"})
        self.assertEqual(result["rows"], [{"name": "keep"}])
        with self.assertRaises(ValueError):
            documents.use({"action": "sqlite_query", "path": str(database), "query": "DELETE FROM items"})

    def test_archive_extraction_requires_confirmation_and_stays_in_root(self):
        archive_path = self.root / "safe.zip"
        with zipfile.ZipFile(archive_path, "w") as archive:
            archive.writestr("folder/note.txt", "safe")

        request = {"action": "extract_archive", "path": str(archive_path), "destination": str(self.root / "out")}
        self.assertTrue(documents.use(request)["confirmation_required"])
        request["confirmed"] = True
        documents.use(request)
        self.assertEqual((self.root / "out" / "folder" / "note.txt").read_text(encoding="utf-8"), "safe")

    def test_archive_extraction_rejects_path_traversal(self):
        archive_path = self.root / "unsafe.zip"
        with zipfile.ZipFile(archive_path, "w") as archive:
            archive.writestr("../../outside.txt", "unsafe")

        with self.assertRaises(ValueError):
            documents.use({
                "action": "extract_archive",
                "path": str(archive_path),
                "destination": str(self.root / "out"),
                "confirmed": True,
            })
        self.assertFalse((self.root.parent / "outside.txt").exists())

    def test_chart_is_written_as_svg(self):
        result = documents.use({
            "action": "create_chart",
            "path": str(self.root / "chart.svg"),
            "title": "Scores",
            "labels": ["Ada", "Lin"],
            "values": [10, 7],
        })

        chart = Path(result["path"]).read_text(encoding="utf-8")
        self.assertIn("<svg", chart)
        self.assertIn("Scores", chart)

    def test_create_and_convert_text_documents_do_not_overwrite(self):
        created = documents.use({
            "action": "create_document",
            "path": str(self.root / "note"),
            "format": "md",
            "content": "# Note\n",
        })
        self.assertEqual(Path(created["path"]).read_text(encoding="utf-8"), "# Note\n")

        converted = documents.use({
            "action": "convert_document",
            "source": created["path"],
            "destination": str(self.root / "note-copy.txt"),
        })
        self.assertEqual(Path(converted["path"]).read_text(encoding="utf-8"), "# Note\n")
        with self.assertRaises(FileExistsError):
            documents.use({
                "action": "create_document",
                "path": created["path"],
                "content": "remplacement",
            })

    def test_office_and_pdf_document_creation_and_reading(self):
        packages = ("docx", "pypdf", "reportlab", "pptx", "openpyxl")
        if not all(importlib.util.find_spec(package) for package in packages):
            self.skipTest("Les dépendances PDF/Office ne sont pas visibles dans cet interpréteur.")
        word = documents.use({
            "action": "create_document",
            "path": str(self.root / "word.docx"),
            "format": "docx",
            "content": "Bonjour depuis DOCX",
        })
        self.assertIn("Bonjour depuis DOCX", documents.use({"action": "read_document", "path": word["path"]})["content"])

        pdf = documents.use({
            "action": "create_document",
            "path": str(self.root / "report.pdf"),
            "format": "pdf",
            "content": "PDF report content",
        })
        self.assertIn("PDF report content", documents.use({"action": "read_document", "path": pdf["path"]})["content"])

        presentation = documents.use({
            "action": "create_document",
            "path": str(self.root / "deck.pptx"),
            "format": "pptx",
            "content": "Title\nSecond slide",
        })
        self.assertIn("Title", documents.use({"action": "read_document", "path": presentation["path"]})["content"])

        workbook = documents.use({
            "action": "create_document",
            "path": str(self.root / "table.xlsx"),
            "format": "xlsx",
            "rows": [{"name": "Ada", "score": 10}],
        })
        summary = documents.use({"action": "analyze_table", "path": workbook["path"]})
        self.assertEqual(summary["sample"][0]["name"], "Ada")

    def test_tool_manager_executes_document_action_with_path_scope(self):
        result = ToolManager.execute(
            {
                "tool": "document",
                "arguments": {
                    "action": "create_document",
                    "path": str(self.root / "inside.txt"),
                    "format": "txt",
                    "content": "dans le projet",
                },
            },
            {},
            None,
            allowed_tools={"document"},
        )

        self.assertEqual(Path(result["path"]).read_text(encoding="utf-8"), "dans le projet")

    def test_archive_creation_requires_confirmation(self):
        source = self.root / "source.txt"
        source.write_text("archive me", encoding="utf-8")
        request = {
            "action": "create_archive",
            "destination": str(self.root / "bundle.zip"),
            "paths": [str(source)],
        }

        self.assertTrue(documents.use(request)["confirmation_required"])
        request["confirmed"] = True
        result = documents.use(request)
        self.assertTrue(Path(result["path"]).is_file())

    def test_documents_cannot_escape_allowed_roots(self):
        with self.assertRaises(PermissionError):
            documents.use({"action": "create_document", "path": str(self.root.parent / "outside.txt"), "content": "no"})


if __name__ == "__main__":
    unittest.main()