"""Exemples pour parser des dates et afficher des durées."""

from __future__ import annotations

from datetime import date, datetime, timezone


def parse_iso_date(value: str) -> date:
    """Parse une date ISO au format AAAA-MM-JJ."""
    return date.fromisoformat(str(value).strip())


def days_between(start: date, end: date) -> int:
    """Retourne le nombre de jours entre deux dates (valeur absolue)."""
    return abs((end - start).days)


def format_duration(seconds: int | float) -> str:
    """Formate une durée en secondes en heures, minutes et secondes."""
    remaining = max(0, int(seconds))
    hours, remaining = divmod(remaining, 3600)
    minutes, seconds = divmod(remaining, 60)
    parts = []
    if hours:
        parts.append(f"{hours} h")
    if minutes:
        parts.append(f"{minutes} min")
    if seconds or not parts:
        parts.append(f"{seconds} s")
    return " ".join(parts)


def utc_now_iso() -> str:
    """Retourne l'heure UTC actuelle au format ISO 8601."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
