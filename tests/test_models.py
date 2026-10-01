import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from local_ia import models


class ModelCatalogTest(unittest.TestCase):
    def test_description_is_found_across_model_categories(self):
        self.assertIn("agent", models.get_model_description("granite4.1:8b").lower())
        self.assertEqual(models.get_model_description("not-installed"), "")

    def test_scan_parses_ollama_rows_deduplicates_and_saves(self):
        result = SimpleNamespace(
            returncode=0,
            stdout=(
                "NAME ID SIZE MODIFIED\n"
                "qwen3:8b model-id 5.2GB 2 days ago\n"
                "qwen3:8b model-id 5.2GB 2 days ago\n"
            ),
            stderr="",
        )
        run_command = Mock(return_value=result)
        save_models = Mock()

        found = models.scan_models("/usr/bin/ollama", run_command, save_models)

        expected = [{
            "name": "qwen3:8b",
            "id": "model-id",
            "size": "5.2GB",
            "modified": "2 days ago",
        }]
        self.assertEqual(found, expected)
        save_models.assert_called_once_with(expected)
        run_command.assert_called_once_with(
            ["/usr/bin/ollama", "list"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )

    def test_scan_without_ollama_does_not_run_or_save(self):
        run_command = Mock()
        save_models = Mock()

        self.assertEqual(models.scan_models(None, run_command, save_models), [])

        run_command.assert_not_called()
        save_models.assert_not_called()

    def test_install_menu_returns_before_ollama_when_user_selects_back(self):
        ui_module = Mock()
        ui_module.prompt.return_value = "0"
        scan_models = Mock(return_value=[])
        get_ollama = Mock()
        run_command = Mock()

        models.install_model(ui_module, scan_models, get_ollama, run_command, Mock())

        scan_models.assert_called_once_with()
        get_ollama.assert_not_called()
        run_command.assert_not_called()

    def test_uninstall_menu_returns_when_user_cancels(self):
        ui_module = Mock()
        ui_module.prompt.return_value = "0"
        scan_models = Mock(return_value=[{"name": "qwen3:8b", "size": "5.2GB"}])
        get_ollama = Mock()
        run_command = Mock()

        models.uninstall_model(ui_module, scan_models, get_ollama, run_command)

        scan_models.assert_called_once_with()
        get_ollama.assert_not_called()
        run_command.assert_not_called()


if __name__ == "__main__":
    unittest.main()