import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from local_ia.core import code_projects
from local_ia.core.tool_manager import ToolManager


class CodeProjectsTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.projects_root = Path(self.directory.name) / "Documents" / "ia_local" / "code"
        self.patch = patch.object(code_projects, "get_projects_root", return_value=self.projects_root)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.directory.cleanup()

    def test_create_and_resume_project(self):
        created = code_projects.create_or_open_project("Mon projet")
        resumed = code_projects.create_or_open_project("Mon projet")

        self.assertEqual(created, resumed)
        self.assertTrue(created.is_dir())
        self.assertEqual(code_projects.list_projects(), [created])

    def test_rejects_path_traversal_and_invalid_names(self):
        for name in ("../outside", "..", "bad/name", "CON"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                code_projects.create_or_open_project(name)

    def test_project_paths_cannot_escape_through_relative_or_absolute_paths(self):
        project = code_projects.create_or_open_project("demo")
        self.assertEqual(code_projects.resolve_project_path(project, "src/main.py"), project / "src/main.py")

        with self.assertRaises(PermissionError):
            code_projects.resolve_project_path(project, "../../outside.txt")
        with self.assertRaises(PermissionError):
            code_projects.resolve_project_path(project, Path(self.directory.name) / "outside.txt")

    def test_project_symlink_cannot_point_outside_the_projects_root(self):
        project = code_projects.create_or_open_project("demo")
        outside = Path(self.directory.name) / "outside"
        outside.mkdir()
        (project / "external").symlink_to(outside, target_is_directory=True)

        with self.assertRaises(PermissionError):
            code_projects.resolve_project_path(project, "external/secret.py")

    def test_install_code_examples_preserves_existing_project_files(self):
        project = code_projects.create_or_open_project("examples-project")
        source = Path(code_projects.CODE_EXAMPLES_SOURCE)
        self.assertTrue(source.is_dir())
        sample_source = source / "text.py"
        self.assertTrue(sample_source.is_file())
        sample_destination = project / "exemple" / "text.py"
        sample_destination.parent.mkdir(parents=True)
        sample_destination.write_text("# user changes\n", encoding="utf-8")

        examples = code_projects.install_code_examples(project)

        self.assertEqual(examples, project / "exemple")
        self.assertEqual(sample_destination.read_text(encoding="utf-8"), "# user changes\n")
        self.assertTrue((examples / "README.md").is_file())
        self.assertTrue((examples / "collection_helpers.py").is_file())
        self.assertTrue((examples / "url_helpers.py").is_file())
        self.assertTrue((examples / "javascript.js").is_file())

    def test_tool_manager_writes_only_inside_the_active_project(self):
        project = code_projects.create_or_open_project("safe-project")
        chat = {"code_project_path": str(project)}
        created = ToolManager.execute(
            {"tool": "write", "arguments": {"path": "src/main.py", "content": "print('ok')"}},
            chat,
            None,
            allowed_tools={"write"},
        )

        self.assertEqual((project / "src" / "main.py").read_text(encoding="utf-8"), "print('ok')")
        self.assertEqual(created["path"], str(project / "src" / "main.py"))
        with self.assertRaises(PermissionError):
            ToolManager.execute(
                {"tool": "write", "arguments": {"path": "../../outside.py", "content": "bad"}},
                chat,
                None,
                allowed_tools={"write"},
            )

    def test_tool_manager_pins_commands_to_the_active_project(self):
        project = code_projects.create_or_open_project("command-project")
        chat = {"code_project_path": str(project)}
        with patch("local_ia.core.tool_manager.command.use", return_value="ok") as run_command:
            ToolManager.execute(
                {
                    "tool": "command",
                    "arguments": {"argv": ["pytest"], "cwd": str(self.projects_root.parent)},
                },
                chat,
                None,
                allowed_tools={"command"},
            )

        self.assertEqual(run_command.call_args.kwargs["cwd"], str(project))

    def test_main_menu_choice_opens_code_projects_directory(self):
        import main

        with patch.object(main.ui, "full_menu"), \
             patch.object(main.ui, "prompt", side_effect=("9", "0")), \
             patch.object(main.ui, "clear_screen"), \
             patch.object(main.ui, "print_ok"), \
             patch.object(main.ui, "print_info"), \
             patch.object(main, "pause"), \
             patch.object(code_projects, "open_code_projects", return_value=self.projects_root) as open_projects:
            main.menu()

        open_projects.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()