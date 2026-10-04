"""Évalue les contrats de réponse sans modèle réel ni accès réseau."""

from __future__ import annotations

import json
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from local_ia.core.agent import LocalAgent


class ResponseEvaluationSuite:
    def __init__(self):
        self.scenarios = (
            ("information", self._information),
            ("code_file", self._code_file),
            ("command_copy", self._command_copy),
            ("application_install", self._application_install),
            ("application_launch", self._application_launch),
        )

    @staticmethod
    def _tool_call(name, **arguments):
        return "<tool_call>" + json.dumps(
            {"tool": name, "arguments": arguments}, ensure_ascii=False
        ) + "</tool_call>"

    @staticmethod
    def _outcome(name, answer, route, progress, checks, **details):
        return {
            "scenario": name,
            "status": "pass" if all(checks.values()) else "fail",
            "checks": checks,
            "route": route,
            "answer": str(answer),
            "progress": progress,
            **details,
        }

    def _information(self):
        agent = LocalAgent(model="evaluation")
        progress = []
        try:
            with patch(
                "local_ia.core.agent.ask_ollama",
                return_value="Rome est la capitale de l'Italie.",
            ):
                answer = agent.respond(
                    {"messages": []},
                    "Quelle est la capitale de l'Italie ?",
                    progress_callback=progress.append,
                )
            return self._outcome(
                "information",
                answer,
                agent.last_route,
                progress,
                {
                    "direct_answer_route": agent.last_route.get("mode") == "chat",
                    "answer_present": "Rome" in answer,
                    "completion_reported": "Réponse prête." in progress,
                },
            )
        finally:
            agent.close()

    def _code_file(self):
        agent = LocalAgent(model="evaluation")
        progress = []
        try:
            with tempfile.TemporaryDirectory() as temporary_directory:
                projects_root = Path(temporary_directory) / "projects"
                project_root = projects_root / "evaluation"
                project_root.mkdir(parents=True)
                chat = {"messages": [], "code_project_path": str(project_root)}
                response = self._tool_call(
                    "write",
                    path="trier_liste.py",
                    content="def trier(valeurs):\n    return sorted(valeurs)\n",
                )
                with patch(
                    "local_ia.core.code_projects.get_projects_root",
                    return_value=projects_root,
                ), patch("local_ia.core.agent.ask_ollama", return_value=response):
                    answer = agent.respond(
                        chat,
                        "Écris un script Python qui trie une liste",
                        progress_callback=progress.append,
                    )
                generated_file = project_root / "trier_liste.py"
                return self._outcome(
                    "code_file",
                    answer,
                    agent.last_route,
                    progress,
                    {
                        "code_route": agent.last_route.get("mode") == "code",
                        "file_created": generated_file.is_file(),
                        "file_content_verified": generated_file.is_file() and "sorted" in generated_file.read_text(encoding="utf-8"),
                        "progress_reports_verification": any("vérifié" in item for item in progress),
                    },
                    file=str(generated_file),
                )
        finally:
            agent.close()

    def _command_copy(self):
        agent = LocalAgent(model="evaluation")
        progress = []
        try:
            response = self._tool_call(
                "command", argv=["flatpak", "install", "flathub", "org.mozilla.firefox"]
            )
            with patch("local_ia.core.agent.ask_ollama", return_value=response), patch.object(
                agent, "execute_tool"
            ) as execute:
                answer = agent.respond(
                    {"messages": []},
                    "Quelle commande pour installer Firefox ?",
                    progress_callback=progress.append,
                )
            return self._outcome(
                "command_copy",
                answer,
                agent.last_route,
                progress,
                {
                    "copy_route": agent.last_route.get("mode") == "command_suggestion",
                    "command_is_copyable": "```sh\nflatpak install flathub org.mozilla.firefox\n```" in answer,
                    "command_not_executed": execute.call_count == 0,
                    "progress_says_not_executed": any("aucune commande exécutée" in item for item in progress),
                },
            )
        finally:
            agent.close()

    def _application_install(self):
        agent = LocalAgent(model="evaluation")
        progress = []
        try:
            pending = {
                "confirmation_required": True,
                "message": "Confirmation nécessaire avant d'installer Firefox.",
            }
            response = self._tool_call("system", action="install_app", value="Firefox")
            with patch("local_ia.core.agent.ask_ollama", return_value=response), patch(
                "local_ia.core.tool_manager.system.use", return_value=pending
            ) as install:
                chat = {"messages": []}
                answer = agent.respond(
                    chat,
                    "Installe Firefox",
                    progress_callback=progress.append,
                )
            return self._outcome(
                "application_install",
                answer,
                agent.last_route,
                progress,
                {
                    "catalog_install_route": agent.last_route.get("action") == "install_application",
                    "confirmation_required": "Confirmation nécessaire" in answer,
                    "pending_tool_saved": chat.get("pending_tool", {}).get("arguments", {}).get("action") == "install_app",
                    "install_not_run_yet": install.call_count == 1,
                    "progress_reports_confirmation": any("confirmation" in item.casefold() for item in progress),
                },
            )
        finally:
            agent.close()

    def _application_launch(self):
        agent = LocalAgent(model="evaluation")
        progress = []
        application = {"name": "Firefox", "argv": ["firefox"]}
        try:
            with patch("local_ia.core.agent.ask_ollama") as ask, patch(
                "local_ia.core.agent.application_launcher.find_application",
                return_value=application,
            ), patch(
                "local_ia.core.agent.application_launcher.launch_application",
                return_value=application,
            ) as launch:
                answer = agent.respond(
                    {"messages": []},
                    "Je veux lancer Firefox",
                    progress_callback=progress.append,
                )
            return self._outcome(
                "application_launch",
                answer,
                agent.last_route,
                progress,
                {
                    "direct_launch_route": agent.last_route.get("mode") == "direct",
                    "launch_requested": answer == "Firefox lancé." and launch.call_count == 1,
                    "model_not_needed": ask.call_count == 0,
                    "progress_reported": bool(progress),
                },
            )
        finally:
            agent.close()

    def run(self):
        started_at = time.perf_counter()
        results = {}
        for name, scenario in self.scenarios:
            try:
                results[name] = scenario()
            except Exception as error:
                results[name] = {
                    "scenario": name,
                    "status": "fail",
                    "checks": {"scenario_completed": False},
                    "error": f"{type(error).__name__}: {error}",
                }

        passed = sum(result["status"] == "pass" for result in results.values())
        failed = len(results) - passed
        return {
            "suite": "response_behavior",
            "mode": "offline deterministic fixtures; no real model or network",
            "duration_ms": round((time.perf_counter() - started_at) * 1000),
            "summary": {"passed": passed, "failed": failed, "total": len(results)},
            "scenarios": results,
        }


def main():
    report = ResponseEvaluationSuite().run()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if report["summary"]["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())