"""Catalogue et opérations de découverte des modèles Ollama."""

from __future__ import annotations

import json
from pathlib import Path

AVAILABLE_MODELS = {
    "Généraliste": [
        {"name": "qwen3:4b", "size": "~2.5 GB", "description": "Modèle compact polyvalent pour le dialogue, le raisonnement et les tâches générales."},
        {"name": "qwen3:8b", "size": "~5.2 GB", "description": "Modèle polyvalent pour dialogue, raisonnement, traduction et tâches générales."},
        {"name": "llama3.2:3b", "size": "~2.0 GB", "description": "Petit modèle généraliste conçu pour fonctionner avec peu de ressources."},
        {"name": "mistral:7b", "size": "~4.1 GB", "description": "Modèle généraliste adapté au dialogue, à la rédaction et aux tâches quotidiennes."},
        {"name": "gemma3:4b", "size": "~3.3 GB", "description": "Modèle compact de Google adapté aux tâches générales et à la vision."},
    ],
    "Programmation": [
        {"name": "qwen2.5-coder:7b", "size": "~4.7 GB", "description": "Génération, correction, compréhension et explication de code."},
        {"name": "qwen2.5-coder:14b", "size": "~9 GB", "description": "Version plus puissante pour les projets logiciels complexes."},
        {"name": "qwen3-coder:30b", "size": "~19 GB", "description": "Programmation avancée et agents capables de travailler sur des projets logiciels."},
        {"name": "deepseek-coder:6.7b", "size": "~4 GB", "description": "Génération et compréhension de nombreux langages de programmation."},
        {"name": "codegemma:7b", "size": "~5 GB", "description": "Génération de code et autocomplétion."},
        {"name": "codellama:7b", "size": "~4 GB", "description": "Modèle Meta spécialisé dans le code."},
    ],
    "Raisonnement": [
        {"name": "deepseek-r1:7b", "size": "~4.7 GB", "description": "Raisonnement logique, résolution de problèmes et analyse."},
        {"name": "deepseek-r1:14b", "size": "~9 GB", "description": "Version plus importante pour les problèmes de raisonnement complexes."},
        {"name": "qwen3:14b", "size": "~9 GB", "description": "Raisonnement, logique, analyse et résolution de problèmes."},
        {"name": "qwq:32b", "size": "~20 GB", "description": "Modèle orienté raisonnement approfondi."},
    ],
    "Mathématiques": [
        {"name": "qwen2-math:1.5b", "size": "~1 GB", "description": "Résolution de problèmes mathématiques avec faible consommation."},
        {"name": "qwen2-math:7b", "size": "~4.4 GB", "description": "Modèle spécialisé dans les problèmes et raisonnements mathématiques."},
    ],
    "Vision / Images": [
        {"name": "gemma3:4b", "size": "~3.3 GB", "description": "Compréhension de texte et analyse d'images."},
        {"name": "llama3.2-vision:11b", "size": "~7.9 GB", "description": "Analyse d'images et compréhension visuelle."},
        {"name": "qwen2.5vl:7b", "size": "~6 GB", "description": "Vision-langage et analyse de documents visuels."},
        {"name": "llava:7b", "size": "~4.7 GB", "description": "Compréhension d'images et questions-réponses visuelles."},
    ],
    "Traduction / Multilingue": [
        {"name": "translategemma:4b", "size": "~3 GB", "description": "Modèle spécialisé dans la traduction multilingue."},
        {"name": "qwen3:8b", "size": "~5.2 GB", "description": "Modèle multilingue adapté à la traduction et à la compréhension de nombreuses langues."},
    ],
    "RAG / Embeddings": [
        {"name": "nomic-embed-text", "size": "~0.3 GB", "description": "Embeddings pour recherche sémantique et systèmes RAG."},
        {"name": "mxbai-embed-large", "size": "~0.7 GB", "description": "Embeddings pour recherche sémantique et bases vectorielles."},
        {"name": "qwen3-embedding:0.6b", "size": "~0.6 GB", "description": "Embeddings Qwen pour recherche sémantique et RAG."},
        {"name": "embeddinggemma:300m", "size": "~0.3 GB", "description": "Modèle d'embeddings extrêmement compact."},
    ],
    "Sciences / Technique": [
        {"name": "granite3.3:8b", "size": "~5 GB", "description": "Raisonnement, analyse et tâches techniques."},
        {"name": "phi3:mini", "size": "~2.2 GB", "description": "Petit modèle Microsoft pour les tâches techniques et analytiques."},
    ],
    "Agents": [
        {"name": "qwen3:8b", "size": "~5.2 GB", "description": "Adapté aux agents utilisant des outils et exécutant des tâches en plusieurs étapes."},
        {"name": "qwen3-coder:30b", "size": "~19 GB", "description": "Agent développeur pour exploration et modification de projets."},
        {"name": "granite4.1:8b", "size": "~5 GB", "description": "Modèle orienté agents, RAG, outils et sorties JSON structurées."},
    ],
}


