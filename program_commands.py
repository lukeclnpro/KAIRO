#!/usr/bin/env python3
"""Execution of local programs requested through the chat."""

from __future__ import annotations

import os
import json
import platform
import shutil
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Optional

import file_commands

MAX_OUTPUT_CHARS = 64 * 1024
DEFAULT_TIMEOUT = 30
CATALOG_PATH = Path(__file__).with_name("program_catalog.json")
BASE_DIR = Path(__file__).resolve().parent
LINUX_MANAGER_ORDER = {
    "ubuntu": ("apt", "flatpak", "dnf", "pacman", "zypper"),
    "debian": ("apt", "flatpak", "dnf", "pacman", "zypper"),
    "linuxmint": ("apt", "flatpak", "dnf", "pacman", "zypper"),
    "fedora": ("dnf", "flatpak", "apt", "pacman", "zypper"),
    "rhel": ("dnf", "flatpak", "apt", "pacman", "zypper"),
    "centos": ("dnf", "flatpak", "apt", "pacman", "zypper"),
    "arch": ("pacman", "flatpak", "apt", "dnf", "zypper"),
    "manjaro": ("pacman", "flatpak", "apt", "dnf", "zypper"),
    "opensuse": ("zypper", "flatpak", "apt", "dnf", "pacman"),
    "opensuse-leap": ("zypper", "flatpak", "apt", "dnf", "pacman"),
    "opensuse-tumbleweed": ("zypper", "flatpak", "apt", "dnf", "pacman"),
}
LINUX_MANAGER_BINARIES = {
    "apt": "apt",
    "dnf": "dnf",
    "flatpak": "flatpak",
    "pacman": "pacman",
    "zypper": "zypper",
}


def load_catalog(path=CATALOG_PATH):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Catalogue d'applications illisible : {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("programs"), list):
        raise ValueError("Le catalogue d'applications est invalide.")
    return data["programs"]


def get_catalog_programs(path=CATALOG_PATH):
    return load_catalog(path)


def find_catalog_program(name, path=CATALOG_PATH):
    normalized = "".join(
        character for character in str(name or "").casefold() if character.isalnum()
    )
    if not normalized:
        return None
    programs = load_catalog(path)

    def normalized_fields(program):
        return {
            "".join(
                character
                for character in str(program.get(key, "")).casefold()
                if character.isalnum()
            )
            for key in ("id", "name")
        }

    for program in programs:
        if normalized in normalized_fields(program):
            return program
    if len(normalized) >= 4:
        matches = [
            program
            for program in programs
            if any(normalized in field for field in normalized_fields(program))
        ]
        if len(matches) == 1:
            return matches[0]
    return None


def _linux_distro_ids():
    try:
        os_release = platform.freedesktop_os_release()
    except (AttributeError, OSError):
        return []
    values = [os_release.get("ID", ""), *os_release.get("ID_LIKE", "").split()]
    return [value.casefold() for value in values if value]


def _validate_install_command(command):
    if not isinstance(command, list) or not command or not all(
        isinstance(argument, str) and argument for argument in command
    ):
        raise ValueError("La commande d'installation du catalogue est invalide.")
    return command


def format_command(command, *, system=None):
    command = _validate_install_command(command)
    if (system or platform.system()).casefold() == "windows":
        return subprocess.list2cmdline(command)
    return shlex.join(command)


def get_installation_plan(
    program_id,
    *,
    catalog_path=CATALOG_PATH,
    system=None,
    distro_ids=None,
    which=None,
):
    which = which or shutil.which
    programs = load_catalog(catalog_path)
    program = next(
        (item for item in programs if item.get("id") == program_id),
        None,
    )
    if program is None:
        raise ValueError(f"Application inconnue dans le catalogue : {program_id}")

    os_name = (system or platform.system()).casefold()
    platform_key = {"windows": "windows", "darwin": "macos", "linux": "linux"}.get(os_name)
    if platform_key is None:
        raise ValueError(f"Système non pris en charge : {system or platform.system()}")

    install_data = program.get("install", {})
    if platform_key == "linux":
        options = install_data.get("linux", {})
        ids = distro_ids if distro_ids is not None else _linux_distro_ids()
        manager_order = next(
            (LINUX_MANAGER_ORDER.get(str(item).casefold()) for item in ids if str(item).casefold() in LINUX_MANAGER_ORDER),
            ("flatpak", "apt", "dnf", "pacman", "zypper"),
        )
        selected = None
        for manager in manager_order:
            spec = options.get(manager)
            if not isinstance(spec, dict) or not which(LINUX_MANAGER_BINARIES[manager]):
                continue
            selected = (manager, spec)
            break
        if selected is None:
            raise ValueError(f"Aucune méthode d'installation disponible pour {program['name']} sur cette distribution Linux.")
        manager, spec = selected
    else:
        spec = install_data.get(platform_key)
        if not isinstance(spec, dict):
            raise ValueError(f"Aucune méthode d'installation disponible pour {program['name']} sur {platform_key}.")
        manager = str(spec.get("manager") or (spec.get("command") or [""])[0])
        if not which(manager):
            raise ValueError(f"Le gestionnaire requis est introuvable : {manager}")

    command = _validate_install_command(spec.get("command"))
    return {
        "program": program,
        "manager": manager,
        "command": command,
        "requires": list(spec.get("requires", [])),
    }


def execute_install_command(command):
    command = _validate_install_command(command)
    return subprocess.run(command, cwd=str(BASE_DIR), check=False, shell=False)


def parse_command(message: str) -> Optional[dict]:
    """Return a parsed command for /executer or /execute."""
    text = message.strip()
    if not text or not text.lower().startswith(("/executer", "/execute")):
        return None
    try:
        parts = shlex.split(text, posix=os.name != "nt")
    except ValueError as exc:
        raise ValueError(f"Commande invalide : {exc}") from exc
    if not parts or parts[0].lower() not in ("/executer", "/execute"):
        return None
    if len(parts) < 2:
        raise ValueError('Syntaxe : /executer "chemin/du/programme" [arguments]')
    return {"path": parts[1], "args": parts[2:]}


def _truncate(value: str) -> str:
    if len(value) <= MAX_OUTPUT_CHARS:
        return value
    return value[:MAX_OUTPUT_CHARS] + "\n...[sortie tronquée]"


def execute_command(message: str) -> Optional[dict]:
    command = parse_command(message)
    if not command:
        return None

    path = file_commands._resolve(command["path"])
    if not path.exists():
        raise FileNotFoundError(f"Programme introuvable : {path}")
    if not path.is_file():
        raise ValueError(f"Ce chemin n'est pas un programme : {path}")

    try:
        executable = [sys.executable, str(path)] if path.suffix.lower() == ".py" else [str(path)]
        completed = subprocess.run(
            [*executable, *command["args"]],
            cwd=str(path.parent),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=DEFAULT_TIMEOUT,
            check=False,
        )
    except PermissionError as exc:
        raise PermissionError(
            f"Le programme n'est pas exécutable : {path}. "
            "Ajoutez un shebang et le droit d'exécution si nécessaire."
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise TimeoutError(f"Exécution interrompue après {DEFAULT_TIMEOUT} secondes.") from exc

    return {
        "command": command,
        "result": {
            "path": str(path),
            "returncode": completed.returncode,
            "stdout": _truncate(completed.stdout or ""),
            "stderr": _truncate(completed.stderr or ""),
        },
    }