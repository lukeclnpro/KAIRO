"""Primitives de vérification des mises à jour de KAIRO."""

from __future__ import annotations

import json
import re
import shutil
import tempfile
import zipfile
from pathlib import Path
from urllib.error import URLError
from urllib import request as urllib_request
from local_ia.http_client import open_url


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
        if any(part in {".git", "__pycache__", ".github"} for part in relative_path.parts):
            continue
        update_files.append(relative_path)

    web_dir = source_dir / "web"
    if web_dir.is_dir():
        for source_path in web_dir.rglob("*"):
            if source_path.is_file() and source_path.suffix.lower() in {".html", ".css", ".js"}:
                update_files.append(source_path.relative_to(source_dir))

    update_files.extend(required_files(source_dir))
    return list(dict.fromkeys(update_files))


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
                elif relative_path.parts and relative_path.parts[0] == "web":
                    label = {".html": "HTML", ".css": "CSS", ".js": "JavaScript"}.get(
                        relative_path.suffix.lower(), "Web"
                    )
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
            ui_module.print_info("Fichiers HTML/CSS/JS de l'interface web mis à jour.")
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