#!/usr/bin/env python3
"""Execution of operating-system commands without invoking a shell."""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
from typing import Optional

import file_commands

MAX_OUTPUT_CHARS = 64 * 1024
DEFAULT_TIMEOUT = 30
MAX_TIMEOUT = 120


def parse_command(message: str) -> Optional[list[str]]:
    text = message.strip()
    if not text.lower().startswith(("/commande", "/command")):
        return None
    try:
        parts = shlex.split(text, posix=os.name != "nt")
    except ValueError as exc:
        raise ValueError(f"Commande invalide : {exc}") from exc
    if not parts or parts[0].lower() not in ("/commande", "/command"):
        return None
    if len(parts) < 2:
        raise ValueError('Syntaxe : /commande "programme" [arguments]')
    return parts[1:]


def _truncate(value: str) -> str:
    if len(value) <= MAX_OUTPUT_CHARS:
        return value
    return value[:MAX_OUTPUT_CHARS] + "\n...[sortie tronquée]"


def execute_argv(argv: list[str], timeout: int = DEFAULT_TIMEOUT, cwd: Optional[str] = None) -> dict:
    if not argv or not argv[0].strip():
        raise ValueError("Commande vide.")
    working_dir = os.path.expanduser("~")
    if cwd:
        # Le dossier de travail doit être dans les dossiers autorisés.
        resolved = file_commands._resolve(cwd)
        if not resolved.is_dir():
            raise NotADirectoryError(f"Dossier de travail introuvable : {resolved}")
        working_dir = str(resolved)
    executable = argv[0]
    if os.path.dirname(executable):
        executable_path = executable
        if not os.path.isabs(executable_path):
            executable_path = os.path.join(working_dir, executable_path)
        if not os.path.isfile(executable_path):
            raise FileNotFoundError(f"Commande introuvable : {executable}")
    elif shutil.which(executable) is None:
        raise FileNotFoundError(f"Commande introuvable : {executable}")
    timeout = max(1, min(int(timeout), MAX_TIMEOUT))
    try:
        completed = subprocess.run(
            argv,
            cwd=working_dir,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise TimeoutError(f"Exécution interrompue après {timeout} secondes.") from exc
    return {
        "command": argv,
        "returncode": completed.returncode,
        "stdout": _truncate(completed.stdout or ""),
        "stderr": _truncate(completed.stderr or ""),
    }


def execute_command(message: str, timeout: int = DEFAULT_TIMEOUT) -> Optional[dict]:
    argv = parse_command(message)
    if argv is None:
        return None
    return execute_argv(argv, timeout=timeout)