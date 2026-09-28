#!/usr/bin/env python3

import os
import sys
import re
import shutil
import subprocess
import platform
import difflib
from pathlib import Path


SYSTEM = platform.system()


# ============================================================
# OUTILS
# ============================================================

def normalize(value):
    value = value.lower()

    for ext in (
        ".exe", ".app", ".bin",
        ".desktop", ".cmd", ".bat"
    ):
        if value.endswith(ext):
            value = value[:-len(ext)]

    value = re.sub(r"[^a-z0-9]+", "", value)

    return value


def similarity(a, b):
    a = normalize(a)
    b = normalize(b)

    if not a or not b:
        return 0.0

    if a == b:
        return 1.0

    if a in b:
        return 0.95

    if b in a:
        return 0.90

    return difflib.SequenceMatcher(
        None,
        a,
        b
    ).ratio()


def run(command, timeout=5):
    try:
        result = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=timeout
        )

        return result.stdout.strip()

    except (
        FileNotFoundError,
        subprocess.TimeoutExpired,
        OSError
    ):
        return ""


# ============================================================
# PATH
# ============================================================

def search_path(query):

    results = []

    normalized_query = normalize(query)

    for directory in os.environ.get(
        "PATH", ""
    ).split(os.pathsep):

        if not directory:
            continue

        directory = Path(directory)

        try:
            if not directory.is_dir():
                continue

            for file in directory.iterdir():

                if not file.is_file():
                    continue

                score = similarity(
                    normalized_query,
                    file.name
                )

                if score >= 0.50:
                    results.append(
                        (score, file)
                    )

        except (PermissionError, OSError):
            pass

    return results


# ============================================================
# WINDOWS
# ============================================================

def search_windows(query):

    results = []

    # --------------------------------------------------------
    # 1. PATH
    # --------------------------------------------------------

    results.extend(
        search_path(query)
    )

    # --------------------------------------------------------
    # 2. Recherche Windows via where.exe
    # --------------------------------------------------------

    output = run(
        ["where", query],
        timeout=3
    )

    if output:

        for line in output.splitlines():

            path = Path(line.strip())

            if path.exists():

                results.append(
                    (0.98, path)
                )

    # --------------------------------------------------------
    # 3. App Paths du registre
    # --------------------------------------------------------

    try:

        import winreg

        registry_roots = [
            (
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\App Paths"
            ),
            (
                winreg.HKEY_LOCAL_MACHINE,
                r"Software\Microsoft\Windows\CurrentVersion\App Paths"
            ),
            (
                winreg.HKEY_LOCAL_MACHINE,
                r"Software\WOW6432Node\Microsoft\Windows\CurrentVersion\App Paths"
            ),
        ]

        q = normalize(query)

        for root, key_path in registry_roots:

            try:

                key = winreg.OpenKey(
                    root,
                    key_path
                )

            except OSError:
                continue

            try:

                count = winreg.QueryInfoKey(key)[0]

                for i in range(count):

                    try:

                        app_name = winreg.EnumKey(
                            key,
                            i
                        )

                        score = similarity(
                            q,
                            app_name
                        )

                        if score < 0.45:
                            continue

                        app_key = winreg.OpenKey(
                            key,
                            app_name
                        )

                        try:

                            executable = winreg.QueryValue(
                                app_key,
                                ""
                            )

                            executable = (
                                executable
                                .strip('"')
                            )

                            path = Path(executable)

                            if path.exists():

                                results.append(
                                    (
                                        score + 0.10,
                                        path
                                    )
                                )

                        except OSError:
                            pass

                        finally:
                            app_key.Close()

                    except OSError:
                        pass

            finally:
                key.Close()

    except ImportError:
        pass

    # --------------------------------------------------------
    # 4. Dossiers classiques
    # Recherche seulement quelques niveaux
    # --------------------------------------------------------

    locations = []

    for variable in (
        "ProgramFiles",
        "ProgramFiles(x86)",
        "LOCALAPPDATA",
        "APPDATA",
    ):

        value = os.environ.get(variable)

        if value:
            locations.append(
                Path(value)
            )

    for base in locations:

        if not base.exists():
            continue

        try:

            # On ne descend que sur quelques niveaux.
            for root, dirs, files in os.walk(base):

                depth = len(
                    Path(root).relative_to(base).parts
                )

                if depth >= 4:
                    dirs[:] = []

                for filename in files:

                    if not filename.lower().endswith(
                        (".exe", ".com", ".cmd", ".bat")
                    ):
                        continue

                    score = similarity(
                        query,
                        filename
                    )

                    if score >= 0.65:

                        results.append(
                            (
                                score,
                                Path(root) / filename
                            )
                        )

        except (PermissionError, OSError):
            pass

    return results


# ============================================================
# MACOS
# ============================================================

