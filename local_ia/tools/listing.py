"""Outil de listage d'un dossier autorisé."""

from __future__ import annotations

import file_commands
from local_ia.tools.file import _allow_standard_directories, normalize_path

MAX_ENTRIES = 200


def use(path=".", max_entries=MAX_ENTRIES):
    _allow_standard_directories()
    target = file_commands._resolve(normalize_path(path or "."))
    if not target.exists():
        raise FileNotFoundError(f"Dossier introuvable : {target}")
    if not target.is_dir():
        raise ValueError(f"Ce chemin n'est pas un dossier : {target}")
    limit = max(1, min(int(max_entries), MAX_ENTRIES))
    children = sorted(target.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower()))
    entries = []
    for item in children[:limit]:
        try:
            size = item.stat().st_size if item.is_file() else None
        except OSError:
            size = None
        entries.append({"name": item.name, "type": "dir" if item.is_dir() else "file", "size": size})
    return {"path": str(target), "entries": entries, "truncated": len(children) > limit}
