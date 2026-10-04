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

    def test_current_information_is_routed_to_web_tool(self):
        route = self.router.route("Quelle est la météo à Paris aujourd'hui ?", lambda *_: None)
        self.assertEqual(route["mode"], "tool")
        self.assertEqual(route["tools"], ("web",))

    def test_unaccented_weather_request_is_routed_to_web_tool(self):
        route = self.router.route("meteo a metz", lambda *_: None)
        self.assertEqual(route["mode"], "tool")
        self.assertEqual(route["tools"], ("web",))

    def test_arithmetic_questions_are_routed_to_calculator_tool(self):
        for message in ("Combien font 12 / 3 ?", "calcule sqrt(81) + 2", "2 + 2"):
            with self.subTest(message=message):
                route = self.router.route(message, lambda *_: None)
                self.assertEqual(route["mode"], "tool")
                self.assertEqual(route["tools"], ("calculator",))

    def test_document_and_table_requests_are_routed_to_document_tool(self):
        for request in ("Analyse ce fichier CSV", "Lis ce PDF", "crée un tableau XLSX"):
            with self.subTest(request=request):
                route = self.router.route(request, lambda *_: None)
                self.assertEqual(route["action"], "document")
                self.assertEqual(route["tools"], ("document",))

    def test_web_search_categories_are_routed_to_web_tool(self):
        for message in (
            "annonces vélo à Metz",
            "trouve le site officiel de la mairie de Metz",
            "recherche Google sur les actualités de Macron",
        ):
            with self.subTest(message=message):
                route = self.router.route(message, lambda *_: None)
                self.assertEqual(route["mode"], "tool")
                self.assertEqual(route["tools"], ("web",))

    def test_code_change_is_routed_to_tool_mode(self):
        route = self.router.route("Corrige le bug dans agent.py", lambda *_: None)
        self.assertEqual(route["mode"], "tool")
        self.assertIn("edit", route["tools"])
        self.assertIn("search", route["tools"])

    def test_contextual_code_followup_targets_the_existing_file(self):
        route = self.router.route(
            "ajoute dedans l'installation auto des dependances",
            lambda *_: None,
            existing_code_file="/tmp/liste_appareils_reseau.py",
        )

        self.assertEqual(route["mode"], "tool")
        self.assertEqual(route["action"], "filesystem")
        self.assertEqual(route["existing_code_file"], "/tmp/liste_appareils_reseau.py")
        self.assertEqual(set(route["tools"]), {"edit", "file", "search", "write"})

    def test_contextual_code_followup_without_an_existing_file_is_not_forced(self):
        route = self.router.route("ajoute dedans l'installation auto des dependances", lambda *_: None)

        self.assertEqual(route["mode"], "agent")

    def test_agent_finds_the_latest_existing_file_reported_in_chat(self):
        import tempfile

        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "liste_appareils_reseau.py"
            target.write_text("print('old')\n", encoding="utf-8")
            chat = {
                "messages": [
                    {"role": "assistant", "content": f"Fichier créé ou modifié : {target}"},
                    {"role": "assistant", "content": "Autre réponse sans fichier."},
                ]
            }

            self.assertEqual(LocalAgent._recent_created_file(chat), str(target.resolve()))

    def test_agent_ignores_missing_file_reported_in_chat(self):
        chat = {
            "messages": [
                {"role": "assistant", "content": "Fichier créé ou modifié : /tmp/no-such-file-kairo.py"},
            ]
        }

        self.assertIsNone(LocalAgent._recent_created_file(chat))

    def test_filesystem_followup_prompt_requires_editing_existing_file(self):
        prompt = ContextCompiler().compile(
            {"messages": []},
            {"langue": "français", "role": "assistant local"},
            [],
            message="ajoute dedans l'installation auto des dependances",
            route={
                "mode": "tool",
                "action": "filesystem",
                "tools": ("edit", "file", "search", "write"),
                "existing_code_file": "/tmp/liste_appareils_reseau.py",
            },
            allow_tools={"edit", "file", "search", "write"},
        )

        self.assertIn("au lieu de créer un nouveau fichier", prompt)
        self.assertIn("/tmp/liste_appareils_reseau.py", prompt)

    def test_plural_folder_request_is_routed_to_filesystem_tools(self):
        route = self.router.route("Liste les dossiers", lambda *_: None)

        self.assertEqual(route["mode"], "tool")
        self.assertIn("list", route["tools"])

    def test_explicit_command_is_routed_to_tool_mode(self):
        route = self.router.route("/commande echo ok", lambda *_: None)
        self.assertEqual(route["mode"], "tool")
        self.assertEqual(route["tools"], ("command",))

    def test_command_suggestion_is_routed_without_execution_tools(self):
        route = self.router.route("Quelle commande pour lancer Firefox ?", lambda *_: None)

        self.assertEqual(route["mode"], "command_suggestion")
        self.assertEqual(route["action"], "command_suggestion")
        self.assertEqual(route["tools"], ())

    def test_code_request_is_routed_to_file_creation(self):
        for message in (
            "Écris un script Python qui trie une liste",
            "Je demande du code pour vérifier une adresse email",
        ):
            with self.subTest(message=message):
                route = self.router.route(message, lambda *_: None)
                self.assertEqual(route["mode"], "code")
                self.assertEqual(route["action"], "code_artifact")
                self.assertIn("write", route["tools"])
                self.assertNotIn("launch", route["tools"])
            calculator_script = self.router.route("crée un script python de calculatrice", lambda *_: None)
            self.assertEqual(calculator_script["action"], "code_artifact")
            self.assertIn("write", calculator_script["tools"])
            self.assertNotIn("create_download", calculator_script["tools"])

    def test_generic_file_creation_uses_the_file_command_route(self):
        route = self.router.route("Crée un fichier de configuration", lambda *_: None)

        self.assertEqual(route["mode"], "code")
        self.assertEqual(route["action"], "code_artifact")
        self.assertEqual(set(route["tools"]), {"file", "write", "edit", "list", "search"})

    def test_downloadable_file_request_is_routed_to_download_tool(self):
        route = self.router.route("Crée un fichier texte à télécharger", lambda *_: None)

        self.assertEqual(route["mode"], "tool")
        self.assertIn("create_download", route["tools"])

    def test_download_request_keeps_download_route_before_generic_file_creation(self):
        route = self.router.route("Crée un fichier texte à télécharger", lambda *_: None)

        self.assertEqual(route["action"], "download")
        self.assertEqual(route["tools"], ("create_download",))

    def test_application_installation_uses_system_tool(self):
        route = self.router.route("Installe Firefox", lambda *_: None)

        self.assertEqual(route["mode"], "tool")
        self.assertEqual(route["action"], "install_application")
        self.assertEqual(route["tools"], ("system",))

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
        prompt = ToolManager.build_prompt({"file", "search", "write"})
        self.assertIn("file :", prompt)
        self.assertIn("search :", prompt)
        self.assertIn("append:true", prompt)
        self.assertIn("En cas de reprise", prompt)
        self.assertNotIn("command :", prompt)
        self.assertNotIn("system :", prompt)

    def test_document_tool_prompt_explains_safe_actions(self):
        prompt = ToolManager.build_prompt({"document"})

        self.assertIn("sqlite_query", prompt)
        self.assertIn("SELECT/WITH", prompt)
        self.assertIn("create_archive", prompt)
        self.assertIn("confirmation utilisateur", prompt)

    def test_tool_manager_executes_calculator(self):
        result = ToolManager.execute(
            {"tool": "calculator", "arguments": {"expression": "sqrt(81) + 12 * 3"}},
            {},
            None,
            allowed_tools={"calculator"},
        )
        self.assertEqual(result, {"expression": "sqrt(81) + 12 * 3", "result": 45.0})

    def test_empty_tool_selection_has_no_tool_prompt(self):
        self.assertEqual(ToolManager.build_prompt(set()), "")

    def test_route_tools_respect_server_allowlist(self):
        route = {"mode": "tool", "tools": ("file", "search", "edit")}
        self.assertEqual(ToolManager.get_tools(route, {"file", "command"}), {"file"})

    def test_agent_route_defaults_to_all_allowed_tools(self):
        route = {"mode": "agent", "tools": None}
        self.assertEqual(
            ToolManager.get_tools(route),
            {"memory", "context", "file", "write", "edit", "list", "search", "launch", "command", "system", "web", "open_page", "calculator", "create_download", "document"},
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
        self.assertEqual(LocalAgent.get_max_tool_steps({"mode": "code"}), 8)
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

    def test_prompt_cache_tracks_the_current_request(self):
        agent = LocalAgent.__new__(LocalAgent)
        agent.model = "dummy"
        agent.context = {"langue": "français", "role": "assistant local"}
        agent.memories = []
        agent.context_compiler = ContextCompiler()
        agent._prepared_prompts = {}
        agent._tool_cache = {}
        route = {"mode": "code", "action": "code_artifact", "tools": ("write", "edit")}
        chat = {"id": 11, "topic": "tests", "messages": []}

        first = agent.prepare_chat(chat, message="Crée un fichier alpha.py", route=route, tools=("write", "edit"))
        second = agent.prepare_chat(chat, message="Crée un fichier beta.py", route=route, tools=("write", "edit"))

        self.assertIsNot(first, second)
        self.assertIn("alpha.py", first[0])
        self.assertIn("beta.py", second[0])

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

    def test_command_suggestion_prompt_forbids_execution(self):
        prompt = ContextCompiler().compile(
            {"messages": []},
            {"langue": "français", "role": "assistant local"},
            [],
            message="Quelle commande pour lancer Firefox ?",
            route={"mode": "command_suggestion", "action": "command_suggestion", "tools": ()},
            allow_tools=set(),
        )

        self.assertIn("commande exacte dans un bloc de code", prompt)
        self.assertIn("pas son exécution", prompt)
        self.assertNotIn("command :", prompt)

    def test_code_prompt_requires_a_file_artifact(self):
        prompt = ContextCompiler().compile(
            {"messages": []},
            {"langue": "français", "role": "assistant local"},
            [],
            message="Écris un script Python",
            route={"mode": "code", "action": "code_artifact", "tools": ("write",)},
            allow_tools={"write"},
        )

        self.assertIn("uniquement un appel <tool_call>", prompt)
        self.assertIn("write ou edit", prompt)
        self.assertIn("nom descriptif", prompt)

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
