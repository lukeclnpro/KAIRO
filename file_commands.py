#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Commandes /fichier pour local_ia.

Syntaxes supportées :
  /fichier-"txt"-"/chemin/fichier.txt"
  /fichier "./fichier.txt"
  /fichier create "./fichier.md"
  /fichier-create-"md"-"./fichier.md"
  /fichier edit "./fichier.md"

Les chemins sont résolus localement sur la machine qui exécute le serveur.
Par défaut, la taille des fichiers lus/écrits est limitée pour éviter
qu'un seul appel ne remplisse le contexte ou le disque. La limite d'écriture
s'applique à chaque bloc; les ajouts successifs n'ont pas de plafond cumulé.
"""

from __future__ import annotations

import base64
import json
import os
import re
import zipfile
from pathlib import Path
from typing import Optional

BASE_DIR = Path(__file__).resolve().parent
MAX_READ_BYTES = 2 * 1024 * 1024
MAX_WRITE_BYTES = 2 * 1024 * 1024
# Par défaut, le serveur ne peut lire/écrire que dans le dossier du projet.
# D autres racines peuvent être ajoutées via FILE_ACCESS_ROOTS dans config.json.
FILE_ACCESS_ROOTS = [BASE_DIR]


def set_access_roots(roots):
    global FILE_ACCESS_ROOTS
    resolved = []
    for root in roots or []:
        try:
            resolved.append(Path(os.path.expanduser(os.path.expandvars(str(root)))).resolve())
        except Exception:
            pass
    FILE_ACCESS_ROOTS = resolved or [BASE_DIR]


def _is_allowed(path: Path) -> bool:
    return any(path == root or root in path.parents for root in FILE_ACCESS_ROOTS)

TEXT_EXTENSIONS = {
    "txt", "md", "markdown", "py", "js", "ts", "tsx", "jsx", "html", "css",
    "json", "jsonl", "csv", "tsv", "xml", "yaml", "yml", "ini", "cfg", "conf",
    "toml", "sh", "bash", "ps1", "bat", "cmd", "sql", "c", "h", "cpp", "hpp",
    "java", "kt", "rs", "go", "php", "rb", "swift", "dart", "vue", "svelte",
    "env", "log", "tex", "rst", "gitignore", "dockerfile"
}


def _clean(value: str) -> str:
    value = str(value or "").strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
        value = value[1:-1]
    return value.strip()


def _resolve(path_text: str, allowed_roots=None) -> Path:
    path_text = os.path.expandvars(os.path.expanduser(_clean(path_text)))
    p = Path(path_text)
    if not p.is_absolute():
        p = BASE_DIR / p
    p = p.resolve()
    if allowed_roots is None:
        roots = FILE_ACCESS_ROOTS
    else:
        roots = [Path(root).expanduser().resolve() for root in allowed_roots]
    if not any(p == root or root in p.parents for root in roots):
        root_names = ", ".join(str(root) for root in roots)
        raise PermissionError(f"Accès refusé. Le chemin doit être dans : {root_names}")
    return p


def _extension(path: Path, explicit: Optional[str] = None) -> str:
    if explicit:
        return explicit.lower().lstrip(".")
    return path.suffix.lower().lstrip(".") or path.name.lower()


def _read_text(path: Path) -> str:
    if path.stat().st_size > MAX_READ_BYTES:
        raise ValueError(f"Fichier trop volumineux ({path.stat().st_size} octets, maximum {MAX_READ_BYTES}).")
    raw = path.read_bytes()
    if len(raw) > MAX_READ_BYTES:
        raise ValueError(f"Fichier trop volumineux ({len(raw)} octets, maximum {MAX_READ_BYTES}).")
    for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError("Le fichier n'est pas un fichier texte lisible.")


def read_file(path_text: str, explicit_extension: Optional[str] = None, allowed_roots=None) -> dict:
    path = _resolve(path_text, allowed_roots)
    if not path.exists():
        raise FileNotFoundError(f"Fichier introuvable : {path}")
    if not path.is_file():
        raise ValueError(f"Ce chemin n'est pas un fichier : {path}")

    ext = _extension(path, explicit_extension)
    size = path.stat().st_size

    if ext in TEXT_EXTENSIONS or ext == path.name.lower():
        content = _read_text(path)
        return {"path": str(path), "extension": ext, "size": size, "content": content, "kind": "text"}

    if ext == "zip":
        if size > MAX_READ_BYTES * 4:
            raise ValueError("Archive ZIP trop volumineuse pour une lecture directe.")
        with zipfile.ZipFile(path) as zf:
            entries = []
            for info in zf.infolist():
                entries.append({"name": info.filename, "size": info.file_size, "directory": info.is_dir()})
            return {
                "path": str(path), "extension": ext, "size": size,
                "kind": "archive", "content": json.dumps(entries, ensure_ascii=False, indent=2)
            }

    # Pour les formats binaires, on ne met pas les octets bruts dans le prompt.
    if size > MAX_READ_BYTES:
        raise ValueError(f"Fichier binaire trop volumineux ({size} octets).")
    raw = path.read_bytes()
    return {
        "path": str(path), "extension": ext, "size": size, "kind": "binary",
        "content": f"Fichier binaire .{ext}, {size} octets. Base64 :\n{base64.b64encode(raw).decode('ascii')}"
    }


def write_file(path_text: str, content: str, explicit_extension: Optional[str] = None, allowed_roots=None) -> dict:
    path = _resolve(path_text, allowed_roots)
    content = str(content)
    raw = content.encode("utf-8")
    if len(raw) > MAX_WRITE_BYTES:
        raise ValueError(f"Contenu trop volumineux ({len(raw)} octets, maximum {MAX_WRITE_BYTES}).")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return {
        "path": str(path),
        "extension": _extension(path, explicit_extension),
        "size": len(raw),
        "content": content,
    }


def append_file(path_text: str, content: str, explicit_extension: Optional[str] = None, allowed_roots=None) -> dict:
    """Ajoute un bloc UTF-8; la limite porte sur ce bloc, pas sur le fichier final."""
    path = _resolve(path_text, allowed_roots)
    raw = str(content).encode("utf-8")
    if len(raw) > MAX_WRITE_BYTES:
        raise ValueError(f"Bloc trop volumineux ({len(raw)} octets, maximum {MAX_WRITE_BYTES}).")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("ab") as output:
        output.write(raw)
    return {
        "path": str(path),
        "extension": _extension(path, explicit_extension),
        "size": path.stat().st_size,
        "appended_size": len(raw),
        "appended": True,
    }


def parse_command(message: str) -> Optional[dict]:
    """Retourne {action, path, extension} si le message est une commande fichier."""
    text = message.strip()

    # Syntaxe demandée : /fichier-"extension"-"chemin"
    m = re.fullmatch(r'/fichier-(["\']?)([^"\'-]+)\1-(["\'])(.*?)\3', text, re.S)
    if m:
        return {"action": "read", "extension": m.group(2), "path": m.group(4)}

    m = re.match(r'/fichier-(create|edit)-(["\']?)([^"\'-]+)\2-(["\'])(.*?)\4(?:\n|$)', text, re.S | re.I)
    if m:
        return {"action": m.group(1).lower(), "extension": m.group(3), "path": m.group(5)}

    # Syntaxe lisible : /fichier "path", /fichier create "path", /fichier edit "path"
    m = re.match(r'/fichier(?:\s+(read|create|edit))?\s+["\'](.+?)["\'](?:\n|$)', text, re.S | re.I)
    if m:
        return {"action": (m.group(1) or "read").lower(), "path": m.group(2), "extension": None}

    return None


def extract_creation_content(message: str, command: dict) -> str:
    """Pour create/edit, tout ce qui suit la ligne de commande devient le contenu."""
    lines = message.splitlines()
    if not lines:
        return ""
    return "\n".join(lines[1:])


def execute_command(message: str) -> Optional[dict]:
    command = parse_command(message)
    if not command:
        return None

    action = command["action"]
    if action == "read":
        result = read_file(command["path"], command.get("extension"))
        return {"command": command, "result": result}

    content = extract_creation_content(message, command)
    if not content:
        raise ValueError("Pour créer/modifier un fichier, ajoutez son contenu après la commande.")
    result = write_file(command["path"], content, command.get("extension"))
    return {"command": command, "result": result}


def prompt_block(result: dict) -> str:
    data = result["result"]
    return (
        "\n\n===== FICHIER FOURNI PAR L'UTILISATEUR =====\n"
        f"Chemin : {data['path']}\n"
        f"Extension : .{data['extension']}\n"
        f"Taille : {data['size']} octets\n"
        f"Type : {data['kind']}\n"
        "----- CONTENU -----\n"
        f"{data['content']}\n"
        "===== FIN DU FICHIER =====\n"
    )
