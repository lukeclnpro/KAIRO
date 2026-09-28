"""Outil de modification ciblée d'un fichier (remplacement de texte exact).

Pensé pour corriger un bug sans réécrire tout le fichier : le texte à
remplacer doit être trouvé exactement une fois. Une sauvegarde est faite
avant chaque modification, et un fichier Python valide ne peut pas être
transformé en fichier invalide.
"""

from __future__ import annotations

import ast
import shutil
import time
from uuid import uuid4
from pathlib import Path

import file_commands
from local_ia.config.manager import BASE_DIR
from local_ia.tools.file import _allow_standard_directories, normalize_path

BACKUP_DIR = BASE_DIR / ".local_ia_backups"


def backup_file(path):
    """Copie le fichier existant dans .local_ia_backups/. Retourne la copie ou None."""
    source = Path(path).expanduser()
    if not source.is_file():
        return None
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    target = BACKUP_DIR / f"{time.strftime('%Y%m%d-%H%M%S')}-{uuid4().hex}-{source.name}"
    try:
        shutil.copy2(source, target)
    except Exception:
        target.unlink(missing_ok=True)
        raise
    return str(target)


def _python_is_valid(source):
    try:
        ast.parse(source)
        return True
    except (SyntaxError, ValueError):
        return False


def use(path, old, new, replace_all=False):
    if not isinstance(old, str) or old == "":
        raise ValueError("Le texte à remplacer (old) est vide.")
    if not isinstance(new, str):
        raise ValueError("Le nouveau texte (new) est manquant.")

    _allow_standard_directories()
    target = file_commands._resolve(normalize_path(path))
    if not target.is_file():
        raise FileNotFoundError(f"Fichier introuvable : {target}")

    text = file_commands._read_text(target)
    # Fichier Windows (CRLF) : le modèle écrit avec des \n.
    if "\r\n" in text and "\r\n" not in old:
        old, new = old.replace("\n", "\r\n"), new.replace("\n", "\r\n")

    found = text.count(old)
    if found == 0:
        raise ValueError(
            "Texte à remplacer introuvable dans le fichier. "
            "Relis le fichier et copie le texte exact (espaces et indentation compris)."
        )
    if found > 1 and not replace_all:
        raise ValueError(
            f"Le texte à remplacer apparaît {found} fois. "
            "Ajoute quelques lignes de contexte pour le rendre unique."
        )

    updated = text.replace(old, new)
    raw = updated.encode("utf-8")
    if len(raw) > file_commands.MAX_WRITE_BYTES:
        raise ValueError("Le fichier modifié serait trop volumineux.")

    syntax_ok = None
    if target.suffix.lower() == ".py":
        syntax_ok = _python_is_valid(updated)
        if not syntax_ok and _python_is_valid(text):
            raise ValueError("Modification refusée : elle introduirait une erreur de syntaxe Python.")

    backup = backup_file(target)
    target.write_bytes(raw)
    return {
        "path": str(target),
        "replacements": found if replace_all else 1,
        "backup": backup,
        "syntax_ok": syntax_ok,
    }
