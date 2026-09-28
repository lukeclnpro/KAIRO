#!/usr/bin/env python3
"""Tests du routeur de requêtes avant compilation du contexte."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from local_ia.core.router import RequestRouter
from local_ia.core.context_compiler import ContextCompiler
from local_ia.core.tool_manager import ToolManager
from local_ia.core.agent import LocalAgent
from local_ia.core.context import build_system_prompt


class RequestRouterTest(unittest.TestCase):
    def setUp(self):
        self.router = RequestRouter()

    def test_router_delegates_direct_actions_to_existing_fast_path(self):
        route = self.router.route("ouvre firefox", lambda message, allowed: "Firefox lancé.", {"launch"})
        self.assertEqual(route, {
            "mode": "direct", "action": "fast_path", "tools": (), "answer": "Firefox lancé."
        })

    def test_router_preserves_fallback_when_fast_path_declines(self):
        route = self.router.route("Quelle est la capitale ?", lambda message, allowed: None, None)
        self.assertEqual(route["mode"], "chat")
        self.assertIsNone(route["answer"])

    def test_simple_question_is_routed_to_chat(self):
        route = self.router.route("Quelle est la capitale de l'Italie ?", lambda *_: None)
        self.assertEqual(route["mode"], "chat")
        self.assertEqual(route["tools"], ())

    def test_code_change_is_routed_to_tool_mode(self):
        route = self.router.route("Corrige le bug dans agent.py", lambda *_: None)
        self.assertEqual(route["mode"], "tool")
        self.assertIn("edit", route["tools"])
        self.assertIn("search", route["tools"])

    def test_explicit_command_is_routed_to_tool_mode(self):
        route = self.router.route("/commande echo ok", lambda *_: None)
        self.assertEqual(route["mode"], "tool")
        self.assertEqual(route["tools"], ("command",))

    def test_mixed_filesystem_and_system_request_keeps_both_tool_groups(self):
        route = self.router.route("Crée un fichier avec mon OS", lambda *_: None)
        self.assertIn("write", route["tools"])
        self.assertIn("system", route["tools"])

    def test_ambiguous_request_keeps_full_agent_fallback(self):
        route = self.router.route("Fais quelque chose d'utile", lambda *_: None)
        self.assertEqual(route["mode"], "agent")
        self.assertIsNone(route["tools"])


class ContextCompilerTest(unittest.TestCase):
    def test_compiler_delegates_to_existing_prompt_builder(self):
        compiler = ContextCompiler()
        chat = {"topic": "tests"}
        context = {"langue": "français", "role": "assistant local"}
        memories = ["Nom: Alex", "Préfère Python"]
        self.assertEqual(
            compiler.compile(chat, context, memories),
            build_system_prompt(memories, chat["topic"], context),
        )

    def test_tool_manager_includes_only_requested_tools(self):
        prompt = ToolManager.build_prompt({"file", "search"})
        self.assertIn("file :", prompt)
        self.assertIn("search :", prompt)
        self.assertNotIn("command :", prompt)
        self.assertNotIn("system :", prompt)

    def test_empty_tool_selection_has_no_tool_prompt(self):
        self.assertEqual(ToolManager.build_prompt(set()), "")

    def test_route_tools_respect_server_allowlist(self):
        route = {"mode": "tool", "tools": ("file", "search", "edit")}
        self.assertEqual(ToolManager.get_tools(route, {"file", "command"}), {"file"})

    def test_agent_route_defaults_to_all_allowed_tools(self):
        route = {"mode": "agent", "tools": None}
        self.assertEqual(
            ToolManager.get_tools(route),
            {"memory", "context", "file", "write", "edit", "list", "search", "launch", "command", "system"},
        )

    def test_validate_refuses_tools_outside_allowlist(self):
        with self.assertRaises(PermissionError):
            ToolManager.validate("command", {"file"})

    def test_compact_result_removes_json_whitespace_and_obeys_limit(self):
        self.assertEqual(
            ToolManager.compact_result({"stdout": "ok", "returncode": 0}),
            '{"stdout":"ok","returncode":0}',
        )
        compact = ToolManager.compact_result({"output": "x" * 100}, max_chars=40)
        self.assertLessEqual(len(compact), 40)
        self.assertTrue(compact.endswith("...[résultat tronqué]"))

    def test_compact_result_summarizes_large_file_and_search_payloads(self):
        large_file = {
            "path": "/tmp/demo.py",
            "content": "\n".join(["import os"] + ["x = 1"] * 100),
        }
        compressed = ToolManager.compact_result(large_file, max_chars=120)
        self.assertIn("/tmp/demo.py", compressed)
        self.assertIn("...", compressed)

        large_search = {
            "matches": [
                {"file": "a.py", "line": 10, "text": "match 1"},
                {"file": "a.py", "line": 12, "text": "match 2"},
                {"file": "a.py", "line": 14, "text": "match 3"},
            ] * 20,
            "files_scanned": 50,
            "truncated": True,
        }
        compressed_search = ToolManager.compact_result(large_search, max_chars=160)
        self.assertIn('"matches"', compressed_search)
        self.assertIn('"truncated":true', compressed_search)

    def test_tool_step_limits_are_route_aware(self):
        self.assertEqual(LocalAgent.get_max_tool_steps({"mode": "tool"}), 3)
        self.assertEqual(LocalAgent.get_max_tool_steps({"mode": "agent"}), 4)
        self.assertEqual(LocalAgent.get_max_tool_steps({"mode": "chat"}), 0)

    def test_duplicate_tool_calls_are_normalized_for_loop_detection(self):
        first = {"tool": "search", "arguments": {"path": ".", "pattern": "foo"}}
        second = {"tool": "search", "arguments": {"pattern": "foo", "path": "."}}
        self.assertEqual(LocalAgent.normalize_tool_call(first), LocalAgent.normalize_tool_call(second))

    def test_prompt_cache_invalidates_when_context_changes(self):
        agent = LocalAgent.__new__(LocalAgent)
        agent.model = "dummy"
        agent.context = {"langue": "français", "role": "assistant local"}
        agent.memories = ["Je travaille en Python"]
        agent.context_compiler = ContextCompiler()
        agent._prepared_prompts = {}
        agent._tool_cache = {}
        route = {"mode": "tool", "tools": ("file", "search")}
        chat = {"id": 10, "topic": "tests", "messages": []}

        first = agent.prepare_chat(chat, message="Corrige app.py", route=route, tools=("file", "search"))
        cached = agent.prepare_chat(chat, message="Corrige app.py", route=route, tools=("file", "search"))
        self.assertIs(first, cached)

        agent.context = {"langue": "anglais", "role": "assistant local"}
        second = agent.prepare_chat(chat, message="Corrige app.py", route=route, tools=("file", "search"))
        self.assertIsNot(first, second)
        self.assertIn("anglais", second[0])

    def test_compile_simple_question_uses_only_base_prompt(self):
        compiler = ContextCompiler()
        messages = [
            {"role": "user", "content": "Bonjour"},
            {"role": "assistant", "content": "Bonjour !"},
        ]
        context = {"langue": "français", "role": "assistant local", "style": "conversationnel"}
        memories = ["Je travaille en Python", "J'utilise Ubuntu"]
        prompt = compiler.compile(
            {"topic": "tests", "messages": messages},
            context,
            memories,
            message="Quelle est la capitale de l'Italie ?",
            route={"mode": "chat", "tools": ()},
            allow_tools=set(),
        )
        self.assertIn("Langue obligatoire : français", prompt)
        self.assertNotIn("Je travaille en Python", prompt)
        self.assertNotIn("file :", prompt)
        self.assertNotIn("command :", prompt)

    def test_compile_code_request_keeps_history_and_file_tools_but_not_launch(self):
        compiler = ContextCompiler()
        chat = {
            "topic": "tests",
            "messages": [
                {"role": "user", "content": "Salut"},
                {"role": "assistant", "content": "Bonjour"},
                {"role": "user", "content": "Corrige app.py"},
            ],
        }
        context = {"langue": "français", "role": "assistant local"}
        prompt = compiler.compile(
            chat,
            context,
            ["Je travaille en Python"],
            message="Corrige le bug dans app.py",
            route={"mode": "tool", "tools": ("file", "search", "edit", "command")},
            allow_tools={"file", "search", "edit", "command"},
        )
        self.assertIn("file :", prompt)
        self.assertIn("search :", prompt)
        self.assertIn("command :", prompt)
        self.assertNotIn("launch :", prompt)
        self.assertIn("Corrige app.py", prompt)

    def test_compile_includes_summary_and_recent_window_only(self):
        compiler = ContextCompiler()
        chat = {
            "topic": "tests",
            "summary": "Travaille sur Local IA et Ollama.",
            "messages": [
                {"role": "user", "content": "message 1"},
                {"role": "assistant", "content": "réponse 1"},
                {"role": "user", "content": "message 2"},
                {"role": "assistant", "content": "réponse 2"},
                {"role": "user", "content": "message 3"},
                {"role": "assistant", "content": "réponse 3"},
                {"role": "user", "content": "message 4"},
                {"role": "assistant", "content": "réponse 4"},
                {"role": "user", "content": "message 5"},
                {"role": "assistant", "content": "réponse 5"},
            ],
        }
        prompt = compiler.compile(
            chat,
            {"langue": "français", "role": "assistant local"},
            ["Travaille sur Local IA et Ollama."],
            message="Quel est le prochain changement ?",
            route={"mode": "chat", "tools": ()},
            allow_tools=set(),
        )
        self.assertIn("Travaille sur Local IA et Ollama.", prompt)
        self.assertNotIn("message 1", prompt)
        self.assertIn("message 5", prompt)
        self.assertIn("réponse 5", prompt)


if __name__ == "__main__":
    unittest.main()
