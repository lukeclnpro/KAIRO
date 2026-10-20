"""Sondes de démarrage isolées pour les outils KAIRO."""

from __future__ import annotations

import json
import signal
import shutil
import sys
import tempfile
import traceback
import webbrowser
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import file_commands
from local_ia.config.manager import openrouter_api_keys, openrouter_base_url
from local_ia.core.memory import init_database
from local_ia.core.tool_manager import ToolManager
from local_ia.tools import browser, download, habitude, launch


class ProbeBlocked(RuntimeError):
    """Un prérequis utilisateur manque ou l'action ne peut pas être sûre en fond."""


TOOL_PROBLEM_GUIDE = (
    {
        "title": "Clé OpenRouter absente",
        "patterns": ("clé openrouter absente", "no api key", "missing api key", "api key is required"),
        "message": "La traduction cloud ne peut pas démarrer sans clé API.",
        "action": "Connecte-toi à OpenRouter et ajoute ou active une clé dans Compte → Gérer les clés API.",
    },
    {
        "title": "Clé API refusée",
        "patterns": ("invalid api key", "invalid key", "unauthorized", "401", "clé invalide", "authentification refusée"),
        "message": "Le service a refusé les identifiants configurés.",
        "action": "Vérifie la clé OpenRouter, son état et le compte associé.",
    },
    {
        "title": "Quota ou crédits épuisés",
        "patterns": ("insufficient_quota", "quota exceeded", "billing", "credit balance", "402", "crédits insuffisants"),
        "message": "Le fournisseur refuse la requête car le quota ou le solde disponible est insuffisant.",
        "action": "Vérifie le quota, les crédits et les limites de facturation du compte fournisseur.",
    },
    {
        "title": "Limite de requêtes atteinte",
        "patterns": ("rate limit", "too many requests", "429", "trop de requêtes"),
        "message": "Le fournisseur limite temporairement le nombre de requêtes.",
        "action": "Attends un peu puis relance le diagnostic ou réduis le rythme des demandes.",
    },
    {
        "title": "Serveur Ollama inaccessible",
        "patterns": ("ollama", "connection refused", "failed to connect", "connexion refusée", "serveur inaccessible"),
        "message": "KAIRO ne parvient pas à joindre le serveur Ollama configuré.",
        "action": "Démarre Ollama et vérifie son adresse dans Paramètres → IA & modèles.",
        "requires_any": ("ollama",),
    },
    {
        "title": "Navigateur indisponible",
        "patterns": ("aucun navigateur par défaut", "no browser", "webbrowser.error", "browser not found"),
        "message": "Aucun navigateur par défaut n’est disponible pour ce test.",
        "action": "Installe un navigateur et définis-le comme navigateur par défaut du système.",
    },
    {
        "title": "Connexion réseau impossible",
        "patterns": (
            "connectionerror", "connection refused", "network is unreachable",
            "failed to establish a new connection", "temporary failure in name resolution",
            "name or service not known", "nodename nor servname", "dns",
            "connexion réseau", "internet unavailable", "openrouter inaccessible",
        ),
        "message": "KAIRO ne parvient pas à joindre le service distant. La connexion Internet ou le serveur peut être indisponible.",
        "action": "Vérifie Internet, le VPN/proxy et l’adresse du fournisseur, puis relance le diagnostic.",
    },
    {
        "title": "Délai d’attente dépassé",
        "patterns": ("timeoutexception", "timed out", "read timeout", "connect timeout", "délai dépassé", "timeout"),
        "message": "Le service n’a pas répondu dans le délai prévu.",
        "action": "Réessaie quand le réseau ou le service sera moins chargé; vérifie aussi le pare-feu.",
    },
    {
        "title": "Permission refusée",
        "patterns": ("permissionerror", "permission denied", "access is denied", "accès refusé", "operation not permitted"),
        "message": "KAIRO n’a pas les droits nécessaires pour effectuer cette action.",
        "action": "Vérifie les droits du dossier ou de l’application ciblée, sans élargir les accès inutilement.",
    },
    {
        "title": "Fichier ou dépendance introuvable",
        "patterns": ("filenotfounderror", "no such file or directory", "modulenotfounderror", "no module named", "not found"),
        "message": "Un fichier, programme ou module requis n’a pas été trouvé.",
        "action": "Vérifie le chemin et l’installation de la dépendance indiquée dans le log détaillé.",
    },
)


