"""Package mémoire orienté architecture finale."""

from __future__ import annotations

from local_ia.core.memory import (
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

from local_ia.core.memory_manager import MemoryManager

__all__ = [
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
