import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from local_ia import start_menu


class StartMenuShortcutTest(unittest.TestCase):
    def test_shortcut_is_created_once_for_current_user(self):
        with tempfile.TemporaryDirectory() as directory, \
               patch.object(start_menu, "_is_windows", return_value=True), \
             patch.dict(os.environ, {"APPDATA": directory}), \
             patch.object(start_menu.shutil, "which", return_value="powershell.exe"), \
             patch.object(start_menu.subprocess, "run") as run:
            project_dir = Path(directory) / "KAIRO"
            project_dir.mkdir()
            shortcut = start_menu.create_start_menu_shortcut(project_dir)

        self.assertEqual(
            shortcut,
            Path(directory) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "KAIRO.lnk",
        )
        command = run.call_args.args[0]
        environment = run.call_args.kwargs["env"]
        self.assertEqual(environment["KAIRO_SHORTCUT_TARGET"], str(Path(os.path.realpath(os.sys.executable))))
        self.assertEqual(environment["KAIRO_SHORTCUT_WORKDIR"], str(project_dir.resolve()))
        self.assertEqual(environment["KAIRO_SHORTCUT_ARGUMENTS"], f'"{project_dir.resolve() / "main.py"}" gui')
        self.assertEqual(command[0], "powershell.exe")
        self.assertIn("-EncodedCommand", command)

    def test_existing_shortcut_is_not_replaced(self):
        with tempfile.TemporaryDirectory() as directory:
            shortcut = Path(directory) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "KAIRO.lnk"
            shortcut.parent.mkdir(parents=True)
            shortcut.write_bytes(b"user-customized shortcut")
            with patch.object(start_menu, "_is_windows", return_value=True), \
                 patch.dict(os.environ, {"APPDATA": directory}), \
                 patch.object(start_menu.shutil, "which", return_value="powershell.exe"), \
                 patch.object(start_menu.subprocess, "run") as run:
                self.assertEqual(start_menu.create_start_menu_shortcut(), shortcut)
                self.assertEqual(shortcut.read_bytes(), b"user-customized shortcut")

        run.assert_not_called()

    def test_non_windows_system_does_not_create_a_shortcut(self):
        with patch.object(start_menu, "_is_windows", return_value=False), \
             patch.object(start_menu.subprocess, "run") as run:
            self.assertIsNone(start_menu.create_start_menu_shortcut())

        run.assert_not_called()


if __name__ == "__main__":
    unittest.main()