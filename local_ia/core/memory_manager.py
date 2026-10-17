"""Compatibilité de l'architecture finale pour la gestion de la mémoire."""

from __future__ import annotations

from local_ia.core.memory import (
    DB_PATH,
    MAX_MEMORIES,
    compute_embedding,
    extract_memory_candidate,
    flush_memory_writes,
    get_memories,
    has_similar_memory,
    init_database,
    save_memory,
    save_memory_if_relevant,
    save_message,
)


class MemoryManager:
    """Petit adaptateur orienté architecture finale."""

    def __init__(self, connection=None):
        self.connection = connection or init_database()

    def get_memories(self, limit=MAX_MEMORIES, query=None):
        return get_memories(self.connection, limit=limit, query=query)

    def save_memory(self, content, async_mode=True):
        return save_memory(self.connection, content, async_mode=async_mode)

    def save_memory_if_relevant(self, content, async_mode=True):
        return save_memory_if_relevant(self.connection, content, async_mode=async_mode)


__all__ = [
    "DB_PATH",
    "MAX_MEMORIES",
    "MemoryManager",
    "compute_embedding",
    "extract_memory_candidate",
    "flush_memory_writes",
    "get_memories",
    "has_similar_memory",
    "init_database",
    "save_memory",
    "save_memory_if_relevant",
    "save_message",
]
