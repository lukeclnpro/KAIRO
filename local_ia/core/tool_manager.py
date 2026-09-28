"""Sélection, validation, exécution et compression des outils de l'agent."""

from __future__ import annotations

import json

from local_ia.tools import command, context as context_tool, edit, file as file_tool
from local_ia.tools import launch, listing, memory, search, system, write

TOOL_INSTRUCTIONS = """Tu disposes d'outils locaux pour agir sur l'ordinateur de l'utilisateur.

Outils et arguments :
- memory : {} — messages précédents et souvenirs enregistrés.
- context : {} — contexte permanent de l'assistant.
- list : {"path":"..."} — lister le contenu d'un dossier.
- search : {"pattern":"...", "path":"...", "extension":"py"} — chercher du texte dans des fichiers.
- file : {"path":"..."} — lire un fichier.
- write : {"path":"...", "content":"..."} — créer un fichier ou le réécrire en entier.
- edit : {"path":"...", "old":"texte exact", "new":"remplacement"} — corriger une partie d'un fichier.
- launch : {"name":"..."} — lancer une application installée.
- command : {"argv":["programme","argument"], "cwd":"/dossier"} — exécuter une commande, sans shell ni pipe.
- system : {"action":"info|up|down|mute|unmute|install|update", "value":"nom-paquet"}

Pour utiliser un outil, réponds UNIQUEMENT avec cette structure :
<tool_call>{"tool":"file","arguments":{"path":"/chemin/fichier"}}</tool_call>
Un seul outil à la fois : tu reçois son résultat, puis tu peux appeler un autre
outil ou répondre à l'utilisateur. Les paramètres peuvent aussi être placés
directement dans l'appel : <tool_call>{"tool":"launch","name":"spotify"}</tool_call>

Pour corriger un bug : 1) lis le code avec file (ou trouve-le avec search),
2) change seulement les lignes fautives avec edit (old = texte exact du fichier),
3) relance le programme ou les tests avec command pour vérifier,
4) résume en une phrase ce qui a été corrigé. Si un outil renvoie une erreur,
corrige ton appel au lieu d'abandonner.
Si la demande dépend d'une information système, utilise d'abord system avec
l'action info, puis write avec le résultat obtenu.

N'invente jamais un résultat d'outil. Si aucun outil n'est nécessaire, réponds
normalement à l'utilisateur. Pour un chemin comme « mon dossier Téléchargements »,
utilise le dossier réel de l'utilisateur, jamais un chemin d'exemple comme
/chemin/dossier/telechargement. Ne demande pas à l'utilisateur d'écrire lui-même
du code d'appel d'outil."""


