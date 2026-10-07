#!/usr/bin/env python3

import shutil
import subprocess
import sys
from pathlib import Path

import json
import os
import getpass
from local_ia.http_client import Request, open_url as urlopen
from urllib.error import URLError

import ui
import program_commands
from local_ia.core import accounts
from local_ia import models as model_manager
from local_ia import menu as menu_manager
from local_ia import updater as update_manager
from local_ia.models import get_model_description
from local_ia.start_menu import create_start_menu_shortcut


# ============================================================
# CONFIGURATION
# ============================================================

BASE_DIR = Path(__file__).resolve().parent

LIST_FILE = BASE_DIR / "list.json"
AGENT_FILE = BASE_DIR / "local_ia" / "cli" / "interface.py"
CONFIG_FILE = BASE_DIR / "config.py"
CHAT_DIR = BASE_DIR / "chats"
GITHUB_REPO = "https://github.com/lukeclnpro/local_ia"
GITHUB_BRANCH = "main"
VERSION_FILE = BASE_DIR / "version.json"
UPDATE_FILE = BASE_DIR / "update.json"
REMOTE_VERSION_URL = (
    "https://raw.githubusercontent.com/"
    "lukeclnpro/local_ia/main/version.json"
)

REMOTE_UPDATE_URL = (
    "https://raw.githubusercontent.com/"
    "lukeclnpro/local_ia/main/update.json"
)

REMOTE_ZIP_URL = (
    "https://github.com/lukeclnpro/local_ia/"
    "archive/refs/heads/main.zip"
)


# ============================================================
# OUTILS
# ============================================================

def clear_screen():
    """Efface le terminal sous Windows et Linux."""
    ui.clear_screen()


def pause():
    ui.pause()


def get_ollama():
    """Retourne le chemin de l'exécutable Ollama."""

    return shutil.which("ollama")


def check_ollama():
    """Vérifie qu'Ollama est disponible."""

    ollama = get_ollama()

    if ollama is None:
        ui.print_error("Ollama n'a pas été trouvé.")
        print()
        print("Vérifiez qu'Ollama est installé et accessible")
        print("depuis le terminal avec :")
        print()
        print(ui.colorize("    ollama --version", ui.C.INFO))

        return False

    return True


# ============================================================
# JSON
# ============================================================

def save_model_list(models):
    return model_manager.save_model_list(models, LIST_FILE)


# ============================================================
# SCAN DES MODELES
# ============================================================

def scan_models():
    return model_manager.scan_models(
        get_ollama(),
        subprocess.run,
        save_model_list,
    )


# ============================================================
# 1 - LANCER L'IA
# ============================================================

def load_config():
    """
    Charge config.json.
    Si le fichier n'existe pas, retourne un dictionnaire vide.
    """

    config_file = BASE_DIR / "config.json"

    if not config_file.exists():
        return {}

    try:
        with config_file.open(
            "r",
            encoding="utf-8"
        ) as file:
            return json.load(file)

    except (OSError, json.JSONDecodeError) as error:

        print(
            f"[ERREUR] Impossible de lire "
            f"config.json : {error}"
        )

        return {}


def resolve_runtime_provider():
    """Retourne le fournisseur LLM actif pour cette session."""
    provider = os.environ.get("LOCAL_IA_PROVIDER", "").strip().lower()
    if provider in {"openrouter", "ollama", "local"}:
        return "openrouter" if provider == "openrouter" else "local"
    return "local"


def clear_session_environment():
    """Supprime les variables de session liées au fournisseur actif."""
    for variable in (
        "LOCAL_IA_PROVIDER",
        "LOCAL_IA_OPENROUTER_KEY",
        "LOCAL_IA_OPENROUTER_KEYS",
        "LOCAL_IA_ACCOUNT",
    ):
        os.environ.pop(variable, None)


def activate_openrouter_session(username, api_keys):
    """Active une session OpenRouter et mémorise la clé de runtime."""
    os.environ["LOCAL_IA_ACCOUNT"] = username
    os.environ["LOCAL_IA_PROVIDER"] = "openrouter"
    set_openrouter_session_keys(api_keys)


