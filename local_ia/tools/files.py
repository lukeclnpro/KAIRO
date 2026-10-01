"""Compatibilité vers le gestionnaire de fichiers."""

from file_commands import (
	BASE_DIR,
	FILE_ACCESS_ROOTS,
	MAX_READ_BYTES,
	MAX_WRITE_BYTES,
	TEXT_EXTENSIONS,
	append_file,
	execute_command,
	extract_creation_content,
	parse_command,
	prompt_block,
	read_file,
	set_access_roots,
	write_file,
)

__all__ = (
	"BASE_DIR", "FILE_ACCESS_ROOTS", "MAX_READ_BYTES", "MAX_WRITE_BYTES",
	"TEXT_EXTENSIONS", "append_file", "execute_command", "extract_creation_content",
	"parse_command", "prompt_block", "read_file", "set_access_roots", "write_file",
)