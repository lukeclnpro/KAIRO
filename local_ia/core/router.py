"""Routage déterministe des demandes vers les outils strictement utiles."""

from __future__ import annotations

import re


_COMMAND = re.compile(r"^\s*/(?:commande|command|execute|executer)\b", re.I)
_LAUNCH = re.compile(r"^\s*(?:peux-tu\s+)?(?:lance|lancer|ouvre|ouvrir|d[ée]marre|d[ée]marrer)\b", re.I)
_SYSTEM_INFO = re.compile(
    r"\b(?:syst[eè]me(?: d'exploitation)?|\bos\b|informations? syst[eè]me)\b", re.I
)
_MEMORY = re.compile(r"\b(?:m[ée]moire|souviens-toi|rappelle-toi)\b", re.I)
_WEB_INFO = re.compile(
    r"\b(?:actualit[ée]s?|actu|news|info|infos|m[ée]t[ée]o|weather|pr[ée]visions?\s+m[ée]t[ée]o|"
    r"aujourd'hui|en\s+ce\s+moment|actuellement|derni[eè]res?\s+(?:infos?|nouvelles?)|"
    r"cours\s+(?:de\s+)?(?:bourse|\w+)|taux\s+de\s+change|trafic)\b",
    re.I,
)
_WEB_SEARCH = re.compile(
    r"\b(?:google|annonces?|petites annonces|site(?:s)?(?: officiel(?:s)?| web| internet)|"
    r"recherch(?:e|er)\s+(?:sur\s+)?(?:internet|le web)|"
    r"cherche(?:r)?\s+(?:sur\s+)?(?:google|internet|le web)|"
    r"[àa]\s+vendre|[àa]\s+louer)\b",
    re.I,
)
_FILE_TARGET = re.compile(
    r"(?:[/\\]|\b[\w.-]+\.(?:py|js|ts|tsx|jsx|html|css|json|txt|md|sh|sql|rs|go|java)\b|\b(?:fichier|dossier|r[ée]pertoire|projet|script|code|programme)\b)",
    re.I,
)
_FILE_ACTION = re.compile(
    r"\b(?:lis|lire|ouvre|affiche|montre|cherche|trouve|liste|cr[ée]e|[ée]cris|modifie|corrige|supprime|renomme|ajoute|remplace|teste|relance|ex[ée]cute|run)\b",
    re.I,
)
_EDIT_ACTION = re.compile(r"\b(?:modifie|corrige|[ée]cris|supprime|renomme|ajoute|remplace|cr[ée]e|teste|relance|ex[ée]cute)\b", re.I)
_SIMPLE_QUESTION = re.compile(
    r"^\s*(?:qui|quoi|quand|o[uù]|pourquoi|comment|combien|quel(?:le)?|est-ce|qu'est-ce|explique|d[ée]finis|traduis|raconte)\b",
    re.I,
)


class RequestRouter:
    """Route les actions directes et classe les demandes avant l'agent."""

    def route(self, message, fast_path, allowed_tools=None):
        answer = fast_path(message, allowed_tools)
        if answer:
            return {"mode": "direct", "action": "fast_path", "tools": (), "answer": answer}

        text = str(message or "").strip()
        if _COMMAND.search(text):
            return {"mode": "tool", "action": "command", "tools": ("command",), "answer": None}

        has_file_target = bool(_FILE_TARGET.search(text))
        if has_file_target and (_FILE_ACTION.search(text) or _SIMPLE_QUESTION.search(text)):
            tools = {"file", "write", "edit", "list", "search"}
            if _EDIT_ACTION.search(text):
                tools.add("command")
            if _SYSTEM_INFO.search(text):
                tools.add("system")
            if _MEMORY.search(text):
                tools.add("memory")
            return {"mode": "tool", "action": "filesystem", "tools": tuple(sorted(tools)), "answer": None}

        if _SYSTEM_INFO.search(text):
            return {"mode": "tool", "action": "system", "tools": ("system",), "answer": None}
        if _MEMORY.search(text):
            return {"mode": "tool", "action": "memory", "tools": ("memory",), "answer": None}
        if _LAUNCH.search(text):
            return {"mode": "tool", "action": "launch", "tools": ("launch",), "answer": None}

        if _WEB_INFO.search(text) or _WEB_SEARCH.search(text):
            return {"mode": "tool", "action": "web", "tools": ("web",), "answer": None}

        if _SIMPLE_QUESTION.search(text) and "?" in text:
            return {"mode": "chat", "action": "chat", "tools": (), "answer": None}
        return {"mode": "agent", "action": "agent", "tools": None, "answer": None}
