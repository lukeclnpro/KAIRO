"""Adaptateur final pour la session Ollama."""

from __future__ import annotations

from local_ia.llm.ollama import OllamaSession, ask, ask_ollama, ask_openrouter, installed_models

__all__ = ["OllamaSession", "ask", "ask_ollama", "ask_openrouter", "installed_models"]
