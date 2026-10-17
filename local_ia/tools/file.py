"""Outil de lecture d'un fichier autorisé."""

from pathlib import Path

import file_commands


def _standard_directories():
    home = Path.home()
    return [home / "Downloads", home / "Téléchargements"]


def normalize_path(path):
    """Convertit les formulations Downloads/Téléchargements en chemin réel."""
    value = str(path or "").strip().strip("\"'")
    folded = value.casefold()
    markers = (
        "téléchargements", "téléchargement", "telechargements", "telechargement",
        "dossier de téléchargements", "dossier de téléchargement",
        "dossier de telechargements", "dossier de telechargement",
        "downloads", "download",
    )
    for marker in sorted(markers, key=len, reverse=True):
        index = folded.find(marker)
        while index >= 0:
            end = index + len(marker)
            before_is_boundary = index == 0 or folded[index - 1] in "/\\ "
            after_is_boundary = end == len(folded) or folded[end] in "/\\ "
            if before_is_boundary and after_is_boundary:
                break
            index = folded.find(marker, index + 1)
        if index < 0:
            continue
        suffix = value[index + len(marker):].lstrip(" /\\")
        directories = _standard_directories()
        base = next((directory for directory in directories if directory.is_dir()), directories[0])
        return str(base / suffix) if suffix else str(base)
    return value


def _allow_standard_directories():
    roots = [str(root) for root in file_commands.FILE_ACCESS_ROOTS]
    for directory in _standard_directories():
        if str(directory.resolve()) not in roots:
            roots.append(str(directory))
    file_commands.set_access_roots(roots)


def use(path, extension=None, allowed_roots=None):
    if allowed_roots is None:
        _allow_standard_directories()
        path = normalize_path(path)
    return file_commands.read_file(path, extension, allowed_roots)