def select_runtime_provider():
    """Affiche le choix initial de compte ou de fournisseur local."""
    try:
        saved_session = accounts.load_saved_session()
    except Exception:
        saved_session = None
    if saved_session:
        username, api_keys = saved_session
        activate_openrouter_session(username, api_keys)
        return "openrouter"

    while True:
        ui.clear_screen()
        ui.brand_logo()
        names = accounts.list_accounts()
        if names:
            print("Comptes locaux : " + ", ".join(names))
        ui.full_menu(
            "BIENVENUE DANS KAIRO",
            [
                ("1", "Se connecter"),
                ("2", "Créer un compte"),
                ("3", "Continuer sans compte (Ollama)"),
            ],
            footer="Votre choix : ",
            clear=False,
        )
        choice = ui.prompt("Votre choix : ").strip().lower()

        if choice == "1":
            api_keys = login_openrouter_account()
            if api_keys:
                username = os.environ.get("LOCAL_IA_ACCOUNT", "").strip()
                activate_openrouter_session(username, api_keys)
                return "openrouter"
            continue

        if choice == "2":
            api_keys = create_openrouter_account()
            if api_keys:
                username = os.environ.get("LOCAL_IA_ACCOUNT", "").strip()
                activate_openrouter_session(username, api_keys)
                return "openrouter"
            continue

        if choice == "3":
            try:
                accounts.clear_saved_session()
            except Exception:
                ui.print_info("La session mémorisée n'a pas pu être effacée du trousseau système.")
            clear_session_environment()
            return "local"

        ui.print_error("Choix invalide.")
        pause()


def login_openrouter_account():
    """Authentifie un compte local existant."""
    names = accounts.list_accounts()
    if not names:
        ui.print_error("Aucun compte local. Choisissez « Créer un compte ».")
        pause()
        return ""
    ui.section_title("CONNEXION")
    print("Comptes disponibles : " + ", ".join(names))
    username = ui.prompt("Nom du compte : ").strip()
    if not username:
        return ""
    password = getpass.getpass("Mot de passe du compte : ")
    try:
        api_keys = accounts.authenticate_api_keys(username, password)
    except ValueError as error:
        ui.print_error(str(error))
        pause()
        return ""
    os.environ["LOCAL_IA_ACCOUNT"] = username
    return api_keys


def set_openrouter_session_keys(api_keys):
    values = [api_keys] if isinstance(api_keys, str) else list(api_keys or [])
    values = list(dict.fromkeys(str(value).strip() for value in values if str(value).strip()))
    if not values:
        raise ValueError("Aucune clé API OpenRouter n'est disponible.")
    os.environ["LOCAL_IA_OPENROUTER_KEYS"] = json.dumps(values)
    os.environ.pop("LOCAL_IA_OPENROUTER_KEY", None)
    username = os.environ.get("LOCAL_IA_ACCOUNT", "").strip()
    if username:
        try:
            accounts.save_session(username, values)
        except Exception:
            ui.print_info("Connexion active, mais la session n'a pas pu être mémorisée par le trousseau système.")


def create_openrouter_account():
    """Crée un compte, puis ouvre ses options API avant validation."""
    show_account_tutorial()
    username = ui.prompt("Nom du nouveau compte : ").strip()
    if not username:
        return ""
    password = getpass.getpass("Mot de passe (8 caractères minimum) : ")
    if len(password) < 8:
        ui.print_error("Le mot de passe doit contenir au moins 8 caractères.")
        pause()
        return ""
    if any(name.casefold() == username.casefold() for name in accounts.list_accounts()):
        ui.print_error("Ce nom de compte existe déjà.")
        pause()
        return ""

    api_keys = configure_openrouter_api()
    if not api_keys:
        return ""
    try:
        accounts.create_account(username, password, api_keys)
    except ValueError as error:
        ui.print_error(str(error))
        pause()
        return ""

    os.environ["LOCAL_IA_ACCOUNT"] = username
    return api_keys


def show_account_tutorial():
    """Présente les premières étapes avant la création du compte."""
    pages = (
        (
            "01 / COMPTE",
            "Votre compte KAIRO protège vos réglages et votre clé API sur cet ordinateur.",
        ),
        (
            "02 / API",
            "Une ou plusieurs clés OpenRouter peuvent répartir les requêtes. Elles sont chiffrées localement et jamais affichées.",
        ),
        (
            "03 / PREMIERS PAS",
            'Choisissez votre modèle, puis essayez une question normale, iahelp "ma demande" ou /code pour créer un projet.',
        ),
    )
    for heading, description in pages:
        ui.clear_screen()
        ui.brand_logo()
        ui.section_title(heading, clear=False)
        ui.print_info(description)
        ui.pause("Entrée pour continuer")


