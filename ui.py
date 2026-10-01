#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Module d'interface partagé.

Fournit :
    - les couleurs ANSI utilisées par main.py, local_ia et config.py
    - les menus "plein écran" (largeur ET hauteur du terminal)
    - des utilitaires d'affichage (horodatage, séparateurs, messages
      colorés OK / ERREUR / ATTENTION / INFO)
"""

import platform
import shutil
import subprocess
import sys
from datetime import datetime


PRODUCT_NAME = "KAIRO"
PRODUCT_TAGLINE = "IA locale, esprit libre"

# Active les couleurs ANSI sous l'invite de commandes Windows
# (sans effet et sans erreur sous Linux/macOS).
try:
    import colorama
    colorama.just_fix_windows_console()
except Exception:
    pass


# ============================================================
# COULEURS ANSI
# ============================================================

class C:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"

    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"
    WHITE = "\033[37m"
    GRAY = "\033[90m"

    BRIGHT_RED = "\033[91m"
    BRIGHT_GREEN = "\033[92m"
    BRIGHT_YELLOW = "\033[93m"
    BRIGHT_BLUE = "\033[94m"
    BRIGHT_MAGENTA = "\033[95m"
    BRIGHT_CYAN = "\033[96m"
    BRIGHT_WHITE = "\033[97m"

    # Rôles sémantiques utilisés dans tout le projet
    BORDER = BRIGHT_BLUE
    TITLE = BOLD + BRIGHT_CYAN
    SUBTITLE = DIM + WHITE
    OPTION = BRIGHT_WHITE
    OPTION_KEY = BOLD + BRIGHT_MAGENTA
    FOOTER = DIM + BRIGHT_YELLOW

    USER = BOLD + BRIGHT_GREEN
    IA = BOLD + BRIGHT_MAGENTA
    TIME = GRAY
    PERF = CYAN
    PERF_LABEL = DIM + CYAN

    OK = BRIGHT_GREEN
    ERROR = BOLD + BRIGHT_RED
    WARN = BRIGHT_YELLOW
    INFO = BRIGHT_CYAN


def colorize(text, color):
    return f"{color}{text}{C.RESET}"


# ============================================================
# TERMINAL
# ============================================================

def term_size():
    """Retourne (colonnes, lignes) du terminal, avec repli si inconnu."""
    size = shutil.get_terminal_size(fallback=(100, 30))
    return max(size.columns, 60), max(size.lines, 20)


def clear_screen():
    """Efface complètement l'écran avant chaque nouvel écran interactif.

    On utilise à la fois la séquence ANSI (rapide et multiplateforme) et
    ``cls`` sous Windows pour éviter que les anciens contenus du terminal
    restent visibles. Le curseur est replacé en haut à gauche.
    """
    try:
        # ED 2 efface l'écran visible ; ED 3 efface le scrollback sur les
        # terminaux qui le supportent.
        sys.stdout.write("\033[2J\033[3J\033[H")
        sys.stdout.flush()
    except Exception:
        pass

    if platform.system() == "Windows":
        try:
            subprocess.run(
                "cls",
                shell=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception:
            pass


def new_screen(title=None):
    """Démarre un nouvel écran : aucun contenu de l'écran précédent ne reste."""
    clear_screen()
    if title:
        section_title(title, clear=False)


# ============================================================
# HORODATAGE
# ============================================================

def format_timestamp(value=None, with_date=True):
    """
    Formate une date/heure pour l'affichage.

    'value' peut être une chaîne ISO (chat JSON) ou None
    (utilise alors l'heure actuelle).
    """

    if value is None:
        dt = datetime.now()
    else:
        try:
            dt = datetime.fromisoformat(value)
        except (TypeError, ValueError):
            return str(value)

    if with_date:
        return dt.strftime("%d/%m/%Y %H:%M:%S")

    return dt.strftime("%H:%M:%S")


# ============================================================
# SEPARATEURS / TEXTE
# ============================================================

def hr(char="─", color=C.BORDER):
    width, _ = term_size()
    return colorize(char * width, color)


