"""Chargement et sauvegarde de la configuration de local_ia."""

from __future__ import annotations

import copy
import json
import os
import threading
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]
CONFIG_PATH = BASE_DIR / "config.json"
_KEY_ROTATION_LOCK = threading.Lock()
_KEY_ROTATION_KEYS = ()
_KEY_ROTATION_INDEX = 0

DEFAULT_CONFIG = {
    "model": "qwen2.5:1.5b",
    "ollama": {
        "url": "http://127.0.0.1:11434",
        "model": "",
        "timeout": 120,
        "stream": False,
        "keep_alive": "30m",
    },
    "openrouter": {
        "model": "openai/gpt-4o-mini",
        "base_url": "https://openrouter.ai/api/v1",
        "timeout": 120,
        "site_url": "",
        "app_name": "Local IA",
    },
}


def _merge(defaults, values):
    result = copy.deepcopy(defaults)
    if isinstance(values, dict):
        for key, value in values.items():
            if isinstance(result.get(key), dict) and isinstance(value, dict):
                result[key] = _merge(result[key], value)
            else:
                result[key] = value
    return result


def load_config(path: Path | None = None) -> dict:
    target = path or CONFIG_PATH
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        data = {}
    return _merge(DEFAULT_CONFIG, data)


def save_config(config: dict, path: Path | None = None) -> None:
    target = path or CONFIG_PATH
    target.write_text(
        json.dumps(config, ensure_ascii=False, indent=4) + "\n",
        encoding="utf-8",
    )


def model_config(config: dict | None = None) -> str:
    data = config if config is not None else load_config()
    nested = data.get("ollama", {})
    if isinstance(nested, dict) and str(nested.get("model", "")).strip():
        return str(nested["model"]).strip()
    return str(data.get("model", DEFAULT_CONFIG["model"])).strip()


def ollama_base_url(config: dict | None = None) -> str:
    data = config if config is not None else load_config()
    nested = data.get("ollama", {})
    value = nested.get("url") if isinstance(nested, dict) else None
    url = str(value or DEFAULT_CONFIG["ollama"]["url"]).rstrip("/")
    return url[:-4] if url.endswith("/api") else url


def openrouter_api_keys() -> list[str]:
    serialized_keys = os.environ.get("LOCAL_IA_OPENROUTER_KEYS", "").strip()
    if serialized_keys:
        try:
            values = json.loads(serialized_keys)
        except json.JSONDecodeError:
            values = []
        if isinstance(values, list):
            keys = list(dict.fromkeys(str(value).strip() for value in values if str(value).strip()))
            if keys:
                return keys

    env_key = os.environ.get("LOCAL_IA_OPENROUTER_KEY") or os.environ.get("OPENROUTER_API_KEY")
    if env_key and str(env_key).strip():
        return [str(env_key).strip()]
    return []


def openrouter_api_key(config: dict | None = None, *, rotate: bool = False) -> str:
    global _KEY_ROTATION_KEYS, _KEY_ROTATION_INDEX

    keys = openrouter_api_keys()
    if not keys:
        return ""
    if not rotate or len(keys) == 1:
        return keys[0]

    signature = tuple(keys)
    with _KEY_ROTATION_LOCK:
        if signature != _KEY_ROTATION_KEYS:
            _KEY_ROTATION_KEYS = signature
            _KEY_ROTATION_INDEX = 0
        selected = keys[_KEY_ROTATION_INDEX % len(keys)]
        _KEY_ROTATION_INDEX += 1
        return selected


def openrouter_model(config: dict | None = None) -> str:
    env_model = os.environ.get("LOCAL_IA_OPENROUTER_MODEL")
    if env_model and str(env_model).strip():
        return str(env_model).strip()

    data = config if config is not None else load_config()
    nested = data.get("openrouter", {})
    if isinstance(nested, dict):
        value = str(nested.get("model", "")).strip()
        if value:
            return value

    # Ne jamais retomber sur le modèle local du système (ex. "llama3.2:3b")
    # quand l'appel est destiné à OpenRouter. L'API OpenRouter exige un
    # identifiant de modèle OpenRouter, pas un nom Ollama.
    return str(DEFAULT_CONFIG["openrouter"]["model"]).strip()


def openrouter_base_url(config: dict | None = None) -> str:
    env_url = os.environ.get("LOCAL_IA_OPENROUTER_BASE_URL")
    if env_url and str(env_url).strip():
        return str(env_url).strip().rstrip("/")

    data = config if config is not None else load_config()
    nested = data.get("openrouter", {})
    value = nested.get("base_url") if isinstance(nested, dict) else None
    return str(value or DEFAULT_CONFIG["openrouter"]["base_url"]).rstrip("/")