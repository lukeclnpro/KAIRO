#!/usr/bin/env python3
"""Find and launch installed desktop applications."""

from __future__ import annotations

import configparser
import os
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path

# La liste des applications change rarement : on la garde en mémoire pour ne pas
# relire tous les fichiers .desktop (ou le menu Démarrer) à chaque lancement.
_APP_CACHE = {"time": 0.0, "apps": []}
_APP_CACHE_TTL = 300

_ALIASES = {
    "word": ("libreoffice", "soffice", "writer"),
    "spotify": ("spotify-launcher",),
}
# Jetons ajoutés par Flatpak dans la ligne Exec, à ne pas passer à l'application.
_FLATPAK_FIELD_CODES = {"@@", "@@u", "@@f", "@@F"}


def _desktop_files():
    roots = [
        Path.home() / ".local/share/applications",
        Path("/usr/share/applications"),
        Path("/usr/local/share/applications"),
        Path("/var/lib/flatpak/exports/share/applications"),
        Path.home() / ".local/share/flatpak/exports/share/applications",
        Path("/var/lib/snapd/desktop/applications"),
    ]
    for root in roots:
        if root.is_dir():
            yield from root.glob("*.desktop")


def _desktop_application(path: Path):
    parser = configparser.ConfigParser(interpolation=None, strict=False)
    parser.optionxform = str
    try:
        parser.read(path, encoding="utf-8")
        section = parser["Desktop Entry"]
        if (
            section.get("Type") != "Application"
            or section.get("NoDisplay", "false").lower() == "true"
            or section.get("Hidden", "false").lower() == "true"
        ):
            return None
        try_exec = section.get("TryExec", "").strip()
        if try_exec and shutil.which(try_exec) is None:
            return None
        name = section.get("Name", path.stem)
        command = section.get("Exec", "")
        if not command:
            return None
        argv = [
            part for part in shlex.split(command)
            if not part.startswith("%") and part not in _FLATPAK_FIELD_CODES
        ]
        if not argv:
            return None
        # Noms localisés (« Calculatrice » pour « Calculator ») : on accepte tous.
        names = {name.lower()}
        for key, value in section.items():
            if key.startswith("Name[") and value.strip():
                names.add(value.strip().lower())
        return {"name": name, "names": sorted(names), "argv": argv, "path": str(path)}
    except (OSError, configparser.Error, KeyError, UnicodeError, ValueError):
        return None


def _cached(load):
    now = time.time()
    if _APP_CACHE["apps"] and now - _APP_CACHE["time"] < _APP_CACHE_TTL:
        return _APP_CACHE["apps"]
    apps = [app for app in load() if app]
    _APP_CACHE.update(time=now, apps=apps)
    return apps


def _linux_applications():
    return _cached(lambda: (_desktop_application(path) for path in _desktop_files()))


def _windows_applications():
    def load():
        roots = [
            Path(os.environ.get("PROGRAMDATA", "")) / "Microsoft/Windows/Start Menu/Programs",
            Path(os.environ.get("APPDATA", "")) / "Microsoft/Windows/Start Menu/Programs",
        ]
        for root in roots:
            for candidate in root.rglob("*") if root.is_dir() else ():
                if candidate.suffix.lower() in (".lnk", ".exe"):
                    yield {
                        "name": candidate.stem,
                        "names": [candidate.stem.lower()],
                        "argv": [str(candidate)],
                        "path": str(candidate),
                    }
    return _cached(load)


def _match(applications, query, aliases=()):
    """Nom exact (ou alias, ou exécutable), puis nom qui commence par, puis qui contient."""
    for candidate in (query, *aliases):
        for app in applications:
            if (
                candidate in app["names"]
                or Path(app["argv"][0]).name.lower() == candidate
                or (candidate == "spotify-launcher" and "spotify (launcher)" in app["names"])
            ):
                return app
    if len(query) >= 3:
        for app in applications:
            if any(name.startswith(query) for name in app["names"]):
                return app
        for app in applications:
            if any(query in name for name in app["names"]):
                return app
    return None


def find_application(name: str):
    query = str(name or "").strip().lower()
    if not query:
        raise ValueError("Nom d'application vide.")

    aliases = _ALIASES.get(query, ())
    executable = shutil.which(query)
    if not executable:
        executable = next((shutil.which(candidate) for candidate in aliases), None)
    if executable:
        return {"name": Path(executable).name, "argv": [executable], "path": executable}

    if sys.platform.startswith("linux"):
        return _match(_linux_applications(), query, aliases)

    if sys.platform == "darwin":
        for root in (Path("/Applications"), Path.home() / "Applications"):
            candidate = root / f"{name}.app"
            if candidate.exists():
                return {"name": name, "argv": ["open", "-a", str(candidate)], "path": str(candidate)}

    if os.name == "nt":
        return _match(_windows_applications(), query, aliases)
    return None


def launch_application(name: str):
    application = find_application(name)
    if not application:
        raise FileNotFoundError(f"Application introuvable : {name}")
    if os.name == "nt" and Path(application["path"]).suffix.lower() == ".lnk" and hasattr(os, "startfile"):
        os.startfile(application["path"])  # les raccourcis .lnk ne se lancent pas avec Popen
        return application
    subprocess.Popen(
        application["argv"],
        cwd=str(Path.home()),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    return application
