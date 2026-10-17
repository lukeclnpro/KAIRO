#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
AI App Launcher - Windows / Linux / macOS

Principe:
1. L'utilisateur décrit ce qu'il veut faire.
2. Le programme détecte les applications installées.
3. OpenRouter choisit UNE application parmi cette liste.
4. Le programme affiche le choix et demande une confirmation.
5. Seulement après confirmation, l'application est lancée.

Sécurité importante:
- Le modèle ne reçoit PAS le droit d'exécuter des commandes.
- Le modèle ne peut sélectionner qu'un ID présent dans l'inventaire local.
- Aucune commande shell générée par le modèle n'est exécutée.
- Le lancement réel est fait localement avec des mécanismes propres à l'OS.

Configuration:
    OPENROUTER_API_KEY=sk-or-v1-...
    OPENROUTER_MODEL=openrouter/free   # optionnel

Exemples:
    python ai_launcher.py
    python ai_launcher.py "je veux retoucher une photo"
    python ai_launcher.py "je veux écrire un document"

Windows PowerShell:
    $env:OPENROUTER_API_KEY="sk-or-v1-..."
    python .\ai_launcher.py

Linux/macOS:
    export OPENROUTER_API_KEY="sk-or-v1-..."
    python3 ai_launcher.py
"""

import json
import difflib
import os
import platform
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from urllib import error, request


OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODEL = os.getenv("OPENROUTER_MODEL", "openrouter/free")
MAX_APPS_SENT_TO_MODEL = 350


# ---------------------------------------------------------------------------
# Utilitaires
# ---------------------------------------------------------------------------

def clean_name(value: str) -> str:
    """Nettoie un nom d'application pour l'affichage."""
    value = value.replace("\x00", " ").strip()
    value = re.sub(r"\s+", " ", value)
    return value


def add_app(apps, seen, name, launch_kind, launch_value, source=""):
    """Ajoute une application sans doublon."""
    name = clean_name(name)
    if not name:
        return

    # Évite les entrées manifestement inutiles.
    bad = {
        "uninstall", "uninstaller", "readme", "license",
        "update", "updater", "uninstall.exe"
    }
    if name.lower() in bad:
        return

    key = (name.lower(), launch_kind, str(launch_value).lower())
    if key in seen:
        return

    app_id = f"app_{len(apps) + 1:04d}"
    item = {
        "id": app_id,
        "name": name,
        "launch_kind": launch_kind,
        "launch_value": str(launch_value),
    }
    if source:
        item["source"] = source

    apps.append(item)
    seen.add(key)


# ---------------------------------------------------------------------------
# Windows
# ---------------------------------------------------------------------------

def scan_windows():
    apps = []
    seen = set()

    # Raccourcis du menu Démarrer.
    start_menu_dirs = []

    appdata = os.environ.get("APPDATA")
    programdata = os.environ.get("PROGRAMDATA")

    if appdata:
        start_menu_dirs.append(
            Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs"
        )
    if programdata:
        start_menu_dirs.append(
            Path(programdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs"
        )

    for base in start_menu_dirs:
        if not base.exists():
            continue
        try:
            for p in base.rglob("*.lnk"):
                add_app(
                    apps,
                    seen,
                    p.stem,
                    "windows_startfile",
                    str(p),
                    "Start Menu",
                )
        except (OSError, PermissionError):
            pass

    # Quelques exécutables connus dans PATH.
    # On ne parcourt pas tout le disque: c'est inutile et très lent.
    common_exes = [
        "firefox", "chrome", "msedge", "brave", "code",
        "notepad", "notepad++", "git", "python", "python3",
        "vlc", "gimp", "inkscape", "blender", "obs64",
        "libreoffice", "winword", "excel", "powerpnt",
    ]

    for exe in common_exes:
        found = shutil.which(exe)
        if found:
            add_app(apps, seen, Path(found).stem, "windows_exe", found, "PATH")

    return apps


# ---------------------------------------------------------------------------
# macOS
# ---------------------------------------------------------------------------

def scan_macos():
    apps = []
    seen = set()

    directories = [
        Path("/Applications"),
        Path.home() / "Applications",
        Path("/System/Applications"),
    ]

    for base in directories:
        if not base.exists():
            continue
        try:
            for p in base.glob("*.app"):
                add_app(
                    apps,
                    seen,
                    p.stem,
                    "mac_open",
                    str(p),
                    str(base),
                )
        except (OSError, PermissionError):
            pass

    return apps


# ---------------------------------------------------------------------------
# Linux
# ---------------------------------------------------------------------------

def parse_desktop_name(desktop_file: Path):
    """
    Récupère Name= dans un .desktop sans dépendance externe.
    """
    try:
        text = desktop_file.read_text(encoding="utf-8", errors="replace")
    except (OSError, PermissionError):
        return None

    in_entry = False
    name = None
    no_display = False

    for raw in text.splitlines():
        line = raw.strip()

        if line == "[Desktop Entry]":
            in_entry = True
            continue

        if in_entry and line.startswith("[") and line != "[Desktop Entry]":
            break

        if not in_entry or not line or line.startswith("#"):
            continue

        if line.startswith("Name="):
            name = line.split("=", 1)[1].strip()

        elif line.startswith("NoDisplay="):
            no_display = line.split("=", 1)[1].strip().lower() == "true"

        elif line.startswith("Hidden="):
            if line.split("=", 1)[1].strip().lower() == "true":
                return None

    if no_display:
        return None

    return clean_name(name) if name else None


def parse_desktop_exec(desktop_file: Path):
    """
    Récupère Exec= et retire les placeholders freedesktop (%U, %F, etc.).
    """
    try:
        text = desktop_file.read_text(encoding="utf-8", errors="replace")
    except (OSError, PermissionError):
        return None

    exec_line = None
    in_entry = False

    for raw in text.splitlines():
        line = raw.strip()

        if line == "[Desktop Entry]":
            in_entry = True
            continue

        if in_entry and line.startswith("[") and line != "[Desktop Entry]":
            break

        if in_entry and line.startswith("Exec="):
            exec_line = line.split("=", 1)[1].strip()
            break

    if not exec_line:
        return None

    try:
        parts = shlex.split(exec_line)
    except ValueError:
        return None

    # Field codes: %U, %F, %u, %f, %i, %c, %k, %%...
    cleaned = []
    for part in parts:
        if re.fullmatch(r"%[fFuUdDicCkKnNvm]", part):
            continue
        part = part.replace("%%", "%")
        cleaned.append(part)

    if not cleaned:
        return None

    # On ne garde que les .desktop qui pointent vers un exécutable identifiable.
    executable = cleaned[0]
    if os.path.isabs(executable):
        if not Path(executable).exists():
            return None
    else:
        if shutil.which(executable) is None:
            return None

    return cleaned


def scan_linux():
    apps = []
    seen = set()

    dirs = [
        Path.home() / ".local" / "share" / "applications",
        Path("/usr/local/share/applications"),
        Path("/usr/share/applications"),
    ]

    for base in dirs:
        if not base.exists():
            continue

        try:
            for desktop_file in base.glob("*.desktop"):
                name = parse_desktop_name(desktop_file)
                exec_parts = parse_desktop_exec(desktop_file)

                if name and exec_parts:
                    add_app(
                        apps,
                        seen,
                        name,
                        "linux_exec",
                        json.dumps(exec_parts, ensure_ascii=False),
                        str(desktop_file),
                    )
        except (OSError, PermissionError):
            pass

    return apps


# ---------------------------------------------------------------------------
# Inventaire multiplateforme
# ---------------------------------------------------------------------------

def scan_installed_apps():
    system = platform.system()

    if system == "Windows":
        apps = scan_windows()
    elif system == "Darwin":
        apps = scan_macos()
    elif system == "Linux":
        apps = scan_linux()
    else:
        raise RuntimeError(f"Système non supporté: {system}")

    # Trie pour rendre le résultat stable.
    apps.sort(key=lambda x: x["name"].lower())

    # Réattribue les IDs après tri.
    for i, app in enumerate(apps, 1):
        app["id"] = f"app_{i:04d}"

    return apps


# ---------------------------------------------------------------------------
# OpenRouter
# ---------------------------------------------------------------------------

def call_openrouter(user_request, apps):
    api_key = os.environ.get("LOCAL_IA_OPENROUTER_KEY") or os.environ.get("OPENROUTER_API_KEY", "")
    if not api_key:
        try:
            from local_ia.config.manager import openrouter_api_key

            api_key = openrouter_api_key()
        except ImportError:
            pass
    if not api_key:
        raise RuntimeError(
            "OPENROUTER_API_KEY n'est pas défini.\n"
            "Windows PowerShell : $env:OPENROUTER_API_KEY=\"sk-or-v1-...\"\n"
            "Linux/macOS        : export OPENROUTER_API_KEY=\"sk-or-v1-...\""
        )

    # Limite de taille pour éviter d'envoyer un inventaire énorme.
    model_apps = apps[:MAX_APPS_SENT_TO_MODEL]

    catalog = [
        {
            "id": app["id"],
            "name": app["name"],
        }
        for app in model_apps
    ]

    system_prompt = """
