#!/usr/bin/env python3
"""
setup.py - local_ia multiplateforme

Systèmes pris en charge :
    - Windows 10 / 11
    - Linux :
        - Arch Linux / CachyOS / Manjaro / EndeavourOS
        - Debian / Ubuntu / Linux Mint / Pop!_OS
        - Fedora / RHEL / Rocky / AlmaLinux
        - openSUSE
        - autres distributions Linux
    - macOS

Le script :
    - détecte automatiquement le système
    - vérifie Python
    - propose Ollama en option s'il n'est pas installé
    - démarre Ollama si disponible
    - crée un environnement virtuel Python
    - installe requirements.txt
    - lance main.py

IMPORTANT :
    Le script n'installe aucun modèle Ollama.

Usage :
    python setup.py

Optionnel :
    python setup.py --no-launch
"""

from __future__ import annotations

import argparse
import os
import platform
import shutil
import shlex
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path
from local_ia.http_client import open_url


MIN_PYTHON = (3, 10)

OLLAMA_HOST = "127.0.0.1"
OLLAMA_PORT = 11434
OLLAMA_LINUX_INSTALL_URL = "https://ollama.com/install.sh"
OLLAMA_DOWNLOAD_URLS = {
    "windows": "https://ollama.com/download/windows",
    "macos": "https://ollama.com/download",
}


# ============================================================
# OUTILS GÉNÉRAUX
# ============================================================

def run(command, *, cwd=None, check=True, capture_output=False):
    """Exécute une commande."""
    display = (
        command
        if isinstance(command, str)
        else " ".join(map(str, command))
    )

    print(f"\n>>> {display}")

    return subprocess.run(
        command,
        cwd=cwd,
        check=check,
        capture_output=capture_output,
        text=True,
    )


def command_exists(command):
    """Retourne True si une commande existe."""
    return shutil.which(command) is not None


def find_project_dir():
    """Retourne le dossier contenant setup.py."""
    project_dir = Path(__file__).resolve().parent
    main_py = project_dir / "main.py"

    if not main_py.is_file():
        raise RuntimeError(
            f"main.py est introuvable dans :\n{project_dir}\n\n"
            "Place setup.py à la racine du projet."
        )

    return project_dir


# ============================================================
# SYSTÈME
# ============================================================

def get_system():
    """Détecte le système d'exploitation."""
    system = platform.system()

    if system == "Windows":
        return "windows"

    if system == "Linux":
        return "linux"

    if system == "Darwin":
        return "macos"

    return "unknown"


def detect_linux_distribution():
    """Détecte la distribution Linux."""
    if not Path("/etc/os-release").is_file():
        return {
            "id": "unknown",
            "name": "Linux",
            "id_like": "",
            "version": "",
        }

    data = {}

    try:
        for line in Path("/etc/os-release").read_text(
            encoding="utf-8",
            errors="replace",
        ).splitlines():

            if "=" not in line:
                continue

            key, value = line.split("=", 1)
            data[key] = value.strip().strip('"')

    except OSError:
        return {
            "id": "unknown",
            "name": "Linux",
            "id_like": "",
            "version": "",
        }

    return {
        "id": data.get("ID", "unknown"),
        "name": data.get("PRETTY_NAME", "Linux"),
        "id_like": data.get("ID_LIKE", ""),
        "version": data.get("VERSION_ID", ""),
    }


def print_system_info():
    """Affiche les informations du système."""
    system = get_system()

    print("\n=== Système détecté ===")
    print(f"Système : {platform.system()}")
    print(f"Version : {platform.release()}")
    print(f"Architecture : {platform.machine()}")

    if system == "linux":
        distro = detect_linux_distribution()

        print(f"Distribution : {distro['name']}")
        print(f"ID : {distro['id']}")

        if distro["version"]:
            print(f"Version : {distro['version']}")

    elif system == "windows":
        print(f"Windows : {platform.version()}")

    elif system == "macos":
        print(f"macOS : {platform.mac_ver()[0]}")


# ============================================================
# PYTHON
# ============================================================

