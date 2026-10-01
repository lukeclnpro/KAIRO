import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from local_ia.cli import interface
from local_ia.core import code_projects


class LocalCodeCliTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.projects_root = Path(self.directory.name) / "Documents" / "ia_local" / "code"
        self.root_patch = patch.object(code_projects, "get_projects_root", return_value=self.projects_root)
        self.root_patch.start()
        self.save_patch = patch.object(interface, "save_chat")
        self.save_patch.start()

    def tearDown(self):
        self.save_patch.stop()
        self.root_patch.stop()
        self.directory.cleanup()

    def test_code_command_parses_project_selection_and_request(self):
        self.assertEqual(
            interface._parse_local_code_command('/code --project "Mon site" ajoute une page accueil'),
            ("Mon site", "ajoute une page accueil"),
        )

    def test_first_code_request_generates_project_name_without_prompting(self):
        chat = {"messages": []}
        with patch("builtins.input", side_effect=AssertionError("unexpected project prompt")):
            request, project = interface._prepare_local_code(
                "/code crée une application simple",
                chat,
            )

        self.assertEqual(request, "crée une application simple")
        self.assertEqual(project, self.projects_root / "application-simple")
        self.assertEqual(chat["code_project_path"], str(project))
        self.assertTrue((project / "exemple" / "README.md").is_file())

    def test_project_name_is_made_unique_from_request(self):
        code_projects.create_or_open_project("lecteur-perf-pc")
        self.assertEqual(
            code_projects.suggest_project_name("crée un lecteur perf pc"),
            "lecteur-perf-pc-2",
        )

    def test_active_code_project_is_reused_without_another_prompt(self):
        project = code_projects.create_or_open_project("Projet existant")
        chat = {"messages": [], "code_project_path": str(project)}
        with patch("builtins.input", side_effect=AssertionError("unexpected project prompt")):
            request, selected = interface._prepare_local_code("/code ajoute des tests", chat)

        self.assertEqual(request, "ajoute des tests")
        self.assertEqual(selected, project)

    def test_existing_command_setting_controls_project_command_tool(self):
        self.assertNotIn("command", interface._local_code_tools({"command_execution": {"enabled": False}}))
        self.assertIn("command", interface._local_code_tools({"command_execution": {"enabled": True}}))

    def test_local_code_instructions_require_autonomous_completion(self):
        instructions = interface._local_code_instructions(self.projects_root / "demo", False)
        self.assertIn("agent de développement autonome", instructions)
        self.assertIn("Ne t'arrête pas après avoir annoncé", instructions)
        self.assertIn("pose une question uniquement", instructions)
        self.assertIn("exemple/README.md", instructions)

    def test_code_loop_proposes_read_only_and_does_not_apply_when_declined(self):
        project = self.projects_root / "demo"

        class FakeAgent:
            calls = []

            def respond(self, chat, request, **kwargs):
                self.calls.append((request, kwargs))
                return "Diagnostic et diff proposés."

        agent = FakeAgent()
        displayed = []
        result = interface._run_local_code_loop(
            agent,
            {"messages": []},
            "corrige le bug",
            project,
            {"file", "write", "edit"},
            input_fn=lambda prompt: "n",
            display=lambda role, content: displayed.append((role, content)),
        )

        self.assertEqual(result, "Proposition refusée ou annulée. Aucun fichier n'a été modifié.")
        self.assertEqual(len(agent.calls), 1)
        self.assertEqual(agent.calls[0][1]["allowed_tools"], interface.LOCAL_CODE_READ_TOOLS)
        self.assertIn("lecture seule", agent.calls[0][1]["external_info"])
        self.assertEqual(displayed, [("assistant", "Diagnostic et diff proposés.")])

    def test_code_loop_applies_only_after_explicit_approval(self):
        project = self.projects_root / "demo"

        class FakeAgent:
            calls = []

            def respond(self, chat, request, **kwargs):
                self.calls.append((request, kwargs))
                return "Diff approuvé." if len(self.calls) == 1 else "Correctif appliqué et testé."

        agent = FakeAgent()
        result = interface._run_local_code_loop(
            agent,
            {"messages": []},
            "corrige le bug",
            project,
            {"file", "write", "edit", "command"},
            input_fn=lambda prompt: "oui",
            display=lambda role, content: None,
        )

        self.assertEqual(result, "Correctif appliqué et testé.")
        self.assertEqual(len(agent.calls), 2)
        self.assertEqual(agent.calls[0][1]["allowed_tools"], interface.LOCAL_CODE_READ_TOOLS)
        self.assertIn("Diff approuvé.", agent.calls[1][0])
        self.assertIn("uniquement la proposition approuvée", agent.calls[1][1]["external_info"])
        self.assertIn("command", agent.calls[1][1]["allowed_tools"])


if __name__ == "__main__":
    unittest.main()