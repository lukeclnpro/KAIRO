"""Exemples de fonctions utilitaires pour les chaînes de caractères."""

from __future__ import annotations

import re
import unicodedata


def normalize_whitespace(value: str) -> str:
    """Réduit toute suite d'espaces à un espace simple."""
    return " ".join(str(value).split())


def slugify(value: str, separator: str = "-") -> str:
    """Crée un identifiant ASCII lisible à partir d'un titre."""
    normalized = unicodedata.normalize("NFKD", str(value)).encode("ascii", "ignore").decode()
    words = re.findall(r"[a-z0-9]+", normalized.casefold())
    return separator.join(words)


def truncate(value: str, max_length: int, suffix: str = "…") -> str:
    """Tronque un texte sans dépasser max_length, suffixe compris."""
    text = str(value)
    if max_length < 0:
        raise ValueError("max_length doit être positif ou nul.")
    if len(text) <= max_length:
        return text
    if max_length <= len(suffix):
        return suffix[:max_length]
    return text[: max_length - len(suffix)].rstrip() + suffix


def extract_words(value: str) -> list[str]:
    """Extrait les mots Unicode d'un texte, dans leur ordre d'apparition."""
    return re.findall(r"[^\W_]+", str(value), flags=re.UNICODE)


def mask_email(value: str) -> str:
    """Masque une adresse e-mail en conservant quelques caractères visibles."""
    email = str(value).strip()
    local, separator, domain = email.partition("@")
    if not separator or not local or not domain:
        raise ValueError("Adresse e-mail invalide.")
    visible = local[:1]
    return f"{visible}{'*' * max(2, len(local) - 1)}@{domain}"
