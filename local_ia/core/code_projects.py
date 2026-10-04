"""Manage LOCAL_CODE projects inside the user's Documents folder."""

from __future__ import annotations

import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import unicodedata
import zipfile
from pathlib import Path, PurePosixPath


_PROJECT_NAME_RE = re.compile(r"[\w .()-]{1,64}", re.UNICODE)
CODE_EXAMPLES_SOURCE = Path(__file__).resolve().parents[2] / "code" / "exemple"
MAX_IMPORTED_PROJECT_BYTES = 512 * 1024 * 1024
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


def _read_project_metadata(project: str | Path) -> tuple[Path, dict]:
    project_root = resolve_active_project(project)
    metadata_path = resolve_project_path(project_root, ".local_ia.json")
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        metadata = {}
    return metadata_path, metadata if isinstance(metadata, dict) else {}


def _write_project_metadata(metadata_path: Path, metadata: dict) -> None:
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def get_project_category(project: str | Path) -> str:
    _metadata_path, metadata = _read_project_metadata(project)
    return str(metadata.get("category") or "").strip()


def set_project_category(project: str | Path, category: str) -> None:
    metadata_path, metadata = _read_project_metadata(project)
    value = str(category or "").strip()
    if value:
        metadata["category"] = value
    else:
        metadata.pop("category", None)
    _write_project_metadata(metadata_path, metadata)


def get_project_disabled_tools(project: str | Path) -> set[str]:
    _metadata_path, metadata = _read_project_metadata(project)
    disabled = metadata.get("disabled_tools", [])
    if not isinstance(disabled, list):
        return set()
    return {name for name in disabled if isinstance(name, str)}


def set_project_disabled_tools(project: str | Path, disabled_tools) -> None:
    metadata_path, metadata = _read_project_metadata(project)
    disabled = sorted({str(name) for name in disabled_tools if isinstance(name, str)})
    if disabled:
        metadata["disabled_tools"] = disabled
    else:
        metadata.pop("disabled_tools", None)
    _write_project_metadata(metadata_path, metadata)


def list_project_tasks(project: str | Path) -> list[dict]:
    _metadata_path, metadata = _read_project_metadata(project)
    tasks = metadata.get("tasks", [])
    if not isinstance(tasks, list):
        return []
    return [task for task in tasks if isinstance(task, dict)]


def save_project_tasks(project: str | Path, tasks: list[dict]) -> None:
    metadata_path, metadata = _read_project_metadata(project)
    if not isinstance(tasks, list) or any(not isinstance(task, dict) for task in tasks):
        raise ValueError("La liste des tâches est invalide.")
    metadata["tasks"] = tasks
    _write_project_metadata(metadata_path, metadata)


def delete_project(project: str | Path) -> None:
    shutil.rmtree(resolve_active_project(project))


def export_project(project: str | Path, destination: str | Path) -> Path:
    project_root = resolve_active_project(project)
    target = Path(destination).expanduser()
    if project_root in target.resolve().parents:
        raise ValueError("L’archive doit être enregistrée en dehors du projet.")
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(f"{project_root.name}/", "")
        for path in sorted(project_root.rglob("*")):
            if path.is_symlink():
                continue
            archive_name = PurePosixPath(project_root.name, *path.relative_to(project_root).parts).as_posix()
            if path.is_dir():
                archive.writestr(f"{archive_name}/", "")
            elif path.is_file():
                archive.write(path, archive_name)
    return target


def import_project(source: str | Path) -> Path:
    source_path = Path(source).expanduser()
    root = get_projects_root().resolve()
    root.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(source_path, "r") as archive:
            entries = []
            top_level_names = set()
            seen_paths = set()
            total_size = 0
            for info in archive.infolist():
                raw_name = info.filename
                if "\\" in raw_name or raw_name.startswith("/"):
                    raise ValueError("L’archive contient un chemin invalide.")
                raw_parts = raw_name.split("/")
                if info.is_dir() and raw_parts[-1] == "":
                    raw_parts.pop()
                if not raw_parts or any(part in {"", ".", ".."} for part in raw_parts):
                    raise ValueError("L’archive contient un chemin invalide.")
                if any(any(character in part for character in '<>:"|?*') for part in raw_parts):
                    raise ValueError("L’archive contient un nom de fichier invalide.")
                if (info.external_attr >> 16) & 0o170000 == stat.S_IFLNK:
                    raise ValueError("L’import de liens symboliques n’est pas autorisé.")
                archive_path = "/".join(raw_parts).casefold()
                if archive_path in seen_paths:
                    raise ValueError("L’archive contient des chemins en double.")
                seen_paths.add(archive_path)
                top_level_names.add(raw_parts[0])
                if len(raw_parts) > 1:
                    total_size += info.file_size
                    if total_size > MAX_IMPORTED_PROJECT_BYTES:
                        raise ValueError("L’archive dépasse la taille maximale de 512 Mo.")
                    entries.append((info, raw_parts[1:]))

            if len(top_level_names) != 1:
                raise ValueError("L’archive doit contenir un seul dossier de projet à sa racine.")
            project_name = _validate_project_name(top_level_names.pop())
            destination = root / project_name
            if destination.exists():
                raise FileExistsError(f"Un projet porte déjà ce nom : {project_name}")

            with tempfile.TemporaryDirectory(prefix=".import-", dir=root) as temporary_directory:
                staging = Path(temporary_directory) / project_name
                staging.mkdir()
                for info, relative_parts in entries:
                    target = staging.joinpath(*relative_parts)
                    if staging not in target.resolve().parents:
                        raise ValueError("L’archive contient un chemin hors du projet.")
                    if info.is_dir():
                        target.mkdir(parents=True, exist_ok=True)
                        continue
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open(info, "r") as archived_file, target.open("wb") as output_file:
                        shutil.copyfileobj(archived_file, output_file)
                staging.rename(destination)
            return destination
    except zipfile.BadZipFile as error:
        raise ValueError("Le fichier sélectionné n’est pas une archive ZIP valide.") from error


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