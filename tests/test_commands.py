#!/usr/bin/env python3
"""Tests autonomes des commandes et outils d'exécution."""

from __future__ import annotations

import sys
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import command_commands
from local_ia.core.agent import LocalAgent
from local_ia.tools import command as command_tool
from local_ia.tools import system


class CommandTest(unittest.TestCase):
    def test_unknown_and_indirect_commands_require_confirmation(self):
        commands = (
            ["python", "-c", "print('hello')"],
            ["perl", "-e", "system('id')"],
            ["find", ".", "-exec", "rm", "-rf", "{}", ";"],
            ["curl", "-o", "payload", "https://example.invalid"],
            ["git", "reset", "--hard"],
            ["awk", "BEGIN { system(\"id\") }"],
            ["env", "python", "-c", "print('hello')"],
        )
        for argv in commands:
            with self.subTest(argv=argv):
                self.assertTrue(command_tool.is_risky(argv))

    def test_simple_read_only_command_does_not_require_confirmation(self):
        self.assertFalse(command_tool.is_risky(["echo", "hello"]))

    def test_parse_command_without_shell(self):
        self.assertEqual(command_commands.parse_command('/commande echo "hello world"'), ["echo", "hello world"])

    def test_execute_argv(self):
        result = command_commands.execute_argv([sys.executable, "-c", "print('ok')"])
        self.assertEqual(result["returncode"], 0)
        self.assertEqual(result["stdout"].strip(), "ok")

    @unittest.skipIf(os.name == "nt", "Le test utilise un exécutable POSIX")
    def test_relative_executable_uses_requested_cwd(self):
        with tempfile.TemporaryDirectory() as directory:
            workdir = Path(directory).resolve()
            executable = workdir / "say-ok"
            executable.write_text("#!/bin/sh\nprintf ok\n", encoding="utf-8")
            executable.chmod(0o755)
            with patch.object(command_commands.file_commands, "_resolve", return_value=workdir):
                result = command_commands.execute_argv(["./say-ok"], cwd=str(workdir))
        self.assertEqual(result["returncode"], 0)
        self.assertEqual(result["stdout"], "ok")

    def test_rejects_missing_executable(self):
        with self.assertRaises(FileNotFoundError):
            command_commands.execute_argv(["command-that-does-not-exist-local-ia"])

    def test_parses_tool_call(self):
        call = LocalAgent.parse_tool_call(
            '<tool_call>{"tool":"command","arguments":{"argv":["echo","ok"]}}</tool_call>'
        )
        self.assertEqual(call["tool"], "command")
        self.assertEqual(call["arguments"]["argv"], ["echo", "ok"])

    def test_parses_markdown_and_incomplete_tool_call_wrappers(self):
        for response in (
            '<tool_call>```json\n{"tool":"write","arguments":{"path":"demo.py","content":"print(1)"}}\n```</tool_call>',
            '<tool_call>{"name":"write","arguments":{"path":"demo.py","content":"print(1)"}}',
        ):
            with self.subTest(response=response):
                self.assertEqual(
                    LocalAgent.parse_tool_call(response),
                    {"tool": "write", "arguments": {"path": "demo.py", "content": "print(1)"}},
                )

    def test_parses_append_from_flat_write_tool_arguments(self):
        call = LocalAgent.parse_tool_call(
            '<tool_call>{"tool":"write","path":"large.txt","content":"next","append":true}</tool_call>'
        )
        self.assertEqual(call["tool"], "write")
        self.assertTrue(call["arguments"]["append"])

    def test_explicit_command_runs_without_calling_the_model(self):
        agent = LocalAgent(model="test")
        try:
            with patch("local_ia.core.agent.ask_ollama") as ask, patch(
                "local_ia.tools.command.execute_argv",
                return_value={"command": ["echo", "hello world"], "returncode": 0, "stdout": "hello world\n", "stderr": ""},
            ) as execute:
                answer = agent.respond({"messages": []}, '/commande echo "hello world"')
        finally:
            agent.close()

        self.assertEqual(answer, "Commande terminée : echo hello world\nhello world")
        self.assertEqual(execute.call_args.args[0], ["echo", "hello world"])
        ask.assert_not_called()

    def test_explicit_command_errors_are_user_facing_and_do_not_call_the_model(self):
        agent = LocalAgent(model="test")
        try:
            with patch("local_ia.core.agent.ask_ollama") as ask, patch(
                "local_ia.tools.command.execute_argv", side_effect=FileNotFoundError("private traceback detail")
            ):
                answer = agent.respond({"messages": []}, "/commande echo hello")
        finally:
            agent.close()

        self.assertEqual(
            answer,
            "Je n'ai pas pu exécuter cette commande. Vérifie le programme, ses arguments et les autorisations.",
        )
        self.assertNotIn("private traceback detail", answer)
        ask.assert_not_called()

    def test_explicit_command_rejects_disabled_command_tool(self):
        agent = LocalAgent(model="test")
        try:
            with patch("local_ia.core.agent.ask_ollama") as ask, patch(
                "local_ia.tools.command.execute_argv"
            ) as execute:
                answer = agent.respond(
                    {"messages": []}, "/commande echo ok", allowed_tools={"file"}
                )
        finally:
            agent.close()

        self.assertEqual(answer, "L'exécution de commandes est désactivée pour cette requête.")
        execute.assert_not_called()
        ask.assert_not_called()

    def test_explicit_risky_command_keeps_confirmation_flow(self):
        agent = LocalAgent(model="test")
        chat = {"messages": []}
        try:
            with patch("local_ia.core.agent.ask_ollama", return_value="Commande confirmée.") as ask, patch(
                "local_ia.tools.command.execute_argv",
                return_value={"command": ["rm", "-rf", "example"], "returncode": 0, "stdout": "", "stderr": ""},
            ) as execute:
                confirmation = agent.respond(chat, "/commande rm -rf example")
                self.assertIn("Confirmation nécessaire", confirmation)
                execute.assert_not_called()
                answer = agent.respond(chat, "oui")
        finally:
            agent.close()

        self.assertEqual(answer, "Commande confirmée.")
        execute.assert_called_once()
        self.assertEqual(execute.call_args.args[0], ["rm", "-rf", "example"])
        ask.assert_called_once()

    def test_malformed_model_tool_call_is_not_returned_to_the_chat(self):
        agent = LocalAgent(model="test")
        try:
            with patch(
                "local_ia.core.agent.ask_ollama",
                return_value='<tool_call>{"tool":"command",not-json}</tool_call>',
            ) as ask:
                answer = agent.respond(
                    {"messages": []}, "fais cette commande", allowed_tools={"command"}
                )
        finally:
            agent.close()

        self.assertEqual(
            answer,
            "Je n'ai pas pu comprendre l'action demandée. Reformule la commande ou précise ses arguments.",
        )
        self.assertNotIn("<tool_call>", answer)
        ask.assert_called_once()

    def test_invalid_model_tool_errors_are_not_exposed_to_the_chat(self):
        agent = LocalAgent(model="test")
        try:
            responses = iter([
                '<tool_call>{"tool":"command","arguments":{"argv":["echo","hello"]}}</tool_call>',
                "Je n'ai pas pu démarrer le programme.",
            ])
            with patch("local_ia.core.agent.ask_ollama", side_effect=lambda *a, **k: next(responses)), patch(
                "local_ia.tools.command.execute_argv", side_effect=FileNotFoundError("private traceback detail")
            ):
                answer = agent.respond(
                    {"messages": []}, "fais cette commande", allowed_tools={"command"}
                )
        finally:
            agent.close()

        self.assertEqual(
            answer,
            "La commande n'a pas réussi ou son résultat n'a pas pu être vérifié.",
        )
        self.assertNotIn("private traceback detail", answer)

    def test_parses_direct_launch_name(self):
        call = LocalAgent.parse_tool_call(
            '<tool_call>{"tool":"launch","name":"spotify"}</tool_call>'
        )
        self.assertEqual(call, {"tool": "launch", "arguments": {"name": "spotify"}})

    def test_normalizes_action_aliases(self):
        call = LocalAgent.parse_tool_call(
            '<tool_call>{"tool":"volume","action":"increase"}</tool_call>'
        )
        self.assertEqual(call["tool"], "system")
        self.assertEqual(call["arguments"]["action"], "increase")

    def test_parses_write_python_style_wrapper(self):
        call = LocalAgent.parse_tool_call(
            "<write.py {\"path\":\"Telechargements/poisson.txt\","
            "\"content\":\"D'autre part\",\"extension\":\"txt\"}}"
        )
        self.assertEqual(call["tool"], "write")
        self.assertEqual(call["arguments"]["path"], "Telechargements/poisson.txt")
        self.assertEqual(call["arguments"]["content"], "D'autre part")

    def test_installation_requires_confirmation(self):
        result = system.use("install", "example-package")
        self.assertTrue(result["confirmation_required"])

    def test_catalog_application_installation_requires_confirmation(self):
        application = {"id": "firefox", "name": "Mozilla Firefox"}
        plan = {
            "manager": "apt",
            "command": ["sudo", "apt", "install", "firefox"],
        }
        with patch.object(system.program_commands, "find_catalog_program", return_value=application), \
             patch.object(system.program_commands, "get_installation_plan", return_value=plan):
            result = system.use("install", "Firefox")

        self.assertTrue(result["confirmation_required"])
        self.assertEqual(
            result["command"],
            ["sudo", "-n", "apt", "install", "--assume-yes", "firefox"],
        )
        self.assertIn("Mozilla Firefox", result["message"])

    def test_catalog_application_installation_runs_only_after_confirmation(self):
        application = {"id": "firefox", "name": "Mozilla Firefox"}
        plan = {
            "manager": "apt",
            "command": ["sudo", "apt", "install", "firefox"],
        }
        with patch.object(system.program_commands, "find_catalog_program", return_value=application), \
             patch.object(system.program_commands, "get_installation_plan", return_value=plan), \
             patch.object(system, "_run", return_value={"command": [], "returncode": 0, "stdout": "", "stderr": ""}) as run:
            result = system.use("install", "Firefox", confirmed=True)

        run.assert_called_once_with(
            ["sudo", "-n", "apt", "install", "--assume-yes", "firefox"]
        )
        self.assertEqual(result["application"], "Mozilla Firefox")

    def test_install_app_is_restricted_to_catalog_entries(self):
        with patch.object(system.program_commands, "find_catalog_program", return_value=None), \
             patch.object(system, "_confirmation") as generic_confirmation:
            with self.assertRaisesRegex(ValueError, "absente du catalogue"):
                system.use("install_app", "unknown-app", confirmed=True)

        generic_confirmation.assert_not_called()

    def test_install_app_waits_for_confirmation_before_running(self):
        application = {"id": "firefox", "name": "Mozilla Firefox"}
        plan = {
            "manager": "flatpak",
            "command": ["flatpak", "install", "--user", "flathub", "org.mozilla.firefox"],
            "requires": ["remote Flathub configuré"],
        }
        with patch.object(system.program_commands, "find_catalog_program", return_value=application), \
             patch.object(system.program_commands, "get_installation_plan", return_value=plan), \
             patch.object(system, "_run") as run:
            pending = system.use("install_app", "Firefox")

        self.assertTrue(pending["confirmation_required"])
        self.assertIn("remote Flathub configuré", pending["message"])
        run.assert_not_called()

    def test_system_info_is_available(self):
        result = system.use("info")
        self.assertIn("system", result)
        self.assertIn("version", result)

    def test_system_info_then_write_can_be_chained(self):
        responses = iter([
            '<tool_call>{"tool":"system","arguments":{"action":"info"}}</tool_call>',
            '<tool_call>{"tool":"write","arguments":{"path":"test.txt","content":"OS Linux","extension":"txt"}}</tool_call>',
            "Fichier créé.",
        ])
        agent = LocalAgent(model="test")
        try:
            with patch("local_ia.core.agent.ask_ollama", side_effect=lambda *args, **kwargs: next(responses)):
                with patch.object(agent, "execute_tool", side_effect=[{"system": "Linux", "version": "test"}, {"path": "/tmp/test.txt"}]) as execute, \
                     patch("local_ia.core.agent.ToolManager.verify_result", return_value={"verified": True, "success": True, "evidence": "test"}):
                    answer = agent.respond({"topic": None, "messages": []}, "crée un fichier avec mon OS")
        finally:
            agent.close()
        self.assertEqual(answer, "Fichier créé.")
        self.assertEqual(execute.call_count, 2)


if __name__ == "__main__":
    unittest.main()