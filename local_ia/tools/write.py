"""Outil de création et de modification de fichiers autorisés."""

from pathlib import Path

from file_commands import append_file, write_file
from local_ia.tools.file import _allow_standard_directories, normalize_path


def use(path, content, extension=None, allowed_roots=None, append=False):
    if allowed_roots is None:
        _allow_standard_directories()
        path = normalize_path(path)
    normalized_path = path
    if extension and not Path(normalized_path).suffix:
        normalized_path += "." + str(extension).lstrip(".")
    writer = append_file if append else write_file
    return writer(normalized_path, content, extension, allowed_roots)