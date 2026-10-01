"""Compilation du contexte par blocs selon la route, l'historique et les outils."""

from __future__ import annotations

import re

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


def _terms(text):
    return {word.casefold() for word in _WORDS.findall(str(text or "")) if len(word) > 1 and word.casefold() not in _STOP_WORDS}


class ContextCompiler:
    def select_memories(self, message, memories, limit=3):
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
        allow_tools = set(allow_tools or ())
        message_text = str(message or "").strip()
        memory_items = self.select_memories(message_text, memories)

        if base_prompt is None:
            base_prompt = build_system_prompt(memory_items, chat.get("topic"), context)
        if not message_text and not route.get("tools") and route.get("mode") in {"agent", "chat"}:
            return base_prompt

        blocks = [("BASE_SYSTEM", base_prompt)]

        summary = str(chat.get("summary") or "").strip()
        if summary:
            blocks.append(("SUMMARY", summary))

        history = get_weighted_chat_history(chat)
        if history:
            recent = history[-4:]
            recent_text = "\n".join(
                f"{entry.get('role', 'user')}: {entry.get('content', '')}"
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

        if message_text:
            blocks.append(("CONTEXT", "Question actuelle :\n" + message_text if route.get("mode") == "chat" else "Contexte de la requête :\n" + message_text))

        prompt_parts = []
        for section, content in blocks:
            if str(content).strip():
                prompt_parts.append(f"[{section}]\n{content}")
        return "\n\n".join(prompt_parts)