def configure_openrouter_api():
    """Configure la clé et les options API avant de créer le compte."""
    config = load_config()
    options = config.setdefault("openrouter", {})
    api_keys = []

    while True:
        ui.full_menu(
            "OPTIONS API OPENROUTER",
            [
                ("1", f"Ajouter une clé API ({len(api_keys)} enregistrée(s))"),
                ("2", f"Modèle : {options.get('model', 'openai/gpt-4o-mini')}"),
                ("3", f"URL API : {options.get('base_url', 'https://openrouter.ai/api/v1')}"),
                ("4", f"Timeout : {options.get('timeout', 120)} secondes"),
                ("0", "Enregistrer et continuer"),
            ],
            footer="Votre choix : ",
        )
        choice = ui.prompt("Votre choix : ").strip()
        if choice == "1":
            api_key = getpass.getpass("Clé API OpenRouter : ").strip()
            if api_key and api_key not in api_keys:
                api_keys.append(api_key)
            elif api_key:
                ui.print_error("Cette clé est déjà saisie.")
        elif choice == "2":
            value = ui.prompt("Modèle OpenRouter : ").strip()
            if value:
                options["model"] = value
        elif choice == "3":
            value = ui.prompt("URL API OpenRouter : ").strip()
            if value:
                options["base_url"] = value.rstrip("/")
        elif choice == "4":
            value = ui.prompt("Timeout en secondes : ").strip()
            try:
                if value:
                    options["timeout"] = max(5, int(value))
            except ValueError:
                ui.print_error("Le timeout doit être un nombre entier.")
        elif choice == "0":
            if not api_keys:
                ui.print_error("Saisissez au moins une clé API avant de continuer.")
                pause()
                continue
            if not save_config(config):
                return ""
            os.environ["LOCAL_IA_OPENROUTER_MODEL"] = str(options.get("model", "openai/gpt-4o-mini"))
            os.environ["LOCAL_IA_OPENROUTER_BASE_URL"] = str(options.get("base_url", "https://openrouter.ai/api/v1"))
            return api_keys
        else:
            ui.print_error("Choix invalide.")


def change_openrouter_key():
    """Remplace la clé du compte et la chiffre avant son enregistrement."""
    username = os.environ.get("LOCAL_IA_ACCOUNT", "")
    if not username:
        ui.print_error("Aucun compte local n'est connecté.")
        pause()
        return
    password = getpass.getpass("Mot de passe du compte : ")
    api_key = getpass.getpass("Nouvelle clé API OpenRouter : ").strip()
    try:
        accounts.update_api_key(username, password, api_key)
        set_openrouter_session_keys(accounts.authenticate_api_keys(username, password))
    except ValueError as error:
        ui.print_error(str(error))
        pause()
        return
    ui.print_ok("Clé OpenRouter chiffrée et enregistrée pour ce compte.")
    pause()


def manage_local_accounts():
    """Connecte, cree ou supprime un compte local."""
    names = accounts.list_accounts()
    ui.section_title("GESTION DES COMPTES LOCAUX")
    print("1. Se connecter")
    print("2. Créer un compte")
    print("3. Supprimer un compte")
    print("4. Gérer les clés API")
    print("0. Retour")
    choice = ui.prompt("Votre choix : ").strip()

    if choice == "1":
        api_keys = login_openrouter_account()
        if api_keys:
            username = os.environ.get("LOCAL_IA_ACCOUNT", "").strip()
            activate_openrouter_session(username, api_keys)
        return

    if choice == "2":
        api_keys = create_openrouter_account()
        if api_keys:
            username = os.environ.get("LOCAL_IA_ACCOUNT", "").strip()
            activate_openrouter_session(username, api_keys)
        return

    if choice == "4":
        manage_openrouter_keys()
        return

    if choice == "3":
        if not names:
            ui.print_error("Aucun compte local à supprimer.")
            pause()
            return
        print("Comptes disponibles : " + ", ".join(names))
        username = ui.prompt("Compte à supprimer : ").strip()
        password = getpass.getpass("Mot de passe du compte : ")
        try:
            accounts.delete_account(username, password)
        except ValueError as error:
            ui.print_error(str(error))
            pause()
            return
        if username.casefold() == os.environ.get("LOCAL_IA_ACCOUNT", "").casefold():
            clear_session_environment()
        ui.print_ok("Compte local supprimé.")
        pause()


def manage_openrouter_keys():
    """Ajoute ou retire des clés du compte local sans les afficher."""
    names = accounts.list_accounts()
    if not names:
        ui.print_error("Aucun compte local disponible.")
        pause()
        return
    current = os.environ.get("LOCAL_IA_ACCOUNT", "")
    username = current if current.casefold() in {name.casefold() for name in names} else ui.prompt(
        "Nom du compte : "
    ).strip()
    password = getpass.getpass("Mot de passe du compte : ")
    try:
        api_keys = accounts.authenticate_api_keys(username, password)
    except ValueError as error:
        ui.print_error(str(error))
        pause()
        return

    ui.section_title("CLÉS API DU COMPTE")
    for index, api_key in enumerate(api_keys, start=1):
        print(f"{index}. Clé OpenRouter ••••{api_key[-4:]}")
    print("1. Ajouter une clé")
    print("2. Retirer une clé")
    print("0. Retour")
    choice = ui.prompt("Votre choix : ").strip()

    try:
        if choice == "1":
            new_key = getpass.getpass("Nouvelle clé API OpenRouter : ").strip()
            accounts.add_api_key(username, password, new_key)
            ui.print_ok("Clé ajoutée et chiffrée.")
        elif choice == "2":
            index = int(ui.prompt("Numéro de clé à retirer : ").strip())
            accounts.remove_api_key(username, password, index)
            ui.print_ok("Clé retirée.")
        else:
            return
        if username.casefold() == current.casefold():
            set_openrouter_session_keys(accounts.authenticate_api_keys(username, password))
    except (ValueError, TypeError) as error:
        ui.print_error(str(error))
    pause()