def explain_tool_problem(detail="", traceback_text="", stderr="", status="failed"):
    """Translate a common tool diagnostic into a concise French explanation."""
    diagnostic = "\n".join(str(value or "") for value in (detail, traceback_text, stderr)).casefold()
    for problem in TOOL_PROBLEM_GUIDE:
        if any(pattern in diagnostic for pattern in problem["patterns"]):
            if "requires_any" not in problem or any(
                token in diagnostic for token in problem["requires_any"]
            ):
                return problem
    if status == "blocked":
        return {
            "title": "Prérequis manquant",
            "message": "Le test ne peut pas être exécuté dans la configuration actuelle.",
            "action": "Lis le détail du blocage ci-dessous et complète le prérequis indiqué.",
        }
    return {
        "title": "Erreur non reconnue",
        "message": "KAIRO n’a pas pu terminer ce test; le log brut peut préciser la cause.",
        "action": "Consulte le détail et la trace complète, puis relance le diagnostic après correction.",
    }


def _execute(tool_name, arguments, connection, workspace):
    tool_call = {"tool": tool_name, "arguments": arguments}
    result = ToolManager.execute(
        tool_call,
        {"id": "tool-health-check"},
        connection,
        allowed_tools={tool_name},
    )
    if isinstance(result, dict) and result.get("error"):
        raise RuntimeError(str(result["error"]))
    if isinstance(result, dict) and result.get("confirmation_required"):
        raise RuntimeError(str(result.get("message", "Confirmation inattendue.")))
    verification = ToolManager.verify_result(
        tool_call,
        result,
        {"id": "tool-health-check"},
    )
    if not verification.get("success"):
        raise RuntimeError(str(verification.get("evidence", "Vérification refusée.")))
    return result


def _allowed_temp_root():
    roots = [Path(root).expanduser().resolve() for root in file_commands.FILE_ACCESS_ROOTS]
    for root in roots:
        if root.is_dir():
            return root
    raise RuntimeError("Aucune racine de fichiers autorisée n'est disponible pour les sondes.")


