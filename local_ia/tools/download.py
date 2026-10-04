"""Persist generated text files and cache copies for GUI download actions."""

from __future__ import annotations

import hashlib
import os
import shutil
import sys
import uuid
from pathlib import Path


if sys.platform == "win32":
    _cache_root = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
elif sys.platform == "darwin":
    _cache_root = Path.home() / "Library" / "Caches"
else:
    _cache_root = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))

CACHE_DIR = _cache_root / "local_ia" / "downloads"
GENERATED_FILES_DIR = Path(__file__).resolve().parents[2] / "fichiers_generes"
MAX_DOWNLOAD_BYTES = 10 * 1024 * 1024


def _filename(value, extension=None):
    name = str(value or "").strip()
    if (
        not name
        or name in {".", ".."}
        or "/" in name
        or "\\" in name
        or any(character in name for character in '<>:"|?*')
        or any(ord(character) < 32 for character in name)
        or len(name) > 180
    ):
        raise ValueError("Nom de fichier invalide.")
    if extension and not Path(name).suffix:
        suffix = str(extension).strip().lstrip(".")
        if not suffix.isalnum() or len(suffix) > 16:
            raise ValueError("Extension de fichier invalide.")
        name = f"{name}.{suffix}"
    return name


def use(filename, content, extension=None):
    filename = _filename(filename, extension)
    if not isinstance(content, str):
        raise ValueError("Le contenu du fichier doit être du texte.")
    payload = content.encode("utf-8")
    if len(payload) > MAX_DOWNLOAD_BYTES:
        raise ValueError("Le fichier dépasse la taille maximale de 10 Mo.")

    artifact_id = uuid.uuid4().hex
    artifact_dir = CACHE_DIR / artifact_id
    artifact_dir.mkdir(parents=True, exist_ok=False)
    persistent_path = None
    try:
        GENERATED_FILES_DIR.mkdir(parents=True, exist_ok=True)
        stem = Path(filename).stem
        suffix = Path(filename).suffix
        attempt = 1
        while True:
            candidate_name = filename if attempt == 1 else f"{stem}-{attempt}{suffix}"
            candidate = GENERATED_FILES_DIR / candidate_name
            try:
                with candidate.open("xb") as output:
                    output.write(payload)
                persistent_path = candidate
                filename = candidate_name
                break
            except FileExistsError:
                attempt += 1

        target = artifact_dir / filename
        with target.open("xb") as output:
            output.write(payload)
    except OSError:
        shutil.rmtree(artifact_dir, ignore_errors=True)
        if persistent_path is not None:
            persistent_path.unlink(missing_ok=True)
        raise
    return {
        "artifact_id": artifact_id,
        "filename": filename,
        "size": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "ready": True,
    }


def resolve_cached_file(artifact_id, filename):
    try:
        normalized_id = uuid.UUID(hex=str(artifact_id)).hex
    except (AttributeError, TypeError, ValueError) as error:
        raise ValueError("Identifiant de fichier invalide.") from error
    filename = _filename(filename)
    artifact_dir = CACHE_DIR / normalized_id
    target = artifact_dir / filename
    if target.is_symlink() or target.resolve().parent != artifact_dir.resolve() or not target.is_file():
        raise FileNotFoundError("Le fichier temporaire n’est plus disponible.")
    return target


def copy_to(artifact_id, filename, destination):
    source = resolve_cached_file(artifact_id, filename)
    target = Path(destination).expanduser()
    shutil.copyfile(source, target)
    return target