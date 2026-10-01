import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from local_ia.cli import iahelp
import main


class FakeAgent:
    calls = []

    def __init__(self, model):
        self.model = model
        self.closed = False

    def respond(self, chat, message, **kwargs):
        self.calls.append((message, kwargs))
        return f"Réponse à : {message}"

    def close(self):
        self.closed = True


class IahelpTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.path = Path(self.temp_dir.name) / "private" / "iahelp-history.json"
        FakeAgent.calls = []

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_requests_include_all_previous_iahelp_turns(self):
        with patch.dict("os.environ", {"LOCAL_IA_OPENROUTER_KEY": "test-key"}, clear=True), \
             patch.object(iahelp, "_pc_context", return_value="Profil PC local de test"):
            first = iahelp.run_request("première commande", path=self.path, agent_factory=FakeAgent)
            second = iahelp.run_request("demande suivante", path=self.path, agent_factory=FakeAgent)

        self.assertEqual(first, "Réponse à : première commande")
        self.assertEqual(second, "Réponse à : demande suivante")
        context = FakeAgent.calls[1][1]["external_info"]
        self.assertIn("première commande", context)
        self.assertIn("Réponse à : première commande", context)
        self.assertIn("Profil PC local de test", context)
        self.assertIn("commande complète, directement copiable", context)
        self.assertEqual(FakeAgent.calls[1][1]["allowed_tools"], set())

    def test_pc_context_reports_detected_commands_and_specs(self):
        def find_command(name):
            return f"/usr/bin/{name}" if name in {"pacman", "custom-tool"} else None

        with patch.object(iahelp.platform, "system", return_value="Linux"), \
             patch.object(iahelp.platform, "release", return_value="test-release"), \
             patch.object(iahelp.platform, "machine", return_value="x86_64"), \
             patch.object(iahelp, "_cpu_name", return_value="Test CPU"), \
             patch.object(iahelp, "_memory_gib", return_value=16.0), \
             patch.object(iahelp.os, "cpu_count", return_value=8), \
             patch.object(iahelp.shutil, "which", side_effect=find_command), \
             patch.dict("os.environ", {"SHELL": "/bin/bash"}), \
             patch.object(iahelp.platform, "freedesktop_os_release", return_value={"PRETTY_NAME": "Test Linux"}, create=True):
            context = iahelp._pc_context("utilise custom-tool")

        self.assertIn("Test Linux (test-release)", context)
        self.assertIn("Test CPU", context)
        self.assertIn("16.0 Gio", context)
        self.assertIn("custom-tool, pacman", context)

    def test_history_is_saved_with_private_permissions(self):
        with patch.dict("os.environ", {"LOCAL_IA_OPENROUTER_KEY": "test-key"}, clear=True):
            iahelp.run_request("question", path=self.path, agent_factory=FakeAgent)

        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o600)
        self.assertNotIn("test-key", self.path.read_text(encoding="utf-8"))

    def test_saved_credentials_use_the_secure_store(self):
        credentials = {}

        class FakeKeyring:
            @staticmethod
            def get_password(service, username):
                return credentials.get((service, username))

            @staticmethod
            def set_password(service, username, password):
                credentials[(service, username)] = password

        with patch.object(iahelp, "_get_keyring", return_value=FakeKeyring):
            self.assertTrue(iahelp._save_credentials("Alice", "api-key"))
            self.assertEqual(iahelp._load_saved_credentials(), ("Alice", "api-key"))

    def test_saved_login_skips_account_and_password_prompts(self):
        config = object()
        with patch.dict("os.environ", {}, clear=True), \
             patch.object(iahelp.accounts, "list_accounts", return_value=["Alice"]), \
             patch.object(iahelp, "_load_saved_credentials", return_value=("alice", "stored-key")), \
             patch.object(iahelp, "openrouter_model", return_value="test-model"), \
             patch.object(iahelp, "openrouter_base_url", return_value="https://example.test/v1"):
            key, model = iahelp._select_provider(
                config,
                input_fn=lambda prompt: self.fail("Le compte ne devrait pas être redemandé"),
                password_reader=lambda prompt: self.fail("Le mot de passe ne devrait pas être redemandé"),
            )
            self.assertEqual(os.environ["LOCAL_IA_OPENROUTER_KEY"], "stored-key")
            self.assertEqual(os.environ["LOCAL_IA_PROVIDER"], "openrouter")

        self.assertEqual((key, model), ("stored-key", "test-model"))

    def test_blank_request_is_rejected_without_calling_agent(self):
        with self.assertRaisesRegex(ValueError, "Indique une demande"):
            iahelp.run_request("  ", path=self.path, agent_factory=FakeAgent)
        self.assertEqual(FakeAgent.calls, [])

    def test_command_help(self):
        self.assertEqual(iahelp.main(["--help"]), 0)

    def test_main_dispatches_iahelp_arguments(self):
        with patch.object(main.sys, "argv", ["main.py", "iahelp", "question", "suivante"]), \
             patch("local_ia.cli.iahelp.main", return_value=0) as command:
            self.assertEqual(main.main(), 0)

        command.assert_called_once_with(["question", "suivante"])


if __name__ == "__main__":
    unittest.main()