Tu es un sélecteur d'applications locales.

Ta mission: choisir l'application installée la plus adaptée à la demande
de l'utilisateur.

RÈGLES STRICTES:
1. Tu peux choisir UNIQUEMENT un id présent dans le catalogue fourni.
2. Tu ne dois jamais inventer une application ou un id.
3. Tu ne dois jamais produire de commande shell.
4. Si aucune application ne convient, retourne selected_app_id=null.
5. Réponds UNIQUEMENT avec un objet JSON valide.
6. Format exact:
{
  "selected_app_id": "app_XXXX" ou null,
  "reason": "courte explication en français",
  "confidence": 0.0
}
""".strip()

    user_prompt = (
        "Demande de l'utilisateur:\n"
        f"{user_request}\n\n"
        "Catalogue des applications installées:\n"
        f"{json.dumps(catalog, ensure_ascii=False, indent=2)}"
    )

    payload = {
        "model": DEFAULT_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0,
        "max_tokens": 300,
    }

    data = json.dumps(payload).encode("utf-8")

    req = request.Request(
        OPENROUTER_URL,
        data=data,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "http://localhost",
            "X-Title": "AI App Launcher",
        },
    )

    try:
        with request.urlopen(req, timeout=60) as response:
            raw = response.read().decode("utf-8")
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"Erreur OpenRouter HTTP {exc.code}: {body[:1000]}"
        ) from exc
    except error.URLError as exc:
        raise RuntimeError(f"Impossible de contacter OpenRouter: {exc}") from exc

    try:
        response_json = json.loads(raw)
        content = response_json["choices"][0]["message"]["content"]
    except (KeyError, IndexError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            f"Réponse OpenRouter inattendue:\n{raw[:2000]}"
        ) from exc

    # Quelques modèles peuvent entourer le JSON de ```json ... ```.
    content = content.strip()
    content = re.sub(r"^```json\s*", "", content, flags=re.I)
    content = re.sub(r"\s*```$", "", content)

    try:
        selection = json.loads(content)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"Le modèle n'a pas renvoyé un JSON valide:\n{content}"
        ) from exc

    return selection


def find_application(user_request, apps=None):
    """Résout un nom d'application installé, avec sélection IA en dernier recours."""
    requested_path = Path(user_request).expanduser()
    if requested_path.exists():
        system = platform.system()
        if system == "Windows":
            launch_kind = "windows_startfile" if requested_path.suffix.lower() == ".lnk" else "windows_exe"
        elif system == "Darwin" and requested_path.suffix == ".app":
            launch_kind = "mac_open"
        elif system == "Linux" and requested_path.is_file() and os.access(requested_path, os.X_OK):
            launch_kind = "linux_exec"
            launch_value = json.dumps([str(requested_path)])
        else:
            launch_kind = None
        if launch_kind:
            if launch_kind != "linux_exec":
                launch_value = str(requested_path)
            return {
                "id": "app_path",
                "name": requested_path.stem,
                "launch_kind": launch_kind,
                "launch_value": launch_value,
            }

    apps = scan_installed_apps() if apps is None else apps
    query = re.sub(r"[^a-z0-9]+", "", clean_name(user_request).lower())
    if not query or not apps:
        return None

    def score(app):
        name = re.sub(r"[^a-z0-9]+", "", app["name"].lower())
        if query == name:
            return 1.0
        if query in name or name in query:
            return 0.92
        return difflib.SequenceMatcher(None, query, name).ratio()

    ranked = sorted(apps, key=score, reverse=True)
    if score(ranked[0]) >= 0.72:
        return ranked[0]

    api_key = os.environ.get("LOCAL_IA_OPENROUTER_KEY") or os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        try:
            from local_ia.config.manager import openrouter_api_key

            api_key = openrouter_api_key()
        except ImportError:
            pass
    if not api_key:
        return None

    selection = call_openrouter(user_request, apps)
    selected_id = selection.get("selected_app_id")
    return next((app for app in apps if app["id"] == selected_id), None)


