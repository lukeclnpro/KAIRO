"""Catalogue et opérations de découverte des modèles Ollama."""

from __future__ import annotations

import json
import re
import unicodedata
from datetime import datetime
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
MODEL_CATALOG_PATH = Path(__file__).with_name("model_catalog.json")
MODEL_CATALOG_VERSION = 1
REQUEST_NEED_TERMS = {
    "code": ("code", "coder", "programm", "python", "javascript", "typescript", "bug", "script", "html", "sql", "api", "refactor", "compile"),
    "reasoning": ("raisonn", "analyse", "analys", "compare", "compar", "pourquoi", "preuve", "logique", "architecture", "strategie", "stratégie", "planifie", "complexe"),
    "math": ("math", "calcul", "equation", "équation", "probabil", "statistique", "integrale", "intégrale", "derivee", "dérivée"),
    "vision": ("image", "photo", "capture", "screenshot", "vision", "document scanne", "document scanné", "graphique"),
    "translation": ("tradui", "traduction", "translate", "translation", "langue"),
    "embeddings": ("embedding", "embeddings", "rag", "recherche semantique", "recherche sémantique"),
    "agents": ("agent", "plusieurs etapes", "plusieurs étapes", "workflow", "automatis", "outils"),
}
COMPLEX_REQUEST_TERMS = (
    "complet", "complexe", "en profondeur", "etape par etape", "étape par étape",
    "plusieurs fichiers", "refactor", "architecture", "benchmark", "preuve",
)


def get_model_description(model_name):
    for category_models in AVAILABLE_MODELS.values():
        for model in category_models:
            if model.get("name") == model_name:
                return model.get("description", "")
    return ""


def recommended_chat_models():
    """Return unique curated chat models; embedding-only models cannot answer chats."""
    recommended = {}
    for category, entries in AVAILABLE_MODELS.items():
        if category == "RAG / Embeddings":
            continue
        for entry in entries:
            name = str(entry.get("name", "")).strip()
            if name and name not in recommended:
                recommended[name] = {**entry, "category": category}
    return sorted(recommended.values(), key=lambda entry: entry["name"].casefold())


def classify_model(model, provider="ollama"):
    """Return estimated use cases and resource tier for a model catalog entry."""
    entry = model if isinstance(model, dict) else {"name": str(model or "")}
    name = str(entry.get("id") or entry.get("name") or "").strip()
    lowered = f"{name} {entry.get('name', '')} {entry.get('description', '')}".casefold()
    details = entry.get("details", {}) if isinstance(entry.get("details"), dict) else {}
    needs = set()
    category_needs = {
        "Généraliste": "general",
        "Programmation": "code",
        "Raisonnement": "reasoning",
        "Mathématiques": "math",
        "Vision / Images": "vision",
        "Traduction / Multilingue": "translation",
        "RAG / Embeddings": "embeddings",
        "Sciences / Technique": "technical",
        "Agents": "agents",
    }
    for category, entries in AVAILABLE_MODELS.items():
        if any(str(item.get("name", "")).casefold() == name.casefold() for item in entries):
            needs.add(category_needs[category])

    if any(term in lowered for term in ("code", "coding", "codestral", "starcoder", "devstral", "programming")):
        needs.add("code")
    if any(term in lowered for term in ("reason", "thinking", "deepseek-r1", "qwq", "reasoner")) or re.search(
        r"(?:^|[/._:-])o[134](?:$|[/._:-])", lowered
    ):
        needs.add("reasoning")
    if any(term in lowered for term in ("math", "calculator", "arithmetic")):
        needs.add("math")
    architecture = entry.get("architecture", {}) if isinstance(entry.get("architecture"), dict) else {}
    modalities = architecture.get("input_modalities", [])
    if "image" in modalities or any(term in lowered for term in ("vision", "llava", "pixtral", "moondream", "-vl")):
        needs.add("vision")
    if any(term in lowered for term in ("translate", "translation", "multilingual", "nllb")):
        needs.add("translation")
    if "embed" in lowered or "embedding" in lowered:
        needs.add("embeddings")
    if "agent" in lowered or "tool-use" in lowered:
        needs.add("agents")
    try:
        context_length = int(entry.get("context_length", 0))
    except (TypeError, ValueError):
        context_length = 0
    if context_length >= 100_000:
        needs.add("long_context")
    if not needs:
        needs.add("general")

    size_text = str(details.get("parameter_size", ""))
    if not size_text:
        size_match = re.search(r"(\d+(?:\.\d+)?)\s*([bm])(?:\b|$)", lowered)
        size_text = f"{size_match.group(1)}{size_match.group(2)}" if size_match else ""
    size_match = re.search(r"(\d+(?:\.\d+)?)\s*([bm])", size_text, re.I)
    parameter_billions = None
    if size_match:
        parameter_billions = float(size_match.group(1))
        if size_match.group(2).casefold() == "m":
            parameter_billions /= 1000

    footprint = ""
    if str(provider).casefold() == "ollama":
        raw_size = entry.get("size")
        if isinstance(raw_size, (int, float)) and raw_size > 0:
            size_gib = raw_size / (1024 ** 3)
            footprint = f"~{size_gib:.1f} Go disque"
        if parameter_billions is not None:
            power = "light" if parameter_billions <= 4 else "medium" if parameter_billions <= 16 else "heavy"
        elif footprint:
            size_gib = raw_size / (1024 ** 3)
            power = "light" if size_gib <= 4.5 else "medium" if size_gib <= 18 else "heavy"
        else:
            power = "unknown"
    else:
        if parameter_billions is not None:
            power = "light" if parameter_billions <= 4 else "medium" if parameter_billions <= 16 else "heavy"
        elif any(term in lowered for term in ("nano", "mini", "flash", "haiku", "small", "lite", "instant")):
            power = "light"
        elif any(term in lowered for term in ("opus", "pro", "max", "large", "reasoner", "70b", "72b", "405b")):
            power = "heavy"
        else:
            power = "medium"

    return {"name": name, "needs": tuple(sorted(needs)), "power": power, "footprint": footprint}


