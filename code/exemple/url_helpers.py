"""Exemples de construction et de lecture d'URL."""

from __future__ import annotations

from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit


def add_query_params(url: str, params: dict[str, object]) -> str:
    """Ajoute des paramètres à une URL en conservant ceux déjà présents."""
    parts = urlsplit(url)
    query = parse_qs(parts.query, keep_blank_values=True)
    for key, value in params.items():
        query[str(key)] = [str(value)]
    encoded = urlencode(query, doseq=True)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, encoded, parts.fragment))


def get_query_param(url: str, name: str, default: str | None = None) -> str | None:
    """Retourne la première valeur d'un paramètre d'URL."""
    values = parse_qs(urlsplit(url).query, keep_blank_values=True).get(name)
    return values[0] if values else default


def normalize_http_url(url: str) -> str:
    """Ajoute HTTPS si le protocole manque et refuse les autres schémas."""
    value = str(url).strip()
    if not value:
        raise ValueError("URL vide.")
    if value.startswith("//"):
        value = "https:" + value
    elif "://" not in value:
        value = "https://" + value
    parts = urlsplit(value)
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        raise ValueError("Une URL HTTP(S) valide est requise.")
    return value