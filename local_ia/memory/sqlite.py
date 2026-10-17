"""Accès SQLite pour la couche mémoire finale."""

from __future__ import annotations

from local_ia.core.memory import init_database, save_memory, save_message, flush_memory_writes

__all__ = ["init_database", "save_memory", "save_message", "flush_memory_writes"]
