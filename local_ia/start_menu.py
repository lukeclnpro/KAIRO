"""Create a per-user Windows Start Menu shortcut for KAIRO."""

from __future__ import annotations

import base64
import os
import shutil
import subprocess
import sys
from pathlib import Path


def _is_windows() -> bool:
    return os.name == "nt"


def create_start_menu_shortcut(project_dir: str | Path | None = None) -> Path | None:
    """Create the KAIRO GUI shortcut once; do nothing on non-Windows systems."""
    if not _is_windows():
        return None

    powershell = shutil.which("powershell.exe") or shutil.which("powershell")
    if not powershell:
        return None

    application_dir = Path(project_dir or Path(__file__).resolve().parents[1]).resolve()
    app_data = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    shortcut_path = app_data / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "KAIRO.lnk"
    if shortcut_path.exists():
        return shortcut_path

    try:
        shortcut_path.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        return None

    python = Path(sys.executable).resolve()
    if python.name.casefold() == "python.exe":
        windowless_python = python.with_name("pythonw.exe")
        if windowless_python.is_file():
            python = windowless_python

    environment = os.environ.copy()
    environment.update({
        "KAIRO_START_MENU_LINK": str(shortcut_path),
        "KAIRO_SHORTCUT_TARGET": str(python),
        "KAIRO_SHORTCUT_ARGUMENTS": f'"{application_dir / "main.py"}" gui',
        "KAIRO_SHORTCUT_WORKDIR": str(application_dir),
    })
    script = "\n".join((
        "$shell = New-Object -ComObject WScript.Shell",
        "$shortcut = $shell.CreateShortcut($env:KAIRO_START_MENU_LINK)",
        "$shortcut.TargetPath = $env:KAIRO_SHORTCUT_TARGET",
        "$shortcut.Arguments = $env:KAIRO_SHORTCUT_ARGUMENTS",
        "$shortcut.WorkingDirectory = $env:KAIRO_SHORTCUT_WORKDIR",
        "$shortcut.Description = 'KAIRO - Assistant local'",
        "$shortcut.Save()",
    ))
    encoded_script = base64.b64encode(script.encode("utf-16le")).decode("ascii")

    try:
        subprocess.run(
            [powershell, "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded_script],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=environment,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return shortcut_path