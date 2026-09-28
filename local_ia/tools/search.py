"""Outil de recherche de texte dans les fichiers d'un dossier autorisé."""

from __future__ import annotations

import os
import re

import file_commands
from local_ia.tools.file import _allow_standard_directories, normalize_path

SKIP_DIRS = {".git", "__pycache__", "node_modules", ".venv", "venv", ".local_ia_backups"}
MAX_FILE_BYTES = 512 * 1024
MAX_FILES = 3000


def use(pattern, path=".", extension=None, max_results=30):
    if not str(pattern or "").strip():
        raise ValueError("Motif de recherche vide.")
    _allow_standard_directories()
    root = file_commands._resolve(normalize_path(path or "."))
    if not root.exists():
        raise FileNotFoundError(f"Chemin introuvable : {root}")
    try:
        regex = re.compile(str(pattern), re.IGNORECASE)
    except re.error:
        regex = re.compile(re.escape(str(pattern)), re.IGNORECASE)
    wanted = str(extension).lower().lstrip(".") if extension else None
    limit = max(1, min(int(max_results), 100))

    candidates = [root] if root.is_file() else []
    files_truncated = False
    if root.is_dir():
        for folder, dirs, names in os.walk(root):
            dirs[:] = [name for name in dirs if name not in SKIP_DIRS]
            candidates.extend(root.__class__(folder) / name for name in names)
            if len(candidates) > MAX_FILES:
                candidates = candidates[:MAX_FILES]
                files_truncated = True
                break

    matches, scanned = [], 0
    for file in candidates[:MAX_FILES]:
        ext = file.suffix.lower().lstrip(".")
        if wanted and ext != wanted:
            continue
        if ext not in file_commands.TEXT_EXTENSIONS:
            continue
        try:
            file = file_commands._resolve(str(file))
            if file.stat().st_size > MAX_FILE_BYTES:
                continue
            lines = file.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        scanned += 1
        for number, line in enumerate(lines, 1):
            if regex.search(line):
                matches.append({"file": str(file), "line": number, "text": line.strip()[:200]})
                if len(matches) > limit:
                    return {"matches": matches[:limit], "files_scanned": scanned, "truncated": True}
    return {"matches": matches, "files_scanned": scanned, "truncated": files_truncated}
