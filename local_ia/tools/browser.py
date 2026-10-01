"""Ouverture de pages HTTP(S) dans le navigateur par défaut."""

from __future__ import annotations

import webbrowser
from urllib.parse import urlsplit


def open_page(url):
    value = str(url or "").strip().strip("<>\"'").rstrip(".,;:!?")
    if not value:
        raise ValueError("Une adresse Web est requise.")

    if value.startswith("//"):
        value = "https:" + value
    elif "://" not in value:
        value = "https://" + value

    parsed = urlsplit(value)
    if parsed.scheme.lower() not in {"http", "https"}:
        raise ValueError("Seules les adresses HTTP et HTTPS peuvent être ouvertes.")
    if not parsed.hostname or any(character.isspace() for character in parsed.hostname):
        raise ValueError("Adresse Web invalide.")
    if parsed.username or parsed.password:
        raise ValueError("Les adresses avec identifiants intégrés ne sont pas autorisées.")
    try:
        parsed.port
    except ValueError as error:
        raise ValueError("Port invalide dans l'adresse Web.") from error

    opened = webbrowser.open(value, new=2, autoraise=True)
    return {
        "url": value,
        "opened": bool(opened),
        "error": "" if opened else "Le navigateur n'a pas confirmé l'ouverture de la page.",
    }