def show_openrouter_key_usage():
    """Affiche les statistiques de la clé OpenRouter active."""
    from local_ia.llm.ollama import get_openrouter_key_usage

    try:
        usage = get_openrouter_key_usage()
    except Exception as error:
        ui.print_error(f"Impossible de récupérer l'utilisation OpenRouter : {error}")
        pause()
        return

    ui.section_title("UTILISATION DE LA CLÉ OPENROUTER")
    if usage.get("label"):
        print(f"Clé : {usage['label']}")
    if usage.get("usage") is not None:
        print(f"Utilisation totale : ${float(usage['usage']):.4f}")
    if usage.get("limit") is not None:
        print(f"Limite : ${float(usage['limit']):.4f}")
    if usage.get("limit_remaining") is not None:
        print(f"Limite restante : ${float(usage['limit_remaining']):.4f}")
    for period in ("daily", "weekly", "monthly"):
        value = usage.get(f"usage_{period}")
        if value is not None:
            print(f"Utilisation {period} : ${float(value):.4f}")
    pause()

def save_config(config):
    """
    Enregistre config.json.
    """

    config_file = BASE_DIR / "config.json"

    try:

        with config_file.open(
            "w",
            encoding="utf-8"
        ) as file:

            json.dump(
                config,
                file,
                indent=4,
                ensure_ascii=False
            )

        return True

    except OSError as error:

        print(
            f"[ERREUR] Impossible d'écrire "
            f"config.json : {error}"
        )

        return False


def list_chat_files():
    """Retourne les conversations JSON disponibles, triées par numéro."""
    CHAT_DIR.mkdir(parents=True, exist_ok=True)
    chats = []

    for path in CHAT_DIR.glob("*.json"):
        if path.stem.isdigit():
            try:
                with open(path, "r", encoding="utf-8") as file:
                    data = json.load(file)

                chats.append({
                    "id": int(path.stem),
                    "topic": data.get("topic"),
                    "messages": len(data.get("messages", [])),
                    "updated_at": data.get("updated_at", "")
                })
            except (OSError, json.JSONDecodeError):
                continue

    return sorted(chats, key=lambda chat: chat["id"], reverse=True)


def select_chat():
    """
    Demande à l'utilisateur s'il veut charger une conversation
    existante ou en créer une nouvelle.
    Retourne ("new", None) ou ("load", chat_id).
    """

    CHAT_DIR.mkdir(parents=True, exist_ok=True)

    while True:
        chats = list_chat_files()

        options = []

        for chat in chats:
            topic = chat["topic"] or "Sans sujet"
            options.append(
                (str(chat["id"]), f"{topic}  ({chat['messages']} messages)")
            )

        options.append(("N", "Créer une nouvelle conversation"))
        options.append(("0", "Retour"))

        ui.full_menu(
            "CONVERSATION",
            options,
            subtitle=None if chats else "Aucune conversation existante.",
            footer="Numéro d'une conversation, N pour nouvelle, ou 0 pour revenir",
        )

        choice = ui.prompt("Votre choix : ").strip().lower()

        if choice == "0":
            return None

        if choice == "n":
            return ("new", None)

        if choice.isdigit():
            chat_id = int(choice)

            if any(chat["id"] == chat_id for chat in chats):
                return ("load", chat_id)

            ui.print_error("Conversation introuvable.")
            pause()
            continue

        ui.print_error("Choix invalide.")
        pause()


