#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Gestionnaire interactif de config.json.

Lancer :
    python config.py

Ce programme permet de créer/modifier config.json depuis l'invite de commandes.
"""

from pathlib import Path
import json
import subprocess
import sys
import os

import ui
from local_ia.core import accounts


BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "config.json"


DEFAULT_CONFIG = {
    "utilisateur": {
        "langue": "français",
        "nom": "",
    },
    "assistant": {
        "role": "assistant personnel local",
        "sujet": "assistant personnel généraliste",
        "ton": "naturel, clair et concis",
        "style": "conversationnel",
        "niveau_detail": "normal",
        "concis": True,
    },
    "regles": {
        "respecter_langue": True,
        "respecter_ton": True,
        "respecter_style": True,
        "respecter_role": True,
        "utiliser_historique": True,
        "utiliser_memoire": True,
        "ne_pas_inventer": True,
        "signaler_incertitude": True,
        "eviter_repetitions": True,
        "code_directement_utilisable": True,
        "adapter_au_sujet": True,
    },
    "instructions": [],
    "ollama": {
        "url": "http://localhost:11434",
        "model": "",
        "timeout": 120,
        "stream": False,
    },
    "openrouter": {
        "model": "openai/gpt-4o-mini",
        "base_url": "https://openrouter.ai/api/v1",
        "timeout": 120,
        "site_url": "",
        "app_name": "Local IA",
    },
    "conversation": {
        "max_history": 20,
        "max_conversations": 100,
        "message_demarrage": True,
        "detecter_sujet": True,
        "sujet_min_mots": 2,
        "sujet_max_mots": 6,
    },
    "memoire": {
        "active": True,
        "max_memories": 100,
        "detection_automatique": True,
        "sauvegarde_automatique": True,
    },
    "recherche": {
        "active": True,
        "moteur": "web",
        "max_resultats": 5,
        "timeout": 15,
        "user_agent": "IA-Agent",
    },
}


def charger_config():
    if not CONFIG_PATH.exists():
        sauvegarder_config(DEFAULT_CONFIG)
        return json.loads(json.dumps(DEFAULT_CONFIG))

    try:
        with CONFIG_PATH.open("r", encoding="utf-8") as f:
            config = json.load(f)
    except (json.JSONDecodeError, OSError):
        print("\n⚠ config.json est invalide. Une configuration par défaut sera utilisée.")
        config = json.loads(json.dumps(DEFAULT_CONFIG))

    fusionner_defauts(config, DEFAULT_CONFIG)
    return config


def fusionner_defauts(config, defaults):
    for cle, valeur in defaults.items():
        if cle not in config:
            config[cle] = json.loads(json.dumps(valeur))
        elif isinstance(valeur, dict) and isinstance(config[cle], dict):
            fusionner_defauts(config[cle], valeur)


def sauvegarder_config(config):
    with CONFIG_PATH.open("w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=4)


def pause():
    ui.pause()


def afficher_titre(titre):
    ui.section_title(titre)


def demander_texte(message, actuel=""):
    print(f"\nValeur actuelle : {actuel}")
    valeur = input(message).strip()
    return actuel if valeur == "" else valeur


def demander_entier(message, actuel):
    while True:
        valeur = input(f"\nValeur actuelle : {actuel}\n{message}").strip()
        if valeur == "":
            return actuel
        try:
            return int(valeur)
        except ValueError:
            print("⚠ Entrez un nombre entier valide.")


def demander_bool(message, actuel):
    valeur_actuelle = "oui" if actuel else "non"

    while True:
        valeur = input(
            f"\nValeur actuelle : {valeur_actuelle}\n"
            f"{message} (o/n) : "
        ).strip().lower()

        if valeur == "":
            return actuel
        if valeur in ("o", "oui", "y", "yes", "1"):
            return True
        if valeur in ("n", "non", "no", "0"):
            return False

        print("⚠ Répondez par o ou n.")


def modifier_utilisateur(config):
    afficher_titre("UTILISATEUR")

    print("1. Langue")
    print("2. Nom")
    print("0. Retour")

    choix = input("\nChoisissez un seul champ à modifier : ").strip()

    if choix == "1":
        print("\nLa langue détermine dans quelle langue l'IA répond à l'utilisateur.")
        config["utilisateur"]["langue"] = demander_texte(
            "Nouvelle langue : ",
            config["utilisateur"]["langue"],
        )
        sauvegarder_config(config)

    elif choix == "2":
        print("\nLe nom permet à l'IA de savoir comment appeler l'utilisateur.")
        config["utilisateur"]["nom"] = demander_texte(
            "Nouveau nom : ",
            config["utilisateur"]["nom"],
        )
        sauvegarder_config(config)


def modifier_assistant(config):
    afficher_titre("ASSISTANT")

    print("1. Rôle")
    print("2. Sujet général")
    print("3. Ton")
    print("4. Style")
    print("5. Niveau de détail")
    print("6. Réponses concises")
    print("0. Retour")

    choix = input("\nChoisissez un seul champ à modifier : ").strip()
    assistant = config["assistant"]

    if choix == "1":
        print("\nRôle : définit la fonction et le comportement général de l'IA.")
        assistant["role"] = demander_texte("Nouveau rôle : ", assistant["role"])

    elif choix == "2":
        print("\nSujet : définit le domaine général dans lequel l'IA doit se comporter.")
        assistant["sujet"] = demander_texte(
            "Nouveau sujet général : ",
            assistant["sujet"],
        )

    elif choix == "3":
        print("\nTon : définit la manière dont l'IA s'exprime (ex. naturel, professionnel, amical).")
        assistant["ton"] = demander_texte("Nouveau ton : ", assistant["ton"])

    elif choix == "4":
        print("\nStyle : définit la forme des réponses (ex. conversationnel, technique, pédagogique).")
        assistant["style"] = demander_texte("Nouveau style : ", assistant["style"])

    elif choix == "5":
        print("\nNiveau de détail : correspond au niveau d'expertise et de profondeur attendu dans les réponses.")
        print("Exemples : débutant, normal, avancé, expert.")
        assistant["niveau_detail"] = demander_texte(
            "Niveau de détail : ",
            assistant["niveau_detail"],
        )

    elif choix == "6":
        print("\nRéponses concises : indique si l'IA doit privilégier des réponses courtes et directes.")
        assistant["concis"] = demander_bool(
            "Réponses concises",
            assistant["concis"],
        )
    else:
        return

    sauvegarder_config(config)


def modifier_regles(config):
    afficher_titre("RÈGLES")

    regles = config["regles"]

    champs = [
        ("1", "respecter_langue", "Respecter la langue"),
        ("2", "respecter_ton", "Respecter le ton"),
        ("3", "respecter_style", "Respecter le style"),
        ("4", "respecter_role", "Respecter le rôle"),
        ("5", "utiliser_historique", "Utiliser l'historique"),
        ("6", "utiliser_memoire", "Utiliser la mémoire"),
        ("7", "ne_pas_inventer", "Ne pas inventer"),
        ("8", "signaler_incertitude", "Signaler les incertitudes"),
        ("9", "eviter_repetitions", "Éviter les répétitions"),
        ("10", "code_directement_utilisable", "Produire du code directement utilisable"),
        ("11", "adapter_au_sujet", "Adapter les réponses au sujet"),
    ]

    for numero, cle, nom in champs:
        print(f"{numero}. {nom}")

    choix = input("\nChoisissez un seul champ à modifier : ").strip()

    for numero, cle, nom in champs:
        if choix == numero:
            descriptions = {
                "respecter_langue": "Force l'IA à utiliser la langue configurée.",
                "respecter_ton": "Force l'IA à respecter le ton configuré.",
                "respecter_style": "Force l'IA à respecter le style configuré.",
                "respecter_role": "Force l'IA à respecter son rôle configuré.",
                "utiliser_historique": "Permet d'utiliser les messages précédents de la conversation.",
                "utiliser_memoire": "Permet d'utiliser les informations mémorisées.",
                "ne_pas_inventer": "Demande à l'IA de ne pas présenter des informations inventées comme des faits.",
                "signaler_incertitude": "Demande à l'IA d'indiquer lorsqu'elle n'est pas certaine.",
                "eviter_repetitions": "Demande à l'IA d'éviter les répétitions inutiles.",
                "code_directement_utilisable": "Demande du code prêt à être utilisé directement.",
                "adapter_au_sujet": "Demande à l'IA d'adapter ses réponses au sujet courant.",
            }
            print(f"\n{descriptions[cle]}")
            regles[cle] = demander_bool(nom, regles[cle])
            sauvegarder_config(config)
            return


def modifier_instructions(config):
    afficher_titre("INSTRUCTIONS PERSONNALISÉES")

    instructions = config["instructions"]

    print("\n1. Ajouter une instruction")
    print("2. Modifier une instruction")
    print("3. Supprimer une instruction")
    print("4. Remplacer toutes les instructions")
    print("0. Retour")

    choix = input("\nChoisissez une seule action : ").strip()

    if choix == "1":
        instruction = input("\nNouvelle instruction : ").strip()
        if instruction:
            instructions.append(instruction)
            sauvegarder_config(config)

    elif choix == "2":
        if not instructions:
            print("\nAucune instruction.")
            return

        for i, instruction in enumerate(instructions, 1):
            print(f"{i}. {instruction}")

        try:
            numero = int(input("\nNuméro à modifier : "))
            if 1 <= numero <= len(instructions):
                nouvelle = input("Nouvelle valeur : ").strip()
                if nouvelle:
                    instructions[numero - 1] = nouvelle
                    sauvegarder_config(config)
            else:
                print("⚠ Numéro invalide.")
        except ValueError:
            print("⚠ Numéro invalide.")

    elif choix == "3":
        if not instructions:
            print("\nAucune instruction.")
            return

        for i, instruction in enumerate(instructions, 1):
            print(f"{i}. {instruction}")

        try:
            numero = int(input("\nNuméro à supprimer : "))
            if 1 <= numero <= len(instructions):
                instructions.pop(numero - 1)
                sauvegarder_config(config)
            else:
                print("⚠ Numéro invalide.")
        except ValueError:
            print("⚠ Numéro invalide.")

    elif choix == "4":
        print("\nEntrez une instruction par ligne.")
        print("Laissez une ligne vide pour terminer.")

        nouvelles = []
        while True:
            ligne = input("> ").strip()
            if not ligne:
                break
            nouvelles.append(ligne)

        config["instructions"] = nouvelles
        sauvegarder_config(config)


def modifier_ollama(config):
    afficher_titre("OLLAMA")

    print("1. URL Ollama")
    print("2. Modèle")
    print("3. Timeout")
    print("4. Streaming")
    print("0. Retour")

    choix = input("\nChoisissez un seul champ à modifier : ").strip()
    ollama = config["ollama"]

    if choix == "1":
        print("\nURL : adresse du serveur Ollama utilisé par l'agent.")
        ollama["url"] = demander_texte("URL Ollama : ", ollama["url"])

    elif choix == "2":
        print("\nModèle : nom du modèle Ollama utilisé pour générer les réponses.")
        ollama["model"] = demander_texte("Modèle : ", ollama["model"])

    elif choix == "3":
        print("\nTimeout : durée maximale d'attente d'une réponse.")
        ollama["timeout"] = demander_entier("Nouveau timeout : ", ollama["timeout"])

    elif choix == "4":
        print("\nStreaming : affiche la réponse progressivement lorsqu'il est activé.")
        ollama["stream"] = demander_bool("Streaming", ollama["stream"])
    else:
        return

    sauvegarder_config(config)


def modifier_openrouter(config):
    afficher_titre("OPENROUTER")

    print("1. Gestion du compte local et de la clé API (depuis le menu principal)")
    print("2. Modèle")
    print("3. Base URL")
    print("4. Timeout")
    print("5. Site URL")
    print("6. Nom de l'application")
    print("0. Retour")

    choix = input("\nChoisissez un seul champ à modifier : ").strip()
    openrouter = config.setdefault("openrouter", {
        "model": "openai/gpt-4o-mini",
        "base_url": "https://openrouter.ai/api/v1",
        "timeout": 120,
        "site_url": "",
        "app_name": "Local IA",
    })
    openrouter.pop("api_key", None)

    if choix == "1":
        print("\nLa clé API est désormais gérée par un compte local et stockée chiffrée.")
        print("Connectez-vous depuis le menu principal pour créer ou utiliser un compte.")
        sauvegarder_config(config)
        return

    elif choix == "2":
        print("\nModèle OpenRouter : exemple openai/gpt-4o-mini, anthropic/claude-3.5-sonnet...")
        openrouter["model"] = demander_texte("Modèle OpenRouter : ", openrouter.get("model", "openai/gpt-4o-mini"))

    elif choix == "3":
        print("\nBase URL OpenRouter. Laissez la valeur par défaut pour l'API standard.")
        openrouter["base_url"] = demander_texte("Base URL OpenRouter : ", openrouter.get("base_url", "https://openrouter.ai/api/v1"))

    elif choix == "4":
        print("\nTimeout : durée maximale d'attente d'une réponse OpenRouter.")
        openrouter["timeout"] = demander_entier("Nouveau timeout : ", openrouter.get("timeout", 120))

    elif choix == "5":
        print("\nSite URL : URL du site qui appelle OpenRouter. Utile pour les metadonnées du provider.")
        openrouter["site_url"] = demander_texte("Site URL : ", openrouter.get("site_url", ""))

    elif choix == "6":
        print("\nNom de l'application : identifiant visible côté OpenRouter.")
        openrouter["app_name"] = demander_texte("Nom de l'application : ", openrouter.get("app_name", "Local IA"))
    else:
        return

    sauvegarder_config(config)


def modifier_conversation(config):
    afficher_titre("CONVERSATION")

    print("1. Nombre maximum de messages")
    print("2. Nombre maximum de conversations")
    print("3. Message de démarrage")
    print("4. Détection automatique du sujet")
    print("5. Nombre minimum de mots du sujet")
    print("6. Nombre maximum de mots du sujet")
    print("0. Retour")

    choix = input("\nChoisissez un seul champ à modifier : ").strip()
    conversation = config["conversation"]

    if choix == "1":
        print("\nHistorique : nombre de messages précédents envoyés au modèle.")
        conversation["max_history"] = demander_entier(
            "Nombre maximum de messages : ",
            conversation["max_history"],
        )

    elif choix == "2":
        print("\nDétermine combien de conversations peuvent être conservées.")
        conversation["max_conversations"] = demander_entier(
            "Nombre maximum de conversations : ",
            conversation["max_conversations"],
        )

    elif choix == "3":
        print("\nDétermine si le message de démarrage de l'agent est affiché.")
        conversation["message_demarrage"] = demander_bool(
            "Afficher le message de démarrage",
            conversation["message_demarrage"],
        )

    elif choix == "4":
        print("\nPermet de déterminer automatiquement le sujet d'une conversation.")
        conversation["detecter_sujet"] = demander_bool(
            "Détecter automatiquement le sujet",
            conversation["detecter_sujet"],
        )

    elif choix == "5":
        print("\nNombre minimum de mots autorisé pour le sujet détecté.")
        conversation["sujet_min_mots"] = demander_entier(
            "Nombre minimum de mots : ",
            conversation["sujet_min_mots"],
        )

    elif choix == "6":
        print("\nNombre maximum de mots autorisé pour le sujet détecté.")
        conversation["sujet_max_mots"] = demander_entier(
            "Nombre maximum de mots : ",
            conversation["sujet_max_mots"],
        )
    else:
        return

    sauvegarder_config(config)


def modifier_memoire(config):
    afficher_titre("MÉMOIRE")

    print("1. Activer la mémoire")
    print("2. Nombre maximum de mémoires")
    print("3. Détection automatique")
    print("4. Sauvegarde automatique")
    print("0. Retour")

    choix = input("\nChoisissez un seul champ à modifier : ").strip()
    memoire = config["memoire"]

    if choix == "1":
        print("\nDétermine si l'IA peut conserver des informations entre les conversations.")
        memoire["active"] = demander_bool("Activer la mémoire", memoire["active"])

    elif choix == "2":
        print("\nNombre maximum d'informations que l'IA peut conserver.")
        memoire["max_memories"] = demander_entier(
            "Nombre maximum de mémoires : ",
            memoire["max_memories"],
        )

    elif choix == "3":
        print("\nPermet de détecter automatiquement les informations à mémoriser.")
        memoire["detection_automatique"] = demander_bool(
            "Détection automatique",
            memoire["detection_automatique"],
        )

    elif choix == "4":
        print("\nEnregistre automatiquement les nouvelles mémoires.")
        memoire["sauvegarde_automatique"] = demander_bool(
            "Sauvegarde automatique",
            memoire["sauvegarde_automatique"],
        )
    else:
        return

    sauvegarder_config(config)


def modifier_recherche(config):
    afficher_titre("RECHERCHE")

    print("1. Activer la recherche")
    print("2. Moteur")
    print("3. Nombre maximum de résultats")
    print("4. Timeout")
    print("5. User-Agent")
    print("0. Retour")

    choix = input("\nChoisissez un seul champ à modifier : ").strip()
    recherche = config["recherche"]

    if choix == "1":
        print("\nDétermine si la fonction de recherche externe est activée.")
        recherche["active"] = demander_bool("Activer la recherche", recherche["active"])

    elif choix == "2":
        print("\nMoteur : service ou méthode utilisé pour effectuer la recherche.")
        recherche["moteur"] = demander_texte("Moteur de recherche : ", recherche["moteur"])

    elif choix == "3":
        print("\nDétermine le nombre de résultats retournés par recherche.")
        recherche["max_resultats"] = demander_entier(
            "Nombre maximum de résultats : ",
            recherche["max_resultats"],
        )

    elif choix == "4":
        print("\nTimeout : durée maximale d'attente de la recherche.")
        recherche["timeout"] = demander_entier(
            "Timeout de recherche : ",
            recherche["timeout"],
        )

    elif choix == "5":
        print("\nUser-Agent : identité envoyée au serveur lors de la recherche.")
        recherche["user_agent"] = demander_texte(
            "User-Agent : ",
            recherche["user_agent"],
        )
    else:
        return

    sauvegarder_config(config)

def afficher_resume(config):
    afficher_titre("CONFIGURATION ACTUELLE")

    print(f"Langue       : {config['utilisateur']['langue']}")
    print(f"Nom          : {config['utilisateur']['nom'] or '(non défini)'}")
    print(f"Rôle         : {config['assistant']['role']}")
    print(f"Sujet        : {config['assistant']['sujet']}")
    print(f"Ton          : {config['assistant']['ton']}")
    print(f"Style        : {config['assistant']['style']}")
    print(f"Modèle       : {config['ollama']['model'] or '(non défini)'}")
    print(f"URL Ollama   : {config['ollama']['url']}")
    print(f"Comptes API  : {len(accounts.list_accounts())} compte(s) local(aux)")
    print(f"Mémoire      : {'activée' if config['memoire']['active'] else 'désactivée'}")
    print(f"Recherche    : {'activée' if config['recherche']['active'] else 'désactivée'}")
    print(f"Instructions : {len(config['instructions'])}")


def reinitialiser(config):
    afficher_titre("RÉINITIALISATION")

    confirmation = input(
        "\nRéinitialiser toute la configuration ? (o/n) : "
    ).strip().lower()

    if confirmation in ("o", "oui", "y", "yes"):
        config.clear()
        config.update(json.loads(json.dumps(DEFAULT_CONFIG)))
        sauvegarder_config(config)
        print("\n✓ Configuration réinitialisée.")
    else:
        print("\nAnnulation.")


def retourner_main():
    """Ferme config.py et relance main.py."""
    main_path = BASE_DIR / "main.py"

    if not main_path.exists():
        print(f"\n⚠ main.py introuvable : {main_path}")
        input("Appuyez sur Entrée pour revenir...")
        return

    # Lorsque config.py est lancé depuis main.py, main.py est déjà
    # en attente : il suffit donc de fermer config.py.
    if os.environ.get("LOCAL_IA_CONFIG_FROM_MAIN") == "1":
        raise SystemExit

    print("\nRetour vers main.py...")
    subprocess.run([sys.executable, str(main_path)])
    raise SystemExit


def menu():
    config = charger_config()

    while True:
        ui.full_menu(
            "CONFIGURATION DE L'IA",
            [
                ("1", "Utilisateur"),
                ("2", "Assistant"),
                ("3", "Règles"),
                ("4", "Instructions personnalisées"),
                ("5", "Ollama"),
                ("6", "OpenRouter"),
                ("7", "Conversation"),
                ("8", "Mémoire"),
                ("9", "Recherche"),
                ("10", "Afficher la configuration"),
                ("11", "Réinitialiser la configuration"),
                ("12", "Sauvegarder"),
                ("0", "Retour vers main.py"),
            ],
            footer="Votre choix : ",
        )

        choix = ui.prompt("Votre choix : ").strip()

        if choix == "1":
            modifier_utilisateur(config)
            sauvegarder_config(config)

        elif choix == "2":
            modifier_assistant(config)
            sauvegarder_config(config)

        elif choix == "3":
            modifier_regles(config)
            sauvegarder_config(config)

        elif choix == "4":
            modifier_instructions(config)
            sauvegarder_config(config)

        elif choix == "5":
            modifier_ollama(config)
            sauvegarder_config(config)

        elif choix == "6":
            modifier_openrouter(config)
            sauvegarder_config(config)

        elif choix == "7":
            modifier_conversation(config)
            sauvegarder_config(config)

        elif choix == "8":
            modifier_memoire(config)
            sauvegarder_config(config)

        elif choix == "9":
            modifier_recherche(config)
            sauvegarder_config(config)

        elif choix == "10":
            afficher_resume(config)
            pause()

        elif choix == "11":
            reinitialiser(config)

        elif choix == "12":
            sauvegarder_config(config)
            print("\n✓ Configuration sauvegardée.")

        elif choix == "0":
            sauvegarder_config(config)
            retourner_main()

        else:
            print("\n⚠ Choix invalide.")


if __name__ == "__main__":
    menu()