def classify_request_needs(message):
    text = unicodedata.normalize("NFKD", str(message or "").casefold())
    text = "".join(char for char in text if not unicodedata.combining(char))
    needs = {
        need
        for need, terms in REQUEST_NEED_TERMS.items()
        if any(term in text for term in terms)
    }
    return needs or {"general"}


def select_openrouter_model(message, models=None, configured_model=""):
    """Select one available cloud model for a request without an extra LLM call."""
    candidates = models if models is not None else get_provider_models(
        "openrouter", chat_only=True, available_only=True
    )
    desired_needs = classify_request_needs(message)
    text = unicodedata.normalize("NFKD", str(message or "").casefold())
    text = "".join(char for char in text if not unicodedata.combining(char))
    complex_request = (
        len(text) >= 450
        or any(term in text for term in COMPLEX_REQUEST_TERMS)
        or ({"code", "reasoning", "math"} & desired_needs and len(text.split()) >= 24)
    )
    specialized_request = bool(desired_needs - {"general"})
    target_power = "heavy" if complex_request else "medium" if specialized_request or len(text.split()) >= 12 else "light"
    power_order = {"light": 0, "medium": 1, "heavy": 2, "unknown": 1}
    best = None

    for model in candidates:
        if not isinstance(model, dict) or not model.get("chat_compatible", True):
            continue
        model_id = str(model.get("id") or model.get("name") or "").strip()
        if not model_id:
            continue
        attributes = model.get("attributes", {})
        attributes = attributes if isinstance(attributes, dict) else {}
        model_needs = set(attributes.get("needs", ("general",)))
        matched_needs = desired_needs & model_needs
        need_score = 5.0 * len(matched_needs)
        if "general" in model_needs:
            need_score += 1.0
        if "general" in desired_needs and "general" not in model_needs:
            need_score -= 1.0
        power = str(attributes.get("power", "unknown"))
        distance = abs(power_order.get(power, 1) - power_order[target_power])
        power_score = 2.0 - distance * 1.5
        if complex_request and power == "light":
            power_score -= 2.0
        if not complex_request and power == "heavy":
            power_score -= 1.0
        try:
            context_length = int(model.get("context_length", 0))
        except (TypeError, ValueError):
            context_length = 0
        context_score = min(context_length / 1_000_000, 1.0) if len(text) >= 2_000 else 0.0

        pricing = model.get("pricing", {})
        try:
            price = float(pricing.get("prompt", -1)) + float(pricing.get("completion", -1))
        except (TypeError, ValueError, AttributeError):
            price = -1
        cost_score = max(0.0, 1.0 - price / 0.00004) if price >= 0 else -0.5
        configured_bonus = 0.2 if model_id == configured_model else 0.0
        score = need_score + power_score + context_score + cost_score + configured_bonus
        rank = (score, -price if price >= 0 else float("-inf"), model_id == configured_model, model_id)
        if best is None or rank > best[0]:
            best = (rank, model_id)

    return best[1] if best else str(configured_model or "").strip()