def get_model_description(model_name):
    for category_models in AVAILABLE_MODELS.values():
        for model in category_models:
            if model.get("name") == model_name:
                return model.get("description", "")
    return ""


def save_model_list(models, list_file):
    try:
        with Path(list_file).open("w", encoding="utf-8") as output:
            json.dump({"models": models}, output, indent=4, ensure_ascii=False)
        return True
    except OSError as error:
        print(f"[ERREUR] Impossible d'écrire {list_file}: {error}")
        return False


def scan_models(ollama_executable, run_command, save_models, print_output=print):
    if ollama_executable is None:
        return []
    try:
        result = run_command(
            [ollama_executable, "list"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except OSError as error:
        print_output(f"[ERREUR] Impossible d'exécuter Ollama : {error}")
        return []

    if result.returncode != 0:
        print_output("[ERREUR] Impossible de récupérer la liste des modèles.")
        if result.stderr:
            print_output(result.stderr.strip())
        return []

    lines = result.stdout.splitlines()
    if len(lines) <= 1:
        save_models([])
        return []

    models = []
    for line in lines[1:]:
        parts = line.strip().split()
        if not parts:
            continue
        models.append({
            "name": parts[0],
            "id": parts[1] if len(parts) > 1 else "",
            "size": parts[2] if len(parts) > 2 else "",
            "modified": " ".join(parts[3:]),
        })

    unique_models = []
    seen = set()
    for model in models:
        if model["name"] not in seen:
            seen.add(model["name"])
            unique_models.append(model)

    save_models(unique_models)
    return unique_models


def install_model(ui_module, scan_models_callback, get_ollama_callback, run_command, pause):
    installed = scan_models_callback()
    installed_names = {model["name"] for model in installed}

    while True:
        categories = list(AVAILABLE_MODELS)
        options = [(str(number), category) for number, category in enumerate(categories, start=1)]
        options.append(("0", "Retour"))
        ui_module.full_menu(
            "INSTALLER UN MODÈLE",
            options,
            footer="Choisissez une catégorie",
        )

        choice = ui_module.prompt("Votre choix : ").strip()
        if not choice.isdigit():
            ui_module.print_error("Choix invalide.")
            pause()
            continue

        category_number = int(choice)
        if category_number == 0:
            return
        if category_number < 1 or category_number > len(categories):
            ui_module.print_error("Choix invalide.")
            pause()
            continue

        category = categories[category_number - 1]
        models = [
            model for model in AVAILABLE_MODELS[category]
            if model["name"] not in installed_names
        ]
        if not models:
            print()
            ui_module.print_info("Tous les modèles de cette catégorie sont déjà installés.")
            pause()
            continue

        while True:
            model_options = [
                (str(number), f"{model['name']}  ({model['size']}) — {model['description']}")
                for number, model in enumerate(models, start=1)
            ]
            model_options.append(("0", "Retour"))
            ui_module.full_menu(
                category.upper(),
                model_options,
                footer="Choisissez un modèle à installer",
            )
            model_choice = ui_module.prompt("Votre choix : ").strip()
            if not model_choice.isdigit():
                ui_module.print_error("Choix invalide.")
                pause()
                continue

            model_number = int(model_choice)
            if model_number == 0:
                break
            if model_number < 1 or model_number > len(models):
                ui_module.print_error("Choix invalide.")
                pause()
                continue

            selected = models[model_number - 1]
            ui_module.section_title("INSTALLATION")
            print(
                ui_module.colorize("Modèle : ", ui_module.C.SUBTITLE)
                + ui_module.colorize(selected["name"], ui_module.C.OK)
            )
            print(ui_module.colorize(f"Taille : {selected['size']}", ui_module.C.WHITE))
            print()
            print(ui_module.colorize(selected["description"], ui_module.C.SUBTITLE))
            print()
            confirmation = ui_module.prompt("Installer ce modèle ? (o/N) : ").strip().lower()
            if confirmation != "o":
                ui_module.print_warn("Installation annulée.")
                pause()
                continue

            ollama_executable = get_ollama_callback()
            if ollama_executable is None:
                print("\n[ERREUR] Ollama introuvable.")
                pause()
                return

            print()
            ui_module.print_info(f"Installation de {selected['name']}...")
            print()
            try:
                result = run_command([ollama_executable, "pull", selected["name"]])
            except KeyboardInterrupt:
                ui_module.print_info("Installation interrompue.")
                pause()
                continue
            except OSError as error:
                ui_module.print_error(str(error))
                pause()
                continue

            if result.returncode != 0:
                ui_module.print_error("L'installation a échoué.")
                pause()
                continue

            print()
            ui_module.print_ok(f"{selected['name']} est installé.")
            installed = scan_models_callback()
            installed_names = {model["name"] for model in installed}
            pause()
            break


def uninstall_model(
    ui_module,
    scan_models_callback,
    get_ollama_callback,
    run_command,
    get_description=get_model_description,
):
    ui_module.clear_screen()
    installed = scan_models_callback()
    print()
    if not installed:
        ui_module.section_title("MODÈLES INSTALLÉS", clear=False)
        ui_module.print_warn("Aucun modèle installé.")
        return

    options = []
    for number, model in enumerate(installed, start=1):
        description = get_description(model["name"])
        label = f"{model['name']}  ({model['size']})"
        if description:
            label += f" — {description}"
        options.append((str(number), label))
    options.append(("0", "Annuler"))
    ui_module.full_menu(
        "MODÈLES INSTALLÉS",
        options,
        footer="Choisissez un modèle à désinstaller",
    )

    choice = ui_module.prompt("Votre choix : ").strip()
    if not choice.isdigit():
        ui_module.print_error("Choix invalide.")
        return
    number = int(choice)
    if number == 0:
        return
    if number < 1 or number > len(installed):
        ui_module.print_error("Choix invalide.")
        return

    selected = installed[number - 1]
    model_name = selected["name"]
    ui_module.section_title("DÉSINSTALLATION")
    print(
        ui_module.colorize("Modèle : ", ui_module.C.SUBTITLE)
        + ui_module.colorize(model_name, ui_module.C.ERROR)
    )
    print(ui_module.colorize(f"Taille : {selected['size']}", ui_module.C.WHITE))
    print()
    confirmation = ui_module.prompt("Confirmer la désinstallation ? (o/N) : ").strip().lower()
    if confirmation != "o":
        ui_module.print_warn("Désinstallation annulée.")
        return

    ollama_executable = get_ollama_callback()
    if ollama_executable is None:
        ui_module.print_error("Ollama est introuvable.")
        return

    print()
    ui_module.print_info(f"Désinstallation de {model_name}...")
    try:
        result = run_command([ollama_executable, "rm", model_name])
    except KeyboardInterrupt:
        ui_module.print_info("Désinstallation interrompue.")
        return
    except OSError as error:
        ui_module.print_error(str(error))
        return

    if result.returncode != 0:
        ui_module.print_error("La désinstallation a échoué.")
        return

    print()
    ui_module.print_ok(f"{model_name} désinstallé.")
    scan_models_callback()