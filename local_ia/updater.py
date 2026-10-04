"""Primitives de vérification des mises à jour de KAIRO."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path
from urllib.error import URLError
from urllib import request as urllib_request
from local_ia.http_client import open_url

REMOTE_VERSION_URL = "https://raw.githubusercontent.com/lukeclnpro/KAIRO/main/version.json"
REMOTE_ARCHIVE_URL = "https://github.com/lukeclnpro/KAIRO/archive/refs/heads/main.zip"


def _run_git(base_dir, arguments, timeout=15):
    import os

    environment = os.environ.copy()
    environment["GIT_TERMINAL_PROMPT"] = "0"
    result = subprocess.run(
        ["git", "-C", str(Path(base_dir).resolve()), *arguments],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
        env=environment,
    )
    if result.returncode:
        message = result.stderr.strip() or result.stdout.strip() or "La commande Git a échoué."
        raise RuntimeError(message)
    return result.stdout.strip()


def inspect_git_update(base_dir):
    root = Path(base_dir).resolve()
    repository_root = Path(_run_git(root, ["rev-parse", "--show-toplevel"])).resolve()
    if repository_root != root:
        raise RuntimeError("Le dossier de l'application n'est pas la racine du dépôt Git.")
    if _run_git(root, ["status", "--porcelain", "--untracked-files=normal"]):
        raise RuntimeError("Mise à jour refusée : le dépôt contient des modifications locales.")
    branch = _run_git(root, ["rev-parse", "--abbrev-ref", "HEAD"])
    try:
        upstream = _run_git(root, ["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"])
    except RuntimeError as error:
        raise RuntimeError("Aucune branche distante de suivi n'est configurée pour ce dépôt.") from error
    return {"root": str(root), "branch": branch, "upstream": upstream}


def update_via_git(base_dir):
    details = inspect_git_update(base_dir)
    output = _run_git(details["root"], ["pull", "--ff-only"], timeout=180)
    return {**details, "output": output or "Le dépôt est déjà à jour."}


def fetch_remote_version(version_url=REMOTE_VERSION_URL):
    request = urllib_request.Request(version_url, headers={"User-Agent": "KAIRO-Updater"})
    with open_url(request, timeout=10) as response:
        data = json.loads(response.read().decode("utf-8"))
    version = data.get("version") if isinstance(data, dict) else None
    if not version:
        raise RuntimeError("La version distante est absente ou invalide.")
    return str(version)


def load_json_file(path):
    try:
        with Path(path).open("r", encoding="utf-8") as source:
            return json.load(source)
    except (OSError, json.JSONDecodeError):
        return None


def get_current_version(version_file):
    data = load_json_file(version_file)
    if not data:
        return "0.0.0"
    return str(data.get("version", "0.0.0"))


def required_update_files(source_dir):
    required_files = [
        Path("version.json"),
        Path("update.json"),
        Path("LICENSE"),
        Path("THIRD_PARTY_NOTICES.md"),
    ]
    for relative_path in required_files:
        if not (Path(source_dir) / relative_path).is_file():
            raise RuntimeError(f"Le fichier {relative_path} est absent du dépôt GitHub.")
    return required_files


def download_json(url, ui_module):
    try:
        request = urllib_request.Request(url, headers={"User-Agent": "Local-IA-Updater"})
        with open_url(request, timeout=10) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception as error:
        print()
        ui_module.print_error(f"Impossible de récupérer les informations : {error}")
        return None


def version_to_tuple(version):
    try:
        parts = re.findall(r"\d+", str(version).strip().lstrip("v"))
        if parts:
            values = tuple(int(part) for part in parts)
            return values + (0,) * max(0, 4 - len(values))
    except (ValueError, TypeError):
        pass
    return (0, 0, 0, 0)


def check_for_update(current_version, remote_data, show_message, ui_module):
    remote_version = str(remote_data.get("version", current_version))
    if version_to_tuple(remote_version) > version_to_tuple(current_version):
        if show_message:
            print()
            ui_module.print_warn("Une nouvelle version est disponible !")
            print(f"Version installée : {current_version}")
            print(f"Nouvelle version  : {remote_version}")
        return True, remote_version

    if show_message:
        print()
        ui_module.print_ok(f"Vous utilisez déjà la dernière version ({current_version}).")
    return False, current_version


def collect_update_files(source_dir, required_files):
    source_dir = Path(source_dir)
    update_files = []
    for source_path in source_dir.rglob("*.py"):
        if not source_path.is_file():
            continue
        relative_path = source_path.relative_to(source_dir)
        if any(
            part in {".git", "__pycache__", ".github", "chats", "code", "fichiers_generes", "tests"}
            for part in relative_path.parts
        ):
            continue
        update_files.append(relative_path)

    catalog_path = source_dir / "program_catalog.json"
    if catalog_path.is_file():
        update_files.append(catalog_path.relative_to(source_dir))

    update_files.extend(required_files(source_dir))
    return list(dict.fromkeys(update_files))


def update_from_archive(base_dir, expected_version, archive_url=REMOTE_ARCHIVE_URL):
    base_dir = Path(base_dir)
    with tempfile.TemporaryDirectory() as temporary_directory:
        temp_dir = Path(temporary_directory)
        request = urllib_request.Request(archive_url, headers={"User-Agent": "KAIRO-Updater"})
        with open_url(request, timeout=60) as response:
            archive_path = temp_dir / "update.zip"
            archive_path.write_bytes(response.read())

        extract_dir = temp_dir / "extracted"
        extract_dir.mkdir()
        with zipfile.ZipFile(archive_path, "r") as archive:
            for member in archive.infolist():
                member_path = Path(member.filename)
                if member_path.is_absolute() or ".." in member_path.parts:
                    raise RuntimeError("L'archive contient un chemin de fichier invalide.")
            archive.extractall(extract_dir)

        source_dirs = list(extract_dir.iterdir())
        if len(source_dirs) != 1 or not source_dirs[0].is_dir():
            raise RuntimeError("Structure de l'archive GitHub invalide.")
        source_dir = source_dirs[0]
        source_version = get_current_version(source_dir / "version.json")
        if version_to_tuple(source_version) != version_to_tuple(expected_version):
            raise RuntimeError(
                f"La version téléchargée ({source_version}) ne correspond pas à la version annoncée "
                f"({expected_version})."
            )

        update_files = collect_update_files(source_dir, required_update_files)
        backup_dir = temp_dir / "backup"
        existing_files = set()
        for relative_path in update_files:
            destination = base_dir / relative_path
            if destination.exists():
                backup_path = backup_dir / relative_path
                backup_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(destination, backup_path)
                existing_files.add(relative_path)

        try:
            for relative_path in update_files:
                source = source_dir / relative_path
                destination = base_dir / relative_path
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
        except Exception:
            for relative_path in update_files:
                destination = base_dir / relative_path
                backup_path = backup_dir / relative_path
                if relative_path in existing_files and backup_path.exists():
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(backup_path, destination)
                elif destination.exists():
                    destination.unlink()
            raise

    return {"version": get_current_version(base_dir / "version.json"), "files_updated": len(update_files)}


def update_program(
    base_dir,
    remote_zip_url,
    ui_module,
    pause,
    check_for_update_callback,
    required_files,
    get_current_version_callback,
    version_to_tuple_callback,
):
    base_dir = Path(base_dir)
    ui_module.clear_screen()
    print()
    ui_module.section_title("MISE À JOUR", clear=False)
    print("Vérification de la dernière version...")

    update_available, version = check_for_update_callback(show_message=True)
    if update_available is None or not update_available:
        pause()
        return

    print()
    confirmation = ui_module.prompt(f"Installer la version {version} ? (o/N) : ").strip().lower()
    if confirmation != "o":
        ui_module.print_warn("Mise à jour annulée.")
        pause()
        return

    print()
    ui_module.print_info("Téléchargement des fichiers de mise à jour...")
    try:
        with tempfile.TemporaryDirectory() as temp:
            temp_dir = Path(temp)
            zip_path = temp_dir / "update.zip"
            request = urllib_request.Request(
                remote_zip_url,
                headers={"User-Agent": "Local-IA-Updater"},
            )
            with open_url(request, timeout=60) as response:
                zip_path.write_bytes(response.read())

            extract_dir = temp_dir / "extracted"
            extract_dir.mkdir()
            with zipfile.ZipFile(zip_path, "r") as archive:
                archive.extractall(extract_dir)

            source_dirs = list(extract_dir.iterdir())
            if len(source_dirs) != 1:
                raise RuntimeError("Structure de l'archive GitHub invalide.")
            source_dir = source_dirs[0]
            update_files = collect_update_files(source_dir, required_files)
            if not update_files:
                raise RuntimeError("Aucun fichier à mettre à jour trouvé.")

            print()
            ui_module.print_info(f"{len(update_files)} fichier(s) à mettre à jour.")
            print()
            for relative_path in update_files:
                if relative_path.suffix == ".py":
                    label = "Python"
                elif relative_path == Path("version.json"):
                    label = "Version"
                elif relative_path == Path("update.json"):
                    label = "Nouveautés"
                elif relative_path in {Path("LICENSE"), Path("THIRD_PARTY_NOTICES.md")}:
                    label = "Licence"
                elif relative_path == Path("program_catalog.json"):
                    label = "Catalogue d'applications"
                else:
                    label = "Fichier"
                print(f"  • {relative_path} ({label})")
            print()

            backup_dir = temp_dir / "backup"
            backup_dir.mkdir()
            existing_files = []
            for relative_path in update_files:
                destination = base_dir / relative_path
                if destination.exists():
                    backup_path = backup_dir / relative_path
                    backup_path.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(destination, backup_path)
                    existing_files.append(relative_path)

            try:
                for relative_path in update_files:
                    source = source_dir / relative_path
                    destination = base_dir / relative_path
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, destination)
            except Exception:
                ui_module.print_error("Erreur pendant la mise à jour.")
                for relative_path in existing_files:
                    backup_path = backup_dir / relative_path
                    destination = base_dir / relative_path
                    if backup_path.exists():
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(backup_path, destination)
                raise

            installed_version = get_current_version_callback()
            if version_to_tuple_callback(installed_version) != version_to_tuple_callback(version):
                ui_module.print_warn(
                    "Attention : la version installée ne correspond pas à la version téléchargée."
                )
                print(f"Version attendue : {version}")
                print(f"Version installée : {installed_version}")

            print()
            ui_module.print_ok(f"Programme mis à jour vers la version {version}.")
            print()
            ui_module.print_info("Fichiers Python mis à jour.")
            ui_module.print_info("Catalogue d'applications mis à jour.")
            ui_module.print_info("version.json mis à jour.")
            ui_module.print_info("update.json mis à jour.")
            print()
            ui_module.print_info("Vos autres fichiers JSON, configurations et conversations ont été conservés.")
            print()
            ui_module.print_info("Redémarrez le programme pour appliquer complètement la mise à jour.")
            pause()
    except URLError as error:
        ui_module.print_error(f"Erreur réseau : {error}")
        pause()
    except zipfile.BadZipFile:
        ui_module.print_error("L'archive téléchargée est invalide.")
        pause()
    except Exception as error:
        ui_module.print_error(f"La mise à jour a échoué : {error}")
        pause()