def search_macos(query):

    results = []

    # PATH
    results.extend(
        search_path(query)
    )

    # --------------------------------------------------------
    # Spotlight
    # --------------------------------------------------------

    if shutil.which("mdfind"):

        output = run(
            [
                "mdfind",
                "-onlyin",
                "/",
                query
            ],
            timeout=5
        )

        for line in output.splitlines():

            path = Path(line.strip())

            if not path.exists():
                continue

            score = similarity(
                query,
                path.name
            )

            if path.name.endswith(".app"):
                score += 0.20

            if score >= 0.45:

                results.append(
                    (
                        min(score, 1.0),
                        path
                    )
                )

    # Applications classiques
    locations = [
        Path("/Applications"),
        Path("/System/Applications"),
        Path.home() / "Applications",
    ]

    for base in locations:

        if not base.exists():
            continue

        try:

            for item in base.iterdir():

                score = similarity(
                    query,
                    item.name
                )

                if score >= 0.45:

                    results.append(
                        (
                            score,
                            item
                        )
                    )

        except (PermissionError, OSError):
            pass

    return results


# ============================================================
# LINUX
# ============================================================

def search_linux(query):

    results = []

    # --------------------------------------------------------
    # PATH
    # --------------------------------------------------------

    results.extend(
        search_path(query)
    )

    # --------------------------------------------------------
    # command -v
    # --------------------------------------------------------

    output = run(
        [
            "bash",
            "-c",
            f"command -v '{query}'"
        ],
        timeout=2
    )

    if output:

        path = Path(output)

        if path.exists():

            results.append(
                (1.0, path)
            )

    # --------------------------------------------------------
    # plocate / locate
    # --------------------------------------------------------

    locator = None

    if shutil.which("plocate"):
        locator = "plocate"

    elif shutil.which("locate"):
        locator = "locate"

    if locator:

        output = run(
            [
                locator,
                "-i",
                query
            ],
            timeout=5
        )

        for line in output.splitlines():

            path = Path(line.strip())

            if not path.exists():
                continue

            if not path.is_file():
                continue

            score = similarity(
                query,
                path.name
            )

            if score >= 0.45:

                results.append(
                    (score, path)
                )

    # --------------------------------------------------------
    # Applications .desktop
    # --------------------------------------------------------

    desktop_dirs = [
        Path("/usr/share/applications"),
        Path("/usr/local/share/applications"),
        Path.home() / ".local/share/applications",
    ]

    for directory in desktop_dirs:

        if not directory.exists():
            continue

        try:

            for desktop in directory.glob(
                "*.desktop"
            ):

                try:
                    content = desktop.read_text(
                        errors="ignore"
                    )

                except OSError:
                    continue

                name_match = re.search(
                    r"^Name=(.+)$",
                    content,
                    re.MULTILINE
                )

                exec_match = re.search(
                    r"^Exec=([^\s]+)",
                    content,
                    re.MULTILINE
                )

                if not name_match or not exec_match:
                    continue

                app_name = name_match.group(1)
                executable = exec_match.group(1)

                score = similarity(
                    query,
                    app_name
                )

                if score >= 0.45:

                    path = Path(executable)

                    if not path.is_absolute():

                        found = shutil.which(
                            executable
                        )

                        if found:
                            path = Path(found)

                    if path.exists():

                        results.append(
                            (
                                score + 0.15,
                                path
                            )
                        )

        except (PermissionError, OSError):
            pass

    return results


# ============================================================
# NETTOYAGE
# ============================================================

def clean_results(results):

    unique = {}

    for score, path in results:

        try:
            path = path.resolve()

        except OSError:
            continue

        if not path.exists():
            continue

        key = str(path).lower()

        if (
            key not in unique
            or score > unique[key][0]
        ):
            unique[key] = (
                score,
                path
            )

    results = list(
        unique.values()
    )

    results.sort(
        key=lambda x: x[0],
        reverse=True
    )

    return results


# ============================================================
# RECHERCHE
# ============================================================

def find_application(query):

    if SYSTEM == "Windows":
        results = search_windows(query)

    elif SYSTEM == "Darwin":
        results = search_macos(query)

    elif SYSTEM == "Linux":
        results = search_linux(query)

    else:
        results = search_path(query)

    return clean_results(results)


# ============================================================
# MAIN
# ============================================================

def main():

    if len(sys.argv) != 2:

        print(
            'Utilisation : python findapp.py "nom de l\'application"',
            file=sys.stderr
        )

        sys.exit(1)

    query = sys.argv[1].strip()

    if not query:
        sys.exit(1)

    results = find_application(query)

    if not results:

        print("NOT_FOUND")
        sys.exit(2)

    # Seulement le meilleur résultat
    print(
        results[0][1]
    )


if __name__ == "__main__":
    main()