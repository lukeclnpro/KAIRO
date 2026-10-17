
"""Traduction de texte via le client OpenRouter configuré dans KAIRO."""


def traduire(texte, langue_cible, langue_source="auto"):
    """Traduit un texte en conservant son sens et sa mise en forme."""
    from local_ia.llm.ollama import ask_openrouter

    if not texte.strip():
        return "Erreur : le texte à traduire est vide."
    if not str(langue_cible or "").strip():
        return "Erreur : la langue cible est obligatoire."

    try:
        return ask_openrouter([
            {
                "role": "system",
                "content": (
                    "Tu es un traducteur professionnel. Traduis fidèlement le texte, "
                    "conserve son sens, son ton et sa mise en forme. Retourne uniquement "
                    "la traduction, sans explication. Langue source : "
                    f"{langue_source or 'auto'}. Langue cible : {langue_cible.strip()}."
                ),
            },
            {"role": "user", "content": str(texte)},
        ], max_tokens=4096).strip()
    except Exception as error:
        return f"Erreur de traduction : {error}"


# ==============================
# INTERFACE TERMINAL
# ==============================

def main():
    print("=" * 45)
    print("       TRADUCTEUR IA - OPENROUTER")
    print("=" * 45)
    print("Tape 'quitter' pour fermer le programme.\n")

    langue_source = input(
        "Langue source (auto par défaut) : "
    ).strip() or "auto"

    langue_cible = input(
        "Langue cible (ex. français, anglais, japonais) : "
    ).strip()

    if not langue_cible:
        print("Erreur : tu dois indiquer une langue cible.")
        return

    while True:
        print("\n" + "-" * 45)
        texte = input("Texte à traduire : ")

        if texte.strip().lower() == "quitter":
            print("Au revoir !")
            break

        if not texte.strip():
            print("Saisis un texte avant de lancer la traduction.")
            continue

        resultat = traduire(
            texte=texte,
            langue_cible=langue_cible,
            langue_source=langue_source
        )

        print("\n--- TRADUCTION ---\n")
        print(resultat)
        print("\n------------------")


if __name__ == "__main__":
    main()
