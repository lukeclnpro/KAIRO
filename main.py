#!/usr/bin/env python3

import platform
import shutil
import subprocess
import sys
from pathlib import Path

import json
import os
import time
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

import ui


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
# MODELES DISPONIBLES A L'INSTALLATION
# ============================================================
#
# La taille et la description affichées ici correspondent
# aux informations connues pour le modèle.
#
# La taille réellement installée sera récupérée par le scan
# Ollama.
#

AVAILABLE_MODELS = {

    "Généraliste": [
        {
            "name": "qwen3:4b",
            "size": "~2.5 GB",
            "description": "Modèle compact polyvalent pour le dialogue, le raisonnement et les tâches générales.",
        },
        {
            "name": "qwen3:8b",
            "size": "~5.2 GB",
            "description": "Modèle polyvalent pour dialogue, raisonnement, traduction et tâches générales.",
        },
        {
            "name": "llama3.2:3b",
            "size": "~2.0 GB",
            "description": "Petit modèle généraliste conçu pour fonctionner avec peu de ressources.",
        },
        {
            "name": "mistral:7b",
            "size": "~4.1 GB",
            "description": "Modèle généraliste adapté au dialogue, à la rédaction et aux tâches quotidiennes.",
        },
        {
            "name": "gemma3:4b",
            "size": "~3.3 GB",
            "description": "Modèle compact de Google adapté aux tâches générales et à la vision.",
        },
    ],

    "Programmation": [
        {
            "name": "qwen2.5-coder:7b",
            "size": "~4.7 GB",
            "description": "Génération, correction, compréhension et explication de code.",
        },
        {
            "name": "qwen2.5-coder:14b",
            "size": "~9 GB",
            "description": "Version plus puissante pour les projets logiciels complexes.",
        },
        {
            "name": "qwen3-coder:30b",
            "size": "~19 GB",
            "description": "Programmation avancée et agents capables de travailler sur des projets logiciels.",
        },
        {
            "name": "deepseek-coder:6.7b",
            "size": "~4 GB",
            "description": "Génération et compréhension de nombreux langages de programmation.",
        },
        {
            "name": "codegemma:7b",
            "size": "~5 GB",
            "description": "Génération de code et autocomplétion.",
        },
        {
            "name": "codellama:7b",
            "size": "~4 GB",
            "description": "Modèle Meta spécialisé dans le code.",
        },
    ],

    "Raisonnement": [
        {
            "name": "deepseek-r1:7b",
            "size": "~4.7 GB",
            "description": "Raisonnement logique, résolution de problèmes et analyse.",
        },
        {
            "name": "deepseek-r1:14b",
            "size": "~9 GB",
            "description": "Version plus importante pour les problèmes de raisonnement complexes.",
        },
        {
            "name": "qwen3:14b",
            "size": "~9 GB",
            "description": "Raisonnement, logique, analyse et résolution de problèmes.",
        },
        {
            "name": "qwq:32b",
            "size": "~20 GB",
            "description": "Modèle orienté raisonnement approfondi.",
        },
    ],

    "Mathématiques": [
        {
            "name": "qwen2-math:1.5b",
            "size": "~1 GB",
            "description": "Résolution de problèmes mathématiques avec faible consommation.",
        },
        {
            "name": "qwen2-math:7b",
            "size": "~4.4 GB",
            "description": "Modèle spécialisé dans les problèmes et raisonnements mathématiques.",
        },
    ],

    "Vision / Images": [
        {
            "name": "gemma3:4b",
            "size": "~3.3 GB",
            "description": "Compréhension de texte et analyse d'images.",
        },
        {
            "name": "llama3.2-vision:11b",
            "size": "~7.9 GB",
            "description": "Analyse d'images et compréhension visuelle.",
        },
        {
            "name": "qwen2.5vl:7b",
            "size": "~6 GB",
            "description": "Vision-langage et analyse de documents visuels.",
        },
        {
            "name": "llava:7b",
            "size": "~4.7 GB",
            "description": "Compréhension d'images et questions-réponses visuelles.",
        },
    ],

    "Traduction / Multilingue": [
        {
            "name": "translategemma:4b",
            "size": "~3 GB",
            "description": "Modèle spécialisé dans la traduction multilingue.",
        },
        {
            "name": "qwen3:8b",
            "size": "~5.2 GB",
            "description": "Modèle multilingue adapté à la traduction et à la compréhension de nombreuses langues.",
        },
    ],

    "RAG / Embeddings": [
        {
            "name": "nomic-embed-text",
            "size": "~0.3 GB",
            "description": "Embeddings pour recherche sémantique et systèmes RAG.",
        },
        {
            "name": "mxbai-embed-large",
            "size": "~0.7 GB",
            "description": "Embeddings pour recherche sémantique et bases vectorielles.",
        },
        {
            "name": "qwen3-embedding:0.6b",
            "size": "~0.6 GB",
            "description": "Embeddings Qwen pour recherche sémantique et RAG.",
        },
        {
            "name": "embeddinggemma:300m",
            "size": "~0.3 GB",
            "description": "Modèle d'embeddings extrêmement compact.",
        },
    ],

    "Sciences / Technique": [
        {
            "name": "granite3.3:8b",
            "size": "~5 GB",
            "description": "Raisonnement, analyse et tâches techniques.",
        },
        {
            "name": "phi3:mini",
            "size": "~2.2 GB",
            "description": "Petit modèle Microsoft pour les tâches techniques et analytiques.",
        },
    ],

    "Agents": [
        {
            "name": "qwen3:8b",
            "size": "~5.2 GB",
            "description": "Adapté aux agents utilisant des outils et exécutant des tâches en plusieurs étapes.",
        },
        {
            "name": "qwen3-coder:30b",
            "size": "~19 GB",
            "description": "Agent développeur pour exploration et modification de projets.",
        },
        {
            "name": "granite4.1:8b",
            "size": "~5 GB",
            "description": "Modèle orienté agents, RAG, outils et sorties JSON structurées.",
        },
    ],
}


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
    """
    Enregistre les modèles détectés dans list.json.
    """

    data = {
        "models": models
    }

    try:

        with LIST_FILE.open(
            "w",
            encoding="utf-8"
        ) as file:

            json.dump(
                data,
                file,
                indent=4,
                ensure_ascii=False
            )

        return True

    except OSError as error:

        print(
            f"[ERREUR] Impossible d'écrire "
            f"{LIST_FILE}: {error}"
        )

        return False


