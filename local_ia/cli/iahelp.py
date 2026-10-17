"""Commande terminal iahelp avec historique de conversations local."""

from __future__ import annotations

import getpass
import json
import os
import platform
import re
import shutil
import sys
import tempfile
from pathlib import Path

from local_ia.config.manager import load_config, model_config, openrouter_base_url, openrouter_model
from local_ia.core import accounts
from local_ia.core.agent import LocalAgent

_COMMAND_CANDIDATES = (
    "apt", "apt-get", "pacman", "dnf", "yum", "zypper", "apk", "brew", "winget", "choco", "scoop",
    "bash", "zsh", "fish", "pwsh", "powershell", "python", "python3", "py", "pip", "pip3",
    "node", "npm", "npx", "git", "curl", "wget", "ssh", "scp", "rsync", "tar", "zip", "unzip", "7z",
    "jq", "yq", "rg", "grep", "find", "sed", "awk", "systemctl", "journalctl", "ps", "top", "htop",
    "free", "df", "du", "ls", "cat", "cp", "mv", "rm", "mkdir", "chmod", "flatpak", "snap", "docker",
    "podman", "kubectl", "ollama", "ffmpeg", "yt-dlp", "code", "firefox", "chromium", "google-chrome",
    "vlc", "gsettings", "xrandr", "pactl", "wpctl", "winget.exe",
)
_IAHELP_COMMAND_GUIDANCE = """Pour une demande qui appelle une action dans le terminal, donne d'abord une commande complète, directement copiable, dans un bloc de code adapté au shell. N'utilise pas de placeholder ni de balise <tool_call> : iahelp conseille mais n'exécute aucune commande. Choisis la syntaxe selon le système et le shell détectés, et n'affirme pas qu'un exécutable est disponible s'il n'est pas dans l'inventaire. Si l'outil nécessaire n'est pas confirmé, fournis une commande courte pour le vérifier (command -v sous Linux/macOS, Get-Command sous PowerShell), puis précise brièvement quoi faire selon le résultat. Pour une commande destructive ou privilégiée, annonce son effet et sa nécessité avant le bloc de commande."""
_KEYRING_SERVICE = "local_ia.iahelp"
_KEYRING_ACTIVE_ACCOUNT = "active-account"


def history_path() -> Path:
    return accounts.accounts_path().with_name("iahelp-history.json")


def _get_keyring():
    try:
        import keyring
    except ImportError:
        return None
    return keyring


def _load_saved_credentials() -> tuple[str | None, str | None]:
    keyring = _get_keyring()
    if keyring is None:
        return None, None
    try:
        username = keyring.get_password(_KEYRING_SERVICE, _KEYRING_ACTIVE_ACCOUNT)
        api_key = keyring.get_password(_KEYRING_SERVICE, f"account:{username}") if username else None
    except Exception:
        return None, None
    return username, api_key


def _save_credentials(username: str, api_key: str) -> bool:
    keyring = _get_keyring()
    if keyring is None:
        return False
    try:
        keyring.set_password(_KEYRING_SERVICE, f"account:{username}", api_key)
        keyring.set_password(_KEYRING_SERVICE, _KEYRING_ACTIVE_ACCOUNT, username)
    except Exception:
        return False
    return True


def _set_openrouter_environment(api_key: str, config) -> str:
    model = openrouter_model(config)
    os.environ["LOCAL_IA_PROVIDER"] = "openrouter"
    os.environ["LOCAL_IA_OPENROUTER_KEY"] = api_key
    os.environ["LOCAL_IA_OPENROUTER_MODEL"] = model
    os.environ["LOCAL_IA_OPENROUTER_BASE_URL"] = openrouter_base_url(config)
    return model


def _memory_gib() -> float | None:
    if os.name == "nt":
        try:
            import ctypes

            class MemoryStatus(ctypes.Structure):
                _fields_ = [
                    ("length", ctypes.c_ulong),
                    ("memory_load", ctypes.c_ulong),
                    ("total_physical", ctypes.c_ulonglong),
                    ("available_physical", ctypes.c_ulonglong),
                    ("total_page_file", ctypes.c_ulonglong),
                    ("available_page_file", ctypes.c_ulonglong),
                    ("total_virtual", ctypes.c_ulonglong),
                    ("available_virtual", ctypes.c_ulonglong),
                    ("available_extended_virtual", ctypes.c_ulonglong),
                ]

            status = MemoryStatus()
            status.length = ctypes.sizeof(status)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                return round(status.total_physical / (1024 ** 3), 1)
        except (AttributeError, OSError):
            return None
        return None

    try:
        total_bytes = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
    except (AttributeError, OSError, ValueError):
        return None
    return round(total_bytes / (1024 ** 3), 1)


def _cpu_name() -> str:
    processor = platform.processor().strip()
    if processor:
        return processor
    try:
        with Path("/proc/cpuinfo").open(encoding="utf-8", errors="replace") as cpu_info:
            for line in cpu_info:
                key, separator, value = line.partition(":")
                if separator and key.strip().lower() in {"model name", "hardware"}:
                    return value.strip()
    except OSError:
        pass
    return "non détecté"