def launch_ai():
    """
    Démarre l'IA en fonction du fournisseur choisi pour cette session.
    La clé OpenRouter n'est pas enregistrée dans config.json.
    """
    ui.clear_screen()

    if not AGENT_FILE.exists():

        print(
            f"[ERREUR] {AGENT_FILE.name} "
            "est introuvable."
        )

        return

    provider = resolve_runtime_provider()

    if provider == "openrouter":
        selected_model = os.environ.get("LOCAL_IA_OPENROUTER_MODEL", "openai/gpt-4o-mini")
        ui.print_ok("Mode OpenRouter activé pour cette session.")
        ui.print_info("La clé API n'est pas stockée dans config.json.")
        print()
    else:
        # --------------------------------------------------------
        # SCAN DES MODELES
        # --------------------------------------------------------

        print()
        print("Recherche des modèles installés...")
        print()

        models = scan_models()

        if not models:

            print(
                "[ERREUR] Aucun modèle Ollama installé."
            )

            if get_ollama() is None:
                print("Ollama est facultatif. Utilisez l'option 10 pour configurer un compte API.")
            else:
                print("Installez d'abord un modèle avec l'option 3.")

            return

        # --------------------------------------------------------
        # CHOIX DU MODELE
        # --------------------------------------------------------

        while True:

            options = []

            for number, model in enumerate(models, start=1):

                description = get_model_description(model["name"])
                label = f"{model['name']}  ({model['size']})"

                if description:
                    label += f" — {description}"

                options.append((str(number), label))

            options.append(("0", "Annuler"))

            ui.full_menu(
                "LANCER L'IA LOCALE",
                options,
                subtitle="Modèles installés",
                footer="Sur quel modèle voulez-vous lancer l'IA ?",
            )

            choice = ui.prompt("Votre choix : ").strip()

            if not choice.isdigit():

                ui.print_error("Choix invalide.")

                pause()
                continue

            number = int(choice)

            if number == 0:

                return

            if number < 1 or number > len(models):

                ui.print_error("Choix invalide.")

                pause()
                continue

            selected_model = models[number - 1]["name"]

            break

        config = load_config()
        config["model"] = selected_model

        if not save_config(config):

            ui.print_error(
                "Le modèle n'a pas pu être enregistré dans config.json."
            )

            pause()
            return

        print()
        ui.print_ok(f"Modèle sélectionné : {selected_model}")
        ui.print_ok("config.json mis à jour.")

    # --------------------------------------------------------
    # CHOIX DE LA CONVERSATION
    # --------------------------------------------------------

    chat_selection = select_chat()

    if chat_selection is None:
        print()
        print("[INFO] Retour au menu principal.")
        return

    chat_mode, chat_id = chat_selection

    # --------------------------------------------------------
    # LANCEMENT DE L'INTERFACE CLI MODULAIRE
    # --------------------------------------------------------

    print()
    ui.section_title("LANCEMENT IA", clear=False)
    print(
        ui.colorize("Modèle utilisé : ", ui.C.SUBTITLE)
        + ui.colorize(selected_model, ui.C.OK)
    )

    if chat_mode == "new":
        print("Conversation : nouvelle")
    else:
        print(f"Conversation : {chat_id}")

    print()

    # Variables d'environnement utilisées par l'interface CLI
    # pour savoir quelle conversation ouvrir au démarrage.
    agent_env = os.environ.copy()
    agent_env["LOCAL_IA_CHAT_MODE"] = chat_mode

    if chat_id is not None:
        agent_env["LOCAL_IA_CHAT_ID"] = str(chat_id)
    else:
        agent_env.pop("LOCAL_IA_CHAT_ID", None)

    try:

        subprocess.run(
            [sys.executable, str(AGENT_FILE)],
            cwd=str(BASE_DIR),
            env=agent_env
        )

    except KeyboardInterrupt:

        print(
            "\n[INFO] IA arrêtée."
        )

    except OSError as error:

        print(
            f"[ERREUR] Impossible de lancer "
            f"l'IA : {error}"
        )

# ============================================================
# 7 - MISE À JOUR DU PROGRAMME
# ============================================================

def load_json_file(path):
    return update_manager.load_json_file(path)


def get_current_version():
    return update_manager.get_current_version(VERSION_FILE)


def _required_update_files(source_dir):
    return update_manager.required_update_files(source_dir)


def download_json(url):
    return update_manager.download_json(url, ui)


def version_to_tuple(version):
    return update_manager.version_to_tuple(version)


def check_for_update(show_message=True):
    """
    Vérifie si une version plus récente est disponible
    sur GitHub.

    Retourne :
        (True, remote_version)
        (False, current_version)
        (None, None) en cas d'erreur.
    """

    current_version = get_current_version()

    remote_data = download_json(
        REMOTE_VERSION_URL
    )

    if remote_data is None:
        return None, None

    return update_manager.check_for_update(
        current_version,
        remote_data,
        show_message,
        ui,
    )


def update_program():
    return update_manager.update_program(
        BASE_DIR,
        REMOTE_ZIP_URL,
        ui,
        pause,
        check_for_update,
        _required_update_files,
        get_current_version,
        version_to_tuple,
    )


# ============================================================
# FORCE UPDATE - RÉINSTALLATION COMPLÈTE DEPUIS GITHUB
# ============================================================

FORCE_UPDATE_PROTECTED = {
    "_chats",
    "_config.json",
    "_list.json",
    "_context.json",
}


