#!/usr/bin/env python3
"""Execution of local programs requested through the chat."""

from __future__ import annotations

import os
import shlex
import subprocess
import sys
from typing import Optional

import file_commands

MAX_OUTPUT_CHARS = 64 * 1024
DEFAULT_TIMEOUT = 30


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