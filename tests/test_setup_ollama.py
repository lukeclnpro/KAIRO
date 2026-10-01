import unittest
from unittest.mock import patch

import setup


class SetupOllamaTest(unittest.TestCase):
    def test_existing_ollama_skips_install_prompt(self):
        with patch.object(setup, "find_ollama", return_value="/usr/bin/ollama"), \
             patch("builtins.input", side_effect=AssertionError("unexpected prompt")), \
             patch.object(setup, "install_ollama") as install:
            self.assertEqual(setup.offer_ollama_install(), "/usr/bin/ollama")

        install.assert_not_called()

    def test_missing_ollama_can_be_skipped(self):
        with patch.object(setup, "find_ollama", return_value=None), \
             patch("builtins.input", return_value="n"), \
             patch.object(setup, "install_ollama") as install:
            self.assertIsNone(setup.offer_ollama_install())

        install.assert_not_called()

    def test_missing_ollama_can_be_installed_after_consent(self):
        with patch.object(setup, "find_ollama", return_value=None), \
             patch("builtins.input", return_value="o"), \
             patch.object(setup, "install_ollama", return_value="/usr/local/bin/ollama") as install:
            self.assertEqual(setup.offer_ollama_install(), "/usr/local/bin/ollama")

        install.assert_called_once_with()

    def test_linux_installer_runs_only_after_install_choice(self):
        with patch.object(setup, "get_system", return_value="linux"), \
             patch.object(setup, "command_exists", return_value=True), \
             patch.object(setup.subprocess, "run", return_value=setup.subprocess.CompletedProcess([], 0)) as run, \
             patch.object(setup, "find_ollama", return_value="/usr/bin/ollama"):
            self.assertEqual(setup.install_ollama(), "/usr/bin/ollama")

        self.assertIn(setup.OLLAMA_LINUX_INSTALL_URL, run.call_args.args[0][2])


if __name__ == "__main__":
    unittest.main()