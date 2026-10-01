#!/usr/bin/env python3
"""Preview or remove project artifacts, chat history, and local user accounts."""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

from local_ia.core.accounts import accounts_path


CACHE_DIRS = {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".hypothesis"}
VENV_DIRS = {".venv", "venv", ".virtualenv", "virtualenv", ".tox", ".nox"}
SKIP_DIRS = {".git", "node_modules"}
PROJECT_MARKERS = {"main.py", "setup.py", "pyproject.toml", "requirements.txt"}


def collect_cleanup_targets(root: Path) -> list[Path]:
    """Return project artifacts and the configured local accounts file."""
    root = root.resolve()
    targets = []

    for current, directories, files in os.walk(root, topdown=True, followlinks=False):
        current_path = Path(current)
        traversable = []

        for name in directories:
            candidate = current_path / name
            if candidate.is_symlink():
                continue
            if name in CACHE_DIRS or name in VENV_DIRS:
                targets.append(candidate)
                continue
            if name in SKIP_DIRS:
                continue
            if candidate == root / "chats":
                targets.extend(
                    path for path in candidate.iterdir()
                    if path.is_file() and not path.is_symlink() and path.suffix.lower() == ".json"
                )
                continue
            traversable.append(name)

        directories[:] = traversable
        for name in files:
            candidate = current_path / name
            if not candidate.is_symlink() and candidate.suffix.lower() in {".pyc", ".pyo"}:
                targets.append(candidate)

    account_file = accounts_path().expanduser().absolute()
    if account_file.is_file() and not account_file.is_symlink():
        targets.append(account_file)

    return sorted(set(targets), key=lambda path: _display_path(path, root))


def _display_path(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


def _parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Nettoie les artefacts locaux avant de distribuer le projet.",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parent,
        help="Racine du projet à nettoyer (par défaut : dossier du script).",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Supprimer les éléments listés après confirmation.",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Confirmer sans question interactive (nécessite --apply).",
    )
    args = parser.parse_args(argv)
    if args.yes and not args.apply:
        parser.error("--yes nécessite --apply.")
    return args


def main(argv=None) -> int:
    args = _parse_args(argv)
    root = args.root.expanduser().resolve()
    if not root.is_dir():
        print(f"Racine de projet introuvable : {root}", file=sys.stderr)
        return 2
    if not any((root / marker).exists() for marker in PROJECT_MARKERS):
        print(f"Aucun marqueur de projet Python trouvé dans : {root}", file=sys.stderr)
        return 2

    targets = collect_cleanup_targets(root)
    print(f"Projet : {root}")
    if not targets:
        print("Rien à nettoyer.")
        return 0

    for path in targets:
        print(f"  {_display_path(path, root)}")
    print(f"Total : {len(targets)} élément(s).")

    if not args.apply:
        print("Aperçu uniquement. Relance avec --apply pour supprimer après confirmation.")
        return 0
    if not args.yes:
        answer = input("Supprimer ces caches, environnements, conversations et comptes ? [o/N] ").strip().casefold()
        if answer not in {"o", "oui", "y", "yes"}:
            print("Nettoyage annulé.")
            return 0

    errors = []
    for path in targets:
        try:
            if path.is_dir() and not path.is_symlink():
                shutil.rmtree(path)
            else:
                path.unlink()
        except OSError as error:
            errors.append(f"{_display_path(path, root)} : {error}")

    if errors:
        print("Certains éléments n'ont pas pu être supprimés :", file=sys.stderr)
        for error in errors:
            print(f"  {error}", file=sys.stderr)
        return 1

    print("Nettoyage terminé.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())