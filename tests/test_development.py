from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from local_ia.core import code_projects
from local_ia.tools import development


class DevelopmentToolTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name) / "projects"
        self.root.mkdir()
        self.root_patch = patch.object(code_projects, "get_projects_root", return_value=self.root)
        self.root_patch.start()
        self.project = code_projects.create_or_open_project("demo")
        self.chat = {"code_project_path": str(self.project)}

    def tearDown(self):
        self.root_patch.stop()
        self.directory.cleanup()

    def test_task_lifecycle_persists_project_tasks(self):
        created = development.use({"action": "add_task", "title": "Ajouter des tests"}, self.chat)
        self.assertEqual(created["task"]["status"], "todo")

        updated = development.use({
            "action": "update_task",
            "id": created["task"]["id"],
            "status": "in_progress",
        }, self.chat)
        self.assertEqual(updated["task"]["status"], "in_progress")
        self.assertEqual(development.use({"action": "list_tasks"}, self.chat)["tasks"], [updated["task"]])

        development.use({"action": "delete_task", "id": created["task"]["id"]}, self.chat)
        self.assertEqual(development.use({"action": "list_tasks"}, self.chat)["tasks"], [])

    def test_python_analysis_reports_syntax_without_executing_source(self):
        source = self.project / "broken.py"
        source.write_text("raise RuntimeError('must not run'\n", encoding="utf-8")

        result = development.use({"action": "analyze_python", "path": "broken.py"}, self.chat)

        self.assertFalse(result["valid_syntax"])
        self.assertEqual(result["diagnostics"][0]["tool"], "python-parser")

    def test_backup_restore_requires_confirmation_and_recovers_content(self):
        source = self.project / "app.py"
        source.write_text("print('before')\n", encoding="utf-8")
        result = development.use({"action": "backup_file", "path": "app.py"}, self.chat)
        source.write_text("print('after')\n", encoding="utf-8")

        restore = {"action": "restore_file", "path": "app.py", "backup": result["backup"]}
        self.assertTrue(development.use(restore, self.chat)["confirmation_required"])
        restore["confirmed"] = True
        self.assertTrue(development.use(restore, self.chat)["restored"])
        self.assertEqual(source.read_text(encoding="utf-8"), "print('before')\n")

    def test_git_reads_are_project_scoped_and_branch_creation_requires_confirmation(self):
        subprocess.run(["git", "init", str(self.project)], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(self.project), "config", "user.name", "Test User"], check=True)
        subprocess.run(["git", "-C", str(self.project), "config", "user.email", "test@example.invalid"], check=True)
        tracked = self.project / "README.md"
        tracked.write_text("hello\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(self.project), "add", "README.md"], check=True)
        subprocess.run(["git", "-C", str(self.project), "commit", "-m", "initial"], check=True, capture_output=True)

        status = development.use({"action": "git_status"}, self.chat)
        self.assertIn("##", status["output"])
        request = {"action": "git_create_branch", "name": "feature/stage-three"}
        self.assertTrue(development.use(request, self.chat)["confirmation_required"])
        request["confirmed"] = True
        self.assertTrue(development.use(request, self.chat)["created"])


if __name__ == "__main__":
    unittest.main()