# ---------------------------------------------------------------------------
# Lancement sécurisé
# ---------------------------------------------------------------------------

def launch_app(app):
    kind = app["launch_kind"]
    value = app["launch_value"]

    if kind == "windows_startfile":
        if platform.system() != "Windows":
            raise RuntimeError("Cette application est enregistrée pour Windows.")
        path = Path(value)
        if not path.exists():
            raise FileNotFoundError(f"Raccourci introuvable: {path}")
        os.startfile(str(path))  # type: ignore[attr-defined]
        return

    if kind == "windows_exe":
        if platform.system() != "Windows":
            raise RuntimeError("Cette application est enregistrée pour Windows.")
        exe = Path(value)
        if not exe.exists():
            raise FileNotFoundError(f"Exécutable introuvable: {exe}")
        subprocess.Popen([str(exe)], shell=False)
        return

    if kind == "mac_open":
        if platform.system() != "Darwin":
            raise RuntimeError("Cette application est enregistrée pour macOS.")
        app_path = Path(value)
        if not app_path.exists():
            raise FileNotFoundError(f"Application introuvable: {app_path}")
        subprocess.Popen(["open", str(app_path)], shell=False)
        return

    if kind == "linux_exec":
        if platform.system() != "Linux":
            raise RuntimeError("Cette application est enregistrée pour Linux.")
        parts = json.loads(value)
        if not parts or not isinstance(parts, list):
            raise RuntimeError("Entrée Linux invalide.")

        executable = parts[0]
        if os.path.isabs(executable):
            if not Path(executable).exists():
                raise FileNotFoundError(f"Exécutable introuvable: {executable}")
        else:
            resolved = shutil.which(executable)
            if not resolved:
                raise FileNotFoundError(
                    f"Exécutable introuvable dans PATH: {executable}"
                )
            parts[0] = resolved

        subprocess.Popen(parts, shell=False)
        return

    raise RuntimeError(f"Type de lancement inconnu: {kind}")


