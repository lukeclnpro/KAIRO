import os
import sys
import shutil
import subprocess
import time

import ui
from pathlib import Path


# ============================================================
# CONFIGURATION
# ============================================================

PROGRAM_DIR = Path(__file__).resolve().parent


# ============================================================
# OUTILS
# ============================================================

def run_command(command):
    try:
        result = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            shell=False
        )
        return result.returncode, result.stdout.strip(), result.stderr.strip()
    except Exception as e:
        return -1, "", str(e)


def ask_yes_no(question):
    while True:
        answer = input(f"{question} [o/n] : ").strip().lower()

        if answer in ("o", "oui", "y", "yes"):
            return True

        if answer in ("n", "non", "no"):
            return False

        print("Répondez par o ou n.")


# ============================================================
# OLLAMA
# ============================================================

def ollama_installed():
    executable = shutil.which("ollama")

    if executable:
        return executable

    # Windows
    if os.name == "nt":
        possible = [
            Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama.exe",
            Path(os.environ.get("PROGRAMFILES", "")) / "Ollama" / "ollama.exe",
        ]

        for path in possible:
            if path.exists():
                return str(path)

    # Linux / macOS
    possible = [
        Path("/usr/local/bin/ollama"),
        Path("/usr/bin/ollama"),
        Path("/opt/homebrew/bin/ollama"),
    ]

    for path in possible:
        if path.exists():
            return str(path)

    return None