def _seed_model_catalog():
    providers = {"ollama": {}, "openrouter": {}}
    category_names = {
        "Généraliste": "general",
        "Programmation": "code",
        "Raisonnement": "reasoning",
        "Mathématiques": "math",
        "Vision / Images": "vision",
        "Traduction / Multilingue": "translation",
        "RAG / Embeddings": "embeddings",
        "Sciences / Technique": "technical",
        "Agents": "agents",
    }
    for category, entries in AVAILABLE_MODELS.items():
        for entry in entries:
            model_id = str(entry.get("name", "")).strip()
            if not model_id:
                continue
            record = providers["ollama"].setdefault(model_id, {
                "id": model_id,
                "name": model_id,
                "provider": "ollama",
                "installed": False,
                "chat_compatible": category != "RAG / Embeddings",
                "description": entry.get("description", ""),
                "recommended_size": entry.get("size", ""),
                "categories": [],
            })
            need = category_names[category]
            if need not in record["categories"]:
                record["categories"].append(need)
            if category != "RAG / Embeddings":
                record["chat_compatible"] = True
            if not record.get("description") and entry.get("description"):
                record["description"] = entry["description"]
            if not record.get("recommended_size") and entry.get("size"):
                record["recommended_size"] = entry["size"]

    for record in providers["ollama"].values():
        profile = classify_model(record, provider="ollama")
        record["attributes"] = {
            "needs": list(profile["needs"]),
            "power": profile["power"],
            "footprint": profile["footprint"],
            "power_source": "catalogue",
        }
    return {
        "version": MODEL_CATALOG_VERSION,
        "providers": providers,
    }


def load_model_catalog(path=None):
    target = Path(path) if path is not None else MODEL_CATALOG_PATH
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        payload = _seed_model_catalog()
    if not isinstance(payload, dict) or not isinstance(payload.get("providers"), dict):
        payload = _seed_model_catalog()
    payload.setdefault("version", MODEL_CATALOG_VERSION)
    for provider in ("ollama", "openrouter"):
        entries = payload["providers"].get(provider)
        if not isinstance(entries, dict):
            payload["providers"][provider] = {}
    return payload


def save_model_catalog(catalog, path=None):
    target = Path(path) if path is not None else MODEL_CATALOG_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(catalog, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def get_provider_models(provider, path=None, *, chat_only=False, available_only=False):
    target = Path(path) if path is not None else MODEL_CATALOG_PATH
    catalog = load_model_catalog(path)
    entries = catalog["providers"].get(provider, {})
    models = [model for model in entries.values() if isinstance(model, dict)] if isinstance(entries, dict) else []
    if not target.exists():
        save_model_catalog(catalog, target)
    if chat_only:
        models = [model for model in models if model.get("chat_compatible", True)]
    if available_only:
        models = [model for model in models if model.get("available", False)]
    return sorted(models, key=lambda model: str(model.get("name") or model.get("id", "")).casefold())


def merge_provider_models(provider, models, path=None, *, replace_snapshot=False):
    if provider not in {"ollama", "openrouter"}:
        raise ValueError(f"Fournisseur de modèles inconnu : {provider}")
    catalog = load_model_catalog(path)
    entries = catalog["providers"].setdefault(provider, {})
    if replace_snapshot:
        for existing in entries.values():
            if isinstance(existing, dict):
                existing["available"] = False
                if provider == "ollama":
                    existing["installed"] = False
    for raw_model in models:
        if not isinstance(raw_model, dict):
            continue
        model_id = str(raw_model.get("id") or raw_model.get("name") or "").strip()
        if not model_id:
            continue
        record = dict(entries.get(model_id, {}))
        record.update(raw_model)
        record["id"] = model_id
        record["name"] = str(record.get("name") or model_id)
        record["provider"] = provider
        record["available"] = bool(raw_model.get("available", True))
        needs = set(record.get("categories", []))
        profile = classify_model(record, provider=provider)
        needs.update(profile["needs"])
        record["categories"] = sorted(needs)
        record["attributes"] = {
            "needs": sorted(needs),
            "power": profile["power"],
            "footprint": profile["footprint"] or str(record.get("recommended_size", "")),
            "power_source": "ollama_metadata" if provider == "ollama" and profile["power"] != "unknown" else "estimated",
        }
        architecture = record.get("architecture", {})
        modality = str(architecture.get("modality", "")).casefold() if isinstance(architecture, dict) else ""
        input_modalities = architecture.get("input_modalities", []) if isinstance(architecture, dict) else []
        embedding_only = "embedding" in modality and "text" not in input_modalities
        record["chat_compatible"] = not embedding_only and "embeddings" not in needs
        if provider == "ollama":
            record["installed"] = bool(raw_model.get("installed", record.get("installed", True)))
        entries[model_id] = record
    catalog["updated_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
    save_model_catalog(catalog, path)
    return catalog


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