def _pc_context(request: str) -> str:
    os_name = platform.system() or "inconnu"
    if os_name == "Linux" and hasattr(platform, "freedesktop_os_release"):
        try:
            os_name = platform.freedesktop_os_release().get("PRETTY_NAME") or os_name
        except OSError:
            pass

    shell_path = os.environ.get("SHELL") or os.environ.get("COMSPEC", "")
    shell = Path(shell_path).name if shell_path else ("PowerShell/cmd" if os.name == "nt" else "inconnu")
    memory_gib = _memory_gib()
    commands = {
        name for name in _COMMAND_CANDIDATES
        if shutil.which(name)
    }
    request_tokens = set(re.findall(r"(?<![\w.-])[\w][\w.+-]{1,63}(?![\w.-])", request))
    commands.update(name for name in request_tokens if shutil.which(name))

    lines = [
        "Fiche technique locale (valeurs détectées à l'exécution) :",
        f"- Système : {os_name} ({platform.release() or 'version inconnue'})",
        f"- Architecture : {platform.machine() or 'inconnue'}",
        f"- Processeur : {_cpu_name()}",
        f"- Cœurs logiques : {os.cpu_count() or 'inconnu'}",
        f"- Mémoire vive : {f'{memory_gib} Gio' if memory_gib is not None else 'non détectée'}",
        f"- Shell : {shell}",
        "- Exécutables courants et outils cités dans la demande, confirmés dans PATH : "
        + (", ".join(sorted(commands)) if commands else "aucun détecté"),
    ]
    return "\n".join(lines)


def _load_history(path: Path) -> list[dict[str, str]]:
    try:
        entries = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"Historique iahelp illisible : {error}") from error
    if not isinstance(entries, list):
        raise ValueError("Le fichier d'historique iahelp est invalide.")
    return [
        {"request": str(entry["request"]), "response": str(entry["response"])}
        for entry in entries
        if isinstance(entry, dict) and "request" in entry and "response" in entry
    ]


def _save_history(entries: list[dict[str, str]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, temporary_name = tempfile.mkstemp(prefix=".iahelp-", dir=path.parent)
    try:
        os.chmod(temporary_name, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            json.dump(entries, output, ensure_ascii=False, indent=2)
            output.write("\n")
        os.replace(temporary_name, path)
        os.chmod(path, 0o600)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)


def _history_context(entries: list[dict[str, str]]) -> str:
    if not entries:
        return "Aucune demande iahelp précédente."
    sections = ["Historique complet des commandes iahelp précédentes :"]
    for index, entry in enumerate(entries, start=1):
        sections.extend([
            f"Commande iahelp {index} : {entry['request']}",
            f"Réponse précédente : {entry['response']}",
        ])
    return "\n".join(sections)


def _select_provider(config, input_fn, password_reader) -> tuple[str, str]:
    env_key = os.environ.get("LOCAL_IA_OPENROUTER_KEY") or os.environ.get("OPENROUTER_API_KEY")
    if env_key:
        return env_key.strip(), openrouter_model(config)

    names = accounts.list_accounts()
    if names:
        saved_username, saved_key = _load_saved_credentials()
        saved_account = next(
            (name for name in names if saved_username and name.casefold() == saved_username.casefold()),
            None,
        )
        if saved_account and saved_key:
            return saved_key, _set_openrouter_environment(saved_key, config)

        print("Comptes API locaux : " + ", ".join(names))
        username = names[0] if len(names) == 1 else input_fn("Compte API à utiliser (Entrée pour Ollama) : ").strip()
        if username:
            password = password_reader("Mot de passe du compte : ")
            key = accounts.authenticate(username, password)
            if not _save_credentials(username, key):
                print(
                    "Connexion réussie, mais le coffre-fort sécurisé est indisponible; "
                    "le mot de passe sera redemandé au prochain lancement.",
                    file=sys.stderr,
                )
            return key, _set_openrouter_environment(key, config)

    os.environ.pop("LOCAL_IA_PROVIDER", None)
    return "", model_config(config)


def run_request(
    request: str,
    *,
    path: Path | None = None,
    input_fn=input,
    password_reader=getpass.getpass,
    agent_factory=None,
) -> str:
    message = str(request or "").strip()
    if not message:
        raise ValueError('Indique une demande : iahelp "message de la demande"')

    config = load_config()
    _, model = _select_provider(config, input_fn, password_reader)
    target = path or history_path()
    entries = _load_history(target)
    agent_type = agent_factory or LocalAgent
    agent = agent_type(model=model)
    chat = {"id": "iahelp", "topic": "Aide terminal", "messages": []}
    try:
        answer = agent.respond(
            chat,
            message,
            external_info="\n\n".join((_history_context(entries), _pc_context(message), _IAHELP_COMMAND_GUIDANCE)),
            allowed_tools=set(),
            stream=False,
        )
    finally:
        agent.close()

    response = str(answer or "").strip()
    entries.append({"request": message, "response": response})
    _save_history(entries, target)
    return response


def main(argv: list[str] | None = None) -> int:
    import sys

    arguments = list(sys.argv[1:] if argv is None else argv)
    if not arguments or arguments in (["-h"], ["--help"]):
        print('Usage : iahelp "message de la demande"')
        print("Les échanges iahelp précédents sont conservés comme contexte local.")
        return 0 if arguments else 2

    request = " ".join(arguments).strip()
    try:
        answer = run_request(request)
    except (OSError, ValueError) as error:
        print(f"Erreur iahelp : {error}", file=sys.stderr)
        return 1
    except Exception as error:
        print(f"Erreur lors de la requête IA : {error}", file=sys.stderr)
        return 1

    print(answer)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
