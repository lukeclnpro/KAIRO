import unittest
from unittest.mock import patch

import program_commands


class ProgramCatalogTest(unittest.TestCase):
    def test_catalog_lists_programs(self):
        programs = program_commands.get_catalog_programs()

        self.assertTrue(programs)
        self.assertIn("firefox", {program["id"] for program in programs})

    def test_linux_plan_uses_distribution_package_manager(self):
        with patch.object(program_commands.shutil, "which", return_value="/usr/bin/apt"):
            plan = program_commands.get_installation_plan(
                "git", system="Linux", distro_ids=["ubuntu"]
            )

        self.assertEqual(plan["manager"], "apt")
        self.assertEqual(plan["command"], ["sudo", "apt", "install", "git"])

    def test_linux_plan_falls_back_to_available_flatpak(self):
        with patch.object(
            program_commands.shutil,
            "which",
            side_effect=lambda executable: "/usr/bin/flatpak" if executable == "flatpak" else None,
        ):
            plan = program_commands.get_installation_plan(
                "firefox", system="Linux", distro_ids=["ubuntu"]
            )

        self.assertEqual(plan["manager"], "flatpak")
        self.assertIn("remote Flathub configuré", plan["requires"])

    def test_windows_plan_uses_catalog_command(self):
        with patch.object(program_commands.shutil, "which", return_value="winget.exe"):
            plan = program_commands.get_installation_plan("firefox", system="Windows")

        self.assertEqual(plan["command"][:4], ["winget", "install", "--exact", "--id"])

    def test_missing_manager_and_unknown_program_are_rejected(self):
        with patch.object(program_commands.shutil, "which", return_value=None):
            with self.assertRaisesRegex(ValueError, "gestionnaire requis"):
                program_commands.get_installation_plan("firefox", system="Windows")
        with self.assertRaisesRegex(ValueError, "Application inconnue"):
            program_commands.get_installation_plan("not-in-catalog")

    def test_catalog_commands_are_executed_without_shell(self):
        with patch.object(program_commands.subprocess, "run") as run:
            program_commands.execute_install_command(["flatpak", "install", "org.example.App"])

        run.assert_called_once_with(
            ["flatpak", "install", "org.example.App"],
            cwd=str(program_commands.BASE_DIR),
            check=False,
            shell=False,
        )

    def test_command_formatting_uses_platform_quoting(self):
        command = ["tool", "path with spaces", "--flag"]

        self.assertEqual(
            program_commands.format_command(command, system="Linux"),
            "tool 'path with spaces' --flag",
        )
        self.assertEqual(
            program_commands.format_command(command, system="Windows"),
            'tool "path with spaces" --flag',
        )


if __name__ == "__main__":
    unittest.main()