def run_startup_tool_checks():
    """Exécute une sonde réelle par outil sans modifier les données de l'utilisateur."""
    workspace = Path(tempfile.mkdtemp(prefix=".kairo-tool-health-", dir=_allowed_temp_root())).resolve()
    connection = None
    checks = []

    def record(tool_name, probe):
        try:
            outcome = probe()
            if isinstance(outcome, tuple):
                status, detail = outcome
            else:
                status, detail = "ok", str(outcome)
            checks.append({"tool": tool_name, "status": status, "detail": detail})
        except ProbeBlocked as error:
            checks.append({"tool": tool_name, "status": "blocked", "detail": str(error)})
        except Exception as error:
            checks.append({
                "tool": tool_name,
                "status": "failed",
                "detail": f"{type(error).__name__}: {error}",
                "traceback": traceback.format_exc(),
            })

    try:
        connection = init_database(workspace / "health.sqlite")
        sample_path = workspace / "sample.txt"
        sample_path.write_text("KAIRO_TOOL_HEALTH_SAMPLE\nRemplace-moi\n", encoding="utf-8")
        write_path = workspace / "write-probe.txt"
        download_cache = workspace / ".downloads"
        generated_dir = workspace / "generated"
        habits_path = workspace / "habits.json"
        legacy_habits_path = workspace / "legacy-habits.json"

        with (
            patch.object(download, "CACHE_DIR", download_cache),
            patch.object(download, "GENERATED_FILES_DIR", generated_dir),
            patch.object(habitude, "FICHIER_JSON", habits_path),
            patch.object(habitude, "ANCIEN_FICHIER_JSON", legacy_habits_path),
        ):
            probes = {
                "memory": lambda: _execute("memory", {}, connection, workspace),
                "context": lambda: _execute("context", {}, connection, workspace),
                "list": lambda: _execute("list", {"path": str(workspace)}, connection, workspace),
                "search": lambda: _execute(
                    "search",
                    {"pattern": "KAIRO_TOOL_HEALTH_SAMPLE", "path": str(workspace), "extension": "txt"},
                    connection,
                    workspace,
                ),
                "file": lambda: _execute("file", {"path": str(sample_path)}, connection, workspace),
                "write": lambda: _execute(
                    "write",
                    {"path": str(write_path), "content": "KAIRO_TOOL_HEALTH_WRITE\n", "append": False},
                    connection,
                    workspace,
                ),
                "create_download": lambda: _execute(
                    "create_download",
                    {"filename": "health-probe", "content": "KAIRO_TOOL_HEALTH_DOWNLOAD\n", "extension": "txt"},
                    connection,
                    workspace,
                ),
                "edit": lambda: _execute(
                    "edit",
                    {"path": str(sample_path), "old": "Remplace-moi", "new": "KAIRO_TOOL_HEALTH_EDITED"},
                    connection,
                    workspace,
                ),
                "command": lambda: _execute(
                    "command",
                    {"argv": [sys.executable, "--version"], "cwd": str(workspace), "timeout": 10, "confirmed": True},
                    connection,
                    workspace,
                ),
                "system": lambda: _execute("system", {"action": "info"}, connection, workspace),
                "calculator": lambda: _execute(
                    "calculator", {"expression": "2 + 2"}, connection, workspace
                ),
                "web": lambda: _probe_weather(connection, workspace),
                "open_page": lambda: _probe_open_page(connection, workspace),
                "translate": lambda: _probe_translation(connection, workspace),
                "document": lambda: _probe_document(connection, workspace),
                "launch": lambda: _probe_launch(connection, workspace),
                "reminder": lambda: _probe_reminder(connection, workspace),
                "habits": lambda: _probe_habits(connection, workspace),
            }

            for tool_name in sorted(ToolManager.ALL_TOOLS):
                probe = probes.get(tool_name)
                if probe is None:
                    record(tool_name, lambda: (_ for _ in ()).throw(RuntimeError("Aucune sonde définie.")))
                else:
                    record(tool_name, probe)
    finally:
        if connection is not None:
            connection.close()
        shutil.rmtree(workspace, ignore_errors=True)

    issues = [check for check in checks if check["status"] in {"failed", "blocked"}]
    return {
        "checks": checks,
        "checked": len(checks),
        "passed": sum(check["status"] == "ok" for check in checks),
        "issues": issues,
    }


def _probe_document(connection, workspace):
    path = workspace / "document-probe.txt"
    expected = "KAIRO_TOOL_HEALTH_DOCUMENT\n"
    _execute(
        "document",
        {"action": "create_document", "path": str(path), "format": "txt", "content": expected},
        connection,
        workspace,
    )
    result = _execute("document", {"action": "read_document", "path": str(path)}, connection, workspace)
    if result.get("content") != expected:
        raise RuntimeError("Le texte relu diffère du document créé.")
    return "Création et lecture vérifiées dans l'espace temporaire."


def _probe_launch(connection, workspace):
    applications = launch.scan_installed_apps()
    if not applications:
        raise ProbeBlocked("Aucune application installée détectée pour tester le lanceur.")
    result = ToolManager.execute(
        {"tool": "launch", "arguments": {"name": applications[0]["name"]}},
        {"id": "tool-health-check"},
        connection,
        allowed_tools={"launch"},
    )
    if not isinstance(result, dict) or not result.get("confirmation_required"):
        raise RuntimeError("Le lanceur n'a pas demandé la confirmation attendue.")
    return "Application détectée et confirmation requise; aucune fenêtre n'a été lancée."