# ============================================================
# SCAN DES MODELES
# ============================================================

def scan_models():
    """
    Lance 'ollama list' et récupère :

        - nom
        - ID
        - taille
        - date de modification

    Puis met automatiquement à jour list.json.
    """

    ollama = get_ollama()

    if ollama is None:
        return []

    try:

        result = subprocess.run(
            [ollama, "list"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace"
        )

    except OSError as error:

        print(
            f"[ERREUR] Impossible d'exécuter Ollama : "
            f"{error}"
        )

        return []

    if result.returncode != 0:

        print(
            "[ERREUR] Impossible de récupérer "
            "la liste des modèles."
        )

        if result.stderr:
            print(result.stderr.strip())

        return []

    models = []

    lines = result.stdout.splitlines()

    if len(lines) <= 1:
        save_model_list([])
        return []

    # --------------------------------------------------------
    # Première ligne :
    #
    # NAME    ID    SIZE    MODIFIED
    # --------------------------------------------------------

    for line in lines[1:]:

        line = line.strip()

        if not line:
            continue

        parts = line.split()

        if not parts:
            continue

        # ----------------------------------------------------
        # Ollama retourne généralement :
        #
        # NAME
        # ID
        # SIZE
        # MODIFIED
        # ----------------------------------------------------

        name = parts[0]
        model_id = parts[1] if len(parts) > 1 else ""
        size = parts[2] if len(parts) > 2 else ""

        modified = " ".join(parts[3:])

        models.append(
            {
                "name": name,
                "id": model_id,
                "size": size,
                "modified": modified,
            }
        )

    # Élimination des doublons
    unique_models = []

    seen = set()

    for model in models:

        name = model["name"]

        if name not in seen:

            seen.add(name)
            unique_models.append(model)

    save_model_list(unique_models)

    return unique_models


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


def select_runtime_provider():
    """Demande le fournisseur au lancement sans l'enregistrer dans config.json."""
    current = resolve_runtime_provider()
    if current == "openrouter":
        return

    ui.clear_screen()
    ui.full_menu(
        "PROVIDEUR IA",
        [
            ("1", "IA locale (Ollama)"),
            ("2", "OpenRouter (clé API saisie au lancement)"),
        ],
        footer="Choisissez le mode d'IA pour cette session : ",
    )

    while True:
        choice = ui.prompt("Votre choix : ").strip().lower()

        if choice == "1":
            os.environ.pop("LOCAL_IA_PROVIDER", None)
            os.environ.pop("LOCAL_IA_OPENROUTER_KEY", None)
            os.environ.pop("LOCAL_IA_OPENROUTER_MODEL", None)
            os.environ.pop("LOCAL_IA_OPENROUTER_BASE_URL", None)
            return

        if choice == "2":
            api_key = ui.prompt("Clé API OpenRouter (non stockée localement) : ").strip()
            if not api_key:
                ui.print_error("Une clé OpenRouter est requise.")
                pause()
                continue
            os.environ["LOCAL_IA_PROVIDER"] = "openrouter"
            os.environ["LOCAL_IA_OPENROUTER_KEY"] = api_key
            os.environ.setdefault("LOCAL_IA_OPENROUTER_MODEL", "openai/gpt-4o-mini")
            os.environ.setdefault("LOCAL_IA_OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
            return

        ui.print_error("Choix invalide.")
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

            print(
                "Installez d'abord un modèle avec "
                "l'option 3."
            )

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
        ui.colorize(f"Modèle utilisé : ", ui.C.SUBTITLE)
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
    """Charge un fichier JSON local."""
    try:
        with path.open("r", encoding="utf-8") as file:
            return json.load(file)
    except (OSError, json.JSONDecodeError):
        return None


def get_current_version():
    """Retourne la version installée localement."""
    data = load_json_file(VERSION_FILE)

    if not data:
        return "0.0.0"

    return str(data.get("version", "0.0.0"))


def download_json(url):
    """Télécharge un fichier JSON depuis GitHub."""
    try:
        import urllib.request

        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Local-IA-Updater"
            }
        )

        with urllib.request.urlopen(
            request,
            timeout=10
        ) as response:

            content = response.read().decode("utf-8")

        return json.loads(content)

    except Exception as error:
        print()
        ui.print_error(
            f"Impossible de récupérer les informations : {error}"
        )
        return None


