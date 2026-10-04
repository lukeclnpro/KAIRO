#!/usr/bin/env python3
"""Tests des actions sur le PC : voie rapide, boucle d'outils, edit/list/search."""

from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import date as date_type
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import application_launcher
import file_commands
from local_ia.core.agent import LocalAgent
from local_ia.tools import command, download as download_tool, edit, listing, search, system
from local_ia.tools.file import normalize_path


def tool(name, **arguments):
    import json
    return "<tool_call>" + json.dumps({"tool": name, "arguments": arguments}) + "</tool_call>"


class ActionTestCase(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.tmp = Path(self.directory.name).resolve()
        file_commands.set_access_roots([self.tmp])
        backups = patch.object(edit, "BACKUP_DIR", self.tmp / ".backups")
        backups.start()
        self.addCleanup(backups.stop)
        self.agent = LocalAgent(model="test")

    def tearDown(self):
        self.agent.close()
        file_commands.set_access_roots([ROOT])
        self.directory.cleanup()

    def ask(self, *answers):
        iterator = iter(answers)
        return patch("local_ia.core.agent.ask_ollama", side_effect=lambda *a, **k: next(iterator))


class FastPathTest(ActionTestCase):
    def test_launch_without_calling_the_model(self):
        app = {"name": "Firefox", "argv": ["firefox"]}
        with patch.object(application_launcher, "find_application", return_value=app), \
             patch.object(application_launcher, "launch_application", return_value=app) as launch, \
             patch("local_ia.core.agent.ask_ollama") as ask:
            answer = self.agent.respond({"messages": []}, "ouvre firefox")
        self.assertEqual(answer, "Firefox lancé.")
        launch.assert_called_once_with("firefox")
        ask.assert_not_called()

    def test_first_person_app_launch_runs_without_calling_the_model(self):
        app = {"name": "Firefox", "argv": ["firefox"]}
        with patch.object(application_launcher, "find_application", return_value=app), \
             patch.object(application_launcher, "launch_application", return_value=app) as launch, \
             patch("local_ia.core.agent.ask_ollama") as ask:
            answer = self.agent.respond({"messages": []}, "Je veux lancer Firefox")

        self.assertEqual(answer, "Firefox lancé.")
        launch.assert_called_once_with("Firefox")
        ask.assert_not_called()

    def test_unknown_application_falls_back_to_the_model(self):
        with patch.object(application_launcher, "find_application", return_value=None), \
             self.ask("Je ne trouve pas cette application.") as ask:
            answer = self.agent.respond({"messages": []}, "ouvre zzzzapp")
        self.assertEqual(answer, "Je ne trouve pas cette application.")
        self.assertEqual(ask.call_count, 1)

    def test_file_requests_are_not_treated_as_applications(self):
        with patch.object(application_launcher, "find_application") as find:
            self.assertIsNone(self.agent.fast_path("ouvre le fichier notes.txt"))
        find.assert_not_called()


class LocalCodeAgentTest(ActionTestCase):
    def test_deferred_single_file_retries_prose_as_a_write_call(self):
        target = self.tmp / "notes.py"
        responses = iter([
            '{"steps":["Créer le fichier Python demandé"]}',
            "Je vais préparer le fichier.",
            tool("write", path=str(target), content="print('bonjour')\n"),
        ])
        used_keys = []

        def fake_ask(_messages, api_key=None, **_kwargs):
            used_keys.append(api_key)
            return next(responses)

        chat = {"messages": []}
        with patch.dict(
            "os.environ",
            {"LOCAL_IA_OPENROUTER_KEYS": '["key-one","key-two"]'},
            clear=False,
        ), patch("local_ia.core.agent.ask_ollama", side_effect=fake_ask):
            proposal = self.agent.respond(
                chat,
                "Crée un fichier Python",
                allowed_tools={"file", "list", "search", "write", "edit"},
                local_code=True,
                defer_file_actions=True,
            )

        self.assertEqual(used_keys, ["key-one", "key-two", "key-two"])
        command = LocalAgent.parse_tool_call(proposal)
        self.assertEqual(command["tool"], "write")
        self.assertFalse(target.exists())
        self.agent.apply_approved_file_call(proposal, chat, allowed_tools={"write"})
        self.assertEqual(target.read_text(encoding="utf-8"), "print('bonjour')\n")

    def test_code_subtasks_are_assigned_to_distinct_keys_and_wait_for_approval(self):
        responses = iter([
            '{"steps":["Créer la page HTML", "Créer la feuille de style"]}',
            tool("write", path=str(self.tmp / "index.html"), content="<h1>Accueil</h1>\n"),
            tool("write", path=str(self.tmp / "style.css"), content="body { color: black; }\n"),
        ])
        used_keys = []

        def fake_ask(_messages, api_key=None, **_kwargs):
            used_keys.append(api_key)
            return next(responses)

        chat = {"messages": []}
        with patch.dict(
            "os.environ",
            {"LOCAL_IA_OPENROUTER_KEYS": '["key-one","key-two"]'},
            clear=False,
        ), patch("local_ia.core.agent.ask_ollama", side_effect=fake_ask):
            proposal = self.agent.respond(
                chat,
                "Crée un site web avec une page d'accueil et une feuille de style",
                allowed_tools={"file", "list", "search", "write", "edit"},
                local_code=True,
                defer_file_actions=True,
            )

        commands = LocalAgent.parse_file_command_plan(proposal)
        self.assertEqual(used_keys, ["key-one", "key-two", "key-one"])
        self.assertEqual(len(commands), 2)
        self.assertFalse((self.tmp / "index.html").exists())
        self.assertFalse((self.tmp / "style.css").exists())

        result = self.agent.apply_approved_file_call(proposal, chat, allowed_tools={"write"})
        self.assertIn("index.html", result)
        self.assertIn("style.css", result)
        self.assertTrue((self.tmp / "index.html").is_file())
        self.assertTrue((self.tmp / "style.css").is_file())

    def test_failed_code_subtask_restarts_without_losing_completed_steps(self):
        html_path = self.tmp / "index.html"
        css_path = self.tmp / "style.css"
        responses = iter([
            '{"steps":["Créer la page HTML", "Créer la feuille de style"]}',
            tool("write", path=str(html_path), content="<h1>Accueil</h1>\n"),
            "Je vais créer le CSS.",
            tool("write", path=str(css_path), content="body { color: #222; }\n"),
        ])
        used_keys = []

        def fake_ask(_messages, api_key=None, **_kwargs):
            used_keys.append(api_key)
            return next(responses)

        chat = {"messages": []}
        with patch.dict(
            "os.environ",
            {"LOCAL_IA_OPENROUTER_KEYS": '["key-one","key-two"]'},
            clear=False,
        ), patch("local_ia.core.agent.ask_ollama", side_effect=fake_ask), \
             patch("local_ia.core.agent.MAX_TOOL_STEPS", 1):
            proposal = self.agent.respond(
                chat,
                "Crée un site simple avec HTML et CSS",
                allowed_tools={"file", "list", "search", "write", "edit"},
                local_code=True,
                defer_file_actions=True,
            )

        commands = LocalAgent.parse_file_command_plan(proposal)
        self.assertEqual(len(commands), 2)
        self.assertEqual(used_keys, ["key-one", "key-two", "key-one", "key-two"])
        self.assertFalse(html_path.exists())
        self.assertFalse(css_path.exists())
        self.agent.apply_approved_file_call(proposal, chat, allowed_tools={"write"})
        self.assertTrue(html_path.is_file())
        self.assertEqual(css_path.read_text(encoding="utf-8"), "body { color: #222; }\n")

    def test_deferred_file_command_does_not_write_until_approved(self):
        target = self.tmp / "approved.py"
        chat = {"messages": []}
        proposal = tool("write", path=str(target), content="print('approved')\n")
        with self.ask(proposal) as ask:
            command = self.agent.respond(
                chat,
                "Crée un script Python",
                allowed_tools={"file", "write", "edit"},
                local_code=True,
                defer_file_actions=True,
            )

        self.assertEqual(ask.call_count, 1)
        self.assertEqual(LocalAgent.parse_tool_call(command), LocalAgent.parse_tool_call(proposal))
        self.assertFalse(target.exists())
        result = self.agent.apply_approved_file_call(command, chat, allowed_tools={"write"})
        self.assertIn("Fichier créé ou modifié", result)
        self.assertEqual(target.read_text(encoding="utf-8"), "print('approved')\n")

    def test_deferred_file_command_respects_disabled_write_permission(self):
        target = self.tmp / "forbidden.py"
        with self.ask(tool("write", path=str(target), content="print('no')\n")):
            answer = self.agent.respond(
                {"messages": []},
                "Crée un script Python",
                allowed_tools={"file"},
                local_code=True,
                defer_file_actions=True,
            )

        self.assertIn("écriture de fichiers est désactivée", answer)
        self.assertFalse(target.exists())

    def test_python_script_response_creates_a_download_artifact(self):
        answer = "```python\ndef calculatrice():\n    return 2 + 2\n```"
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(download_tool, "CACHE_DIR", Path(directory)), \
             patch.object(download_tool, "GENERATED_FILES_DIR", Path(directory) / "generated"), \
             self.ask(answer, answer) as ask:
            response = self.agent.respond(
                {"messages": []},
                "crée un script python de calculatrice",
            )

            self.assertEqual(ask.call_count, 2)
            self.assertEqual(response, answer)
            self.assertEqual(len(self.agent.generated_downloads), 1)
            artifact = self.agent.generated_downloads[0]
            self.assertEqual(artifact["filename"], "calculatrice.py")
            cached_file = download_tool.resolve_cached_file(artifact["artifact_id"], artifact["filename"])
            self.assertEqual(cached_file.read_text(encoding="utf-8"), "def calculatrice():\n    return 2 + 2\n")
            persistent_file = download_tool.GENERATED_FILES_DIR / "calculatrice.py"
            self.assertEqual(persistent_file.read_text(encoding="utf-8"), cached_file.read_text(encoding="utf-8"))

    def test_download_tool_creates_verified_cache_artifact(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(
            download_tool, "CACHE_DIR", Path(directory)
        ), patch.object(download_tool, "GENERATED_FILES_DIR", Path(directory) / "generated"), self.ask(
            tool("create_download", filename="rapport", content="Résultat\n", extension="txt")
        ) as ask:
            answer = self.agent.respond(
                {"messages": []},
                "Crée un fichier texte à télécharger",
                allowed_tools={"create_download"},
            )

            self.assertEqual(ask.call_count, 1)
            self.assertEqual(answer, "Fichier prêt à télécharger : rapport.txt")
            self.assertEqual(len(self.agent.generated_downloads), 1)
            artifact = self.agent.generated_downloads[0]
            cached_file = download_tool.resolve_cached_file(artifact["artifact_id"], artifact["filename"])
            self.assertEqual(cached_file.read_text(encoding="utf-8"), "Résultat\n")

    def test_local_code_creates_script_from_markdown_wrapped_tool_call(self):
        script_path = self.tmp / "demonstration.py"
        tool_call = tool(
            "write",
            path=str(script_path),
            content='def greet(name):\n    return f"Bonjour, {name} !"\n\nprint(greet("KAIRO"))\n',
        )
        markdown_call = f"J'ai préparé le script.\n```xml\n{tool_call}\n```"
        with self.ask(markdown_call, "Le script de démonstration est créé et prêt à lancer.") as ask:
            answer = self.agent.respond(
                {"messages": []},
                "crée un script pour faire une démonstration",
                allowed_tools={"file", "write"},
                local_code=True,
            )

        self.assertEqual(ask.call_count, 2)
        self.assertIn("Bonjour, {name}", script_path.read_text(encoding="utf-8"))
        self.assertIn("démonstration", answer)

    def test_local_code_agent_recovers_from_plan_and_continues_after_write(self):
        created_file = self.tmp / "index.html"
        with self.ask(
            "Je vais créer un plan puis le fichier HTML.",
            tool("write", path=str(created_file), content="<h1>dashboard</h1>"),
            "Le fichier est relu et le projet est terminé.",
        ) as ask:
            answer = self.agent.respond(
                {"messages": []},
                "crée une page html",
                allowed_tools={"file", "write"},
                local_code=True,
            )

        self.assertEqual(ask.call_count, 3)
        self.assertTrue(all(call.kwargs["max_tokens"] == 4096 for call in ask.call_args_list))
        self.assertEqual(created_file.read_text(encoding="utf-8"), "<h1>dashboard</h1>")
        self.assertEqual(answer, "Le fichier est relu et le projet est terminé.")

    def test_natural_code_request_creates_a_file(self):
        script_path = self.tmp / "trier_liste.py"
        progress = []
        with self.ask(
            tool("write", path=str(script_path), content="def trier(valeurs):\n    return sorted(valeurs)\n")
        ) as ask:
            answer = self.agent.respond(
                {"messages": []},
                "Écris un script Python qui trie une liste",
                progress_callback=progress.append,
            )

        self.assertEqual(self.agent.last_route["mode"], "code")
        self.assertTrue(script_path.is_file())
        self.assertIn("trier_liste.py", answer)
        self.assertEqual(ask.call_count, 1)
        self.assertTrue(any("Étape 1/8" in item for item in progress))
        self.assertIn("Action terminée; résultat vérifié.", progress)

    def test_explicit_application_path_is_saved_and_reusable_by_name(self):
        application_path = self.tmp / "ZapZap App"
        application_path.write_text("#!/bin/sh\n", encoding="utf-8")
        application_path.chmod(0o755)
        registry_path = self.tmp / "applications.json"

        with patch.object(application_launcher, "_registry_path", return_value=registry_path), \
             patch.object(application_launcher.subprocess, "Popen") as process:
            answer = self.agent.respond({"messages": []}, f"lance {application_path}")
            saved_application = application_launcher.find_application("ZapZap App")

        self.assertEqual(answer, "ZapZap App lancé.")
        self.assertEqual(saved_application["path"], str(application_path))
        self.assertEqual(saved_application["argv"], [str(application_path)])
        self.assertTrue(registry_path.is_file())
        process.assert_called_once()

    def test_application_path_in_a_statement_is_saved_without_launching(self):
        application_path = self.tmp / "ZapZap App"
        application_path.write_text("#!/bin/sh\n", encoding="utf-8")
        application_path.chmod(0o755)
        registry_path = self.tmp / "applications.json"

        with patch.object(application_launcher, "_registry_path", return_value=registry_path), \
             patch.object(application_launcher.subprocess, "Popen") as process, \
             patch("local_ia.core.agent.ask_ollama") as ask:
            answer = self.agent.respond(
                {"messages": []},
                f"Le chemin de l'application ZapZap est {application_path}",
            )
            saved_application = application_launcher.find_application("ZapZap App")

        self.assertEqual(answer, "Chemin de ZapZap App enregistré sous le nom ZapZap.")
        self.assertEqual(saved_application["path"], str(application_path))
        process.assert_not_called()
        ask.assert_not_called()

    def test_application_alias_is_saved_and_common_typo_resolves(self):
        application_path = self.tmp / "ZapZap"
        application_path.write_text("#!/bin/sh\n", encoding="utf-8")
        application_path.chmod(0o755)
        registry_path = self.tmp / "applications.json"

        with patch.object(application_launcher, "_registry_path", return_value=registry_path), \
             patch.object(application_launcher.shutil, "which", return_value=str(application_path)), \
             patch.object(application_launcher.subprocess, "Popen") as process, \
             patch("local_ia.core.agent.ask_ollama") as ask:
            answer = self.agent.respond(
                {"messages": []}, "sur mon pc, whatsapp est zapzap"
            )
            found = application_launcher.find_application("watsapp")
            found_with_typo = application_launcher.find_application("wharsapp")
            launch_answer = self.agent.respond({"messages": []}, "lance watsapp")

        self.assertEqual(answer, "whatsapp associé à ZapZap pour les prochains lancements.")
        self.assertEqual(found["path"], str(application_path))
        self.assertEqual(found["name"], "ZapZap")
        self.assertEqual(found_with_typo["path"], str(application_path))
        self.assertEqual(launch_answer, "ZapZap lancé.")
        process.assert_called_once()
        ask.assert_not_called()

    def test_followup_app_name_correction_uses_failed_launch_context(self):
        chat = {
            "messages": [
                {"role": "user", "content": "lance whatsapp"},
                {"role": "assistant", "content": "WhatsApp ne semble pas installé."},
            ],
        }
        application = {"name": "ZapZap", "argv": ["zapzap"], "path": "/usr/bin/zapzap"}
        with patch.object(
            application_launcher, "register_application_alias", return_value=application
        ) as register, patch.object(
            application_launcher, "launch_application", return_value=application
        ) as launch, patch("local_ia.core.agent.ask_ollama") as ask:
            answer = self.agent.respond(chat, "elle s'apelle zapzap")

        self.assertEqual(answer, "ZapZap associé à whatsapp et lancé.")
        register.assert_called_once_with("whatsapp", "zapzap")
        launch.assert_called_once_with("whatsapp")
        ask.assert_not_called()

    def test_copied_tool_call_is_not_mistaken_for_an_application_path(self):
        pasted_call = (
            'Je vais lancer ZapZap. <tool_call>{"tool":"launch",'
            '"arguments":{"name":"ZapZap"}}</tool_call>'
        )
        with patch.object(application_launcher, "register_application") as register, \
             self.ask("Je peux traiter cette demande normalement.") as ask:
            answer = self.agent.respond({"messages": []}, pasted_call)

        self.assertEqual(answer, "Je peux traiter cette demande normalement.")
        register.assert_not_called()
        self.assertEqual(ask.call_count, 1)

    def test_respects_allowed_tools(self):
        with patch.object(application_launcher, "find_application") as find:
            self.assertIsNone(self.agent.fast_path("ouvre firefox", allowed_tools={"file"}))
        find.assert_not_called()

    def test_volume(self):
        with patch.object(system, "use", return_value={"returncode": 0}) as use:
            self.assertEqual(self.agent.fast_path("baisse le volume de 20"), "Volume baissé.")
            self.assertEqual(self.agent.fast_path("coupe le son"), "Son coupé.")
        self.assertEqual(use.call_args_list[0].args, ("down", None, 20))
        self.assertIsNone(self.agent.fast_path("écris un poème sur le son de la mer"))

    def test_system_info_is_answered_without_ollama(self):
        info = {"system": "Linux", "release": "6.1", "machine": "x86_64"}
        with patch.object(system, "use", return_value=info) as use, \
             patch("local_ia.core.agent.ask_ollama") as ask:
            answer = self.agent.respond({"messages": []}, "Quel système d'exploitation j'utilise ?")
        self.assertEqual(answer, "Système : Linux 6.1 (x86_64)")
        use.assert_called_once_with("info")
        ask.assert_not_called()
        self.assertEqual(self.agent.last_route["mode"], "direct")
        self.assertEqual(self.agent.last_route["action"], "fast_path")

    def test_current_date_is_answered_without_ollama(self):
        with patch("local_ia.core.agent.date") as current_date, \
             patch("local_ia.core.agent.ask_ollama") as ask:
            current_date.today.return_value = date_type(2026, 9, 28)
            answer = self.agent.respond({"messages": []}, "on est quel jour ?")
        self.assertEqual(answer, "Aujourd'hui, nous sommes le lundi 28 septembre 2026.")
        ask.assert_not_called()
        self.assertEqual(self.agent.last_route["mode"], "direct")

    def test_system_info_fast_path_respects_tool_permissions(self):
        with patch.object(system, "use") as use:
            answer = self.agent.fast_path("Quel système d'exploitation j'utilise ?", allowed_tools={"file"})
        self.assertIsNone(answer)
        use.assert_not_called()


class ToolLoopTest(ActionTestCase):
    def test_messages_sent_to_model_include_history_importance(self):
        chat = {"id": 42, "topic": "tests", "messages": [
            {"role": "user", "content": "question précédente"},
        ]}

        messages = self.agent.build_messages(chat, "question actuelle")

        self.assertIn("[Importance: 100%] question précédente", messages[1]["content"])
        self.assertEqual(messages[-1], {"role": "user", "content": "question actuelle"})
        self.assertEqual(chat["messages"][0]["content"], "question précédente")

    def test_system_prompt_is_prepared_once_per_chat(self):
        chat = {"id": 42, "topic": "tests", "messages": []}
        with patch("local_ia.core.context_compiler.build_system_prompt", return_value="prompt") as build_prompt:
            first = self.agent.build_messages(chat, "premier message")
            second = self.agent.build_messages(chat, "deuxième message")
        self.assertEqual(build_prompt.call_count, 1)
        self.assertEqual(first[0]["content"], second[0]["content"])

    def test_simple_question_does_not_send_tool_definitions(self):
        with self.ask("Rome.") as ask:
            self.agent.respond({"messages": []}, "Quelle est la capitale de l'Italie ?")
        system_prompt = ask.call_args.args[0][0]["content"]
        self.assertNotIn("file :", system_prompt)
        self.assertNotIn("command :", system_prompt)
        self.assertNotIn("system :", system_prompt)
        self.assertIn("sans répétition", system_prompt)

    def test_multiple_keys_split_chat_into_minimal_steps_and_verify_globally(self):
        responses = iter([
            '{"steps":["Expliquer la capitale", "Donner un fait utile"]}',
            "Rome est la capitale de l'Italie.",
            "Elle est située dans la région du Latium.",
            '{"correct":true,"issues":[]}',
        ])
        used_keys = []

        def fake_ask(_messages, api_key=None, **_kwargs):
            used_keys.append(api_key)
            return next(responses)

        progress = []
        with patch.dict(
            "os.environ",
            {"LOCAL_IA_OPENROUTER_KEYS": '["key-one","key-two"]'},
            clear=False,
        ), patch("local_ia.core.agent.ask_ollama", side_effect=fake_ask):
            answer = self.agent.respond(
                {"messages": []},
                "Quelle est la capitale de l'Italie et quel fait utile puis-je retenir ?",
                progress_callback=progress.append,
            )

        self.assertIn("Rome est la capitale", answer)
        self.assertIn("région du Latium", answer)
        self.assertEqual(used_keys, ["key-one", "key-two", "key-one", "key-two"])
        self.assertIn("Vérification globale de la réponse…", progress)
        self.assertIn("Réponse vérifiée globalement.", progress)

    def test_global_verifier_triggers_one_repair_phase_and_rechecks(self):
        responses = iter([
            '{"steps":["Répondre à la question"]}',
            "La capitale est Roma.",
            '{"correct":false,"issues":["Nom de ville non francisé"]}',
            "La capitale est Rome.",
            '{"correct":true,"issues":[]}',
        ])
        used_keys = []

        def fake_ask(_messages, api_key=None, **_kwargs):
            used_keys.append(api_key)
            return next(responses)

        with patch.dict(
            "os.environ",
            {"LOCAL_IA_OPENROUTER_KEYS": '["key-one","key-two"]'},
            clear=False,
        ), patch("local_ia.core.agent.ask_ollama", side_effect=fake_ask):
            answer = self.agent.respond({"messages": []}, "Quelle est la capitale de l'Italie ?")

        self.assertEqual(answer, "La capitale est Rome.")
        self.assertEqual(used_keys, ["key-one", "key-two", "key-one", "key-two", "key-one"])

    def test_tool_steps_use_keys_in_order_and_verify_final_answer(self):
        responses = iter([
            '{"steps":["Lister le contenu du dossier"]}',
            tool("list", path=str(self.tmp)),
            "Le dossier contient les fichiers du projet.",
            '{"correct":true,"issues":[]}',
        ])
        used_keys = []

        def fake_ask(_messages, api_key=None, **_kwargs):
            used_keys.append(api_key)
            return next(responses)

        with patch.dict(
            "os.environ",
            {"LOCAL_IA_OPENROUTER_KEYS": '["key-one","key-two"]'},
            clear=False,
        ), patch("local_ia.core.agent.ask_ollama", side_effect=fake_ask), patch.object(
            self.agent, "execute_tool", return_value={"entries": ["README.md"]}
        ) as execute:
            answer = self.agent.respond({"messages": []}, "Liste le dossier")

        self.assertEqual(answer, "Le dossier contient les fichiers du projet.")
        self.assertEqual(used_keys, ["key-one", "key-two", "key-one", "key-two"])
        execute.assert_called_once()

    def test_command_suggestion_returns_copyable_argv_without_execution(self):
        response = tool("command", argv=["flatpak", "install", "flathub", "org.mozilla.firefox"])
        with self.ask(response), patch.object(self.agent, "execute_tool") as execute:
            answer = self.agent.respond(
                {"messages": []},
                "Quelle commande pour installer Firefox ?",
            )

        self.assertEqual(
            answer,
            "Commande à copier :\n```sh\nflatpak install flathub org.mozilla.firefox\n```",
        )
        execute.assert_not_called()

    def test_code_request_gets_filesystem_tools_without_system_tools(self):
        allowed = {"file", "write", "edit", "list", "search", "command"}
        with self.ask("Je vais lire le fichier.") as ask:
            self.agent.respond({"messages": []}, "Corrige le bug dans app.py", allowed_tools=allowed)
        system_prompt = ask.call_args.args[0][0]["content"]
        self.assertIn("file :", system_prompt)
        self.assertIn("search :", system_prompt)
        self.assertIn("command :", system_prompt)
        self.assertNotIn("launch :", system_prompt)
        self.assertNotIn("system :", system_prompt)

    def test_server_allowlist_removes_disallowed_tools_from_prompt(self):
        allowed = {"file", "search", "edit"}
        with self.ask("Je vais examiner le fichier.") as ask:
            self.agent.respond({"messages": []}, "Corrige le bug dans app.py", allowed_tools=allowed)
        system_prompt = ask.call_args.args[0][0]["content"]
        self.assertIn("edit :", system_prompt)
        self.assertNotIn("command :", system_prompt)
        self.assertNotIn("system :", system_prompt)

    def test_simple_action_costs_a_single_model_call(self):
        target = str(self.tmp / "note.txt")
        with self.ask(tool("write", path=target, content="salut")) as ask:
            answer = self.agent.respond({"messages": []}, "crée note.txt avec salut")
        self.assertEqual(ask.call_count, 1)
        self.assertIn("note.txt", answer)
        self.assertEqual(Path(target).read_text(), "salut")

    def test_model_cannot_claim_write_success_without_readback_proof(self):
        target = self.tmp / "missing.txt"
        fake_result = {"path": str(target), "size": 4, "content": "done"}
        with self.ask(
            tool("write", path=str(target), content="done"),
            "Le fichier a été créé avec succès.",
        ) as ask, patch.object(self.agent, "execute_tool", return_value=fake_result):
            answer = self.agent.respond({"messages": []}, "crée missing.txt")

        self.assertEqual(
            answer,
            "Je n'ai pas pu confirmer que le contenu attendu est bien enregistré; je ne peux pas annoncer la création comme terminée.",
        )
        self.assertEqual(ask.call_count, 2)
        self.assertIn('"verified":false', ask.call_args.args[0][-1]["content"])

    def test_agent_writes_large_files_as_ordered_chunks(self):
        target = self.tmp / "large.txt"
        answers = [tool("write", path=str(target), content="part-0", append=False)]
        answers.extend(
            tool("write", path=str(target), content=f"|part-{index}", append=True)
            for index in range(1, 7)
        )
        answers.append("Le fichier complet a été écrit en blocs.")
        with self.ask(*answers) as ask:
            answer = self.agent.respond(
                {"messages": []}, "crée un très grand fichier large.txt"
            )

        self.assertEqual(answer, "Le fichier complet a été écrit en blocs.")
        self.assertEqual(ask.call_count, 8)
        self.assertEqual(target.read_text(encoding="utf-8"), "|".join(f"part-{i}" for i in range(7)))

    def test_chained_request_still_asks_the_model_after_the_tool(self):
        target = str(self.tmp / "note.txt")
        with self.ask(tool("write", path=target, content="a"), "Fichier créé, tout est prêt.") as ask:
            answer = self.agent.respond({"messages": []}, "crée note.txt puis dis-moi quand c'est prêt")
        self.assertEqual(ask.call_count, 2)
        self.assertEqual(answer, "Fichier créé, tout est prêt.")

    def test_fixes_a_bug_read_edit_run(self):
        script = self.tmp / "app.py"
        script.write_text("print(valeur)\n", encoding="utf-8")
        answers = (
            tool("file", path=str(script)),
            tool("edit", path=str(script), old="print(valeur)", new="print('ok')"),
            tool("command", argv=[sys.executable, str(script)], cwd=str(self.tmp)),
            "Bug corrigé : le script affiche ok.",
        )
        chat = {"messages": []}
        done = {"command": [sys.executable, str(script)], "returncode": 0, "stdout": "ok\n", "stderr": ""}
        with self.ask(*answers) as ask, patch(
            "local_ia.tools.command.execute_argv", return_value=done
        ) as execute:
            answer = self.agent.respond(chat, "corrige le bug de app.py")
            self.assertIn("Confirmation nécessaire", answer)
            self.assertIn("pending_tool", chat)
            answer = self.agent.respond(chat, "oui")
        self.assertEqual(ask.call_count, 4)
        self.assertEqual(answer, "Bug corrigé : le script affiche ok.")
        execute.assert_called_once_with(
            [sys.executable, str(script)],
            timeout=command.DEFAULT_TIMEOUT,
            cwd=str(self.tmp),
        )
        self.assertEqual(script.read_text(), "print('ok')\n")
        last_tool_message = ask.call_args.args[0][-1]
        self.assertEqual(last_tool_message["role"], "tool")
        self.assertIn('"stdout":"ok', last_tool_message["content"])

    def test_tool_error_is_given_back_to_the_model(self):
        script = self.tmp / "a.py"
        script.write_text("x = 1\n", encoding="utf-8")
        with self.ask(tool("edit", path=str(script), old="absent", new="y"), "Je relis le fichier.") as ask:
            answer = self.agent.respond({"messages": []}, "corrige a.py")
        self.assertEqual(
            answer,
            "Je n'ai pas pu confirmer la modification sur disque; je ne peux pas annoncer la correction comme terminée.",
        )
        self.assertIn("n'a pas abouti", ask.call_args.args[0][-1]["content"])
        self.assertNotIn("introuvable", ask.call_args.args[0][-1]["content"])

    def test_model_repeating_itself_is_stopped(self):
        call = tool("list", path=str(self.tmp))
        with self.ask(call, call, call, call) as ask:
            answer = self.agent.respond({"messages": []}, "liste le dossier")
        self.assertEqual(
            answer,
            "J'ai arrêté l'action list après une répétition pour éviter de tourner en rond.",
        )
        self.assertEqual(ask.call_count, 2)

    def test_tool_step_limit_does_not_claim_request_is_complete(self):
        calls = [
            tool("list", path=str(self.tmp / f"directory-{index}"))
            for index in range(4)
        ]
        with self.ask(*calls) as ask, patch.object(
            self.agent, "execute_tool", return_value={"entries": []}
        ) as execute:
            answer = self.agent.respond({"messages": []}, "liste le dossier")

        self.assertIn("arrêté après 3 actions", answer)
        self.assertIn("pas confirmée comme terminée", answer)
        self.assertEqual(execute.call_count, 3)
        self.assertEqual(ask.call_count, 4)

    def test_missing_argument_gives_a_readable_error(self):
        with self.assertRaisesRegex(ValueError, "old"):
            self.agent.execute_tool({"tool": "edit", "arguments": {"path": "x", "new": "y"}}, {})

    def test_large_results_are_truncated_for_the_model(self):
        big = self.tmp / "big.txt"
        big.write_text("a" * 50000, encoding="utf-8")
        with self.ask(tool("file", path=str(big)), "Fichier lu.") as ask:
            self.agent.respond({"messages": []}, "lis big.txt")
        self.assertLess(len(ask.call_args.args[0][-1]["content"]), 7000)


class ConfirmationTest(ActionTestCase):
    def test_application_installation_uses_catalog_action_and_requests_confirmation(self):
        confirmation = {
            "confirmation_required": True,
            "message": "Confirme l'installation de Firefox.",
        }
        with self.ask(tool("system", action="install_app", value="Firefox")) as ask, patch(
            "local_ia.core.tool_manager.system.use", return_value=confirmation
        ) as install:
            answer = self.agent.respond({"messages": []}, "Installe Firefox")

        self.assertIn("Confirme l'installation", answer)
        install.assert_called_once_with("install_app", "Firefox", 5, False)
        self.assertIn("install_app|install|update", ask.call_args.args[0][0]["content"])

    def test_risky_command_needs_confirmation_then_runs(self):
        chat = {"messages": []}
        with self.ask(tool("command", argv=["rm", "-rf", str(self.tmp / "x")])) as ask:
            answer = self.agent.respond(chat, "supprime le dossier x")
        self.assertIn("Confirmation nécessaire", answer)
        self.assertEqual(ask.call_count, 1)
        self.assertIn("pending_tool", chat)

        done = {"command": ["rm"], "returncode": 0, "stdout": "", "stderr": ""}
        with patch("local_ia.tools.command.execute_argv", return_value=done) as run, \
             self.ask("Dossier supprimé.") as ask:
            answer = self.agent.respond(chat, "oui")
        run.assert_called_once()
        self.assertEqual(answer, "Dossier supprimé.")
        self.assertNotIn("pending_tool", chat)

    def test_harmless_command_needs_no_confirmation(self):
        self.assertFalse(command.is_risky(["echo", "hello"]))
        self.assertTrue(command.is_risky(["python3", "x.py"]))

    def test_dangerous_commands_stay_risky_through_wrappers(self):
        wrapped_commands = (
            ["nice", "-n", "10", "rm", "-rf", "/tmp/data"],
            ["time", "-o", "/tmp/time.log", "rm", "-rf", "/tmp/data"],
            ["xargs", "-I", "{}", "rm", "-rf", "/tmp/data"],
            ["env", "-S", "rm -rf /tmp/data"],
        )
        for argv in wrapped_commands:
            with self.subTest(argv=argv):
                self.assertTrue(command.is_risky(argv))

        for argv in (["rm", "a"], ["/bin/rm", "a"], ["sudo", "ls"], ["mkfs.ext4", "/dev/x"], ["kill", "1"]):
            self.assertTrue(command.is_risky(argv), argv)


class EditToolTest(ActionTestCase):
    def test_replaces_once_and_keeps_a_backup(self):
        path = self.tmp / "a.py"
        path.write_text("a = 1\nb = 2\n", encoding="utf-8")
        result = edit.use(str(path), "b = 2", "b = 3")
        self.assertEqual(path.read_text(), "a = 1\nb = 3\n")
        self.assertTrue(result["syntax_ok"])
        self.assertEqual(Path(result["backup"]).read_text(), "a = 1\nb = 2\n")

    def test_rejects_ambiguous_and_missing_text(self):
        path = self.tmp / "a.txt"
        path.write_text("x\nx\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "2 fois"):
            edit.use(str(path), "x", "y")
        with self.assertRaisesRegex(ValueError, "introuvable"):
            edit.use(str(path), "zzz", "y")
        self.assertEqual(edit.use(str(path), "x", "y", replace_all=True)["replacements"], 2)

    def test_backups_do_not_overwrite_each_other_with_same_timestamp(self):
        path = self.tmp / "version.txt"
        path.write_text("v0", encoding="utf-8")
        with patch("local_ia.tools.edit.time.strftime", return_value="same-time"):
            first = edit.use(str(path), "v0", "v1")["backup"]
            second = edit.use(str(path), "v1", "v2")["backup"]
        self.assertNotEqual(first, second)
        self.assertEqual(Path(first).read_text(encoding="utf-8"), "v0")

    def test_edit_is_cancelled_when_backup_fails(self):
        path = self.tmp / "protected.txt"
        path.write_text("before", encoding="utf-8")
        with patch("local_ia.tools.edit.shutil.copy2", side_effect=PermissionError("backup denied")):
            with self.assertRaises(PermissionError):
                edit.use(str(path), "before", "after")
        self.assertEqual(path.read_text(encoding="utf-8"), "before")

    def test_refuses_to_break_valid_python(self):
        path = self.tmp / "ok.py"
        path.write_text("x = 1\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "syntaxe"):
            edit.use(str(path), "x = 1", "x = (")
        self.assertEqual(path.read_text(), "x = 1\n")

    def test_can_repair_a_file_that_is_already_broken(self):
        path = self.tmp / "broken.py"
        path.write_text("x = (\n", encoding="utf-8")
        self.assertTrue(edit.use(str(path), "x = (", "x = 1")["syntax_ok"])

    def test_handles_windows_line_endings(self):
        path = self.tmp / "crlf.txt"
        path.write_bytes(b"a\r\nb\r\n")
        edit.use(str(path), "a\nb", "a\nc")
        self.assertEqual(path.read_bytes(), b"a\r\nc\r\n")

    def test_rejects_paths_outside_allowed_roots(self):
        with self.assertRaises(PermissionError):
            edit.use("/etc/hostname", "a", "b")


class ExplorationToolsTest(ActionTestCase):
    def test_downloads_normalization_requires_a_path_component_boundary(self):
        path = "/workspace/downloads-archive/data.txt"
        self.assertEqual(normalize_path(path), path)

    def test_list_directory(self):
        (self.tmp / "dossier").mkdir()
        (self.tmp / "a.txt").write_text("abc", encoding="utf-8")
        result = listing.use(str(self.tmp))
        self.assertEqual([e["name"] for e in result["entries"]], ["dossier", "a.txt"])
        self.assertEqual(result["entries"][1]["size"], 3)

    def test_search_finds_lines_and_skips_junk(self):
        (self.tmp / "a.py").write_text("un\nTODO: corriger\n", encoding="utf-8")
        (self.tmp / "__pycache__").mkdir()
        (self.tmp / "__pycache__" / "b.py").write_text("TODO caché\n", encoding="utf-8")
        result = search.use("todo", str(self.tmp), extension="py")
        self.assertEqual([(Path(m["file"]).name, m["line"]) for m in result["matches"]], [("a.py", 2)])

    def test_search_does_not_follow_symlinks_outside_allowed_roots(self):
        with tempfile.TemporaryDirectory() as outside:
            secret = Path(outside) / "secret.txt"
            secret.write_text("private-marker", encoding="utf-8")
            link = self.tmp / "secret.txt"
            try:
                link.symlink_to(secret)
            except OSError as error:
                self.skipTest(f"Création de lien symbolique indisponible : {error}")
            result = search.use("private-marker", str(self.tmp))
        self.assertEqual(result["matches"], [])

    def test_search_marks_result_limit_only_when_more_matches_exist(self):
        (self.tmp / "only.txt").write_text("needle\n", encoding="utf-8")
        result = search.use("needle", str(self.tmp), max_results=1)
        self.assertFalse(result["truncated"])

    def test_search_marks_file_scan_limit_as_truncated(self):
        (self.tmp / "a.txt").write_text("needle\n", encoding="utf-8")
        (self.tmp / "b.txt").write_text("needle\n", encoding="utf-8")
        with patch("local_ia.tools.search.MAX_FILES", 1):
            result = search.use("absent", str(self.tmp))
        self.assertTrue(result["truncated"])

    def test_system_action_aliases(self):
        self.assertEqual(system.normalize_action("Augmenter"), "up")
        self.assertEqual(system.normalize_action("mute"), "mute")


class LauncherTest(unittest.TestCase):
    def test_hidden_desktop_entries_are_ignored(self):
        with tempfile.TemporaryDirectory() as folder:
            desktop = Path(folder) / "hidden.desktop"
            desktop.write_text(
                "[Desktop Entry]\nType=Application\nName=Hidden\nHidden=true\nExec=hidden-app\n",
                encoding="utf-8",
            )
            self.assertIsNone(application_launcher._desktop_application(desktop))

    def test_desktop_entries_with_missing_tryexec_are_ignored(self):
        with tempfile.TemporaryDirectory() as folder:
            desktop = Path(folder) / "missing.desktop"
            desktop.write_text(
                "[Desktop Entry]\nType=Application\nName=Missing\nTryExec=/not/installed/here\nExec=missing-app\n",
                encoding="utf-8",
            )
            self.assertIsNone(application_launcher._desktop_application(desktop))

    def test_malformed_desktop_without_entry_section_is_ignored(self):
        with tempfile.TemporaryDirectory() as folder:
            desktop = Path(folder) / "malformed.desktop"
            desktop.write_text("[Other Section]\nName=Not an app\n", encoding="utf-8")
            self.assertIsNone(application_launcher._desktop_application(desktop))

    def test_localized_names_and_cache(self):
        with tempfile.TemporaryDirectory() as folder:
            desktop = Path(folder) / "calc.desktop"
            desktop.write_text(
                "[Desktop Entry]\nType=Application\nName=Calculator\nName[fr]=Calculatrice\nExec=gnome-calculator %U\n",
                encoding="utf-8",
            )
            application_launcher._APP_CACHE.update(time=0.0, apps=[])
            with patch.object(application_launcher, "_desktop_files", return_value=[desktop]), \
                 patch.object(application_launcher.sys, "platform", "linux"):
                found = application_launcher.find_application("calculatrice")
                self.assertEqual(found["argv"], ["gnome-calculator"])
                desktop.unlink()  # le cache évite de rescanner le disque à chaque lancement
                self.assertIsNotNone(application_launcher.find_application("calculator"))
            application_launcher._APP_CACHE.update(time=0.0, apps=[])


if __name__ == "__main__":
    unittest.main()
