"""Theme presets, persistence format, and stylesheet overrides for KAIRO."""

from __future__ import annotations

import json
import re
from copy import deepcopy


COLOR_FIELDS = (
    "window",
    "surface",
    "text",
    "accent",
    "button_background",
    "button_text",
    "primary_text",
    "border",
    "button_hover",
    "hover_text",
)
BUTTON_STYLES = {"rounded": 9, "square": 2, "pill": 18}

BUILTIN_THEMES = (
    {
        "id": "forest",
        "name": "Forêt",
        "base": "dark",
        "window": "#111714",
        "surface": "#171f1b",
        "text": "#e7eee9",
        "accent": "#b9e9c6",
        "button_background": "#222d26",
        "button_text": "#e1e9e3",
        "primary_text": "#102016",
        "border": "#344138",
        "button_hover": "#2d3c31",
        "hover_text": "#f5fff7",
        "button_style": "rounded",
        "wallpaper": "",
    },
    {
        "id": "paper",
        "name": "Papier",
        "base": "light",
        "window": "#f1f4ef",
        "surface": "#fbfcf9",
        "text": "#25352c",
        "accent": "#4e8b5d",
        "button_background": "#e7eee7",
        "button_text": "#294334",
        "primary_text": "#173722",
        "border": "#cbd8cd",
        "button_hover": "#dceade",
        "hover_text": "#1e492d",
        "button_style": "rounded",
        "wallpaper": "",
    },
    {
        "id": "ocean",
        "name": "Océan",
        "base": "dark",
        "window": "#111a20",
        "surface": "#1a272e",
        "text": "#e5f0f2",
        "accent": "#83d5ca",
        "button_background": "#253940",
        "button_text": "#e5f0f2",
        "primary_text": "#102422",
        "border": "#3b5058",
        "button_hover": "#31535a",
        "hover_text": "#f4ffff",
        "button_style": "square",
        "wallpaper": "",
    },
    {
        "id": "ember",
        "name": "Ambre",
        "base": "dark",
        "window": "#1c1715",
        "surface": "#29211e",
        "text": "#f2e9e3",
        "accent": "#f1b77d",
        "button_background": "#392d27",
        "button_text": "#fff4e8",
        "primary_text": "#23160e",
        "border": "#544138",
        "button_hover": "#49382d",
        "hover_text": "#fff4e8",
        "button_style": "pill",
        "wallpaper": "",
    },
)

_BUILTINS = {theme["id"]: theme for theme in BUILTIN_THEMES}
_COLOR_PATTERN = re.compile(r"^#[0-9a-fA-F]{6}$")


def _normalize_profile(candidate, fallback=None):
    if not isinstance(candidate, dict):
        return None
    theme_id = str(candidate.get("id", "")).strip()
    if theme_id not in _BUILTINS and not theme_id.startswith("custom-"):
        return None

    profile = deepcopy(fallback or _BUILTINS.get(theme_id) or BUILTIN_THEMES[0])
    profile["id"] = theme_id
    name = str(candidate.get("name", profile["name"])).strip()
    profile["name"] = name[:40] or profile["name"]
    profile["base"] = candidate.get("base", profile["base"])
    if profile["base"] not in {"dark", "light"}:
        profile["base"] = fallback.get("base", "dark") if fallback else "dark"

    for field in COLOR_FIELDS:
        if isinstance(profile.get(field), str) and _COLOR_PATTERN.fullmatch(profile[field]):
            profile[field] = profile[field].upper()
        value = candidate.get(field, profile[field])
        if isinstance(value, str) and _COLOR_PATTERN.fullmatch(value):
            profile[field] = value.upper()

    button_style = candidate.get("button_style", profile["button_style"])
    if button_style in BUTTON_STYLES:
        profile["button_style"] = button_style
    wallpaper = candidate.get("wallpaper", profile.get("wallpaper", ""))
    profile["wallpaper"] = wallpaper.strip() if isinstance(wallpaper, str) else ""
    return profile