def version_to_tuple(version):
    """
    Transforme une version du type 1.2.3
    en tuple comparable.
    """
    try:
        parts = str(version).strip().lstrip("v").split(".")

        return tuple(
            int(part)
            for part in parts
        )

    except (ValueError, AttributeError):
        return (0, 0, 0)


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

    remote_version = str(
        remote_data.get(
            "version",
            current_version
        )
    )

    current_tuple = version_to_tuple(
        current_version
    )

    remote_tuple = version_to_tuple(
        remote_version
    )

    if remote_tuple > current_tuple:

        if show_message:
            print()

            ui.print_warn(
                "Une nouvelle version est disponible !"
            )

            print(
                f"Version installée : {current_version}"
            )

            print(
                f"Nouvelle version  : {remote_version}"
            )

        return True, remote_version

    if show_message:
        print()

        ui.print_ok(
            f"Vous utilisez déjà la dernière version "
            f"({current_version})."
        )

    return False, current_version


def update_program():
    """
    Télécharge la dernière version du dépôt GitHub.

    Fichiers mis à jour :
        - tous les fichiers Python (.py)
        - tous les fichiers HTML/CSS/JS du dossier web/
        - version.json
        - update.json

    Les autres fichiers locaux, les configurations,
    les conversations et les autres données utilisateur
    ne sont jamais remplacés.
    """
    ui.clear_screen()

    print()

    ui.section_title(
        "MISE À JOUR",
        clear=False
    )

    print(
        "Vérification de la dernière version..."
    )

    update_available, version = check_for_update(
        show_message=True
    )

    if update_available is None:
        pause()
        return

    if not update_available:
        pause()
        return

    print()

    confirmation = ui.prompt(
        f"Installer la version {version} ? (o/N) : "
    ).strip().lower()

    if confirmation != "o":
        ui.print_warn(
            "Mise à jour annulée."
        )
        pause()
        return

    print()

    ui.print_info(
        "Téléchargement des fichiers de mise à jour..."
    )

    import tempfile
    import zipfile
    import urllib.request

    try:

        with tempfile.TemporaryDirectory() as temp:

            temp_dir = Path(temp)

            zip_path = temp_dir / "update.zip"

            # =================================================
            # TÉLÉCHARGEMENT DE L'ARCHIVE GITHUB
            # =================================================

            request = urllib.request.Request(
                REMOTE_ZIP_URL,
                headers={
                    "User-Agent": "Local-IA-Updater"
                }
            )

            with urllib.request.urlopen(
                request,
                timeout=60
            ) as response:

                with zip_path.open(
                    "wb"
                ) as file:

                    file.write(
                        response.read()
                    )

            # =================================================
            # EXTRACTION
            # =================================================

            extract_dir = temp_dir / "extracted"

            extract_dir.mkdir()

            with zipfile.ZipFile(
                zip_path,
                "r"
            ) as archive:

                archive.extractall(
                    extract_dir
                )

            source_dirs = list(
                extract_dir.iterdir()
            )

            if len(source_dirs) != 1:

                raise RuntimeError(
                    "Structure de l'archive GitHub invalide."
                )

            source_dir = source_dirs[0]

            # =================================================
            # RECHERCHE DES FICHIERS À METTRE À JOUR
            # =================================================
            #
            # On récupère :
            #
            #   - tous les .py
            #   - version.json
            #   - update.json
            #
            # Les autres JSON ne sont PAS touchés.
            #

            update_files = []

            # -------------------------------------------------
            # FICHIERS PYTHON
            # -------------------------------------------------

            for source_path in source_dir.rglob("*.py"):

                if not source_path.is_file():
                    continue

                relative_path = (
                    source_path.relative_to(
                        source_dir
                    )
                )

                # Ne jamais récupérer les fichiers Python
                # présents dans certains dossiers inutiles.
                if any(
                    part in {
                        ".git",
                        "__pycache__",
                        ".github",
                    }
                    for part in relative_path.parts
                ):
                    continue

                update_files.append(
                    relative_path
                )

            # -------------------------------------------------
            # FICHIERS WEB (HTML / CSS / JS)
            # -------------------------------------------------
            #
            # L'interface web fait partie intégrante du programme.
            # On installe donc automatiquement tous les fichiers
            # .html, .css et .js du dossier web/.
            #
            # Les autres fichiers présents dans web/ ne sont pas
            # remplacés par le service de mise à jour.
            #

            for source_path in (source_dir / "web").rglob("*"):
                if not source_path.is_file():
                    continue

                if source_path.suffix.lower() not in {
                    ".html",
                    ".css",
                    ".js",
                }:
                    continue

                relative_path = source_path.relative_to(source_dir)

                update_files.append(relative_path)

            # -------------------------------------------------
            # FICHIERS JSON AUTORISÉS
            # -------------------------------------------------

            json_files = [
                Path("version.json"),
                Path("update.json"),
            ]

            for relative_path in json_files:

                source_path = (
                    source_dir / relative_path
                )

                if not source_path.is_file():

                    raise RuntimeError(
                        f"Le fichier {relative_path} "
                        "est absent du dépôt GitHub."
                    )

                update_files.append(
                    relative_path
                )

            # -------------------------------------------------
            # SUPPRESSION DES DOUBLONS
            # -------------------------------------------------

            update_files = list(
                dict.fromkeys(update_files)
            )

            if not update_files:

                raise RuntimeError(
                    "Aucun fichier à mettre à jour trouvé."
                )

            # =================================================
            # AFFICHAGE
            # =================================================

            print()

            ui.print_info(
                f"{len(update_files)} fichier(s) "
                "à mettre à jour."
            )

            print()

            for relative_path in update_files:

                if relative_path.suffix == ".py":

                    label = "Python"

                elif relative_path == Path("version.json"):

                    label = "Version"

                elif relative_path == Path("update.json"):

                    label = "Nouveautés"

                elif relative_path.parts and relative_path.parts[0] == "web":

                    label = {
                        ".html": "HTML",
                        ".css": "CSS",
                        ".js": "JavaScript",
                    }.get(
                        relative_path.suffix.lower(),
                        "Web",
                    )

                else:

                    label = "Fichier"

                print(
                    f"  • {relative_path} ({label})"
                )

            print()

            # =================================================
            # SAUVEGARDE DES FICHIERS ACTUELS
            # =================================================

            backup_dir = (
                temp_dir / "backup"
            )

            backup_dir.mkdir()

            existing_files = []

            for relative_path in update_files:

                destination = (
                    BASE_DIR / relative_path
                )

                if destination.exists():

                    backup_path = (
                        backup_dir / relative_path
                    )

                    backup_path.parent.mkdir(
                        parents=True,
                        exist_ok=True
                    )

                    shutil.copy2(
                        destination,
                        backup_path
                    )

                    existing_files.append(
                        relative_path
                    )

            # =================================================
            # INSTALLATION DES FICHIERS
            # =================================================

            try:

                for relative_path in update_files:

                    source = (
                        source_dir / relative_path
                    )

                    destination = (
                        BASE_DIR / relative_path
                    )

                    destination.parent.mkdir(
                        parents=True,
                        exist_ok=True
                    )

                    shutil.copy2(
                        source,
                        destination
                    )

            except Exception:

                # ---------------------------------------------
                # RESTAURATION EN CAS D'ERREUR
                # ---------------------------------------------

                ui.print_error(
                    "Erreur pendant la mise à jour."
                )

                for relative_path in existing_files:

                    backup_path = (
                        backup_dir / relative_path
                    )

                    destination = (
                        BASE_DIR / relative_path
                    )

                    if backup_path.exists():

                        destination.parent.mkdir(
                            parents=True,
                            exist_ok=True
                        )

                        shutil.copy2(
                            backup_path,
                            destination
                        )

                raise

            # =================================================
            # VÉRIFICATION DE VERSION
            # =================================================

            installed_version = get_current_version()

            if version_to_tuple(installed_version) != version_to_tuple(version):

                ui.print_warn(
                    "Attention : la version installée "
                    "ne correspond pas à la version téléchargée."
                )

                print(
                    f"Version attendue : {version}"
                )

                print(
                    f"Version installée : {installed_version}"
                )

            # =================================================
            # FIN
            # =================================================

            print()

            ui.print_ok(
                f"Programme mis à jour vers la version {version}."
            )

            print()

            ui.print_info(
                "Fichiers Python mis à jour."
            )

            ui.print_info(
                "Fichiers HTML/CSS/JS de l'interface web mis à jour."
            )

            ui.print_info(
                "version.json mis à jour."
            )

            ui.print_info(
                "update.json mis à jour."
            )

            print()

            ui.print_info(
                "Vos autres fichiers JSON, configurations "
                "et conversations ont été conservés."
            )

            print()

            ui.print_info(
                "Redémarrez le programme pour appliquer "
                "complètement la mise à jour."
            )

            pause()

    except urllib.error.URLError as error:

        ui.print_error(
            f"Erreur réseau : {error}"
        )

        pause()

    except zipfile.BadZipFile:

        ui.print_error(
            "L'archive téléchargée est invalide."
        )

        pause()

    except Exception as error:

        ui.print_error(
            f"La mise à jour a échoué : {error}"
        )

        pause()


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
    import urllib.request
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

        request = urllib.request.Request(
            REMOTE_ZIP_URL,
            headers={"User-Agent": "Local-IA-Force-Updater"},
        )

        with urllib.request.urlopen(request, timeout=120) as response:
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
            )
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

