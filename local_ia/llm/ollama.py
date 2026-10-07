"""Client HTTP minimal pour Ollama et OpenRouter."""

from __future__ import annotations

import json
import threading
from urllib.error import HTTPError
from local_ia.http_client import Request, open_url as urlopen

from local_ia.config.manager import (
    load_config,
    model_config,
    ollama_base_url,
    openrouter_api_key,
    openrouter_base_url,
    openrouter_model,
)

DEFAULT_KEEP_ALIVE = "30m"
MAX_CONTEXT_TOKENS = 800
MAX_RESPONSE_TOKENS = 256
FALLBACK_OPENROUTER_MODEL = "openai/gpt-4o-mini"
_REQUEST_QUEUE_LOCK = threading.Lock()


def _estimate_tokens_text(value):
    text = value if isinstance(value, str) else str(value or "")
    if not text:
        return 0
    return max(1, len(text) // 4)


def _message_tokens(message):
    if not isinstance(message, dict):
        return 0
    content = message.get("content", "")
    if isinstance(content, list):
        text = "\n".join(
            str(part.get("text") or part.get("content") or "")
            for part in content
            if isinstance(part, dict)
        )
    else:
        text = str(content or "")
    role = str(message.get("role", "user") or "user")
    return _estimate_tokens_text(role) + _estimate_tokens_text(text) + 4


def _limit_messages_to_budget(messages, max_tokens=MAX_CONTEXT_TOKENS):
    safe_messages = []
    if not isinstance(messages, list):
        return safe_messages

    total = 0
    for message in messages:
        total += _message_tokens(message)

    if total <= max_tokens:
        return list(messages)

    retained = []
    current_tokens = 0
    for message in reversed(messages):
        msg_tokens = _message_tokens(message)
        if current_tokens + msg_tokens <= max_tokens:
            retained.append(message)
            current_tokens += msg_tokens
    retained.reverse()
    if retained:
        return retained
    return [{"role": "user", "content": "Réponse tronquée pour respecter la limite de contexte de 2000 tokens."}]


def _chunk_oversized_message(message, max_tokens=MAX_CONTEXT_TOKENS):
    if not isinstance(message, dict):
        return [message]

    content = message.get("content", "")
    if isinstance(content, list):
        text = "\n".join(
            str(part.get("text") or part.get("content") or "")
            for part in content
            if isinstance(part, dict)
        )
    else:
        text = str(content or "")

    if not text:
        return [message]

    chunk_size = max(256, max_tokens * 4)
    chunks = []
    for index in range(0, len(text), chunk_size):
        part = dict(message)
        part["content"] = text[index:index + chunk_size]
        chunks.append(part)
    return chunks


def _split_messages_for_queue(messages, max_tokens=MAX_CONTEXT_TOKENS):
    if not isinstance(messages, list):
        return [[]]

    chunks = []
    current = []
    current_tokens = 0

    for message in messages:
        if _message_tokens(message) > max_tokens:
            if current:
                chunks.append(current)
                current = []
                current_tokens = 0
            for sub_message in _chunk_oversized_message(message, max_tokens=max_tokens):
                sub_tokens = _message_tokens(sub_message)
                if sub_tokens > max_tokens:
                    sub_message["content"] = str(sub_message.get("content", ""))[: max(64, max_tokens * 4)]
                    sub_tokens = _message_tokens(sub_message)
                if current and current_tokens + sub_tokens > max_tokens:
                    chunks.append(current)
                    current = []
                    current_tokens = 0
                current.append(sub_message)
                current_tokens += sub_tokens
            continue

        msg_tokens = _message_tokens(message)
        if current and current_tokens + msg_tokens > max_tokens:
            chunks.append(current)
            current = []
            current_tokens = 0
        current.append(message)
        current_tokens += msg_tokens

    if current:
        chunks.append(current)

    return chunks if chunks else [[]]


def _merge_chunk_responses(parts):
    cleaned = [str(part).strip() for part in parts if str(part).strip()]
    if not cleaned:
        return ""
    return "\n\n".join(cleaned)


def _normalize_message_content(content):
    if content is None:
        return ""
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                text = item.get("text") or item.get("content") or ""
                if text:
                    parts.append(str(text).strip())
            else:
                text = str(item).strip()
                if text:
                    parts.append(text)
        text = "\n".join(part for part in parts if part)
        return text[:6000]
    if isinstance(content, dict):
        text = json.dumps(content, ensure_ascii=False, default=str).strip()
        return text[:6000]
    text = str(content).strip()
    return text[:6000]


def _normalize_openrouter_messages(messages):
    if not isinstance(messages, list):
        return [{"role": "user", "content": _normalize_message_content(messages)}]

    normalized = []
    for message in messages:
        if isinstance(message, str):
            normalized.append({"role": "user", "content": message})
            continue
        if not isinstance(message, dict):
            continue
        role = str(message.get("role") or "user").lower()
        if role not in {"user", "assistant", "system"}:
            role = "user"
        content = _normalize_message_content(message.get("content"))
        if not content.strip():
            continue
        normalized.append({"role": role, "content": content[:6000]})

    if not normalized:
        return [{"role": "user", "content": "Bonjour"}]
    return normalized


def key_usage_percent(messages, max_tokens=MAX_CONTEXT_TOKENS):
    if not isinstance(messages, list):
        return 0
    used_tokens = sum(_message_tokens(message) for message in messages if isinstance(message, dict))
    if max_tokens <= 0:
        return 0
    return min(100, int((used_tokens / max_tokens) * 100))


def openrouter_usage_status(messages, max_tokens=MAX_CONTEXT_TOKENS):
    used_tokens = sum(_message_tokens(message) for message in messages if isinstance(message, dict))
    percent = key_usage_percent(messages, max_tokens=max_tokens)
    return {
        "used_tokens": used_tokens,
        "max_tokens": max_tokens,
        "percent": percent,
        "remaining_tokens": max(0, max_tokens - used_tokens),
        "safe": percent < 100,
    }


def _openrouter_model_or_none(model):
    """N'utilise le modèle explicite que s'il s'agit d'un identifiant OpenRouter
    (ex. "openai/gpt-4o-mini"). Un nom de modèle Ollama comme "llama3.2:3b" ne
    veut rien dire pour OpenRouter : dans ce cas on renvoie None pour laisser
    ask_openrouter retomber sur le modèle configuré dans openrouter.model.
    """
    text = str(model or "").strip()
    if "/" in text:
        return text
    return None


def get_openrouter_key_usage(timeout=10, api_key=None):
    """Retourne les informations d'utilisation de la clé OpenRouter choisie ou active."""
    config = load_config()
    api_key = str(api_key or openrouter_api_key(config)).strip()
    if not api_key:
        raise ValueError("Aucune clé API OpenRouter n'est configurée pour cette session.")

    request = Request(
        openrouter_base_url(config) + "/key",
        headers={"Authorization": f"Bearer {api_key}"},
        method="GET",
    )
    with urlopen(request, timeout=max(5, int(timeout))) as response:
        result = json.loads(response.read().decode("utf-8"))

    data = result.get("data") if isinstance(result, dict) else None
    if not isinstance(data, dict):
        raise ValueError("Réponse d'utilisation OpenRouter invalide.")
    return data


class OllamaSession:
    """Session unique pour les appels Ollama avec keep_alive centralisé."""

    _instance = None

    def __init__(self, config=None):
        self.config = config if config is not None else load_config()
        self.keep_alive = self._resolve_keep_alive(self.config)

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @staticmethod
    def _resolve_keep_alive(config):
        nested = config.get("ollama", {}) if isinstance(config, dict) else {}
        if isinstance(nested, dict):
            value = nested.get("keep_alive")
            if value is not None and str(value).strip():
                return str(value).strip()
        return DEFAULT_KEEP_ALIVE

    def _request_settings(self, model=None, timeout=None, stream=False):
        config = load_config()
        nested = config.get("ollama", {}) if isinstance(config, dict) else {}
        selected_model = str(model or "").strip() or model_config(config)
        request_timeout = timeout if timeout is not None else (nested.get("timeout", 120) if isinstance(nested, dict) else 120)
        keep_alive = self._resolve_keep_alive(config)
        payload = {
            "model": selected_model,
            "messages": [],
            "stream": bool(stream),
            "keep_alive": keep_alive,
        }
        return {
            "config": config,
            "base_url": ollama_base_url(config),
            "payload": payload,
            "timeout": max(5, int(request_timeout)),
            "keep_alive": keep_alive,
            "model": selected_model,
        }

    def generate(self, messages, model=None, timeout=None, stream=None, max_tokens=None, api_key=None):
        config = load_config()
        if stream is None:
            stream = bool(config.get("ollama", {}).get("stream", False)) if isinstance(config.get("ollama", {}), dict) else False
        if api_key or openrouter_api_key(config):
            openrouter_options = {"api_key": api_key} if api_key else {}
            text = ask_openrouter(
                messages,
                model=_openrouter_model_or_none(model),
                timeout=timeout,
                max_tokens=max_tokens,
                **openrouter_options,
            )
            return text if not stream else [text]

        if stream:
            return list(self.stream(messages, model=model, timeout=timeout, max_tokens=max_tokens))

        messages = _limit_messages_to_budget(messages, MAX_CONTEXT_TOKENS)
        settings = self._request_settings(model=model, timeout=timeout, stream=False)
        payload = {
            "model": settings["model"],
            "messages": messages,
            "stream": False,
            "keep_alive": settings["keep_alive"],
        }
        if max_tokens is not None:
            payload["options"] = {"num_predict": max(1, int(max_tokens))}
        request = Request(
            settings["base_url"] + "/api/chat",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=settings["timeout"]) as response:
            result = json.loads(response.read().decode("utf-8"))
        return result.get("message", {}).get("content", "").strip()

    def stream(self, messages, model=None, timeout=None, max_tokens=None, api_key=None):
        config = load_config()
        if api_key or openrouter_api_key(config):
            openrouter_options = {"api_key": api_key} if api_key else {}
            text = ask_openrouter(
                messages,
                model=_openrouter_model_or_none(model),
                timeout=timeout,
                max_tokens=max_tokens,
                **openrouter_options,
            )
            if text:
                yield text
            return

        settings = self._request_settings(model=model, timeout=timeout, stream=True)
        payload = {
            "model": settings["model"],
            "messages": messages,
            "stream": True,
            "keep_alive": settings["keep_alive"],
        }
        if max_tokens is not None:
            payload["options"] = {"num_predict": max(1, int(max_tokens))}
        request = Request(
            settings["base_url"] + "/api/chat",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=settings["timeout"]) as response:
            for raw in response:
                if not raw:
                    continue
                if isinstance(raw, bytes):
                    raw = raw.decode("utf-8", errors="ignore")
                try:
                    part = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                content = part.get("message", {}).get("content") if isinstance(part, dict) else ""
                if isinstance(content, str) and content:
                    yield content

    def tool_call(self, messages, model=None, timeout=None):
        answer = self.generate(messages, model=model, timeout=timeout)
        if not answer:
            return None
        try:
            prefix = answer.split("<tool_call>", 1)[1].rsplit("</tool_call>", 1)[0]
            return json.loads(prefix)
        except (IndexError, ValueError, TypeError):
            return None

    def health_check(self):
        config = load_config()
        base_url = ollama_base_url(config)
        request = Request(base_url + "/api/version", method="GET")
        try:
            with urlopen(request, timeout=4) as response:
                payload = json.loads(response.read().decode("utf-8"))
            return {"ok": True, "details": payload}
        except Exception as exc:  # pragma: no cover - réseau hors ligne
            return {"ok": False, "error": str(exc)}


def _openrouter_content(result):
    if not isinstance(result, dict):
        return ""

    choices = result.get("choices") or []
    if not choices:
        return str(result.get("content", "") or "").strip()

    first = choices[0]
    if not isinstance(first, dict):
        return ""

    message = first.get("message") or {}
    if not isinstance(message, dict):
        return ""

    content = message.get("content")
    if isinstance(content, list):
        text_parts = []
        for part in content:
            if isinstance(part, dict):
                text = part.get("text") or part.get("content") or ""
                if isinstance(text, str):
                    text_parts.append(text)
        if text_parts:
            return "\n".join(text_parts).strip()

    if isinstance(content, str):
        return content.strip()

    return str(content or "").strip()


def _request_openrouter_once(messages, model=None, timeout=None, max_tokens=None, api_key=None):
    config = load_config()
    api_key = str(api_key or openrouter_api_key(config, rotate=True)).strip()
    if not api_key:
        raise ValueError("Clé API OpenRouter absente. Connectez-vous à un compte local depuis le menu.")

    nested = config.get("openrouter", {}) if isinstance(config.get("openrouter", {}), dict) else {}
    explicit_model = str(model or "").strip()
    if explicit_model and "/" in explicit_model:
        selected_model = explicit_model
    else:
        selected_model = openrouter_model(config)
    request_timeout = timeout if timeout is not None else nested.get("timeout", 120)
    cleaned_messages = _normalize_openrouter_messages(_limit_messages_to_budget(messages, MAX_CONTEXT_TOKENS))

    def _request_with_payload(payload):
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": str(nested.get("site_url") or "https://localhost"),
            "X-Title": str(nested.get("app_name") or "Local IA"),
        }
        request = Request(
            openrouter_base_url(config) + "/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        with urlopen(request, timeout=max(5, int(request_timeout))) as response:
            return json.loads(response.read().decode("utf-8"))

    def _detailed_http_error(exc):
        # exc.read() ne peut être lu qu'une seule fois : on le capture ici pour
        # remonter le vrai motif renvoyé par OpenRouter (clé invalide, modèle
        # inconnu, crédit épuisé, etc.) au lieu du générique "HTTP Error 400".
        try:
            raw_body = exc.read().decode("utf-8", errors="ignore")
        except Exception:
            raw_body = ""
        finally:
            exc.close()
        detail = raw_body
        try:
            parsed = json.loads(raw_body)
            if isinstance(parsed, dict):
                detail = (
                    (parsed.get("error") or {}).get("message")
                    if isinstance(parsed.get("error"), dict)
                    else parsed.get("error") or parsed.get("message") or raw_body
                )
        except (json.JSONDecodeError, TypeError):
            pass
        message = f"OpenRouter HTTP {exc.code} : {detail}" if detail else f"OpenRouter HTTP {exc.code} : {exc.reason}"
        return ValueError(message)

    response_limit = MAX_RESPONSE_TOKENS if max_tokens is None else max_tokens
    payload = {
        "model": selected_model,
        "messages": cleaned_messages,
        "stream": False,
        "max_tokens": min(4096, max(256, int(response_limit))),
    }

    try:
        result = _request_with_payload(payload)
    except HTTPError as exc:
        first_error = _detailed_http_error(exc)
        fallback = {
            "model": selected_model,
            "messages": cleaned_messages,
            "stream": False,
        }
        try:
            result = _request_with_payload(fallback)
        except HTTPError as exc2:
            second_error = _detailed_http_error(exc2)
            if (
                exc2.code == 404
                and "no endpoints found" in str(second_error).casefold()
                and selected_model != FALLBACK_OPENROUTER_MODEL
            ):
                fallback["model"] = FALLBACK_OPENROUTER_MODEL
                try:
                    result = _request_with_payload(fallback)
                except HTTPError as fallback_error:
                    raise _detailed_http_error(fallback_error) from second_error
            else:
                raise second_error from first_error

    return _openrouter_content(result)


def ask_openrouter(messages, model=None, timeout=None, max_tokens=None, api_key=None):
    chunks = _split_messages_for_queue(messages, MAX_CONTEXT_TOKENS)
    if len(chunks) == 1:
        return _request_openrouter_once(
            chunks[0], model=model, timeout=timeout, max_tokens=max_tokens, api_key=api_key
        )

    with _REQUEST_QUEUE_LOCK:
        parts = []
        for chunk in chunks:
            parts.append(
                _request_openrouter_once(
                    chunk, model=model, timeout=timeout, max_tokens=max_tokens, api_key=api_key
                )
            )
    return _merge_chunk_responses(parts)


def ask_ollama(messages, model=None, timeout=None, stream=None, max_tokens=None, api_key=None):
    if stream is None:
        config = load_config()
        stream = bool(config.get("ollama", {}).get("stream", False)) if isinstance(config.get("ollama", {}), dict) else False
    if stream:
        return OllamaSession.get_instance().stream(
            messages, model=model, timeout=timeout, max_tokens=max_tokens, api_key=api_key
        )
    return OllamaSession.get_instance().generate(
        messages, model=model, timeout=timeout, max_tokens=max_tokens, api_key=api_key
    )


def ask(messages, model=None, timeout=None, stream=None, max_tokens=None):
    return ask_ollama(messages, model=model, timeout=timeout, stream=stream, max_tokens=max_tokens)


def installed_models():
    try:
        with urlopen(ollama_base_url() + "/api/tags", timeout=4) as response:
            data = json.loads(response.read().decode("utf-8"))
        raw = data.get("models", []) if isinstance(data, dict) else data
        return {"models": [item for item in raw if isinstance(item, dict) and item.get("name")], "error": None}
    except Exception as exc:
        return {"models": [], "error": str(exc)}


__all__ = ["OllamaSession", "ask", "ask_ollama", "ask_openrouter", "installed_models"]