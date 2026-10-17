"""Exemples d'opérations de fichiers avec chemins explicites."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path


def read_text(path: str | Path, encoding: str = "utf-8") -> str:
    """Lit un fichier texte."""
    return Path(path).read_text(encoding=encoding)


def write_text_atomic(path: str | Path, content: str, encoding: str = "utf-8") -> None:
    """Écrit un fichier via un fichier temporaire puis un remplacement atomique."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
    try:
        with os.fdopen(descriptor, "w", encoding=encoding) as output:
            output.write(content)
        os.replace(temporary_name, target)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)


def load_json(path: str | Path, default=None):
    """Charge un JSON; retourne default seulement si le fichier n'existe pas."""
    target = Path(path)
    try:
        return json.loads(target.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default


def save_json(path: str | Path, data, *, indent: int = 2) -> None:
    """Enregistre des données JSON lisibles en UTF-8."""
    text = json.dumps(data, ensure_ascii=False, indent=indent) + "\n"
    write_text_atomic(path, text)


def list_files(directory: str | Path, suffix: str | None = None) -> list[Path]:
    """Liste les fichiers d'un dossier, éventuellement filtrés par extension."""
    root = Path(directory)
    if not root.is_dir():
        return []
    return sorted(
        (path for path in root.iterdir() if path.is_file() and (suffix is None or path.suffix == suffix)),
        key=lambda path: path.name.casefold(),
    )


def sha256_file(path: str | Path) -> str:
    """Calcule l'empreinte SHA-256 d'un fichier par blocs."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for block in iter(lambda: source.read(65536), b""):
            digest.update(block)
    return digest.hexdigest()