class ToolResultCompressor:
    @staticmethod
    def _summarize_text(value, max_chars):
        if not isinstance(value, str):
            return value
        text = value.strip().replace("\r\n", "\n")
        if len(text) <= max_chars:
            return text
        if max_chars <= 12:
            return text[:max_chars]
        return text[: max_chars - 12] + "...[tronqué]"

    @staticmethod
    def _compact_match_list(matches):
        if not isinstance(matches, list):
            return matches
        sample = matches[:1]
        compact = {"matches": sample}
        if len(matches) > len(sample):
            compact["match_count"] = len(matches)
            compact["truncated"] = True
        else:
            compact["truncated"] = False
        return compact

    @staticmethod
    def compact(payload, max_chars=2500):
        if isinstance(payload, dict):
            if "matches" in payload:
                compact = ToolResultCompressor._compact_match_list(payload.get("matches"))
                for key, value in payload.items():
                    if key == "matches":
                        continue
                    if key in {"files_scanned", "matched_files", "truncated"}:
                        compact[key] = value
                if "truncated" not in compact:
                    compact["truncated"] = bool(payload.get("truncated", False))
                return ToolResultCompressor._finalize(compact, max_chars)

            if "content" in payload and isinstance(payload.get("content"), str):
                path = payload.get("path")
                content = payload.get("content")
                preview = "\n".join(content.strip().splitlines()[:10])
                compact = {"path": path, "preview": ToolResultCompressor._summarize_text(preview, max(50, max_chars // 3))}
                if len(content) > len(preview):
                    compact["truncated"] = True
                    compact["char_count"] = len(content)
                elif "truncated" in payload:
                    compact["truncated"] = bool(payload.get("truncated", False))
                return ToolResultCompressor._finalize(compact, max_chars)

            compact = {}
            for key, value in payload.items():
                if isinstance(value, str):
                    compact[key] = ToolResultCompressor._summarize_text(value, max(60, max_chars // 4))
                elif isinstance(value, list):
                    compact[key] = value[:3]
                    if len(value) > 3:
                        compact[key + "_truncated"] = True
                        compact[key + "_count"] = len(value)
                else:
                    compact[key] = value
            return ToolResultCompressor._finalize(compact, max_chars)

        if isinstance(payload, list):
            compact = payload[:3]
            if len(payload) > 3:
                compact = {"items": compact, "truncated": True, "count": len(payload)}
            return ToolResultCompressor._finalize(compact, max_chars)

        return ToolResultCompressor._finalize(payload, max_chars)

    @staticmethod
    def _finalize(payload, max_chars):
        text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str)
        marker = "...[résultat tronqué]"
        if len(text) <= max_chars:
            return text
        if max_chars <= len(marker):
            return marker[:max_chars]
        return text[: max_chars - len(marker)] + marker


class ToolManager:
    TOOL_GROUPS = {
        "filesystem": frozenset({"file", "write", "edit", "list", "search"}),
        "system": frozenset({"launch", "command", "system"}),
        "memory": frozenset({"memory"}),
        "context": frozenset({"context"}),
    }
    TOOL_DESCRIPTIONS = {
        "memory": 'memory : {} — messages précédents et souvenirs enregistrés.',
        "context": 'context : {} — contexte permanent de l’assistant.',
        "list": 'list : {"path":"..."} — lister le contenu d’un dossier.',
        "search": 'search : {"pattern":"...", "path":"...", "extension":"py"} — chercher dans des fichiers.',
        "file": 'file : {"path":"..."} — lire un fichier.',
        "write": 'write : {"path":"...", "content":"..."} — créer ou réécrire un fichier.',
        "edit": 'edit : {"path":"...", "old":"texte exact", "new":"remplacement"} — modifier un fichier.',
        "launch": 'launch : {"name":"..."} — lancer une application installée.',
        "command": 'command : {"argv":["programme","argument"], "cwd":"/dossier"} — exécuter sans shell.',
        "system": 'system : {"action":"info|up|down|mute|unmute|install|update", "value":"nom-paquet"} — information ou action système.',
    }
    ALL_TOOLS = frozenset().union(*TOOL_GROUPS.values())

    @classmethod
    def get_tools(cls, route, allowed_tools=None):
        if route.get("mode") in {"direct", "chat"}:
            selected = set()
        elif route.get("tools") is None:
            selected = set(cls.ALL_TOOLS)
        else:
            selected = set(route["tools"]) & cls.ALL_TOOLS
        if allowed_tools is not None:
            selected.intersection_update(allowed_tools)
        return selected

    @staticmethod
    def validate(tool_name, allowed_tools=None):
        if allowed_tools is not None and tool_name not in allowed_tools:
            hint = ""
            if tool_name in {"launch", "command", "system"}:
                hint = (
                    " Elle est désactivée : l'utilisateur doit activer command_execution "
                    "dans config.json ou demander explicitement de lancer/exécuter."
                )
            raise PermissionError(f"L'outil {tool_name} n'est pas autorisé pour cette requête.{hint}")

    @staticmethod
    def _arg(arguments, key):
        if arguments.get(key) is None:
            raise ValueError(f"Argument manquant : {key}")
        return arguments[key]

    @classmethod
    def execute(cls, tool_call, chat, connection, allowed_tools=None):
        tool_name = tool_call["tool"]
        arguments = tool_call["arguments"]
        cls.validate(tool_name, allowed_tools)
        arg = cls._arg
        if tool_name == "memory":
            return memory.use(connection, chat)
        if tool_name == "context":
            return context_tool.use()
        if tool_name == "file":
            return file_tool.use(arg(arguments, "path"), arguments.get("extension"))
        if tool_name == "write":
            return write.use(arg(arguments, "path"), arg(arguments, "content"), arguments.get("extension"))
        if tool_name == "edit":
            return edit.use(
                arg(arguments, "path"), arg(arguments, "old"), arg(arguments, "new"),
                bool(arguments.get("replace_all", False)),
            )
        if tool_name == "list":
            return listing.use(arguments.get("path") or ".")
        if tool_name == "search":
            return search.use(
                arg(arguments, "pattern"), arguments.get("path") or ".",
                arguments.get("extension"), arguments.get("max_results", 30),
            )
        if tool_name == "launch":
            return launch.use(arg(arguments, "name"))
        if tool_name == "command":
            options = {"cwd": arguments.get("cwd"), "confirmed": bool(arguments.get("confirmed", False))}
            if arguments.get("timeout") is not None:
                options["timeout"] = arguments["timeout"]
            return command.use(arg(arguments, "argv"), **options)
        if tool_name == "system":
            return system.use(
                arg(arguments, "action"), arguments.get("value"),
                arguments.get("amount", 5), arguments.get("confirmed", False),
            )
        raise ValueError(f"Outil inconnu : {tool_name}")

    @staticmethod
    def build_prompt(tools=None):
        selected = set(ToolManager.ALL_TOOLS if tools is None else tools) & ToolManager.ALL_TOOLS
        if not selected:
            return ""
        if selected == ToolManager.ALL_TOOLS:
            return TOOL_INSTRUCTIONS

        ordered = [name for name in ToolManager.TOOL_DESCRIPTIONS if name in selected]
        lines = [
            "Tu disposes uniquement des outils locaux suivants :",
            *(f"- {ToolManager.TOOL_DESCRIPTIONS[name]}" for name in ordered),
            "",
            'Pour appeler un outil, réponds uniquement avec <tool_call>{"tool":"nom","arguments":{...}}</tool_call>.',
            "Un seul outil par réponse. Tu recevras son résultat avant de continuer.",
            "N'invente jamais un résultat d'outil. Si un outil échoue, corrige l'appel ou explique le blocage.",
        ]
        if ToolManager.TOOL_GROUPS["filesystem"].intersection(selected):
            lines.extend([
                "Pour corriger du code, lis ou cherche d'abord le fichier, puis modifie seulement ce qui est nécessaire.",
                "Respecte les racines de fichiers autorisées et n'invente pas de chemins.",
            ])
        if "system" in selected:
            lines.append("Pour une information système, utilise system avec l'action info.")
        return "\n".join(lines)

    @staticmethod
    def compact_result(payload, max_chars=2500):
        return ToolResultCompressor.compact(payload, max_chars=max_chars)