def load_library(serialized=None):
    """Return built-in themes merged with valid saved overrides and custom themes."""
    profiles = {theme["id"]: _normalize_profile(theme) for theme in BUILTIN_THEMES}
    if isinstance(serialized, str):
        try:
            serialized = json.loads(serialized)
        except json.JSONDecodeError:
            serialized = None
    if not isinstance(serialized, list):
        return list(profiles.values())

    for candidate in serialized:
        if not isinstance(candidate, dict):
            continue
        theme_id = str(candidate.get("id", ""))
        existing = profiles.get(theme_id)
        if existing is None and not theme_id.startswith("custom-"):
            continue
        normalized = _normalize_profile(candidate, existing)
        if normalized:
            profiles[theme_id] = normalized
    return list(profiles.values())


def serialize_library(profiles):
    valid = []
    seen = set()
    for candidate in profiles:
        profile = _normalize_profile(candidate)
        if profile and profile["id"] not in seen:
            valid.append(profile)
            seen.add(profile["id"])
    return json.dumps(valid, ensure_ascii=False, separators=(",", ":"))


def create_custom_theme(name, source, identifier):
    source = _normalize_profile(source) or deepcopy(BUILTIN_THEMES[0])
    theme_id = f"custom-{identifier}"
    profile = deepcopy(source)
    profile.update({"id": theme_id, "name": str(name).strip()[:40] or "Mon thème"})
    return profile


def find_theme(profiles, theme_id):
    return next((theme for theme in profiles if theme.get("id") == theme_id), None)


def stylesheet_overrides(profile, wallpaper_url=""):
    profile = _normalize_profile(profile) or deepcopy(BUILTIN_THEMES[0])
    radius = BUTTON_STYLES[profile["button_style"]]
    rules = f"""
        QWidget {{ color: {profile['text']}; }}
        QWidget#root, QWidget#mainPanel {{ background-color: {profile['window']}; }}
        QWidget#sidebar, QWidget#conversationDrawer, QWidget#editorPanel {{ background-color: {profile['surface']}; }}
        QWidget#accountOverview, QWidget#authPanel {{ background-color: {profile['surface']}; }}
        QPushButton {{ color: {profile['button_text']}; background-color: {profile['button_background']}; border-color: {profile['border']}; border-radius: {radius}px; }}
        QPushButton:hover {{ color: {profile['hover_text']}; background-color: {profile['button_hover']}; border-color: {profile['accent']}; }}
        QPushButton:checked, QPushButton#sendButton, QPushButton#saveButton, QPushButton#authPrimaryButton {{ color: {profile['primary_text']}; background-color: {profile['accent']}; border-color: {profile['accent']}; border-radius: {radius}px; }}
        QComboBox, QLineEdit, QPlainTextEdit, QTextBrowser, QTableWidget {{ color: {profile['text']}; border-color: {profile['accent']}; }}
        QTabBar#toolNavigation {{ background-color: {profile['surface']}; border: 1px solid {profile['border']}; border-radius: {radius + 3}px; padding: 4px; }}
        QTabBar#toolNavigation::tab {{ color: {profile['button_text']}; background-color: {profile['button_background']}; border: 1px solid {profile['border']}; border-radius: {radius}px; padding: 9px 15px; margin: 1px 3px; min-width: 88px; min-height: 22px; font-weight: 600; }}
        QTabBar#toolNavigation::tab:hover {{ color: {profile['hover_text']}; background-color: {profile['button_hover']}; border-color: {profile['accent']}; }}
        QTabBar#toolNavigation::tab:selected {{ color: {profile['primary_text']}; background-color: {profile['accent']}; border-color: {profile['accent']}; font-weight: 800; }}
        QTabBar#toolNavigation::tab:disabled {{ color: {profile['text']}; background-color: transparent; border-color: transparent; }}
        QTabBar::tab:selected {{ color: {profile['primary_text']}; border-bottom-color: {profile['accent']}; }}
        QScrollBar::handle:vertical, QScrollBar::handle:horizontal {{ background-color: {profile['accent']}; }}
    """
    if wallpaper_url:
        rules += (
            f'QWidget#root, QWidget#mainPanel {{ background-image: url("{wallpaper_url}"); '
            "background-position: center; background-repeat: no-repeat; }"
        )
    return rules