from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]

import sys

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from local_ia.core.agent import LocalAgent


class BenchmarkSuite:
    """Simple harness pour mesurer les principaux scénarios sans vraie LLM."""

    def __init__(self, root: Path | str = ROOT):
        self.root = Path(root)

    def _prompt_size(self, agent: LocalAgent, chat: dict[str, Any], message: str, tools=None, route=None) -> int:
        messages = agent.build_messages(chat, message, tools=tools, route=route)
        return len(str(messages[0].get("content", "")))

    def _run_named_scenario(self, name: str, question: str, responses: list[str], *, tools=None, route=None, memory_items=None, tool_result_chars=0):
        chat = {"id": 1, "topic": "benchmark", "messages": []}
        agent = LocalAgent(model="test")
        if memory_items:
            agent.memories = list(memory_items)

        ollama_calls = 0
        first_token_ms = None
        start = time.perf_counter()

        def fake_ask_ollama(messages, model=None, stream=False):
            nonlocal ollama_calls, first_token_ms
            ollama_calls += 1
            if first_token_ms is None:
                first_token_ms = (time.perf_counter() - start) * 1000
            if responses:
                return responses.pop(0)
            return "Réponse benchmark." 

        with patch("local_ia.core.agent.ask_ollama", side_effect=fake_ask_ollama):
            answer = agent.respond(chat, question, allowed_tools=tools, stream=False)

        total_ms = int((time.perf_counter() - start) * 1000)
        prompt_chars = self._prompt_size(agent, chat, question, tools=tools, route=route)
        summary = {
            "scenario": name,
            "answer": answer,
            "first_token_ms": int(first_token_ms if first_token_ms is not None else total_ms),
            "total_ms": total_ms,
            "ollama_calls": ollama_calls,
            "prompt_chars": prompt_chars,
            "memory_items": len(agent.memories),
            "history_messages": len(chat.get("messages", [])),
            "tool_result_chars": int(tool_result_chars),
            "disk_write_ms": 0,
        }
        agent.close()
        return summary

    def run(self) -> dict[str, Any]:
        scenarios = {
            "simple_question": self._run_named_scenario(
                "simple_question",
                "Quelle est la capitale de l'Italie ?",
                ["Rome est la capitale de l'Italie."],
            ),
            "memory_question": self._run_named_scenario(
                "memory_question",
                "Quel modèle utilise mon projet ?",
                ["Le projet utilise Python et SQLite."],
                memory_items=["Le projet utilise Python et SQLite.", "Le projet est un assistant local."],
            ),
            "file_read": self._run_named_scenario(
                "file_read",
                "Lis le fichier README.md",
                [
                    "<tool_call>{\"tool\":\"file\",\"arguments\":{\"path\":\"README.md\"}} </tool_call>",
                    "README.md contient la description du projet.",
                ],
                tools={"file"},
                tool_result_chars=420,
            ),
            "project_search": self._run_named_scenario(
                "project_search",
                "Recherche LocalAgent dans le projet",
                [
                    "<tool_call>{\"tool\":\"search\",\"arguments\":{\"pattern\":\"LocalAgent\",\"path\":\".\"}} </tool_call>",
                    "J'ai trouvé la classe LocalAgent dans le cœur du projet.",
                ],
                tools={"search"},
                tool_result_chars=640,
            ),
            "file_edit": self._run_named_scenario(
                "file_edit",
                "Modifie le fichier demo.txt",
                [
                    "<tool_call>{\"tool\":\"edit\",\"arguments\":{\"path\":\"demo.txt\",\"old\":\"avant\",\"new\":\"après\"}} </tool_call>",
                    "Fichier modifié avec succès.",
                ],
                tools={"edit"},
                tool_result_chars=220,
            ),
            "complex_tool_task": self._run_named_scenario(
                "complex_tool_task",
                "Fais une recherche puis corrige le fichier concerné",
                [
                    "<tool_call>{\"tool\":\"search\",\"arguments\":{\"pattern\":\"TODO\",\"path\":\".\"}} </tool_call>",
                    "<tool_call>{\"tool\":\"edit\",\"arguments\":{\"path\":\"demo.txt\",\"old\":\"TODO\",\"new\":\"OK\"}} </tool_call>",
                    "La tâche est terminée.",
                ],
                tools={"search", "edit"},
                tool_result_chars=760,
            ),
        }

        return {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "root": str(self.root),
            "scenarios": scenarios,
        }


def main() -> None:
    report = BenchmarkSuite().run()
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