def get_model_description(model_name):
    for category_models in AVAILABLE_MODELS.values():
        for model in category_models:
            if model.get("name") == model_name:
                return model.get("description", "")

    return ""


# ============================================================
# 3 - INSTALLER UN MODELE
# ============================================================

def install_model():
    """
    Menu spécialisé d'installation des modèles.
    """

    installed = scan_models()

    installed_names = {
        model["name"]
        for model in installed
    }

    while True:

        categories = list(AVAILABLE_MODELS.keys())

        options = [
            (str(number), category)
            for number, category in enumerate(categories, start=1)
        ]
        options.append(("0", "Retour"))

        ui.full_menu(
            "INSTALLER UN MODÈLE",
            options,
            footer="Choisissez une catégorie",
        )

        choice = ui.prompt("Votre choix : ").strip()

        if not choice.isdigit():
            ui.print_error("Choix invalide.")
            pause()
            continue

        category_number = int(choice)

        if category_number == 0:
            return

        if (
            category_number < 1
            or category_number > len(categories)
        ):
            ui.print_error("Choix invalide.")
            pause()
            continue

        category = categories[category_number - 1]

        models = [
            model
            for model in AVAILABLE_MODELS[category]
            if model["name"] not in installed_names
        ]

        # ----------------------------------------------------
        # Tous les modèles de cette catégorie sont déjà
        # installés.
        # ----------------------------------------------------

        if not models:

            print()
            ui.print_info(
                "Tous les modèles de cette catégorie sont déjà installés."
            )

            pause()
            continue

        # ----------------------------------------------------
        # MENU DES MODELES
        # ----------------------------------------------------

        while True:

            model_options = [
                (
                    str(number),
                    f"{model['name']}  ({model['size']}) — {model['description']}",
                )
                for number, model in enumerate(models, start=1)
            ]
            model_options.append(("0", "Retour"))

            ui.full_menu(
                category.upper(),
                model_options,
                footer="Choisissez un modèle à installer",
            )

            model_choice = ui.prompt("Votre choix : ").strip()

            if not model_choice.isdigit():

                ui.print_error("Choix invalide.")

                pause()
                continue

            model_number = int(model_choice)

            if model_number == 0:
                break

            if (
                model_number < 1
                or model_number > len(models)
            ):

                ui.print_error("Choix invalide.")

                pause()
                continue

            selected = models[model_number - 1]

            # ------------------------------------------------
            # CONFIRMATION
            # ------------------------------------------------

            ui.section_title("INSTALLATION")

            print(
                ui.colorize("Modèle : ", ui.C.SUBTITLE)
                + ui.colorize(selected["name"], ui.C.OK)
            )

            print(
                ui.colorize(f"Taille : {selected['size']}", ui.C.WHITE)
            )

            print()

            print(
                ui.colorize(selected["description"], ui.C.SUBTITLE)
            )

            print()

            confirmation = ui.prompt(
                "Installer ce modèle ? (o/N) : "
            ).strip().lower()

            if confirmation != "o":

                ui.print_warn("Installation annulée.")

                pause()
                continue

            # ------------------------------------------------
            # INSTALLATION OLLAMA
            # ------------------------------------------------

            ollama = get_ollama()

            if ollama is None:

                print(
                    "\n[ERREUR] Ollama introuvable."
                )

                pause()
                return

            print()
            ui.print_info(f"Installation de {selected['name']}...")
            print()

            try:

                result = subprocess.run(
                    [
                        ollama,
                        "pull",
                        selected["name"]
                    ]
                )

            except KeyboardInterrupt:

                ui.print_info("Installation interrompue.")

                pause()
                continue

            except OSError as error:

                ui.print_error(str(error))

                pause()
                continue

            if result.returncode != 0:

                ui.print_error("L'installation a échoué.")

                pause()
                continue

            print()
            ui.print_ok(f"{selected['name']} est installé.")

            # ------------------------------------------------
            # RESCAN
            # ------------------------------------------------

            installed = scan_models()

            installed_names = {
                model["name"]
                for model in installed
            }

            pause()

            # Retour au menu des catégories
            break

