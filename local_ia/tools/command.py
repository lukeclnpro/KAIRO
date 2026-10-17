"""Outil d'exécution d'une commande sans interpréteur shell."""

import os
import shlex

from command_commands import DEFAULT_TIMEOUT, execute_argv

# Toute commande qui n'est pas explicitement reconnue comme une simple lecture
# demande confirmation. Cette liste reste volontairement conservatrice.
RISKY_PROGRAMS = {
    "rm", "rmdir", "shred", "truncate", "del", "erase", "rd", "format",
    "sudo", "su", "doas", "dd", "fdisk", "parted", "mkswap",
    "shutdown", "reboot", "poweroff", "halt",
    "kill", "killall", "pkill", "taskkill",
    "chmod", "chown",
}
READ_ONLY_PROGRAMS = {
    "cat", "date", "df", "dir", "du", "echo", "file", "free", "grep",
    "head", "id", "ls", "more", "nproc", "pgrep", "ps", "pwd", "rg",
    "stat", "tail", "uname", "uptime", "users", "wc", "which", "who",
    "whoami", "where", "whereis",
}
SHELLS = {"sh", "bash", "zsh", "fish", "dash", "ksh", "csh", "tcsh", "cmd", "powershell", "pwsh"}
WRAPPERS = {"env", "nohup", "nice", "time", "command", "exec", "xargs", "timeout"}


def _program(item):
    name = os.path.basename(str(item).replace("\\", "/")).lower()
    return name[:-4] if name.endswith(".exe") else name


def is_risky(argv):
    """Vrai par défaut; seuls quelques outils de lecture simple sont dispensés."""
    items = list(argv)
    if not items:
        return True

    program = _program(items[0])
    if (
        program in RISKY_PROGRAMS
        or program in SHELLS
        or program in WRAPPERS
        or program.startswith("mkfs")
    ):
        return True

    if program not in READ_ONLY_PROGRAMS:
        return True

    # find permet d'exécuter une commande avec -exec/-execdir et d'effacer
    # des fichiers avec -delete; il n'est donc pas inclus dans l'allowlist.
    if program == "find":
        return True
    return False


def use(argv, timeout=DEFAULT_TIMEOUT, cwd=None, confirmed=False):
    if isinstance(argv, str):  # les petits modèles écrivent souvent "python app.py"
        argv = shlex.split(argv, posix=os.name != "nt")
    if not isinstance(argv, list) or not all(isinstance(item, str) for item in argv):
        raise ValueError("argv doit être une liste de chaînes de caractères.")
    if is_risky(argv) and not confirmed:
        return {
            "confirmation_required": True,
            "action": "command",
            "command": argv,
            "message": f"Confirmation nécessaire avant : {' '.join(argv)}",
        }
    return execute_argv(argv, timeout=timeout, cwd=cwd)
