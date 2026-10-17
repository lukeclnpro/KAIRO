"""Retriever de mémoire compatible architecture finale."""

from __future__ import annotations

from local_ia.core.memory import (
    get_memories,
    has_similar_memory,
    save_memory_if_relevant,
)

__all__ = ["get_memories", "has_similar_memory", "save_memory_if_relevant"]
