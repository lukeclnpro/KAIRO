"""Routage déterministe des demandes vers les outils strictement utiles."""

from __future__ import annotations

import re


_COMMAND = re.compile(r"^\s*/(?:commande|command|execute|executer)\b", re.I)
_COMMAND_SUGGESTION = re.compile(
    r"^\s*(?:quelle(?:\s+est)?\s+(?:la\s+)?commande|"
    r"donne(?:[- ]moi)?\s+(?:la\s+)?commande|commande\s+(?:pour|brute|à\s+copier)|"
    r"commande\s+à\s+copier)\b",
    re.I,
)
_APP_INSTALL = re.compile(
    r"^\s*(?:(?:peux-tu|pourrais-tu)\s+)*(?:installe(?:r)?|install(?:er)?|"
    r"je\s+veux\s+installer|je\s+voudrais\s+installer|j'aimerais\s+installer)\b",
    re.I,
)
_CODE_REQUEST = re.compile(
    r"(?:\b(?:g[ée]n[ée]re|[ée]cris|cr[ée]e|produis|code|create|write)\b.{0,120}\b"
    r"(?:code|script|programme|fonction|classe|page|site|application|api|fichier|file)\b|"
    r"^\s*(?:je\s+veux|je\s+voudrais|j'aimerais|je\s+demande|donne[- ]moi)\s+(?:du\s+)?"
    r"(?:code|un\s+script|un\s+programme|une\s+fonction|une\s+page|un\s+site)\b)",
    re.I,
)
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
_PAGE_ADDRESS = re.compile(
    r"(?:https?://|www\.)[^\s<>]+|(?:[\w](?:[\w-]*[\w])?\.)+[a-z]{2,}(?:/[^\s<>]*)?",
    re.I,
)
_OPEN_PAGE_ACTION = re.compile(
    r"\b(?:ouvre|ouvrir|visite|visiter|affiche|afficher|va\s+sur|aller\s+sur|open|visit|go\s+to)\b",
    re.I,
)
_CALCULATOR_INTENT = re.compile(
    r"\b(?:calcul(?:e|er|atrice)?|combien\s+(?:font|fait)|r[ée]sultat\s+de|racine\s+carr[ée]e)\b",
    re.I,
)
_ARITHMETIC_EXPRESSION = re.compile(
    r"(?<![\w.])\d+(?:[.,]\d+)?\s*(?:\+|\*{1,2}|/|%|\^|×|÷|\s+-\s+)\s*(?:\d|\(|pi\b|e\b)",
    re.I,
)
_FILE_TARGET = re.compile(
    r"(?:[/\\]|\b[\w.-]+\.(?:py|js|ts|tsx|jsx|html|css|json|txt|md|sh|sql|rs|go|java)\b|\b(?:fichiers?|dossiers?|r[ée]pertoires?|projets?|scripts?|code|programmes?)\b)",
    re.I,
)
_FILE_ACTION = re.compile(
    r"\b(?:lis|lire|ouvre|affiche|montre|cherche|trouve|liste|cr[ée]e|[ée]cris|modifie|corrige|supprime|renomme|ajoute|remplace|teste|relance|ex[ée]cute|run)\b",
    re.I,
)
_DOWNLOAD_REQUEST = re.compile(
    r"\b(?:t[eé]l[eé]charg(?:er|ement|eable)|download|r[eé]cup[eé]rer\s+(?:le\s+)?fichier|enregistrer\s+(?:le\s+)?fichier)\b",
    re.I,
)
_DOCUMENT_INTENT = re.compile(
    r"\b(?:pdf|docx|xlsx|pptx|csv|tsv|sqlite|base de donn[ée]es?|archive zip|tableau|feuille de calcul|document word|pr[ée]sentation powerpoint|graphique)\b",
    re.I,
)
_CONTEXTUAL_CODE_EDIT = re.compile(
    r"\b(?:ajoute|ajouter|rajoute|modifier|modifie|corrige|int[èe]gre|mets|mettez|" 
    r"installe|installer|teste|test[eé]r)\b.*\b(?:dedans|l[àa]-dedans|y|dans\s+(?:le|la|ce|cet|cette)|"
    r"au\s+(?:fichier|code|script|programme)|[àa]\s+ce\s+(?:fichier|code|script|programme))\b",
    re.I,
)
_EDIT_ACTION = re.compile(r"\b(?:modifie|corrige|[ée]cris|supprime|renomme|ajoute|remplace|cr[ée]e|teste|relance|ex[ée]cute)\b", re.I)
_SIMPLE_QUESTION = re.compile(
    r"^\s*(?:qui|quoi|quand|o[uù]|pourquoi|comment|combien|quel(?:le)?|est-ce|qu'est-ce|explique|d[ée]finis|traduis|raconte)\b",
    re.I,
)


class RequestRouter:
    """Route les actions directes et classe les demandes avant l'agent."""

    def route(self, message, fast_path, allowed_tools=None, *, existing_code_file=None):
        answer = fast_path(message, allowed_tools)
        if answer:
            return {"mode": "direct", "action": "fast_path", "tools": (), "answer": answer}

        text = str(message or "").strip()
        if _COMMAND.search(text):
            return {"mode": "tool", "action": "command", "tools": ("command",), "answer": None}

        if _COMMAND_SUGGESTION.search(text):
            return {"mode": "command_suggestion", "action": "command_suggestion", "tools": (), "answer": None}

        if _APP_INSTALL.search(text):
            return {"mode": "tool", "action": "install_application", "tools": ("system",), "answer": None}

        if _PAGE_ADDRESS.search(text) and _OPEN_PAGE_ACTION.search(text):
            return {"mode": "tool", "action": "open_page", "tools": ("open_page",), "answer": None}

        if _SYSTEM_INFO.search(text) and _FILE_TARGET.search(text) and _FILE_ACTION.search(text):
            return {
                "mode": "tool",
                "action": "filesystem",
                "tools": ("edit", "file", "list", "search", "system", "write"),
                "answer": None,
            }

        if _DOWNLOAD_REQUEST.search(text) and re.search(
            r"\b(?:cr[ée]e|[ée]cris|g[ée]n[ée]re|create|write)\b", text, re.I
        ):
            return {"mode": "tool", "action": "download", "tools": ("create_download",), "answer": None}

        if _CODE_REQUEST.search(text):
            tools = {"file", "write", "edit", "list", "search"}
            if re.search(r"\b(?:teste|tester|ex[ée]cute|lance|relance|run)\b", text, re.I):
                tools.add("command")
            return {"mode": "code", "action": "code_artifact", "tools": tuple(sorted(tools)), "answer": None}

        if existing_code_file and _CONTEXTUAL_CODE_EDIT.search(text):
            return {
                "mode": "tool",
                "action": "filesystem",
                "tools": ("edit", "file", "search", "write"),
                "answer": None,
                "existing_code_file": str(existing_code_file),
            }

        if _DOCUMENT_INTENT.search(text):
            return {"mode": "tool", "action": "document", "tools": ("document",), "answer": None}

        if _CALCULATOR_INTENT.search(text) or _ARITHMETIC_EXPRESSION.search(text):
            return {"mode": "tool", "action": "calculator", "tools": ("calculator",), "answer": None}

        has_file_target = bool(_FILE_TARGET.search(text))
        if has_file_target and (_FILE_ACTION.search(text) or _SIMPLE_QUESTION.search(text)):
            tools = {"file", "write", "edit", "list", "search"}
            if _DOWNLOAD_REQUEST.search(text):
                tools.add("create_download")
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
