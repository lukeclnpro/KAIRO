"""Outil permettant à l'agent de consulter la mémoire et l'historique."""

from __future__ import annotations

from local_ia.core.conversation import get_chat_history
from local_ia.core.memory import get_memories


def use(connection, chat, limit=12):
    history = get_chat_history(chat, limit=limit)
    memories = get_memories(connection)
    return {
        "history": history,
        "memories": memories,
    }