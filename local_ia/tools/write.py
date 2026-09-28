"""Outil de création et de modification de fichiers autorisés."""

from pathlib import Path

from file_commands import write_file
from local_ia.tools.file import _allow_standard_directories, normalize_path


def use(path, content, extension=None):
    _allow_standard_directories()
    normalized_path = normalize_path(path)
    if extension and not Path(normalized_path).suffix:
        normalized_path += "." + str(extension).lstrip(".")
    return write_file(normalized_path, content, extension)