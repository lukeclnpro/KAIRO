"""Actions système courantes et contrôlées."""

from __future__ import annotations

import shutil
import subprocess
import platform


def _run(argv):
    if not shutil.which(argv[0]):
        raise FileNotFoundError(f"Commande système introuvable : {argv[0]}")
    result = subprocess.run(
        argv,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    return {
        "command": argv,
        "returncode": result.returncode,
        "stdout": result.stdout.strip(),
        "stderr": result.stderr.strip(),
    }


def volume(action, amount=5):
    """Modifie le volume avec l'outil audio disponible."""
    action = str(action or "").lower().strip()
    amount = max(1, min(int(amount), 100))
    if shutil.which("wpctl"):
        target = "@DEFAULT_AUDIO_SINK@"
        commands = {
            "up": ["wpctl", "set-volume", target, f"{amount}%+"],
            "down": ["wpctl", "set-volume", target, f"{amount}%-"],
            "mute": ["wpctl", "set-mute", target, "1"],
            "unmute": ["wpctl", "set-mute", target, "0"],
        }
    elif shutil.which("pactl"):
        commands = {
            "up": ["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"+{amount}%"],
            "down": ["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"-{amount}%"],
            "mute": ["pactl", "set-sink-mute", "@DEFAULT_SINK@", "1"],
            "unmute": ["pactl", "set-sink-mute", "@DEFAULT_SINK@", "0"],
        }
    else:
        raise RuntimeError("Aucun outil audio compatible n'est disponible.")
    if action not in commands:
        raise ValueError("Action volume attendue : up, down, mute ou unmute.")
    return _run(commands[action])


def _confirmation(action, package=None):
    if shutil.which("pacman"):
        command = ["sudo", "pacman", "-S", "--needed", package] if action == "install" else ["sudo", "pacman", "-Syu"]
    elif shutil.which("apt-get"):
        command = ["sudo", "apt-get", "install", "-y", package] if action == "install" else ["sudo", "apt-get", "update"]
    elif shutil.which("dnf"):
        command = ["sudo", "dnf", "install", "-y", package] if action == "install" else ["sudo", "dnf", "upgrade", "-y"]
    else:
        raise RuntimeError("Aucun gestionnaire de paquets compatible n'est disponible.")
    return {
        "confirmation_required": True,
        "action": action,
        "package": package,
        "command": command,
        "message": f"Confirmation nécessaire avant : {' '.join(command)}",
    }


ACTION_ALIASES = {
    "increase": "up", "augmenter": "up", "monter": "up", "plus": "up",
    "decrease": "down", "diminuer": "down", "baisser": "down", "moins": "down",
    "silence": "mute", "muet": "mute",
}


def normalize_action(action):
    """Ramène « Augmenter », « baisser »… aux actions up/down/mute/unmute."""
    action = str(action or "").lower().strip()
    return ACTION_ALIASES.get(action, action)


def use(action, value=None, amount=5, confirmed=False):
    """Exécute une action sûre ou prépare une action privilégiée."""
    action = normalize_action(action)
    if action in {"info", "os_info", "system_info"}:
        return {
            "system": platform.system(),
            "release": platform.release(),
            "version": platform.version(),
            "machine": platform.machine(),
        }
    if action in {"up", "down", "mute", "unmute"}:
        return volume(action, amount)
    if action == "install":
        package = str(value or "").strip()
        if not package or any(char in package for char in "/;&|`$\n"):
            raise ValueError("Nom de paquet invalide.")
        pending = _confirmation(action, package)
        if not confirmed:
            return pending
        return _run(["sudo", "-n", *pending["command"][1:]])
    if action in {"update", "upgrade"}:
        pending = _confirmation("update")
        if not confirmed:
            return pending
        return _run(["sudo", "-n", *pending["command"][1:]])
    raise ValueError("Action système inconnue.")