def wrap_text(text, width):
    """Découpe le texte en lignes qui tiennent dans 'width', en
    respectant les retours à la ligne existants."""

    result = []

    for paragraph in text.split("\n"):

        if paragraph == "":
            result.append("")
            continue

        words = paragraph.split(" ")
        current = ""

        for word in words:

            candidate = (current + " " + word).strip()

            if len(candidate) > width and current:
                result.append(current)
                current = word
            else:
                current = candidate

        if current:
            result.append(current)

    return result


# ============================================================
# MENU PLEIN ECRAN
# ============================================================

def full_menu(title, options, subtitle=None, footer=None, clear=True):
    """
    Affiche un menu qui occupe toute la fenêtre du terminal
    (largeur ET hauteur).

    options : liste de tuples (touche, libellé)
    """

    if clear:
        clear_screen()

    width, height = term_size()
    inner = width - 2

    lines = []

    lines.append(colorize("╔" + "═" * inner + "╗", C.BORDER))

    title_text = f" {title} ".center(inner)
    lines.append(
        colorize("║", C.BORDER)
        + colorize(title_text, C.TITLE)
        + colorize("║", C.BORDER)
    )

    if subtitle:
        for sub_line in wrap_text(subtitle, inner - 4):
            sub_text = f"  {sub_line}".ljust(inner)
            lines.append(
                colorize("║", C.BORDER)
                + colorize(sub_text, C.SUBTITLE)
                + colorize("║", C.BORDER)
            )

    lines.append(colorize("╠" + "═" * inner + "╣", C.BORDER))

    blank_row = (
        colorize("║", C.BORDER) + " " * inner + colorize("║", C.BORDER)
    )
    lines.append(blank_row)

    for key, label in options:

        key_text = f"  {key}."
        entry = f"{key_text} {label}"
        entry = entry.ljust(inner)

        row = (
            colorize("║", C.BORDER)
            + colorize(key_text, C.OPTION_KEY)
            + colorize(entry[len(key_text):], C.OPTION)
            + colorize("║", C.BORDER)
        )

        lines.append(row)

    lines.append(blank_row)
    lines.append(colorize("╠" + "═" * inner + "╣", C.BORDER))

    footer_text = footer or "Entrez le numéro de votre choix, puis Entrée"
    footer_line = f"  {footer_text}".ljust(inner)
    lines.append(
        colorize("║", C.BORDER)
        + colorize(footer_line, C.FOOTER)
        + colorize("║", C.BORDER)
    )

    lines.append(colorize("╚" + "═" * inner + "╝", C.BORDER))

    # Remplissage vertical pour occuper toute la hauteur du terminal.
    content_height = len(lines) + 2
    padding = max(0, height - content_height)
    top_pad = padding // 2

    print("\n" * top_pad, end="")

    for line in lines:
        print(line)

    print()


def section_title(title, clear=True):
    """Bandeau de titre pleine largeur, pour les écrans qui ne sont
    pas des menus à choix multiples (listes, confirmations, etc.)."""

    if clear:
        clear_screen()

    width, _ = term_size()

    print(colorize("═" * width, C.BORDER))
    print(colorize(f" {title}".center(width), C.TITLE))
    print(colorize("═" * width, C.BORDER))
    print()


def brand_logo():
    """Affiche le logotype terminal de KAIRO."""
    print(colorize("       ╭──────────────────────────╮", C.BORDER))
    print(
        colorize("       │", C.BORDER)
        + colorize("   ◈ ", C.OPTION_KEY)
        + colorize(PRODUCT_NAME, C.TITLE)
        + colorize("                 │", C.BORDER)
    )
    print(
        colorize("       │", C.BORDER)
        + colorize(f" {PRODUCT_TAGLINE:<25}", C.INFO)
        + colorize("│", C.BORDER)
    )
    print(colorize("       ╰──────────────────────────╯", C.BORDER))
    print()


# ============================================================
# ENTREES / SORTIES
# ============================================================

def prompt(text=">> ", color=C.BRIGHT_CYAN):
    return input(colorize(text, color))


def pause(text="Appuyez sur Entrée pour continuer..."):
    input("\n" + colorize(text, C.DIM))


def print_ok(text):
    print(colorize(f"[OK] {text}", C.OK))


def print_error(text):
    print(colorize(f"[ERREUR] {text}", C.ERROR))


def print_warn(text):
    print(colorize(f"[ATTENTION] {text}", C.WARN))


def print_info(text):
    print(colorize(text, C.INFO))
