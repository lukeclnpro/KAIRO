import unittest
import tempfile
from types import ModuleType
from unittest.mock import patch
import json
from pathlib import Path

import main


class MainMenuProviderTest(unittest.TestCase):
    def test_update_requires_project_and_dependency_license_files(self):
        with tempfile.TemporaryDirectory() as directory:
            source_dir = Path(directory)
            expected = [
                Path("version.json"),
                Path("update.json"),
                Path("LICENSE"),
                Path("THIRD_PARTY_NOTICES.md"),
            ]
            for relative_path in expected:
                (source_dir / relative_path).write_text("file", encoding="utf-8")

            self.assertEqual(main._required_update_files(source_dir), expected)

            (source_dir / "LICENSE").unlink()
            with self.assertRaisesRegex(RuntimeError, "LICENSE"):
                main._required_update_files(source_dir)

    def test_show_updates_displays_versions_newest_first(self):
        releases = [
            {"version": "1.2.0", "date": "2026-01-01", "title": "Ancienne", "changes": []},
            {"version": "2.0.0", "date": "2026-02-01", "title": "Récente", "changes": []},
        ]
        with patch.object(main, "load_json_file", return_value={"versions": releases}), \
             patch.object(main.ui, "clear_screen"), \
             patch.object(main.ui, "section_title"), \
             patch.object(main.ui, "print_info"), \
             patch.object(main.ui, "colorize", side_effect=lambda text, *_: text) as colorize, \
             patch.object(main, "pause") as pause:
            main.show_updates()

        shown_versions = [
            call.args[0]
            for call in colorize.call_args_list
            if call.args[0].startswith("Version ")
        ]
        self.assertEqual(shown_versions, ["Version 2.0.0", "Version 1.2.0"])
        pause.assert_called_once_with()

    def test_gui_command_dispatches_to_graphical_entrypoint(self):
        gui_module = ModuleType("local_ia.gui")
        gui_module.run_gui = lambda: 23

        with patch.dict("sys.modules", {"local_ia.gui": gui_module}):
            with patch.object(main.sys, "argv", ["main.py", "gui"]):
                with patch.object(main, "create_start_menu_shortcut") as create_shortcut:
                    self.assertEqual(main.main(), 23)

                    create_shortcut.assert_called_once_with(main.BASE_DIR)

    def test_startup_login_choice_authenticates_local_account(self):
        with patch.dict("os.environ", {}, clear=True), \
             patch.object(main.accounts, "load_saved_session", return_value=None), \
             patch.object(main.accounts, "list_accounts", return_value=["alice"]), \
             patch.object(main, "login_openrouter_account", return_value=["account-key"]) as login, \
             patch.object(main.ui, "full_menu"), \
             patch.object(main.ui, "clear_screen"), \
             patch.object(main.ui, "prompt", return_value="1"):
            self.assertEqual(main.select_runtime_provider(), "openrouter")
            self.assertEqual(json.loads(main.os.environ["LOCAL_IA_OPENROUTER_KEYS"]), ["account-key"])

        login.assert_called_once_with()

    def test_startup_restores_saved_account_without_showing_login_menu(self):
        with patch.dict("os.environ", {}, clear=True), \
             patch.object(main.accounts, "load_saved_session", return_value=("alice", ["saved-key"])), \
             patch.object(main.ui, "full_menu") as full_menu:
            self.assertEqual(main.select_runtime_provider(), "openrouter")
            self.assertEqual(main.os.environ["LOCAL_IA_ACCOUNT"], "alice")
            self.assertEqual(json.loads(main.os.environ["LOCAL_IA_OPENROUTER_KEYS"]), ["saved-key"])

        full_menu.assert_not_called()

    def test_startup_create_choice_routes_to_account_creation(self):
        with patch.dict("os.environ", {}, clear=True), \
             patch.object(main.accounts, "load_saved_session", return_value=None), \
             patch.object(main.accounts, "list_accounts", return_value=[]), \
             patch.object(main, "create_openrouter_account", return_value=["new-key"]) as create, \
             patch.object(main.ui, "full_menu"), \
             patch.object(main.ui, "clear_screen"), \
             patch.object(main.ui, "prompt", return_value="2"):
            self.assertEqual(main.select_runtime_provider(), "openrouter")

        create.assert_called_once_with()

    def test_account_creation_configures_api_before_encrypted_storage(self):
        with patch.object(main.ui, "prompt", return_value="alice"), \
             patch.object(main.getpass, "getpass", return_value="account-password"), \
             patch.object(main, "configure_openrouter_api", return_value=["api-secret", "api-secret-2"]) as configure, \
             patch.object(main, "show_account_tutorial") as tutorial, \
             patch.object(main.accounts, "list_accounts", return_value=[]), \
             patch.object(main.accounts, "create_account") as create:
            self.assertEqual(main.create_openrouter_account(), ["api-secret", "api-secret-2"])

        configure.assert_called_once_with()
        tutorial.assert_called_once_with()
        create.assert_called_once_with("alice", "account-password", ["api-secret", "api-secret-2"])

    def test_account_tutorial_has_three_branded_pages(self):
        with patch.object(main.ui, "clear_screen"), \
             patch.object(main.ui, "brand_logo") as brand_logo, \
             patch.object(main.ui, "section_title") as section_title, \
             patch.object(main.ui, "print_info"), \
             patch.object(main.ui, "pause") as pause:
            main.show_account_tutorial()

        self.assertEqual(brand_logo.call_count, 3)
        self.assertEqual(
            [entry.args[0] for entry in section_title.call_args_list],
            ["01 / COMPTE", "02 / API", "03 / PREMIERS PAS"],
        )
        self.assertEqual(pause.call_count, 3)

    def test_api_options_accept_multiple_keys_then_save_and_continue(self):
        config = {"openrouter": {"model": "openai/gpt-4o-mini", "base_url": "https://openrouter.ai/api/v1"}}
        with patch.dict("os.environ", {}, clear=True), \
             patch.object(main, "load_config", return_value=config), \
             patch.object(main, "save_config", return_value=True) as save_config, \
             patch.object(main.ui, "full_menu"), \
             patch.object(main.ui, "prompt", side_effect=("1", "1", "0")), \
             patch.object(main.getpass, "getpass", side_effect=("api-secret", "api-secret-2")):
            self.assertEqual(main.configure_openrouter_api(), ["api-secret", "api-secret-2"])
            self.assertEqual(main.os.environ["LOCAL_IA_OPENROUTER_MODEL"], "openai/gpt-4o-mini")

        save_config.assert_called_once_with(config)

    def test_openrouter_menu_hides_local_model_management(self):
        options = main.get_main_menu_options("openrouter")
        option_labels = dict(options)

        self.assertEqual(option_labels["2"], "Modifier la clé API OpenRouter")
        self.assertEqual(option_labels["3"], "Voir l'utilisation de la clé API")
        self.assertNotIn("4", option_labels)
        self.assertIn("5", option_labels)
        self.assertIn("9", option_labels)

    def test_changing_openrouter_key_persists_encrypted_account_key(self):
        with patch.dict("os.environ", {"LOCAL_IA_ACCOUNT": "alice"}, clear=True), \
             patch.object(main.getpass, "getpass", side_effect=("account-password", "new-runtime-key")), \
             patch.object(main.accounts, "update_api_key") as update_api_key, \
             patch.object(main.accounts, "authenticate_api_keys", return_value=["new-runtime-key"]) as authenticate_keys, \
             patch.object(main.ui, "print_ok"), \
             patch.object(main, "pause"):
            main.change_openrouter_key()
            self.assertEqual(json.loads(main.os.environ["LOCAL_IA_OPENROUTER_KEYS"]), ["new-runtime-key"])
        update_api_key.assert_called_once_with("alice", "account-password", "new-runtime-key")
        authenticate_keys.assert_called_once_with("alice", "account-password")

    def test_local_menu_keeps_model_management(self):
        options = main.get_main_menu_options("local")
        option_numbers = {number for number, _ in options}

        self.assertTrue({"2", "3", "4"}.issubset(option_numbers))
        self.assertIn("10", option_numbers)
        self.assertEqual(dict(options)["6"], "Installer une application")

    def test_catalog_install_requires_confirmation_before_execution(self):
        programs = [{"id": "firefox", "name": "Firefox", "category": "Navigateur"}]
        plan = {
            "manager": "flatpak",
            "command": ["flatpak", "install", "org.mozilla.firefox"],
            "requires": [],
        }
        with patch.object(main.program_commands, "get_catalog_programs", return_value=programs), \
             patch.object(main.program_commands, "get_installation_plan", return_value=plan), \
             patch.object(main.program_commands, "execute_install_command") as execute, \
             patch.object(main, "pause"), \
             patch.object(main.ui, "section_title"), \
             patch("builtins.print"), \
             patch.object(main.ui, "print_info") as print_info:
            answers = iter(("1", "n"))
            main.install_catalog_application(input_fn=lambda _prompt: next(answers))

        execute.assert_not_called()
        print_info.assert_called_once_with("Installation annulée.")

    def test_app_menu_remains_available_without_ollama(self):
        with patch.object(main.sys, "argv", ["main.py"]), \
             patch("local_ia.desktop_tray.start_tray"), \
             patch.object(main, "select_runtime_provider", return_value="local"), \
             patch.object(main, "check_ollama", return_value=False), \
             patch.object(main, "scan_models") as scan_models, \
             patch.object(main.ui, "section_title"), \
             patch.object(main.ui, "print_info"), \
             patch.object(main, "menu") as menu:
            main.main()

        scan_models.assert_not_called()
        menu.assert_called_once_with()

    def test_hidden_model_choices_are_rejected_in_openrouter_mode(self):
        with patch.object(main, "resolve_runtime_provider", return_value="openrouter"), \
             patch.object(main.ui, "full_menu"), \
             patch.object(main.ui, "prompt", side_effect=("3", "0")), \
             patch.object(main.ui, "clear_screen"), \
             patch.object(main.ui, "print_error") as print_error, \
             patch.object(main.ui, "print_info"), \
             patch.object(main, "pause"), \
             patch.object(main, "install_model") as install_model:
            main.menu()

        print_error.assert_called_once()
        install_model.assert_not_called()


if __name__ == "__main__":
    unittest.main()