def force_update():
    """Réinstalle intégralement le dépôt GitHub en conservant uniquement les 4 éléments protégés."""
    ui.clear_screen()
    import tempfile
    import zipfile
    import textwrap

    print()
    ui.section_title("FORCE UPDATE", clear=False)
    ui.print_warn("Réinstallation complète depuis GitHub.")
    print()
    print("Éléments conservés :")
    print("  • _chats/")
    print("  • _config.json")
    print("  • _list.json")
    print("  • _context.json")
    print()

    temp_root = Path(tempfile.mkdtemp(prefix="local_ia_force_update_"))
    zip_path = temp_root / "repository.zip"
    extract_dir = temp_root / "extracted"
    helper_path = temp_root / "force_update_worker.py"

    try:
        ui.print_info("Téléchargement complet du dépôt GitHub...")

        request = Request(
            REMOTE_ZIP_URL,
            headers={"User-Agent": "Local-IA-Force-Updater"},
        )

        with urlopen(request, timeout=120) as response:
            with zip_path.open("wb") as file:
                shutil.copyfileobj(response, file)

        ui.print_ok("Dépôt téléchargé.")

        extract_dir.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(zip_path, "r") as archive:
            archive.extractall(extract_dir)

        source_dirs = [path for path in extract_dir.iterdir() if path.is_dir()]
        if len(source_dirs) != 1:
            raise RuntimeError("Structure de l'archive GitHub invalide.")

        source_dir = source_dirs[0]

        worker_code = textwrap.dedent('''
            import os
            import shutil
            import sys
            from pathlib import Path

            PROTECTED = {
                "_chats",
                "_config.json",
                "_list.json",
                "_context.json",
            }

            def is_protected(relative_path):
                parts = Path(relative_path).parts
                return bool(parts) and parts[0] in PROTECTED

            def remove_path(path):
                if path.is_dir() and not path.is_symlink():
                    shutil.rmtree(path)
                else:
                    path.unlink(missing_ok=True)

            def copy_repository(source, destination):
                for root, dirs, files in os.walk(source):
                    root_path = Path(root)
                    relative_root = root_path.relative_to(source)

                    dirs[:] = [
                        name for name in dirs
                        if not is_protected(relative_root / name)
                    ]

                    destination_root = destination / relative_root
                    destination_root.mkdir(parents=True, exist_ok=True)

                    for filename in files:
                        relative_file = relative_root / filename
                        if is_protected(relative_file):
                            continue

                        source_file = source / relative_file
                        destination_file = destination / relative_file
                        destination_file.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(source_file, destination_file)

            def main():
                source = Path(sys.argv[1]).resolve()
                destination = Path(sys.argv[2]).resolve()

                for item in destination.iterdir():
                    if item.name in PROTECTED:
                        continue
                    remove_path(item)

                copy_repository(source, destination)

                print()
                print("========================================")
                print(" LOCAL_IA : FORCE UPDATE TERMINÉ")
                print("========================================")
                print()
                print("Réinstallation complète depuis GitHub terminée.")
                print("Conservés : _chats, _config.json, _list.json, _context.json")

            if __name__ == "__main__":
                try:
                    main()
                except Exception as error:
                    print()
                    print("[ERREUR] La réinstallation a échoué :", error)
                    sys.exit(1)
        ''').strip() + "\n"

        helper_path.write_text(worker_code, encoding="utf-8")

        ui.print_info("Lancement de la réinstallation complète...")
        print()

        process = subprocess.Popen(
            [sys.executable, str(helper_path), str(source_dir), str(BASE_DIR)],
            cwd=str(BASE_DIR),
        )
        return process.wait()

    except URLError as error:
        ui.print_error(f"Erreur réseau pendant le force update : {error}")
        return 1
    except zipfile.BadZipFile:
        ui.print_error("L'archive GitHub téléchargée est invalide.")
        return 1
    except Exception as error:
        ui.print_error(f"Le force update a échoué : {error}")
        return 1


# ============================================================
# 8 - AFFICHER LES NOUVEAUTÉS
# ============================================================