# ============================================================
# 4 - DESINSTALLER UN MODELE
# ============================================================

def uninstall_model():
    """
    Effectue un scan puis permet de supprimer
    un modèle installé.
    """
    ui.clear_screen()

    installed = scan_models()

    print()

    if not installed:

        ui.section_title("MODÈLES INSTALLÉS", clear=False)
        ui.print_warn("Aucun modèle installé.")

        return

    options = []

    for number, model in enumerate(installed, start=1):

        description = get_model_description(model["name"])
        label = f"{model['name']}  ({model['size']})"

        if description:
            label += f" — {description}"

        options.append((str(number), label))

    options.append(("0", "Annuler"))

    ui.full_menu(
        "MODÈLES INSTALLÉS",
        options,
        footer="Choisissez un modèle à désinstaller",
    )

    choice = ui.prompt("Votre choix : ").strip()

    if not choice.isdigit():

        ui.print_error("Choix invalide.")
        return

    number = int(choice)

    if number == 0:
        return

    if number < 1 or number > len(installed):

        ui.print_error("Choix invalide.")
        return

    selected = installed[number - 1]

    model_name = selected["name"]

    ui.section_title("DÉSINSTALLATION")
    print(
        ui.colorize("Modèle : ", ui.C.SUBTITLE)
        + ui.colorize(model_name, ui.C.ERROR)
    )
    print(ui.colorize(f"Taille : {selected['size']}", ui.C.WHITE))
    print()

    confirmation = ui.prompt(
        "Confirmer la désinstallation ? (o/N) : "
    ).strip().lower()

    if confirmation != "o":

        ui.print_warn("Désinstallation annulée.")
        return

    ollama = get_ollama()

    if ollama is None:

        ui.print_error("Ollama est introuvable.")

        return

    print()
    ui.print_info(f"Désinstallation de {model_name}...")

    try:

        result = subprocess.run(
            [ollama, "rm", model_name]
        )

    except KeyboardInterrupt:

        ui.print_info("Désinstallation interrompue.")

        return

    except OSError as error:

        ui.print_error(str(error))

        return

    if result.returncode != 0:

        ui.print_error("La désinstallation a échoué.")

        return

    print()
    ui.print_ok(f"{model_name} désinstallé.")

    # Rescan après désinstallation
    scan_models()


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



