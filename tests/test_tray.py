import tempfile
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from local_ia import desktop_tray


class DesktopTrayTest(unittest.TestCase):
    def test_autostart_entry_launches_tray_mode(self):
        with tempfile.TemporaryDirectory() as directory:
            autostart_file = Path(directory) / "autostart" / "local-ia-tray.desktop"
            with patch.object(desktop_tray, "AUTOSTART_FILE", autostart_file), \
                 patch.object(desktop_tray, "MAIN_SCRIPT", Path("/opt/local ia/main.py")), \
                 patch.object(desktop_tray.sys, "executable", "/opt/python/bin/python"):
                desktop_tray.install_autostart()

            contents = autostart_file.read_text(encoding="utf-8")
            self.assertIn('Exec="/opt/python/bin/python" "/opt/local ia/main.py" --tray', contents)
            self.assertIn("Terminal=false", contents)

    def test_click_launches_main_in_konsole(self):
        with patch.object(desktop_tray.shutil, "which", side_effect=lambda name: "/usr/bin/konsole" if name == "konsole" else None), \
             patch.object(desktop_tray.subprocess, "Popen") as popen, \
             patch.object(desktop_tray.sys, "executable", "/opt/python/bin/python"), \
             patch.object(desktop_tray, "MAIN_SCRIPT", Path("/opt/local_ia/main.py")):
            desktop_tray.launch_main()

        self.assertEqual(
            popen.call_args.args[0],
            ["/usr/bin/konsole", "--separate", "-e", "/opt/python/bin/python", "/opt/local_ia/main.py"],
        )

    def test_gui_launch_uses_main_cli_entrypoint_without_terminal(self):
        with patch.object(desktop_tray, "IS_WINDOWS", False), \
             patch.object(desktop_tray, "_tray_python_executable", return_value="/opt/python/bin/python"), \
             patch.object(desktop_tray, "MAIN_SCRIPT", Path("/opt/local_ia/main.py")), \
             patch.object(desktop_tray.subprocess, "Popen") as popen:
            desktop_tray.launch_gui()

        self.assertEqual(
            popen.call_args.args[0],
            ["/opt/python/bin/python", "/opt/local_ia/main.py", "--gui"],
        )
        self.assertIs(popen.call_args.kwargs["stdin"], subprocess.DEVNULL)
        self.assertIs(popen.call_args.kwargs["stdout"], subprocess.DEVNULL)

    def test_windows_autostart_uses_pythonw_registry_entry(self):
        winreg = MagicMock()
        winreg.HKEY_CURRENT_USER = object()
        winreg.REG_SZ = 1
        with patch.dict(sys.modules, {"winreg": winreg}), \
             patch.object(desktop_tray, "IS_WINDOWS", True), \
             patch.object(desktop_tray, "_tray_python_executable", return_value=r"C:\Python\pythonw.exe"), \
             patch.object(desktop_tray, "MAIN_SCRIPT", Path(r"C:\Local IA\main.py")):
            desktop_tray.install_autostart()

        key = winreg.CreateKey.return_value.__enter__.return_value
        winreg.SetValueEx.assert_called_once_with(
            key,
            "LOCAL_IA Tray",
            0,
            winreg.REG_SZ,
            subprocess.list2cmdline(
                (r"C:\Python\pythonw.exe", r"C:\Local IA\main.py", "--tray")
            ),
        )

    def test_windows_tray_click_opens_a_new_console(self):
        with patch.object(desktop_tray, "IS_WINDOWS", True), \
             patch.object(desktop_tray, "_console_python_executable", return_value=r"C:\Python\python.exe"), \
             patch.object(desktop_tray, "MAIN_SCRIPT", Path(r"C:\Local IA\main.py")), \
             patch.object(desktop_tray.subprocess, "CREATE_NEW_CONSOLE", 16, create=True), \
             patch.object(desktop_tray.subprocess, "Popen") as popen:
            desktop_tray.launch_main()

        self.assertEqual(
            popen.call_args.args[0],
            [r"C:\Python\python.exe", r"C:\Local IA\main.py"],
        )
        self.assertEqual(popen.call_args.kwargs["creationflags"], 16)

    def test_windows_tray_starts_without_a_console_window(self):
        with patch.object(desktop_tray, "IS_WINDOWS", True), \
             patch.object(desktop_tray, "install_autostart"), \
             patch.object(desktop_tray, "_tray_python_executable", return_value=r"C:\Python\pythonw.exe"), \
             patch.object(desktop_tray, "MAIN_SCRIPT", Path(r"C:\Local IA\main.py")), \
             patch.object(desktop_tray.subprocess, "CREATE_NO_WINDOW", 8, create=True), \
             patch.object(desktop_tray.subprocess, "Popen") as popen:
            desktop_tray.start_tray()

        self.assertEqual(popen.call_args.kwargs["creationflags"], 8)


if __name__ == "__main__":
    unittest.main()