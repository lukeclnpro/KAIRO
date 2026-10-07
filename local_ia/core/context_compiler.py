"""Compilation du contexte par blocs selon la route, l'historique et les outils."""

from __future__ import annotations

import re
from pathlib import Path

from local_ia.core.context import build_system_prompt
from local_ia.core.conversation import get_weighted_chat_history
from local_ia.core.tool_manager import ToolManager

_WORDS = re.compile(r"[^\W_]+", re.UNICODE)
_STOP_WORDS = {
    "a", "au", "aux", "avec", "ce", "ces", "dans", "de", "des", "du", "elle", "en", "et",
    "est", "eux", "il", "je", "la", "le", "les", "leur", "lui", "ma", "mais", "me", "mes",
    "mon", "ne", "nos", "notre", "nous", "on", "ou", "par", "pas", "pour", "qu", "que",
    "qui", "sa", "se", "ses", "son", "sur", "ta", "te", "tes", "toi", "ton", "tu", "un",
    "une", "vos", "votre", "vous", "the", "and", "for", "from", "is", "it", "of", "on", "to",
}
_COURSES = {
    "python.txt": ("python", "script", "pip", "fonction", "classe", "py.", "programmation"),
    "reseaux.txt": ("réseau", "reseau", "tcp", "udp", "http", "https", "dns", "ip", "internet", "wifi", "wi-fi"),
    "html_css.txt": ("html", "css", "web", "page", "site", "responsive", "flexbox", "grid"),
    "mise_en_forme.txt": ("mise en forme", "markdown", "typographie", "formatage", "formater", "présentation", "document"),
    "javascript.txt": ("javascript", "js", "node", "dom", "promise", "async", "typescript"),
    "git.txt": ("git", "commit", "branche", "merge", "conflit", "versionnement", "version control"),
}


def _terms(text):
    return {word.casefold() for word in _WORDS.findall(str(text or "")) if len(word) > 1 and word.casefold() not in _STOP_WORDS}