def ollama_server_url():
    """Retourne l'URL de l'API Ollama configurée."""
    config = load_config()
    value = config.get("ollama", {}) if isinstance(config, dict) else {}
    if isinstance(value, dict):
        url = value.get("url") or "http://127.0.0.1:11434"
    else:
        url = "http://127.0.0.1:11434"

    url = str(url).rstrip("/")
    if url.endswith("/api"):
        url = url[:-4]
    return url


def ollama_is_running():
    """Vérifie que le serveur Ollama répond à /api/tags."""
    try:
        request = Request(
            ollama_server_url() + "/api/tags",
            method="GET",
        )
        with urlopen(request, timeout=2) as response:
            return response.status == 200
    except (URLError, HTTPError, OSError, TimeoutError):
        return False


def wait_for_ollama(timeout=30):
    """Attend qu'Ollama soit disponible."""
    deadline = time.monotonic() + timeout

    while time.monotonic() < deadline:
        if ollama_is_running():
            return True
        time.sleep(0.5)

    return False


def start_ollama_for_server():
    """
    Prépare Ollama avant de lancer server.py.

    - Vérifie que l'exécutable Ollama existe.
    - Ne relance pas Ollama s'il est déjà actif.
    - Sinon démarre `ollama serve` en arrière-plan.
    - Attend que l'API soit réellement disponible.
    - Vérifie le modèle configuré et le télécharge s'il manque.
    """
    ollama = get_ollama()

    if ollama is None:
        ui.print_error("Ollama est introuvable dans le PATH.")
        return False

    print()
    ui.section_title("PRÉPARATION DE L'IA", clear=False)

    if ollama_is_running():
        ui.print_ok("Serveur Ollama déjà actif.")
    else:
        ui.print_info("Démarrage du serveur Ollama...")

        try:
            kwargs = {
                "cwd": str(BASE_DIR),
                "stdin": subprocess.DEVNULL,
                "stdout": subprocess.DEVNULL,
                "stderr": subprocess.DEVNULL,
            }

            if os.name == "nt" or sys.platform.startswith("win"):
                kwargs["creationflags"] = getattr(
                    subprocess, "CREATE_NO_WINDOW", 0
                )
            else:
                kwargs["start_new_session"] = True

            subprocess.Popen(
                [ollama, "serve"],
                **kwargs,
            )
        except OSError as error:
            ui.print_error(f"Impossible de démarrer Ollama : {error}")
            return False

        if not wait_for_ollama(30):
            ui.print_error(
                "Ollama a été lancé mais son API ne répond pas "
                "après 30 secondes."
            )
            return False

        ui.print_ok("Serveur Ollama prêt.")

    # Le projet accepte à la fois l'ancien format {"model": "..."}
    # et le nouveau format {"ollama": {"model": "..."}}.
    config = load_config()
    model = ""

    nested = config.get("ollama", {})
    if isinstance(nested, dict):
        model = str(nested.get("model") or "").strip()

    if not model:
        model = str(config.get("model") or "").strip()

    if not model:
        ui.print_error(
            "Aucun modèle n'est configuré dans config.json."
        )
        ui.print_info(
            "Lancez d'abord l'IA locale (option 1) pour sélectionner un modèle."
        )
        return False

    # Vérifie que le modèle est installé.
    try:
        request = Request(
            ollama_server_url() + "/api/tags",
            method="GET",
        )
        with urlopen(request, timeout=5) as response:
            data = json.loads(response.read().decode("utf-8"))

        installed = {
            str(item.get("name", "")).strip()
            for item in data.get("models", [])
            if item.get("name")
        }
    except Exception as error:
        ui.print_error(f"Impossible de vérifier les modèles Ollama : {error}")
        return False

    if model not in installed:
        ui.print_warn(
            f"Le modèle '{model}' n'est pas installé. Téléchargement..."
        )

        try:
            result = subprocess.run(
                [ollama, "pull", model],
                cwd=str(BASE_DIR),
                check=False,
            )
        except OSError as error:
            ui.print_error(f"Impossible de lancer `ollama pull` : {error}")
            return False

        if result.returncode != 0:
            ui.print_error(
                f"Le téléchargement du modèle '{model}' a échoué."
            )
            return False

        ui.print_ok(f"Modèle '{model}' prêt.")
    else:
        ui.print_ok(f"Modèle '{model}' déjà installé.")

    return True


