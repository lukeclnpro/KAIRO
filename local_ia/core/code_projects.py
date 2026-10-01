"""Manage LOCAL_CODE projects inside the user's Documents folder."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import unicodedata
from pathlib import Path


_PROJECT_NAME_RE = re.compile(r"[\w .()-]{1,64}", re.UNICODE)
CODE_EXAMPLES_SOURCE = Path(__file__).resolve().parents[2] / "code" / "exemple"
_WINDOWS_RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}


def get_documents_directory() -> Path:
    if os.name == "nt":
        try:
            import winreg

            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders",
            ) as key:
                value, _ = winreg.QueryValueEx(key, "Personal")
            return Path(os.path.expandvars(value)).expanduser()
        except (ImportError, OSError):
            pass

    if sys.platform.startswith("linux"):
        xdg_user_dir = shutil.which("xdg-user-dir")
        if xdg_user_dir:
            try:
                result = subprocess.run(
                    [xdg_user_dir, "DOCUMENTS"],
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=2,
                )
                directory = Path(result.stdout.strip()).expanduser()
                if directory.is_absolute():
                    return directory
            except (OSError, subprocess.SubprocessError):
                pass

    return Path.home() / "Documents"


def get_projects_root() -> Path:
    return get_documents_directory() / "ia_local" / "code"


def _validate_project_name(name: str) -> str:
    value = str(name or "").strip()
    if (
        not value
        or value in {".", ".."}
        or not _PROJECT_NAME_RE.fullmatch(value)
        or value.endswith((".", " "))
        or value.split(".", 1)[0].upper() in _WINDOWS_RESERVED_NAMES
    ):
        raise ValueError("Nom de projet invalide. Utilise 1 à 64 lettres, chiffres, espaces, tirets ou parenthèses.")
    return value


def create_or_open_project(name: str) -> Path:
    project_name = _validate_project_name(name)
    root = get_projects_root().resolve()
    root.mkdir(parents=True, exist_ok=True)
    project = (root / project_name).resolve()
    if project.parent != root:
        raise ValueError("Le chemin du projet doit rester dans le dossier des projets Local IA.")
    if project.exists() and not project.is_dir():
        raise FileExistsError(f"Un fichier porte déjà le nom du projet : {project_name}")
    project.mkdir(exist_ok=True)
    return project


def suggest_project_name(description: str) -> str:
    """Construit un nom de projet lisible et unique depuis la demande."""
    normalized = unicodedata.normalize("NFKD", str(description or "").casefold())
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    ignored_words = {
        "cree", "creer", "moi", "me", "un", "une", "le", "la", "les", "des",
        "du", "de", "dans", "avec", "qui", "que", "pour", "et", "mon", "ma",
        "please", "make", "create", "a", "an", "the", "my", "me", "with", "for",
    }
    words = [
        word for word in re.findall(r"[a-z0-9]+", ascii_text)
        if word not in ignored_words
    ]
    base_name = "-".join(words[:6])[:48].strip("-") or "nouveau-projet"
    existing_names = {project.name.casefold() for project in list_projects()}
    candidate = base_name
    suffix = 2
    while candidate.casefold() in existing_names:
        suffix_text = f"-{suffix}"
        candidate = f"{base_name[:48 - len(suffix_text)].rstrip('-')}{suffix_text}"
        suffix += 1
    return candidate


def list_projects() -> list[Path]:
    root = get_projects_root().resolve()
    if not root.is_dir():
        return []
    return sorted(
        (path for path in root.iterdir() if path.is_dir() and path.resolve().parent == root),
        key=lambda path: path.name.casefold(),
    )


def resolve_active_project(path: str | Path) -> Path:
    root = get_projects_root().resolve()
    project = Path(path).expanduser().resolve()
    if project.parent != root or not project.is_dir():
        raise ValueError("Le projet actif est introuvable ou situé hors du dossier Local IA.")
    return project


def resolve_project_path(project: str | Path, path: str | Path = ".") -> Path:
    project_root = resolve_active_project(project)
    requested = Path(str(path or ".")).expanduser()
    target = (requested if requested.is_absolute() else project_root / requested).resolve()
    if target != project_root and project_root not in target.parents:
        raise PermissionError("Accès refusé : le mode code ne peut accéder qu'au projet actif.")
    return target


def install_code_examples(project: str | Path) -> Path:
    """Ajoute les exemples manquants au projet actif sans écraser ses fichiers."""
    project_root = resolve_active_project(project)
    examples_root = resolve_project_path(project_root, "exemple")
    if not CODE_EXAMPLES_SOURCE.is_dir():
        return examples_root

    for source in CODE_EXAMPLES_SOURCE.rglob("*"):
        if not source.is_file():
            continue
        relative_path = source.relative_to(CODE_EXAMPLES_SOURCE)
        destination = resolve_project_path(project_root, Path("exemple") / relative_path)
        if destination.exists():
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
    return examples_root


def open_code_projects() -> Path:
    root = get_projects_root().resolve()
    root.mkdir(parents=True, exist_ok=True)

    if os.name == "nt":
        os.startfile(str(root))
    else:
        opener = "open" if sys.platform == "darwin" else "xdg-open"
        executable = shutil.which(opener)
        if executable is None:
            raise FileNotFoundError(f"Impossible de trouver {opener} pour ouvrir le dossier.")
        subprocess.Popen(
            [executable, str(root)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    return root