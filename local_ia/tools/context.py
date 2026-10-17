"""Outil permettant à l'agent de consulter le contexte permanent."""

from local_ia.core.context import load_context


def use():
    return load_context()