def launch_server():
    """
    Prépare toute la pile IA puis lance server.py dans la même console.

    Ollama est démarré (si nécessaire) et le modèle configuré est vérifié/
    téléchargé avant de démarrer le serveur web. Le serveur prend ensuite
    la main dans cette même fenêtre jusqu'à son arrêt avec Ctrl+C.
    """
    ui.clear_screen()
    server_file = BASE_DIR / "server.py"

    if not server_file.exists():
        ui.print_error("server.py est introuvable.")
        pause()
        return

    ui.section_title("SERVEUR WEB", clear=False)
    print(
        ui.colorize(
            "Le serveur sera lancé dans cette même console après la préparation d'Ollama.",
            ui.C.INFO,
        )
    )
    print()

    while True:
        raw_port = ui.prompt("Port HTTP (8080 par défaut) : ").strip()

        if not raw_port:
            port = 8080
            break

        if not raw_port.isdigit():
            ui.print_error("Le port doit être un nombre.")
            continue

        port = int(raw_port)

        if not 1 <= port <= 65535:
            ui.print_error("Le port doit être compris entre 1 et 65535.")
            continue

        break

    # IMPORTANT : Ollama et le modèle sont préparés AVANT de lancer le serveur.
    if not start_ollama_for_server():
        pause()
        return

    print()
    ui.print_ok("Ollama et le modèle sont prêts.")
    ui.print_info(f"Démarrage du serveur sur le port {port}...")
    print()

    env = os.environ.copy()
    env["LOCAL_IA_MAIN_PID"] = str(os.getpid())
    env["LOCAL_IA_SERVER_PORT"] = str(port)

    try:
        # Aucun nouveau terminal / aucune nouvelle console :
        # server.py s'exécute directement dans la console actuelle.
        result = subprocess.run(
            [sys.executable, str(server_file), str(port)],
            cwd=str(BASE_DIR),
            env=env,
            check=False,
        )

        if result.returncode != 0:
            ui.print_error(
                f"Le serveur s'est arrêté avec le code {result.returncode}."
            )
        else:
            ui.print_info("Serveur arrêté.")

    except KeyboardInterrupt:
        print("\n")
        ui.print_info("Arrêt du serveur demandé.")
    except OSError as error:
        ui.print_error(f"Impossible de lancer le serveur : {error}")

    pause()