def show_updates():
    """
    Affiche les nouveautés depuis le fichier update.json local.

    Aucun téléchargement depuis GitHub n'est effectué.
    """
    ui.clear_screen()

    print()

    ui.section_title(
        "NOUVEAUTÉS",
        clear=False
    )

    ui.print_info(
        "Lecture des nouveautés locales..."
    )

    # --------------------------------------------------------
    # CHARGEMENT DU FICHIER LOCAL
    # --------------------------------------------------------

    data = load_json_file(UPDATE_FILE)

    if data is None:

        ui.print_error(
            f"Impossible de lire {UPDATE_FILE.name}."
        )

        pause()
        return

    versions = data.get(
        "versions",
        []
    )

    if not versions:

        ui.print_warn(
            "Aucune nouveauté disponible."
        )

        pause()
        return

    # --------------------------------------------------------
    # TRI : PLUS RÉCENTE EN PREMIER
    # --------------------------------------------------------

    versions = sorted(
        versions,
        key=lambda item: version_to_tuple(
            item.get("version", "0.0.0")
        ),
        reverse=True,
    )

    # --------------------------------------------------------
    # AFFICHAGE
    # --------------------------------------------------------

    for release in versions:

        version = release.get(
            "version",
            "?"
        )

        date = release.get(
            "date",
            ""
        )

        title = release.get(
            "title",
            ""
        )

        print()

        print(
            ui.colorize(
                f"Version {version}",
                ui.C.OK
            )
        )

        if date:

            print(
                ui.colorize(
                    f"Date : {date}",
                    ui.C.DIM + ui.C.WHITE
                )
            )

        if title:

            print(
                ui.colorize(
                    title,
                    ui.C.SUBTITLE
                )
            )

        changes = release.get(
            "changes",
            []
        )

        for change in changes:

            print(
                f"  • {change}"
            )

    print()

    pause()

# ============================================================
# 2 - LISTER LES MODELES
# ============================================================

def list_models():
    """
    Scan Ollama puis affiche les modèles installés
    avec leur taille.
    """
    ui.clear_screen()

    print()
    ui.print_info("Scan des modèles Ollama...")
    print()

    models = scan_models()

    ui.section_title("MODÈLES INSTALLÉS", clear=False)

    if not models:

        ui.print_warn("Aucun modèle installé.")
        return

    for number, model in enumerate(models, start=1):

        print(
            ui.colorize(f"{number}. {model['name']}", ui.C.OPTION_KEY)
        )

        print(
            ui.colorize(f"   Taille      : {model['size']}", ui.C.WHITE)
        )

        if model["id"]:
            print(
                ui.colorize(f"   ID          : {model['id']}", ui.C.DIM + ui.C.WHITE)
            )

        if model["modified"]:
            print(
                ui.colorize(f"   Modifié     : {model['modified']}", ui.C.DIM + ui.C.WHITE)
            )

        # Cherche une description dans la liste prédéfinie
        description = get_model_description(
            model["name"]
        )

        if description:

            print(
                ui.colorize(f"   Description : {description}", ui.C.SUBTITLE)
            )

        print()

    ui.print_info(f"Total : {len(models)} modèle(s)")


# ============================================================
# DESCRIPTION DES MODELES
# ============================================================

# ============================================================
# 3 - INSTALLER UN MODELE
# ============================================================

def install_model():
    return model_manager.install_model(ui, scan_models, get_ollama, subprocess.run, pause)

# ============================================================
# 4 - DESINSTALLER UN MODELE
# ============================================================

def uninstall_model():
    return model_manager.uninstall_model(
        ui,
        scan_models,
        get_ollama,
        subprocess.run,
        get_model_description,
    )


# ============================================================
# 5 - MODIFIER LA CONFIGURATION DE L'IA
# ============================================================

def edit_ai_config():
    """Lance l'outil interactif de configuration de l'IA."""
    ui.clear_screen()

    if not CONFIG_FILE.exists():
        print(
            f"[ERREUR] {CONFIG_FILE.name} est introuvable."
        )
        return

    env = os.environ.copy()
    env["LOCAL_IA_CONFIG_FROM_MAIN"] = "1"

    try:
        subprocess.run(
            [sys.executable, str(CONFIG_FILE)],
            cwd=str(BASE_DIR),
            env=env
        )
    except KeyboardInterrupt:
        print("\n[INFO] Configuration interrompue.")
    except OSError as error:
        print(
            f"[ERREUR] Impossible de lancer la configuration : {error}"
        )



def install_catalog_application(input_fn=None):
    input_fn = input_fn or ui.prompt
    try:
        programs = program_commands.get_catalog_programs()
    except ValueError as error:
        ui.print_error(str(error))
        pause()
        return

    ui.section_title("INSTALLER UNE APPLICATION", clear=False)
    for index, program in enumerate(programs, 1):
        print(f"{index:>2}. {program['name']} · {program.get('category', 'Autre')}")
    print(" 0. Retour")
    choice = input_fn("Application à installer : ").strip()
    if choice == "0":
        return
    if not choice.isdecimal() or not 1 <= int(choice) <= len(programs):
        ui.print_error("Choix invalide.")
        pause()
        return

    program = programs[int(choice) - 1]
    try:
        plan = program_commands.get_installation_plan(program["id"])
    except (KeyError, ValueError) as error:
        ui.print_error(str(error))
        pause()
        return

    print(f"\nApplication : {program['name']}")
    print(f"Gestionnaire : {plan['manager']}")
    print(f"Commande : {program_commands.format_command(plan['command'])}")
    if plan["requires"]:
        print("Prérequis : " + ", ".join(plan["requires"]))
    confirmation = input_fn("Lancer cette installation ? [o/N] ").strip().casefold()
    if confirmation not in {"o", "oui", "y", "yes"}:
        ui.print_info("Installation annulée.")
        return

    try:
        result = program_commands.execute_install_command(plan["command"])
    except OSError as error:
        ui.print_error(f"Impossible de lancer l'installation : {error}")
    else:
        if result.returncode == 0:
            ui.print_ok(f"{program['name']} installé.")
        else:
            ui.print_error(f"L'installation s'est terminée avec le code {result.returncode}.")
    pause()