# ---------------------------------------------------------------------------
# Interface
# ---------------------------------------------------------------------------

def ask_user_request():
    if len(sys.argv) > 1:
        return " ".join(sys.argv[1:]).strip()

    print("=== AI App Launcher ===")
    print("Décris ce que tu veux faire.")
    print("Exemple: « je veux monter une vidéo »")
    print()

    try:
        return input("> ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return ""


def main():
    user_request = ask_user_request()

    if not user_request:
        print("Aucune demande.")
        return 1

    print("\nRecherche des applications installées...")
    apps = scan_installed_apps()

    if not apps:
        print("Aucune application détectée.")
        return 1

    print(f"{len(apps)} application(s) détectée(s).")
    print(f"Analyse avec OpenRouter ({DEFAULT_MODEL})...\n")

    selection = call_openrouter(user_request, apps)

    selected_id = selection.get("selected_app_id")
    reason = selection.get("reason", "")
    confidence = selection.get("confidence", 0)

    if not selected_id:
        print("Je n'ai trouvé aucune application installée adaptée.")
        if reason:
            print(f"Raison: {reason}")
        return 0

    # Vérification critique: l'ID doit provenir de notre propre inventaire.
    app_by_id = {app["id"]: app for app in apps}
    app = app_by_id.get(selected_id)

    if app is None:
        print("Erreur: le modèle a proposé une application inconnue.")
        return 2

    print("Application proposée")
    print("--------------------")
    print(f"Nom        : {app['name']}")
    print(f"Confiance  : {float(confidence):.0%}")
    print(f"Pourquoi   : {reason}")
    print()

    answer = input(f"Lancer « {app['name']} » ? [o/N] ").strip().lower()

    if answer not in {"o", "oui", "y", "yes"}:
        print("Annulé.")
        return 0

    try:
        launch_app(app)
    except Exception as exc:
        print(f"Impossible de lancer l'application: {exc}")
        return 3

    print(f"✓ {app['name']} a été lancée.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