def check_python():
    """Vérifie la version de Python."""
    version = sys.version_info

    print(
        f"\nPython détecté : "
        f"{version.major}.{version.minor}.{version.micro}"
    )

    if version < MIN_PYTHON:
        raise RuntimeError(
            f"Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]} "
            "ou plus récent est requis.\n"
            f"Version détectée : "
            f"{version.major}.{version.minor}.{version.micro}"
        )


# ============================================================
# OUTILS SYSTÈME
# ============================================================

def check_basic_tools():
    """Vérifie les outils indispensables."""
    system = get_system()

    if system == "windows":
        python_ok = (
            command_exists("python")
            or command_exists("py")
        )
    else:
        python_ok = (
            command_exists("python3")
            or command_exists("python")
        )

    if not python_ok:
        raise RuntimeError(
            "Python est introuvable.\n\n"
            "Installe Python 3.10 ou plus récent puis "
            "relance setup.py."
        )

    print("Outils système : OK")


# ============================================================
# OLLAMA
# ============================================================

def find_ollama():
    """Cherche Ollama dans le PATH et les emplacements classiques."""
    path = shutil.which("ollama")

    if path:
        return path

    system = get_system()
    possible_paths = []

    if system == "windows":
        local_app_data = os.environ.get("LOCALAPPDATA")

        if local_app_data:
            possible_paths.extend([
                Path(local_app_data)
                / "Programs"
                / "Ollama"
                / "ollama.exe",

                Path(local_app_data)
                / "Ollama"
                / "ollama.exe",
            ])

        possible_paths.extend([
            Path("C:/Program Files/Ollama/ollama.exe"),
            Path("C:/Program Files (x86)/Ollama/ollama.exe"),
        ])

    elif system == "macos":
        possible_paths.extend([
            Path("/usr/local/bin/ollama"),
            Path("/opt/homebrew/bin/ollama"),
            Path(
                "/Applications/Ollama.app/"
                "Contents/Resources/ollama"
            ),
        ])

    elif system == "linux":
        possible_paths.extend([
            Path("/usr/local/bin/ollama"),
            Path("/usr/bin/ollama"),
            Path.home() / ".local" / "bin" / "ollama",
        ])

    for candidate in possible_paths:
        if candidate.is_file():
            return str(candidate)

    return None


def check_ollama():
    """Retourne le chemin Ollama s'il est installé, sinon None."""
    ollama = find_ollama()

    if ollama:
        print(f"\nOllama détecté : {ollama}")
        return ollama

    print("\nOllama n'est pas installé. Local IA peut aussi fonctionner sans Ollama.")
    return None


def install_ollama():
    """Install Ollama after explicit user consent, or open its official installer."""
    system = get_system()
    if system == "linux":
        if not command_exists("curl"):
            print("curl est absent; installation automatique d'Ollama impossible.")
            return None
        result = subprocess.run(
            ["sh", "-c", f"curl -fsSL {OLLAMA_LINUX_INSTALL_URL} | sh"],
            check=False,
        )
        if result.returncode != 0:
            print("L'installation d'Ollama a échoué; Local IA continuera sans lui.")
            return find_ollama()
        return find_ollama()

    download_url = OLLAMA_DOWNLOAD_URLS.get(system)
    if download_url is None:
        print("Installation automatique d'Ollama indisponible sur ce système.")
        return None

    print(f"\nInstalle Ollama depuis : {download_url}")
    try:
        webbrowser.open(download_url)
    except webbrowser.Error:
        pass
    try:
        input("Après l'installation, appuie sur Entrée pour continuer sans Ollama : ")
    except EOFError:
        pass
    return find_ollama()


def offer_ollama_install():
    """Ask whether to install Ollama only when it is not already installed."""
    ollama = check_ollama()
    if ollama:
        return ollama

    choice = input("Installer Ollama maintenant ? [o/N] : ").strip().casefold()
    if choice not in {"o", "oui", "y", "yes"}:
        print("Installation d'Ollama ignorée. Local IA sera installé sans Ollama.")
        return None

    try:
        ollama = install_ollama()
    except (OSError, subprocess.SubprocessError) as error:
        print(f"Installation d'Ollama impossible : {error}")
        return None

    if not ollama:
        print("Ollama reste indisponible. L'installation de Local IA continue sans lui.")
    return ollama