# ============================================================
# MENU PRINCIPAL
# ============================================================
def get_version():
    version_file = Path(__file__).parent / "version.json"

    try:
        with open(version_file, "r", encoding="utf-8") as file:
            data = json.load(file)

        return (
            data.get("version", "Inconnue"),
            data.get("patch", "Inconnu"),
            data.get("modified_at", "Date inconnue"),
        )

    except (FileNotFoundError, json.JSONDecodeError):
        return "Inconnue", "Inconnu", "Date inconnue"


def get_main_menu_options(provider=None):
    provider = provider or resolve_runtime_provider()
    return menu_manager.get_main_menu_options(provider)


def menu():

    while True:
        version, patch, modified_at = get_version()
        provider = resolve_runtime_provider()

        ui.full_menu(
            f"{ui.PRODUCT_NAME} - v{version}",
            get_main_menu_options(provider),
            subtitle=f"Patch {patch} · Modifié le {modified_at}",
            footer="Votre choix : ",
        )

        choice = ui.prompt(
            "Votre choix : "
        ).strip()

        # Chaque outil commence sur un écran neuf : le menu précédent
        # et la saisie de la commande ne restent jamais affichés.
        ui.clear_screen()

        if choice == "1":

            launch_ai()
            pause()

        elif choice == "2" and provider == "openrouter":

            change_openrouter_key()

        elif choice == "3" and provider == "openrouter":

            show_openrouter_key_usage()

        elif choice == "2" and provider != "openrouter":

            list_models()
            pause()

        elif choice == "3" and provider != "openrouter":

            install_model()

        elif choice == "4" and provider != "openrouter":

            uninstall_model()
            pause()

        elif choice in {"2", "3", "4"}:

            ui.print_error("La gestion des modèles Ollama est indisponible avec OpenRouter.")
            pause()

        elif choice == "5":

            edit_ai_config()

        elif choice == "6":

            install_catalog_application()

        elif choice == "7":

            update_program()

        elif choice == "8":

            show_updates()

        elif choice == "9":

            from local_ia.core.code_projects import open_code_projects

            try:
                project_folder = open_code_projects()
                ui.print_ok(f"Dossier des projets de code : {project_folder}")
            except (FileNotFoundError, OSError) as error:
                ui.print_error(f"Impossible d'ouvrir le dossier des projets : {error}")
            pause()

        elif choice == "10":

            manage_local_accounts()

        elif choice == "0":

            ui.print_info(
                "Fermeture."
            )

            break

        else:

            ui.print_error(
                "Choix invalide."
            )

            pause()


def show_help():
    return menu_manager.show_help()


# ============================================================
# PROGRAMME PRINCIPAL
# ============================================================

def main():

    # Commandes en ligne de commande. Elles sont traitées avant
    # le menu et avant toute vérification Ollama.
    if len(sys.argv) > 1:
        command = sys.argv[1].strip().lower()

        if command in {"gui", "--gui"}:
            create_start_menu_shortcut(BASE_DIR)
            from local_ia.gui import run_gui

            return run_gui()

        if command == "--tray":
            create_start_menu_shortcut(BASE_DIR)
            from local_ia.desktop_tray import run_tray

            return run_tray()

        if command in {"help", "-h", "--help"}:
            show_help()
            return 0

        if command == "force_update":
            return force_update()

        if command == "iahelp":
            from local_ia.cli.iahelp import main as iahelp_main

            return iahelp_main(sys.argv[2:])

    create_start_menu_shortcut(BASE_DIR)

    if (
        not os.environ.get("LOCAL_IA_GUI_CHILD")
        and (sys.platform.startswith("linux") or os.name == "nt")
    ):
        from local_ia.desktop_tray import start_tray

        start_tray()

    ui.brand_logo()
    ui.section_title(f"{ui.PRODUCT_NAME} · IA LOCALE", clear=False)

    provider = select_runtime_provider()

    if provider == "local":
        if check_ollama():
            scan_models()
        else:
            ui.print_info("Ollama n'est pas installé. Le menu reste disponible pour utiliser un compte API.")

    menu()


if __name__ == "__main__":
    result = main()
    if isinstance(result, int):
        sys.exit(result)
