#!/usr/bin/env python3
"""Find and launch installed desktop applications."""

from __future__ import annotations

import configparser
import difflib
import json
import os
import shlex
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

# La liste des applications change rarement : on la garde en mémoire pour ne pas
# relire tous les fichiers .desktop (ou le menu Démarrer) à chaque lancement.
_APP_CACHE = {"time": 0.0, "apps": [], "scanned": False}
_APP_CACHE_TTL = 300
_APP_CACHE_LOCK = threading.RLock()
_APP_SCAN_LOCK = threading.Lock()
_APP_SCAN_READY = threading.Event()
_APP_SCAN_THREAD = None

_ALIASES = {
    "word": ("libreoffice", "soffice", "writer"),
    "spotify": ("spotify-launcher",),
}
# Jetons ajoutés par Flatpak dans la ligne Exec, à ne pas passer à l'application.
_FLATPAK_FIELD_CODES = {"@@", "@@u", "@@f", "@@F"}


def _registry_path():
    if os.name == "nt":
        data_home = Path(os.environ.get("APPDATA", Path.home() / "AppData/Roaming"))
    elif sys.platform == "darwin":
        data_home = Path.home() / "Library/Application Support"
    else:
        data_home = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))
    return data_home / "local_ia" / "applications.json"


def _normalize_name(name):
    return "".join(character for character in str(name).casefold() if character.isalnum())