# ============================================================
# SERVEUR OLLAMA
# ============================================================

def ollama_api_available():
    """Vérifie si le serveur Ollama répond."""
    url = (
        f"http://{OLLAMA_HOST}:"
        f"{OLLAMA_PORT}/api/tags"
    )

    try:
        with open_url(
            url,
            timeout=2,
        ) as response:
            return response.status == 200

    except (
        urllib.error.URLError,
        TimeoutError,
        ConnectionError,
        OSError,
    ):
        return False


def wait_for_ollama(timeout=30):
    """Attend le démarrage du serveur Ollama."""
    print("Attente du démarrage d'Ollama...")

    start = time.monotonic()

    while time.monotonic() - start < timeout:
        if ollama_api_available():
            return True

        time.sleep(1)

    return False


def start_ollama_linux(ollama):
    """Démarre Ollama sous Linux."""
    if ollama_api_available():
        print("Serveur Ollama : actif.")
        return

    print("\n=== Démarrage d'Ollama ===")

    if command_exists("systemctl"):
        status = subprocess.run(
            [
                "systemctl",
                "is-active",
                "--quiet",
                "ollama",
            ],
            check=False,
        )

        if status.returncode == 0:
            print("Service Ollama : actif.")
            return

        result = subprocess.run(
            [
                "systemctl",
                "start",
                "ollama",
            ],
            check=False,
        )

        if result.returncode != 0 and command_exists("sudo"):
            print(
                "Tentative de démarrage avec sudo..."
            )

            result = subprocess.run(
                [
                    "sudo",
                    "systemctl",
                    "start",
                    "ollama",
                ],
                check=False,
            )

        if result.returncode == 0:
            if wait_for_ollama():
                print("Serveur Ollama : actif.")
                return

    print(
        "Tentative de lancement direct "
        "de `ollama serve`..."
    )

    try:
        subprocess.Popen(
            [ollama, "serve"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError as exc:
        raise RuntimeError(
            f"Impossible de démarrer Ollama : {exc}"
        ) from exc

    if wait_for_ollama():
        print("Serveur Ollama : actif.")
        return

    raise RuntimeError(
        "Ollama est installé mais son serveur "
        "ne répond pas."
    )


def start_ollama_macos(ollama):
    """Démarre Ollama sous macOS."""
    if ollama_api_available():
        print("Serveur Ollama : actif.")
        return

    print("\n=== Démarrage d'Ollama ===")

    try:
        subprocess.Popen(
            [ollama, "serve"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError as exc:
        raise RuntimeError(
            f"Impossible de démarrer Ollama : {exc}"
        ) from exc

    if wait_for_ollama():
        print("Serveur Ollama : actif.")
        return

    raise RuntimeError(
        "Ollama est installé mais son serveur "
        "ne répond pas."
    )


def start_ollama_windows(ollama):
    """Démarre Ollama sous Windows."""
    if ollama_api_available():
        print("Serveur Ollama : actif.")
        return

    print("\n=== Démarrage d'Ollama ===")

    try:
        subprocess.Popen(
            [ollama, "serve"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(
                subprocess,
                "CREATE_NO_WINDOW",
                0,
            ),
        )
    except OSError as exc:
        raise RuntimeError(
            f"Impossible de démarrer Ollama : {exc}"
        ) from exc

    if wait_for_ollama():
        print("Serveur Ollama : actif.")
        return

    raise RuntimeError(
        "Ollama est installé mais son serveur "
        "ne répond pas.\n\n"
        "Ouvre l'application Ollama depuis le "
        "menu Démarrer puis relance setup.py."
    )


def ensure_ollama_service(ollama):
    """S'assure qu'Ollama répond."""
    if ollama_api_available():
        print("Serveur Ollama : actif.")
        return

    system = get_system()

    if system == "linux":
        start_ollama_linux(ollama)

    elif system == "macos":
        start_ollama_macos(ollama)

    elif system == "windows":
        start_ollama_windows(ollama)

    else:
        raise RuntimeError(
            "Système d'exploitation non pris en charge."
        )


# ============================================================
# TEST OLLAMA
# ============================================================

def test_ollama(project_dir, python_cmd):
    """Lance ollama_test.py s'il existe."""
    test_file = project_dir / "ollama_test.py"

    if not test_file.is_file():
        print(
            "\nollama_test.py absent : "
            "test Ollama ignoré."
        )
        return

    print("\n=== Test Ollama du projet ===")

    run(
        [
            str(python_cmd),
            str(test_file),
        ],
        cwd=project_dir,
    )


# ============================================================
# ENVIRONNEMENT VIRTUEL
# ============================================================

def get_venv_python(project_dir):
    """Retourne le Python du venv."""
    venv_dir = project_dir / ".venv"

    if get_system() == "windows":
        return venv_dir / "Scripts" / "python.exe"

    return venv_dir / "bin" / "python"


def create_venv(project_dir):
    """Crée l'environnement virtuel."""
    venv_dir = project_dir / ".venv"
    venv_python = get_venv_python(project_dir)

    if venv_python.is_file():
        print(
            f"\nEnvironnement virtuel déjà présent : "
            f"{venv_dir}"
        )
        return venv_python

    print(
        "\n=== Création de l'environnement virtuel ==="
    )

    run([
        sys.executable,
        "-m",
        "venv",
        str(venv_dir),
    ])

    if not venv_python.is_file():
        raise RuntimeError(
            "Le Python du venv n'a pas été créé :\n"
            f"{venv_python}"
        )

    return venv_python


# ============================================================
# DÉPENDANCES
# ============================================================

def install_python_dependencies(
    project_dir,
    venv_python,
):
    """Installe requirements.txt."""
    requirements = project_dir / "requirements.txt"

    print("\n=== Dépendances Python ===")

    run([
        str(venv_python),
        "-m",
        "pip",
        "install",
        "--upgrade",
        "pip",
    ])

    if not requirements.is_file():
        print(
            "requirements.txt absent : "
            "aucune dépendance supplémentaire."
        )
        return

    print(f"Installation depuis : {requirements}")

    run([
        str(venv_python),
        "-m",
        "pip",
        "install",
        "-r",
        str(requirements),
    ])


# ============================================================
# LANCEMENT
# ============================================================

def launch_project(project_dir, venv_python):
    """Lance main.py."""
    main_py = project_dir / "main.py"

    print("\n=== Lancement de local_ia ===")

    run(
        [
            str(venv_python),
            str(main_py),
        ],
        cwd=project_dir,
    )


def _append_managed_block(path, marker, content):
    try:
        current = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        current = ""
    if marker in current:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as file:
        if current and not current.endswith("\n"):
            file.write("\n")
        file.write(f"\n{marker}\n{content}\n")


def _register_unix_command_path(command_dir):
    marker = "# local_ia iahelp PATH"
    export_block = (
        'case ":$PATH:" in *":$HOME/.local/bin:"*) ;; '
        '*) export PATH="$HOME/.local/bin:$PATH" ;; esac'
    )
    for filename in (".profile", ".bashrc", ".zshrc"):
        _append_managed_block(Path.home() / filename, marker, export_block)

    fish_path = Path.home() / ".config" / "fish" / "conf.d" / "local_ia_iahelp.fish"
    _append_managed_block(
        fish_path,
        marker,
        'fish_add_path --path "$HOME/.local/bin"',
    )


def _register_windows_command_path(command_dir):
    import winreg

    key_path = r"Environment"
    with winreg.OpenKey(
        winreg.HKEY_CURRENT_USER,
        key_path,
        0,
        winreg.KEY_QUERY_VALUE | winreg.KEY_SET_VALUE,
    ) as key:
        try:
            current, value_type = winreg.QueryValueEx(key, "Path")
        except FileNotFoundError:
            current, value_type = "", winreg.REG_EXPAND_SZ
        entries = [part for part in current.split(os.pathsep) if part]

        def normalize(value):
            return os.path.normcase(os.path.normpath(os.path.expandvars(value)))

        if normalize(str(command_dir)) not in {normalize(part) for part in entries}:
            entries.append(str(command_dir))
            winreg.SetValueEx(key, "Path", 0, value_type, os.pathsep.join(entries))


def install_iahelp_command(project_dir, venv_python):
    """Installe la commande iahelp dans le PATH utilisateur."""
    system = get_system()
    main_py = (Path(project_dir) / "main.py").resolve()
    python_path = Path(venv_python).resolve()

    if system == "windows":
        command_dir = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "LocalIA" / "bin"
        command_dir.mkdir(parents=True, exist_ok=True)
        launcher = command_dir / "iahelp.cmd"
        launcher.write_text(
            f'@echo off\n"{python_path}" "{main_py}" iahelp %*\n',
            encoding="utf-8",
        )
        _register_windows_command_path(command_dir)
    elif system in {"linux", "macos"}:
        command_dir = Path.home() / ".local" / "bin"
        command_dir.mkdir(parents=True, exist_ok=True)
        launcher = command_dir / "iahelp"
        launcher.write_text(
            "#!/bin/sh\n"
            f"exec {shlex.quote(str(python_path))} {shlex.quote(str(main_py))} iahelp \"$@\"\n",
            encoding="utf-8",
        )
        launcher.chmod(0o755)
        _register_unix_command_path(command_dir)
    else:
        raise RuntimeError(f"Système non pris en charge pour iahelp : {system}")

    print(f"Commande iahelp installée : {launcher}")
    print("Ouvre un nouveau terminal si la commande n'est pas encore reconnue.")
    return launcher


# ============================================================
# ARGUMENTS
# ============================================================

def parse_arguments():
    parser = argparse.ArgumentParser(
        description=(
            "Installation multiplateforme "
            "de local_ia."
        )
    )

    parser.add_argument(
        "--no-launch",
        action="store_true",
        help=(
            "Installe tout sans lancer main.py."
        ),
    )

    return parser.parse_args()


# ============================================================
# MAIN
# ============================================================

def main():
    args = parse_arguments()

    system = get_system()

    if system == "unknown":
        raise RuntimeError(
            f"Système non pris en charge : "
            f"{platform.system()}"
        )

    print("========================================")
    print("       KAIRO - Installation")
    print("       Multiplateforme")
    print("========================================")

    project_dir = find_project_dir()

    print(f"\nDossier du projet : {project_dir}")

    print_system_info()

    # Python
    check_python()
    check_basic_tools()

    # Ollama est facultatif : la proposition n'apparaît que s'il est absent.
    print("\n=== Vérification Ollama (facultatif) ===")
    ollama = offer_ollama_install()
    ollama_ready = False
    if ollama:
        try:
            ensure_ollama_service(ollama)
            ollama_ready = ollama_api_available()
        except (OSError, RuntimeError, subprocess.SubprocessError) as error:
            print(f"Ollama indisponible : {error}")
            print("Local IA continuera sans Ollama.")
    else:
        print("Ollama ignoré; vous pourrez l'installer plus tard depuis https://ollama.com/download.")

    # Environnement Python
    venv_python = create_venv(project_dir)

    install_python_dependencies(
        project_dir,
        venv_python,
    )

    install_iahelp_command(project_dir, venv_python)

    # Ne pas bloquer l'installation si Ollama n'est pas installé ou démarré.
    if ollama_ready:
        test_ollama(project_dir, venv_python)
    else:
        print("\nTest Ollama ignoré : aucun serveur Ollama disponible.")

    # Lancement
    if args.no_launch:
        print(
            "\n--no-launch utilisé : "
            "main.py ne sera pas lancé."
        )
    else:
        launch_project(
            project_dir,
            venv_python,
        )

    print("\n========================================")
    print("Installation terminée.")
    print("========================================")


# ============================================================
# ERREURS
# ============================================================

if __name__ == "__main__":
    try:
        main()

    except KeyboardInterrupt:
        print(
            "\nInstallation interrompue.",
            file=sys.stderr,
        )
        sys.exit(130)

    except subprocess.CalledProcessError as exc:
        print(
            "\nErreur : une commande a échoué "
            f"avec le code {exc.returncode}.",
            file=sys.stderr,
        )
        sys.exit(exc.returncode)

    except RuntimeError as exc:
        print(
            f"\nErreur : {exc}",
            file=sys.stderr,
        )
        sys.exit(1)

    except Exception as exc:
        print(
            "\nErreur inattendue : "
            f"{type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        sys.exit(1)