class ContextCompiler:
    @staticmethod
    def load_relevant_courses(message):
        query = str(message or "").casefold()
        course_dir = Path(__file__).resolve().parents[2] / "cours"
        matches = [
            filename for filename, keywords in _COURSES.items()
            if any(
                re.search(r"(?<!\w)" + re.escape(keyword) + r"(?!\w)", query)
                for keyword in keywords
            )
        ]
        if not matches and re.search(r"\b(?:cours|apprendre|apprends|notions|fiche)\b", query):
            matches = list(_COURSES)
        sections = []
        for filename in matches:
            try:
                content = (course_dir / filename).read_text(encoding="utf-8").strip()
            except OSError:
                continue
            if content:
                sections.append(content)
        return sections

    def select_memories(self, message, memories, limit=2):
        if not memories:
            return []
        query_terms = _terms(message)
        if not query_terms:
            return list(memories[:limit])
        ranked = []
        for index, memory in enumerate(memories):
            score = len(query_terms & _terms(memory))
            if score:
                ranked.append((score, index, memory))
        ranked.sort(key=lambda item: (-item[0], item[1]))
        return [memory for _, _, memory in ranked[:limit]]

    def compile(self, chat, context, memories, message=None, route=None, allow_tools=None, tool_prompt="", base_prompt=None):
        route = route or {"mode": "agent", "tools": None}
        code_mode = route.get("mode") in {"code", "local_code"}
        allow_tools = set(allow_tools or ())
        message_text = str(message or "").strip()
        memory_items = [] if code_mode else self.select_memories(message_text, memories)

        if code_mode:
            base_prompt = (
                "MODE FICHIER : traite uniquement la demande de création ou de modification de fichier. "
                "Pour chaque nouveau fichier, produis une implémentation complète, directement utilisable et adaptée "
                "à l'usage demandé, pas un exemple minimal ou une simple démonstration. Inclus les imports, le point "
                "d'entrée et les interactions nécessaires; gère les entrées invalides et les erreurs courantes. "
                "N'utilise pas de valeurs d'exemple codées en dur comme seul comportement; évite les TODO, pass, "
                "placeholders et code tronqué. Avant l'écriture, vérifie que le code satisfait chaque partie de la "
                "demande, que les noms et appels sont cohérents et que le parcours principal est exécutable. "
                "Pour une modification, préserve le comportement sans rapport avec la demande. "
                "Utilise les outils de lecture autorisés si nécessaire, puis réponds uniquement par un appel "
                "<tool_call> JSON valide </tool_call> utilisant write ou edit. "
                "N'ajoute aucun plan, commentaire, résumé, Markdown ni texte avant ou après l'appel. "
                "N'utilise jamais command pour créer ou modifier un fichier."
            )
        elif base_prompt is None:
            base_prompt = build_system_prompt(memory_items, chat.get("topic"), context)
        if not message_text and not route.get("tools") and route.get("mode") in {"agent", "chat"}:
            return base_prompt

        blocks = [("CODE_SYSTEM" if code_mode else "BASE_SYSTEM", base_prompt)]

        course_sections = self.load_relevant_courses(message_text)
        if course_sections:
            if re.search(r"\b(?:cours|apprendre|apprends|notions|fiche)\b", message_text.casefold()):
                selected_sections = course_sections
            else:
                selected_sections = course_sections[:2]
            blocks.append(("COURS_DE_REFERENCE", "\n\n".join(selected_sections)))

        summary = "" if code_mode else str(chat.get("summary") or "").strip()
        if summary:
            blocks.append(("SUMMARY", summary))

        history = [] if code_mode else get_weighted_chat_history(chat)
        if history:
            recent = history[-2:]
            recent_text = "\n".join(
                f"{entry.get('role', 'user')}: {str(entry.get('content', ''))[:260]}"
                for entry in recent if str(entry.get('content', '')).strip()
            )
            if recent_text:
                history_guidance = (
                    "Les pourcentages indiquent l'importance des messages précédents : "
                    "100 % pour le plus récent, puis une décroissance de 25 % à chaque message."
                )
                blocks.append(("HISTORY", f"{history_guidance}\n{recent_text}"))

        if message_text and memory_items:
            blocks.append(("MEMORY", "\n".join(memory_items)))

        selected_tools = set(route.get("tools") or ())
        if allow_tools:
            selected_tools &= allow_tools
        tool_block = ""
        if selected_tools:
            tool_block = ToolManager.build_prompt(selected_tools)
        elif tool_prompt:
            tool_block = tool_prompt
        if tool_block:
            blocks.append(("TOOLS", tool_block))

        route_guidance = {
            "chat": "Réponds directement à la question. Commence par l'information utile, reste complet et évite les répétitions.",
            "command_suggestion": "L'utilisateur demande une commande à copier, pas son exécution. Donne la commande exacte dans un bloc de code, avec seulement une brève précision si nécessaire. N'appelle aucun outil et n'invente pas de résultat.",
            "code_artifact": (
                "Implémente le besoin complet, directement utilisable, pas un extrait ou une démonstration minimale. "
                "Le programme doit réaliser l'usage décrit plutôt que montrer un seul exemple figé; par exemple, "
                "un script qui crée des fichiers texte doit permettre de choisir le nom et le contenu, pas seulement "
                "écrire example.txt avec une valeur codée en dur. Inclus les imports, un point d'entrée utilisable, "
                "la validation des entrées et la gestion des erreurs courantes; aucun TODO, pass, placeholder ou code "
                "tronqué. Vérifie mentalement que le parcours principal satisfait toute la demande. "
                "Retourne uniquement un appel <tool_call> JSON valide à write ou edit pour créer ou modifier le fichier. "
                "Aucun texte ou bloc Markdown hors de cet appel. Si aucun nom n'est donné, choisis un nom descriptif "
                "dans le dossier autorisé."
            ),
            "filesystem": "Pour modifier un fichier existant, lis son contenu actuel avec file puis applique uniquement les changements demandés avec edit ou write. Si un fichier existant est identifié dans l'historique, travaille sur celui-ci au lieu de créer un nouveau fichier ou de répondre avec un extrait de code. Préserve tout ce qui n'est pas concerné et vérifie le résultat sur disque.",
            "install_application": "L'utilisateur demande explicitement une installation. Utilise system avec action install_app et le nom exact de l'application; l'installation doit venir du catalogue et attendre la confirmation utilisateur retournée par l'outil. N'exécute pas une commande différente.",
        }
        guidance = route_guidance.get(route.get("action"))
        if guidance:
            existing_code_file = route.get("existing_code_file")
            if existing_code_file:
                guidance += f" Fichier à modifier : {existing_code_file}."
            blocks.append(("RESPONSE_POLICY", guidance))

        if message_text:
            blocks.append(("CONTEXT", "Question actuelle :\n" + message_text if route.get("mode") == "chat" else "Contexte de la requête :\n" + message_text))

        prompt_parts = []
        for section, content in blocks:
            if str(content).strip():
                prompt_parts.append(f"[{section}]\n{content}")
        return "\n\n".join(prompt_parts)
