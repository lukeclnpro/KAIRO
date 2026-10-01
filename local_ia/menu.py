"""Construction des options du menu principal."""


def get_main_menu_options(provider):
    options = [("1", "Lancer l'IA locale")]
    if provider == "openrouter":
        options.extend([
            ("2", "Modifier la clé API OpenRouter"),
            ("3", "Voir l'utilisation de la clé API"),
        ])
    else:
        options.extend([
            ("2", "Lister les modèles"),
            ("3", "Installer un modèle"),
            ("4", "Désinstaller un modèle"),
        ])
    options.extend([
        ("5", "Modifier la configuration de l'IA"),
        ("6", "Lancer sur le serveur"),
        ("7", "Mettre à jour le programme"),
        ("8", "Voir les nouveautés"),
        ("9", "Ouvrir les projets de code"),
        ("10", "Gérer les comptes locaux"),
        ("0", "Quitter"),
    ])
    return options


def show_help():
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
    print("  python main.py gui")
    print("      Ouvre la console graphique liée aux mêmes menus et données que le terminal.")
    print()
    print('  iahelp "message de la demande"')
    print("      Envoie une demande à l'IA avec l'historique des commandes iahelp précédentes.")
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