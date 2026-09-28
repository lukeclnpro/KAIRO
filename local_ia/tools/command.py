"""Outil d'exécution d'une commande sans interpréteur shell."""

import os
import shlex

from command_commands import DEFAULT_TIMEOUT, execute_argv

# Programmes qui détruisent, arrêtent ou modifient le système : ils demandent
# une confirmation explicite de l'utilisateur avant de s'exécuter.
RISKY_PROGRAMS = {
    "rm", "rmdir", "shred", "truncate", "del", "erase", "rd", "format",
    "sudo", "su", "doas", "dd", "fdisk", "parted", "mkswap",
    "shutdown", "reboot", "poweroff", "halt",
    "kill", "killall", "pkill", "taskkill",
    "chmod", "chown",
}
SHELLS = {"sh", "bash", "zsh", "fish", "dash", "ksh", "csh", "tcsh", "cmd", "powershell", "pwsh"}
WRAPPERS = {"env", "nohup", "nice", "time", "command", "exec", "xargs"}


def _program(item):
    name = os.path.basename(str(item).replace("\\", "/")).lower()
    return name[:-4] if name.endswith(".exe") else name


def is_risky(argv):
    """Vrai si la commande doit être confirmée avant exécution."""
    items = list(argv)
    for index, item in enumerate(items[:-1]):
        if _program(item) == "env" and items[index + 1] in {"-S", "--split-string"}:
            try:
                items[index + 2:index + 3] = shlex.split(items[index + 2], posix=os.name != "nt")
            except (IndexError, ValueError):
                return True
            break
    for item in items:
        program = _program(item)
        if program in WRAPPERS or item.startswith("-") or "=" in item:
            continue
        if program in RISKY_PROGRAMS or program in SHELLS or program.startswith("mkfs"):
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