def _read_registry():
    try:
        data = json.loads(_registry_path().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _write_registry(data):
    path = _registry_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def list_registered_applications():
    """Return unique applications saved for name-based launching."""
    applications = {}
    for entry in _read_registry().values():
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name", "")).strip()
        path = str(entry.get("path", "")).strip()
        if name and path:
            key = (_normalize_name(name), os.path.normcase(os.path.normpath(path)))
            applications[key] = {"name": name, "path": path}
    return sorted(applications.values(), key=lambda application: application["name"].casefold())


def unregister_application(path: str):
    """Remove all saved names that point to the given application path."""
    target = os.path.normcase(os.path.abspath(os.path.expanduser(str(path))))
    registry = _read_registry()
    matching_aliases = [
        alias for alias, entry in registry.items()
        if isinstance(entry, dict)
        and os.path.normcase(os.path.abspath(os.path.expanduser(str(entry.get("path", ""))))) == target
    ]
    for alias in matching_aliases:
        del registry[alias]
    if matching_aliases:
        _write_registry(registry)
    return len(matching_aliases)


def _application_from_path(path: Path):
    path = path.expanduser()
    if not path.exists():
        return None
    path = path.resolve()

    if sys.platform.startswith("linux") and path.suffix.lower() == ".desktop":
        return _desktop_application(path)
    if sys.platform == "darwin" and path.is_dir() and path.suffix.lower() == ".app":
        return {
            "name": path.stem,
            "names": [path.stem.casefold()],
            "argv": ["open", "-a", str(path)],
            "path": str(path),
        }
    if os.name == "nt" and path.suffix.lower() == ".lnk":
        return {
            "name": path.stem,
            "names": [path.stem.casefold()],
            "argv": [str(path)],
            "path": str(path),
        }
    if path.is_file() and (
        (os.name == "nt" and path.suffix.lower() in {".exe", ".com"})
        or os.access(path, os.X_OK)
    ):
        return {
            "name": path.stem,
            "names": [path.stem.casefold()],
            "argv": [str(path)],
            "path": str(path),
        }
    return None


def register_application(name: str, path: str):
    """Save a user-provided application path under its display and localized names."""
    application = _application_from_path(Path(path))
    if not application:
        raise FileNotFoundError(f"Chemin d'application introuvable ou non exécutable : {path}")

    display_name = str(name or application["name"]).strip()
    if not display_name:
        raise ValueError("Nom d'application vide.")
    application["name"] = display_name
    application["names"] = sorted(set(application["names"] + [display_name.casefold()]))

    registry = _read_registry()
    for alias in application["names"]:
        key = _normalize_name(alias)
        if key:
            registry[key] = {"name": display_name, "path": application["path"]}
    _write_registry(registry)
    return application


def register_application_alias(alias: str, application_name: str):
    """Map a user-facing app name to an installed app or an explicit path."""
    alias = str(alias or "").strip()
    if not alias:
        raise ValueError("Nom d'application vide.")

    requested_path = Path(str(application_name or "")).expanduser()
    if requested_path.is_absolute() or requested_path.exists():
        application = _application_from_path(requested_path)
    else:
        application = find_application(application_name)
    if not application:
        raise FileNotFoundError(f"Application introuvable : {application_name}")

    application = register_application(application["name"], application["path"])
    registry = _read_registry()
    registry[_normalize_name(alias)] = {
        "name": application["name"],
        "path": application["path"],
    }
    _write_registry(registry)
    return application


def _linux_desktop_directory():
    config_home = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    user_dirs_file = config_home / "user-dirs.dirs"
    try:
        for line in user_dirs_file.read_text(encoding="utf-8").splitlines():
            key, separator, value = line.partition("=")
            if separator and key.strip() == "XDG_DESKTOP_DIR":
                value = value.strip().strip('"').replace("$HOME", str(Path.home()))
                return Path(value).expanduser()
    except (OSError, UnicodeError):
        pass
    return Path.home() / "Desktop"


def _desktop_files():
    data_home = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share")
    roots = [
        data_home / "applications",
        Path("/usr/share/applications"),
        Path("/usr/local/share/applications"),
        Path("/var/lib/flatpak/exports/share/applications"),
        data_home / "flatpak/exports/share/applications",
        Path("/var/lib/snapd/desktop/applications"),
        _linux_desktop_directory(),
        Path("/opt"),
    ]
    roots.extend(
        Path(directory) / "applications"
        for directory in os.environ.get("XDG_DATA_DIRS", "/usr/local/share:/usr/share").split(os.pathsep)
        if directory
    )
    seen = set()
    for root in roots:
        if root.is_dir():
            try:
                for candidate in root.rglob("*.desktop"):
                    key = str(candidate)
                    if key not in seen:
                        seen.add(key)
                        yield candidate
            except OSError:
                continue


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
        categories = [item.strip().casefold() for item in section.get("Categories", "").split(";") if item.strip()]
        return {
            "name": name,
            "names": sorted(names),
            "argv": argv,
            "path": str(path),
            "categories": categories,
        }
    except (OSError, configparser.Error, KeyError, UnicodeError, ValueError):
        return None


def _cached(load, force=False):
    with _APP_CACHE_LOCK:
        now = time.time()
        if _APP_CACHE["scanned"] and not force and now - _APP_CACHE["time"] < _APP_CACHE_TTL:
            return _APP_CACHE["apps"]
        apps = [app for app in load() if app]
        _APP_CACHE.update(time=now, apps=apps, scanned=True)
        return apps


def _linux_applications(force=False):
    def load():
        for path in _desktop_files():
            application = _desktop_application(path)
            if application:
                yield application
        for root in (Path.home() / "Applications", Path.home() / "AppImages", Path("/opt")):
            for path in _walk_application_files(root, {".appimage"}, max_depth=5):
                application = _application_from_path(path)
                if application:
                    yield application
    return _cached(load, force=force)


_WALK_SKIP_DIRS = {
    ".git", "cache", "caches", "common files", "node_modules", "packages",
    "temp", "tmp", "updates", "windowsapps",
}


def _walk_application_files(root, suffixes, max_depth=6):
    root = Path(root)
    if not root.is_dir():
        return
    base_depth = len(root.parts)
    try:
        for current, directories, filenames in os.walk(root, onerror=lambda _error: None, followlinks=False):
            depth = len(Path(current).parts) - base_depth
            directories[:] = [
                name for name in directories
                if name.casefold() not in _WALK_SKIP_DIRS and not (Path(current) / name).is_symlink()
            ]
            if depth >= max_depth:
                directories.clear()
            for filename in filenames:
                candidate = Path(current) / filename
                if candidate.suffix.casefold() in suffixes:
                    yield candidate
    except OSError:
        return


def _windows_applications(force=False):
    def load():
        program_data = Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData"))
        app_data = Path(os.environ.get("APPDATA", Path.home() / "AppData/Roaming"))
        local_app_data = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local"))
        shortcuts = [
            program_data / "Microsoft/Windows/Start Menu/Programs",
            app_data / "Microsoft/Windows/Start Menu/Programs",
            program_data / "Microsoft/Windows/Start Menu",
            app_data / "Microsoft/Windows/Start Menu",
            Path.home() / "Desktop",
            program_data / "Desktop",
        ]
        installations = [
            Path(value) for value in (
                os.environ.get("ProgramFiles"),
                os.environ.get("ProgramFiles(x86)"),
            ) if value
        ] + [local_app_data / "Programs"]
        seen = set()
        for root in shortcuts:
            for candidate in _walk_application_files(root, {".lnk"}, max_depth=10):
                if str(candidate).casefold() not in seen:
                    seen.add(str(candidate).casefold())
                    yield _application_from_path(candidate)
        for root in installations:
            for candidate in _walk_application_files(root, {".exe", ".com"}, max_depth=6):
                if candidate.stem.casefold().startswith(("unins", "uninstall", "setup", "install")):
                    continue
                if str(candidate).casefold() not in seen:
                    seen.add(str(candidate).casefold())
                    yield _application_from_path(candidate)
    return _cached(load, force=force)


def _mac_applications(force=False):
    def load():
        roots = [
            Path("/Applications"),
            Path.home() / "Applications",
            Path("/System/Applications"),
            Path("/System/Library/CoreServices"),
        ]
        for root in roots:
            for candidate in _walk_macos_applications(root):
                yield {
                    "name": candidate.stem,
                    "names": [candidate.stem.casefold()],
                    "argv": ["open", "-a", str(candidate)],
                    "path": str(candidate),
                }
    return _cached(load, force=force)


def _walk_macos_applications(root, max_depth=7):
    root = Path(root)
    if not root.is_dir():
        return
    base_depth = len(root.parts)
    try:
        for current, directories, _filenames in os.walk(root, onerror=lambda _error: None, followlinks=False):
            depth = len(Path(current).parts) - base_depth
            apps = [name for name in directories if name.casefold().endswith(".app")]
            for name in apps:
                yield Path(current) / name
            directories[:] = [
                name for name in directories
                if not name.casefold().endswith(".app")
                and name.casefold() not in _WALK_SKIP_DIRS
                and not (Path(current) / name).is_symlink()
            ]
            if depth >= max_depth:
                directories.clear()
    except OSError:
        return


def _refresh_application_index():
    if sys.platform.startswith("linux"):
        _linux_applications(force=True)
    elif sys.platform == "darwin":
        _mac_applications(force=True)
    elif os.name == "nt":
        _windows_applications(force=True)
    _APP_SCAN_READY.set()


def _application_scan_loop():
    while True:
        try:
            _refresh_application_index()
        except (OSError, PermissionError, ValueError):
            _APP_SCAN_READY.set()
        _APP_SCAN_WAKEUP.wait(_APP_CACHE_TTL)
        _APP_SCAN_WAKEUP.clear()


_APP_SCAN_WAKEUP = threading.Event()


def start_application_scanner():
    """Start a non-blocking scanner that refreshes the local app index periodically."""
    global _APP_SCAN_THREAD
    with _APP_SCAN_LOCK:
        if _APP_SCAN_THREAD and _APP_SCAN_THREAD.is_alive():
            return
        _APP_SCAN_THREAD = threading.Thread(
            target=_application_scan_loop,
            name="kairo-application-index",
            daemon=True,
        )
        _APP_SCAN_THREAD.start()


def list_applications():
    """Return installed desktop applications without exposing launch commands."""
    start_application_scanner()
    if not _APP_SCAN_READY.is_set():
        _APP_SCAN_READY.wait(1.5)
    with _APP_CACHE_LOCK:
        applications = list(_APP_CACHE["apps"])

    unique = {}
    for application in applications:
        name = str(application.get("name", "")).strip()
        if name:
            key = _normalize_name(name)
            entry = unique.setdefault(key, {"name": name, "categories": []})
            entry["categories"] = sorted(set(entry["categories"]) | set(application.get("categories", [])))
    return sorted(unique.values(), key=lambda application: application["name"].casefold())


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
    raw_query = str(name or "").strip().strip("\"'")
    if not raw_query:
        raise ValueError("Nom d'application vide.")

    requested_path = Path(raw_query).expanduser()
    if requested_path.is_absolute() or requested_path.exists():
        application = _application_from_path(requested_path)
        if application:
            return register_application(application["name"], str(requested_path))
        if requested_path.is_absolute():
            return None

    query = raw_query.lower()
    registry = _read_registry()
    normalized_query = _normalize_name(query)
    registered = registry.get(normalized_query)
    if registered is None and len(normalized_query) >= 5:
        close_alias = max(
            registry,
            key=lambda alias: difflib.SequenceMatcher(None, normalized_query, alias).ratio(),
            default=None,
        )
        if close_alias and difflib.SequenceMatcher(None, normalized_query, close_alias).ratio() >= 0.82:
            registered = registry[close_alias]
    if isinstance(registered, dict):
        application = _application_from_path(Path(registered.get("path", "")))
        if application:
            application["name"] = registered.get("name") or application["name"]
            application["names"] = sorted(
                set(application["names"] + [application["name"].casefold()])
            )
            return application

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
