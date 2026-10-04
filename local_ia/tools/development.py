"""Project-scoped development, Git, backup, and task operations."""

from __future__ import annotations

import ast
import difflib
import hashlib
import importlib.util
import json
import re
import shutil
import subprocess
import sys
import uuid
from datetime import datetime
from pathlib import Path

from local_ia.core import code_projects
from local_ia.tools import command, edit

_TASK_STATUSES = {"todo", "in_progress", "done"}
_MAX_TEXT_COMPARE_BYTES = 1_000_000


def _project(chat):
    path = chat.get("code_project_path")
    if not path:
        raise ValueError("Cette action nécessite un projet de code actif.")
    return code_projects.resolve_active_project(path)


def _git(project, arguments):
    result = subprocess.run(
        ["git", "-C", str(project), *arguments],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    if result.returncode:
        message = result.stderr.strip() or result.stdout.strip() or "La commande Git a échoué."
        raise ValueError(message[:2000])
    return result.stdout.strip()


def _project_relative_path(project, value):
    text = str(value or "").strip()
    relative = Path(text)
    if not text or relative.is_absolute() or ".." in relative.parts:
        raise ValueError("Le chemin doit rester relatif au projet et ne pas contenir '..'.")
    return code_projects.resolve_project_path(project, relative)


def _git_paths(project, values):
    if not isinstance(values, list) or not values:
        raise ValueError("Fournis une liste de chemins relatifs au projet.")
    paths = []
    for value in values:
        target = _project_relative_path(project, value)
        paths.append(target.relative_to(project).as_posix())
    return paths


def _git_action(action, project, arguments):
    if action == "git_status":
        return {"action": action, "output": _git(project, ["status", "--short", "--branch"])}
    if action == "git_log":
        limit = max(1, min(int(arguments.get("limit", 20)), 50))
        output = _git(project, ["log", f"-{limit}", "--date=short", "--pretty=format:%h%x09%ad%x09%s"])
        return {"action": action, "commits": output.splitlines() if output else []}
    if action == "git_diff":
        command = ["diff", "--cached"] if arguments.get("staged") else ["diff"]
        paths = arguments.get("paths")
        if paths:
            command.extend(["--", *_git_paths(project, paths)])
        output = _git(project, command)
        return {"action": action, "diff": output[:50000], "truncated": len(output) > 50000}
    if action == "git_stage":
        paths = _git_paths(project, arguments.get("paths"))
        _git(project, ["add", "--", *paths])
        return {"action": action, "staged": paths}
    if action == "git_create_branch":
        name = str(arguments.get("name") or "").strip()
        if not name or name.startswith("-") or ".." in name:
            raise ValueError("Nom de branche invalide.")
        _git(project, ["check-ref-format", "--branch", name])
        if not arguments.get("confirmed"):
            return {
                "confirmation_required": True,
                "action": action,
                "message": f"Confirme la création de la branche Git « {name} ».",
            }
        _git(project, ["branch", name])
        return {"action": action, "branch": name, "created": True}
    if action == "git_commit":
        message = str(arguments.get("message") or "").strip()
        paths = _git_paths(project, arguments.get("paths"))
        if not message:
            raise ValueError("Le commit nécessite un message.")
        if not arguments.get("confirmed"):
            return {
                "confirmation_required": True,
                "action": action,
                "message": f"Confirme le commit Git de {len(paths)} chemin(s) : {message}",
            }
        _git(project, ["add", "--", *paths])
        _git(project, ["commit", "--only", "-m", message, "--", *paths])
        return {"action": action, "commit": _git(project, ["rev-parse", "--short", "HEAD"]), "created": True}
    raise ValueError("Action Git inconnue.")


def _backup_action(action, project, arguments):
    backup_directory = project / ".local_ia_backups"
    if action == "backup_file":
        target = _project_relative_path(project, arguments.get("path"))
        if not target.is_file():
            raise FileNotFoundError(f"Fichier à sauvegarder introuvable : {target.name}")
        backup = edit.backup_file(target, backup_directory)
        return {"action": action, "path": str(target), "backup": backup, "created": bool(backup)}

    if action == "restore_file":
        target = _project_relative_path(project, arguments.get("path"))
        backup = Path(str(arguments.get("backup") or "")).expanduser().resolve()
        if backup.is_symlink() or backup.parent != backup_directory.resolve() or not backup.is_file():
            raise PermissionError("La sauvegarde doit être un fichier direct du dossier .local_ia_backups.")
        if not arguments.get("confirmed"):
            return {
                "confirmation_required": True,
                "action": action,
                "message": f"Confirme la restauration de {backup.name} vers {target.relative_to(project).as_posix()}.",
            }
        if backup.stat().st_size > 2 * 1024 * 1024:
            raise ValueError("La sauvegarde dépasse la limite de restauration de 2 Mo.")
        edit.backup_file(target, backup_directory)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(backup, target)
        return {"action": action, "path": str(target), "restored_from": str(backup), "restored": True}
    raise ValueError("Action de sauvegarde inconnue.")


def _analyze_python(project, arguments):
    target = _project_relative_path(project, arguments.get("path"))
    if target.suffix.casefold() != ".py" or not target.is_file():
        raise ValueError("L'analyse syntaxique attend un fichier Python existant.")
    if target.stat().st_size > 2 * 1024 * 1024:
        raise ValueError("Le fichier dépasse la limite d'analyse de 2 Mo.")
    source = target.read_text(encoding="utf-8")
    try:
        ast.parse(source, filename=str(target))
    except SyntaxError as error:
        diagnostics = [{
            "tool": "python-parser",
            "line": error.lineno,
            "column": error.offset,
            "message": error.msg,
        }]
        return {"action": "analyze_python", "path": str(target), "valid_syntax": False, "diagnostics": diagnostics}

    diagnostics = []
    if importlib.util.find_spec("ruff"):
        result = subprocess.run(
            [sys.executable, "-m", "ruff", "check", "--output-format", "json", str(target)],
            cwd=project,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        try:
            diagnostics = json.loads(result.stdout or "[]")
        except json.JSONDecodeError:
            diagnostics = [{"message": (result.stderr or result.stdout)[:2000]}]
    return {
        "action": "analyze_python",
        "path": str(target),
        "valid_syntax": True,
        "diagnostics": diagnostics,
        "ruff_available": bool(importlib.util.find_spec("ruff")),
    }


def _format_python(project, arguments):
    target = _project_relative_path(project, arguments.get("path"))
    if target.suffix.casefold() != ".py" or not target.is_file():
        raise ValueError("Le formatage attend un fichier Python existant.")
    if not importlib.util.find_spec("ruff"):
        raise ValueError("Ruff n'est pas installé. Installe les dépendances de développement du projet.")
    if not arguments.get("confirmed"):
        return {
            "confirmation_required": True,
            "action": "format_python",
            "message": f"Confirme le formatage de {target.relative_to(project).as_posix()}; une sauvegarde préalable sera créée.",
        }
    backup = edit.backup_file(target, project / ".local_ia_backups")
    result = subprocess.run(
        [sys.executable, "-m", "ruff", "format", str(target)],
        cwd=project,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if result.returncode:
        raise ValueError((result.stderr or result.stdout or "Ruff a échoué.")[:2000])
    return {"action": "format_python", "path": str(target), "backup": backup, "formatted": True, "output": result.stdout.strip()}


def _tasks(action, project, arguments):
    tasks = code_projects.list_project_tasks(project)
    if action == "list_tasks":
        return {"action": action, "tasks": tasks}
    if action == "add_task":
        title = str(arguments.get("title") or "").strip()
        if not title or len(title) > 240:
            raise ValueError("Le titre de tâche doit contenir entre 1 et 240 caractères.")
        task = {
            "id": uuid.uuid4().hex[:12],
            "title": title,
            "status": "todo",
            "created_at": datetime.now().isoformat(timespec="seconds"),
        }
        tasks.append(task)
        code_projects.save_project_tasks(project, tasks)
        return {"action": action, "task": task, "created": True}
    task_id = str(arguments.get("id") or "")
    task = next((item for item in tasks if item.get("id") == task_id), None)
    if task is None:
        raise ValueError("Tâche introuvable dans ce projet.")
    if action == "update_task":
        if arguments.get("title") is not None:
            title = str(arguments["title"]).strip()
            if not title or len(title) > 240:
                raise ValueError("Le titre de tâche doit contenir entre 1 et 240 caractères.")
            task["title"] = title
        if arguments.get("status") is not None:
            status = str(arguments["status"])
            if status not in _TASK_STATUSES:
                raise ValueError("Statut invalide; valeurs permises: todo, in_progress, done.")
            task["status"] = status
        task["updated_at"] = datetime.now().isoformat(timespec="seconds")
        code_projects.save_project_tasks(project, tasks)
        return {"action": action, "task": task, "updated": True}
    if action == "delete_task":
        tasks.remove(task)
        code_projects.save_project_tasks(project, tasks)
        return {"action": action, "id": task_id, "deleted": True}
    raise ValueError("Action de tâche inconnue.")


def use(arguments, chat):
    if not isinstance(arguments, dict):
        raise ValueError("Les arguments development doivent être un objet.")
    project = _project(chat)
    action = arguments.get("action")
    if action.startswith("git_"):
        return _git_action(action, project, arguments)
    if action in {"backup_file", "restore_file"}:
        return _backup_action(action, project, arguments)
    if action == "analyze_python":
        return _analyze_python(project, arguments)
    if action == "format_python":
        return _format_python(project, arguments)
    if action in {"list_tasks", "add_task", "update_task", "delete_task"}:
        return _tasks(action, project, arguments)
    if action == "run_tests":
        if not arguments.get("confirmed"):
            return {"confirmation_required": True, "action": action, "message": "Confirme l'exécution des tests du projet."}
        timeout = max(1, min(int(arguments.get("timeout", 120)), 600))
        return command.use([sys.executable, "-m", "unittest", "discover", "-s", "tests"], timeout=timeout, cwd=str(project), confirmed=True)
    raise ValueError("Action development inconnue.")