def _probe_reminder(connection, workspace):
    title = f"__kairo_health_{workspace.name}"
    due_at = (datetime.now().astimezone() + timedelta(hours=2)).isoformat(timespec="minutes")
    created = _execute(
        "reminder",
        {"action": "create", "title": title, "due_at": due_at, "repeat": "none"},
        connection,
        workspace,
    )
    reminder_id = created["reminder"]["id"]
    listed = _execute("reminder", {"action": "list"}, connection, workspace)
    if not any(item.get("id") == reminder_id for item in listed.get("reminders", [])):
        raise RuntimeError("Le rappel créé n'apparaît pas dans la liste.")
    _execute("reminder", {"action": "cancel", "id": reminder_id}, connection, workspace)
    return "Création, lecture et suppression vérifiées dans la base temporaire."


def _probe_habits(connection, workspace):
    task = f"__kairo_health_{workspace.name}"
    _execute(
        "habits",
        {"action": "add", "habit": {"task": task, "frequency": "daily", "type": "ai"}},
        connection,
        workspace,
    )
    listed = _execute("habits", {"action": "list"}, connection, workspace)
    if not any(item.get("task") == task for item in listed.get("habits", [])):
        raise RuntimeError("L'habitude créée n'apparaît pas dans la liste.")
    _execute("habits", {"action": "delete", "task": task}, connection, workspace)
    return "Création, lecture et suppression vérifiées dans le fichier temporaire."


def _probe_weather(connection, workspace):
    result = _execute(
        "web",
        {"query": "météo demain à Metz", "category": "weather"},
        connection,
        workspace,
    )
    if result.get("type") != "weather" or not result.get("daily_forecast"):
        raise RuntimeError("Le service n'a pas renvoyé de prévisions journalières.")
    return "Service météo et prévisions journalières accessibles."


def _probe_open_page(connection, workspace):
    try:
        webbrowser.get()
    except webbrowser.Error as error:
        raise ProbeBlocked(f"Aucun navigateur par défaut disponible : {error}") from error
    with patch.object(browser.webbrowser, "open", return_value=True):
        result = _execute(
            "open_page",
            {"url": "https://example.com"},
            connection,
            workspace,
        )
    return "Navigateur détecté et routage validé; aucune fenêtre n'a été ouverte."


def _probe_translation(connection, workspace):
    api_keys = openrouter_api_keys()
    if not api_keys:
        raise ProbeBlocked("Clé OpenRouter absente; test de traduction réelle impossible.")
    try:
        result = _execute(
            "translate",
            {"text": "Bonjour.", "target_language": "anglais", "source_language": "français"},
            connection,
            workspace,
        )
    except Exception as error:
        raise RuntimeError(
            f"OpenRouter inaccessible à {openrouter_base_url()} avec {len(api_keys)} clé(s) configurée(s): {error}"
        ) from error
    if not str(result.get("translation", "")).strip():
        raise RuntimeError("L'API de traduction a renvoyé une réponse vide.")
    return "Requête courte OpenRouter exécutée; réponse non vide reçue."


def main():
    def stop_with_cleanup(_signum, _frame):
        raise SystemExit(143)

    signal.signal(signal.SIGTERM, stop_with_cleanup)
    try:
        result = run_startup_tool_checks()
    except Exception as error:
        result = {
            "checks": [],
            "checked": 0,
            "passed": 0,
            "issues": [{
                "tool": "startup",
                "status": "failed",
                "detail": f"{type(error).__name__}: {error}",
                "traceback": traceback.format_exc(),
            }],
        }
    print(json.dumps(result, ensure_ascii=False, default=str))
    return 1 if result["issues"] else 0


if __name__ == "__main__":
    raise SystemExit(main())