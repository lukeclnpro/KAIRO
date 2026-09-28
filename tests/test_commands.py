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
from local_ia.tools import system


class CommandTest(unittest.TestCase):
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
                with patch.object(agent, "execute_tool", side_effect=[{"system": "Linux", "version": "test"}, {"path": "/tmp/test.txt"}]) as execute:
                    answer = agent.respond({"topic": None, "messages": []}, "crée un fichier avec mon OS")
        finally:
            agent.close()
        self.assertEqual(answer, "Fichier créé.")
        self.assertEqual(execute.call_count, 2)


if __name__ == "__main__":
    unittest.main()