def stop_ollama():
    print("\n[INFO] Arrêt d'Ollama...")

    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/F", "/IM", "ollama.exe"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
        else:
            subprocess.run(
                ["pkill", "-f", "ollama"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
    except Exception:
        pass

    time.sleep(2)


# ============================================================
# SUPPRESSION DES MODÈLES
# ============================================================

def get_ollama_models(ollama):
    code, stdout, stderr = run_command(
        [ollama, "list"]
    )

    if code != 0:
        print("[ERREUR] Impossible de récupérer la liste des modèles.")
        if stderr:
            print(stderr)
        return []

    models = []

    lines = stdout.splitlines()

    # Première ligne = en-tête
    for line in lines[1:]:
        line = line.strip()

        if not line:
            continue

        # Le nom est la première colonne
        name = line.split()[0]

        if name:
            models.append(name)

    return models


def remove_models():
    ollama = ollama_installed()

    if not ollama:
        print("\n[INFO] Ollama n'est pas installé.")
        return

    models = get_ollama_models(ollama)

    if not models:
        print("\n[INFO] Aucun modèle Ollama installé.")
        return

    print("\n============================================================")
    print("MODÈLES OLLAMA")
    print("============================================================")

    for i, model in enumerate(models, 1):
        print(f"{i}. {model}")

    print()
    print("Choisissez les modèles à supprimer.")
    print("  A = tous les modèles")
    print("  0 = annuler")
    print()

    choice = input("Votre choix : ").strip()

    if choice == "0":
        print("[INFO] Suppression annulée.")
        return

    if choice.lower() == "a":
        selected = models
    else:
        try:
            indexes = [
                int(x.strip())
                for x in choice.split(",")
            ]

            selected = [
                models[i - 1]
                for i in indexes
                if 1 <= i <= len(models)
            ]

        except ValueError:
            print("[ERREUR] Choix invalide.")
            return

    if not selected:
        print("[INFO] Aucun modèle sélectionné.")
        return

    print("\nModèles sélectionnés :")
    for model in selected:
        print(f"  - {model}")

    if not ask_yes_no("\nConfirmer la suppression"):
        print("[INFO] Suppression annulée.")
        return

    for model in selected:
        print(f"\n[SUPPRESSION] {model}")

        code, _, stderr = run_command(
            [ollama, "rm", model]
        )

        if code == 0:
            print(f"[OK] {model} supprimé.")
        else:
            print(f"[ERREUR] Impossible de supprimer {model}.")
            if stderr:
                print(stderr)


# ============================================================
# DÉSINSTALLATION OLLAMA
# ============================================================

def uninstall_ollama():
    ollama = ollama_installed()

    if not ollama:
        print("\n[INFO] Ollama n'est pas installé.")
        return

    print("\n============================================================")
    print("DÉSINSTALLATION D'OLLAMA")
    print("============================================================")

    print(f"Ollama détecté : {ollama}")
    print()

    print("Cette opération va désinstaller Ollama.")
    print("Les modèles doivent être supprimés séparément.")

    if not ask_yes_no("\nConfirmer la désinstallation d'Ollama"):
        print("[INFO] Désinstallation annulée.")
        return

    stop_ollama()

    try:
        if os.name == "nt":
            # Windows : désinstallation via winget si disponible
            winget = shutil.which("winget")

            if winget:
                print("[INFO] Désinstallation via winget...")

                subprocess.run(
                    [
                        winget,
                        "uninstall",
                        "--id",
                        "Ollama.Ollama",
                        "--silent",
                        "--accept-source-agreements"
                    ]
                )

            else:
                # Recherche du désinstalleur classique
                uninstallers = [
                    Path(os.environ.get("LOCALAPPDATA", ""))
                    / "Programs"
                    / "Ollama"
                    / "uninstall.exe",

                    Path(os.environ.get("PROGRAMFILES", ""))
                    / "Ollama"
                    / "uninstall.exe",
                ]

                uninstaller = next(
                    (p for p in uninstallers if p.exists()),
                    None
                )

                if uninstaller:
                    print("[INFO] Lancement du désinstalleur Ollama...")
                    subprocess.Popen([str(uninstaller)])
                else:
                    print(
                        "[ATTENTION] Désinstalleur Ollama introuvable."
                    )
                    print(
                        "Veuillez désinstaller Ollama depuis les paramètres "
                        "Windows."
                    )

        elif sys.platform == "darwin":
            # macOS
            applications = [
                Path("/Applications/Ollama.app"),
                Path.home() / "Applications" / "Ollama.app",
            ]

            removed = False

            for app in applications:
                if app.exists():
                    print(f"[SUPPRESSION] {app}")
                    shutil.rmtree(app, ignore_errors=True)
                    removed = True

            if not removed:
                print("[INFO] Ollama.app introuvable.")

        else:
            # Linux
            print("[INFO] Désinstallation Ollama sous Linux.")

            package_managers = [
                ["apt", "remove", "-y", "ollama"],
                ["dnf", "remove", "-y", "ollama"],
                ["pacman", "-Rns", "--noconfirm", "ollama"],
            ]

            removed = False

            for command in package_managers:
                if shutil.which(command[0]):
                    code, _, _ = run_command(command)

                    if code == 0:
                        removed = True
                        break

            if not removed:
                print(
                    "[ATTENTION] Gestionnaire de paquets Ollama "
                    "non détecté."
                )
                print(
                    "Ollama devra être désinstallé manuellement."
                )

    except Exception as e:
        print(f"[ERREUR] {e}")

    print("\n[OK] Opération Ollama terminée.")


# ============================================================
# SUPPRESSION DU PROGRAMME
# ============================================================

def remove_program():
    print("\n============================================================")
    print("SUPPRESSION DE LOCAL_IA")
    print("============================================================")

    print(f"Dossier : {PROGRAM_DIR}")
    print()
    print("Cette opération supprimera entièrement le programme")
    print("et tous ses fichiers présents dans ce dossier.")

    if not ask_yes_no("\nConfirmer la suppression du programme"):
        print("[INFO] Suppression annulée.")
        return

    # Arrêter les processus éventuels
    print("\n[INFO] Arrêt des processus Local_IA...")

    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/F", "/FI", "WINDOWTITLE eq LOCAL_IA*"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
    except Exception:
        pass

    time.sleep(1)

    # Windows ne peut pas supprimer directement le script en cours.
    if os.name == "nt":

        temp_bat = Path(os.environ.get("TEMP", "")) / (
            "local_ia_uninstall_" + str(os.getpid()) + ".bat"
        )

        bat = f"""@echo off
timeout /t 2 /nobreak >nul
rmdir /s /q "{PROGRAM_DIR}"
del "%~f0"
"""

        temp_bat.write_text(
            bat,
            encoding="utf-8"
        )

        subprocess.Popen(
            ["cmd.exe", "/c", str(temp_bat)],
            creationflags=subprocess.CREATE_NO_WINDOW
        )

    else:

        import shlex

        command = (
            f"sleep 2; "
            f"rm -rf {shlex.quote(str(PROGRAM_DIR))}"
        )

        subprocess.Popen(
            ["sh", "-c", command],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )

    print("\n[OK] Suppression du programme lancée.")
    print("Le dossier sera supprimé après la fermeture de ce script.")

    time.sleep(2)


# ============================================================
# MENU
# ============================================================

def main():

    while True:

        ui.clear_screen()
        print()
        print("=" * 60)
        print("LOCAL_IA — DÉSINSTALLATEUR")
        print("=" * 60)
        print()
        print("1. Supprimer le programme Local_IA")
        print("2. Supprimer des modèles Ollama")
        print("3. Désinstaller Ollama")
        print("4. Supprimer les modèles ET désinstaller Ollama")
        print("5. Tout supprimer (programme + modèles + Ollama)")
        print("0. Quitter")
        print()

        choice = input("Votre choix : ").strip()
        ui.clear_screen()

        if choice == "1":
            remove_program()

        elif choice == "2":
            remove_models()

        elif choice == "3":
            uninstall_ollama()

        elif choice == "4":
            remove_models()
            uninstall_ollama()

        elif choice == "5":
            remove_models()
            uninstall_ollama()
            remove_program()
            break

        elif choice == "0":
            print("\nDésinstallation annulée.")
            break

        else:
            print("\n[ERREUR] Choix invalide.")


if __name__ == "__main__":
    main()