# ============================================================
# MENU PRINCIPAL
# ============================================================
def get_version():
    version_file = Path(__file__).parent / "version.json"

    try:
        with open(version_file, "r", encoding="utf-8") as file:
            data = json.load(file)

        return data.get("version", "Inconnue")

    except (FileNotFoundError, json.JSONDecodeError):
        return "Inconnue"

def menu():

    while True:
        version = get_version()

        ui.full_menu(
            f"OLLAMA LOCAL AI - v{version}",
            [
                ("1", "Lancer l'IA locale"),
                ("2", "Lister les modèles"),
                ("3", "Installer un modèle"),
                ("4", "Désinstaller un modèle"),
                ("5", "Modifier la configuration de l'IA"),
                ("6", "Lancer sur le serveur"),
                ("7", "Mettre à jour le programme"),
                ("8", "Voir les nouveautés"),
                ("0", "Quitter"),
            ],
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

        elif choice == "2":

            list_models()
            pause()

        elif choice == "3":

            install_model()

        elif choice == "4":

            uninstall_model()
            pause()

        elif choice == "5":

            edit_ai_config()

        elif choice == "6":

            launch_server()

        elif choice == "7":

            update_program()

        elif choice == "8":

            show_updates()

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
    """Affiche les commandes disponibles de LOCAL_IA."""
    print()
    print("=" * 72)
    print("LOCAL_IA - COMMANDES DISPONIBLES")
    print("=" * 72)
    print()
    print("COMMANDES PRINCIPALES")
    print("  python main.py")
    print("      Lance LOCAL_IA et affiche le menu principal.")
    print()
    print("  python main.py help")
    print("      Affiche cette aide et la liste des commandes disponibles.")
    print()
    print("  python main.py -h")
    print("  python main.py --help")
    print("      Affiche également cette aide.")
    print()
    print("  python main.py force_update")
    print("      Force une réinstallation complète depuis GitHub.")
    print("      Tout est remplacé sauf :")
    print("        - _chats/")
    print("        - _config.json")
    print("        - _list.json")
    print("        - _context.json")
    print()
    print("SCRIPTS UTILITAIRES")
    print("  python setup.py")
    print("      Installe LOCAL_IA sur l'ordinateur.")
    print()
    print("  python uninstall.py")
    print("      Désinstalle LOCAL_IA. Le script permet de choisir")
    print("      séparément la suppression de LOCAL_IA, des modèles")
    print("      Ollama et d'Ollama lui-même.")
    print()
    print("  python config.py")
    print("      Permet de modifier la configuration de l'IA.")
    print()
    print("  python ollama_test.py")
    print("      Vérifie l'installation et l'accessibilité d'Ollama.")
    print()
    print("MENU LOCAL_IA")
    print("  Une fois 'python main.py' lancé, le menu permet notamment de :")
    print("    1 - Lancer l'IA locale")
    print("    2 - Lister les modèles")
    print("    3 - Installer un modèle")
    print("    4 - Désinstaller un modèle")
    print("    5 - Modifier la configuration de l'IA")
    print("    6 - Lancer le serveur")
    print("    7 - Mettre à jour le programme")
    print("    8 - Voir les nouveautés")
    print("    0 - Quitter")
    print()
    print("=" * 72)
    print()


# ============================================================
# PROGRAMME PRINCIPAL
# ============================================================

def main():

    # Commandes en ligne de commande. Elles sont traitées avant
    # le menu et avant toute vérification Ollama.
    if len(sys.argv) > 1:
        command = sys.argv[1].strip().lower()

        if command in {"help", "-h", "--help"}:
            show_help()
            return 0

        if command == "force_update":
            return force_update()

    ui.section_title("OLLAMA LOCAL AI")

    select_runtime_provider()

    if resolve_runtime_provider() == "local":
        if not check_ollama():
            pause()
            sys.exit(1)

        # Scan automatique au démarrage uniquement en mode local
        scan_models()

    menu()


if __name__ == "__main__":
    result = main()
    if isinstance(result, int):
        sys.exit(result)
