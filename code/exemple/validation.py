"""Exemples de validations simples sans dépendance externe."""

from __future__ import annotations

import re
from urllib.parse import urlsplit


def clamp(value: float, minimum: float, maximum: float) -> float:
    """Limite une valeur à l'intervalle [minimum, maximum]."""
    if minimum > maximum:
        raise ValueError("minimum ne peut pas dépasser maximum.")
    return max(minimum, min(value, maximum))


def is_valid_email(value: str) -> bool:
    """Vérifie une forme d'e-mail courante; ne remplace pas une confirmation."""
    email = str(value).strip()
    return bool(re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email))


def is_http_url(value: str) -> bool:
    """Accepte uniquement une URL HTTP(S) avec un hôte."""
    try:
        parsed = urlsplit(str(value).strip())
        return parsed.scheme in {"http", "https"} and bool(parsed.hostname)
    except ValueError:
        return False


def is_strong_password(value: str, minimum_length: int = 12) -> bool:
    """Exige la longueur minimale, une lettre et un chiffre."""
    password = str(value)
    return (
        len(password) >= minimum_length
        and any(character.isalpha() for character in password)
        and any(character.isdigit() for character in password)
    )


def parse_integer(value: str, minimum: int | None = None, maximum: int | None = None) -> int:
    """Convertit un entier et vérifie ses bornes éventuelles."""
    number = int(str(value).strip())
    if minimum is not None and number < minimum:
        raise ValueError(f"La valeur doit être au moins {minimum}.")
    if maximum is not None and number > maximum:
        raise ValueError(f"La valeur doit être au plus {maximum}.")
    return number
