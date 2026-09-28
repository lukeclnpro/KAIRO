"""Stockage JSON des conversations."""

from __future__ import annotations

import json
import re
import threading
from datetime import datetime
from pathlib import Path
from queue import Queue

from local_ia.config.manager import BASE_DIR

CHAT_DIR = BASE_DIR / "chats"
MAX_HISTORY = 8
_WRITE_QUEUE = Queue()
_WRITE_THREAD = None
_TOPIC_MARKER_RE = re.compile(
    r"\b(?:à\s+propos\s+de|au\s+sujet\s+de|concernant|sur|about|regarding|de)\s+(.+)",
    re.I,
)
_WEATHER_RE = re.compile(r"\b(?:m[ée]t[ée]o|weather|pr[ée]visions?)\b", re.I)
_PLACE_MARKER_RE = re.compile(r"\b(?:à|a|au|dans|in|at)\s+(.+)", re.I)
_CAPITALIZED_TOPIC_RE = re.compile(r"\b[A-ZÀ-ÖØ-Þ][\wÀ-ž'-]*\b")
_NON_TOPIC_CAPITALS = {
    "aujourd'hui", "bonjour", "combien", "comment", "donne", "est", "explique",
    "hello", "hey", "je", "le", "les", "macron", "parle", "peux", "pourquoi",
    "quel", "quelle", "quels", "quelles", "qui", "raconte", "salut", "vous",
}
_GENERIC_SUBJECTS = {
    "a", "au", "aux", "ce", "cela", "celle", "celui", "ces", "cette", "comment",
    "des", "du", "elle", "elles", "en", "il", "ils", "la", "le", "les", "leur",
    "leurs", "lui", "ma", "mes", "mon", "sa", "ses", "son", "ça", "the", "they",
}
_TRAILING_CONTEXT_RE = re.compile(
    r"\b(?:aujourd'hui|demain|maintenant|actuellement|ce soir|ce matin|cette nuit)\b.*$",
    re.I,
)


def _title_case(value):
    return " ".join(
        word if word.isupper() else word[:1].upper() + word[1:].lower()
        for word in value.split()
    )


def _clean_subject(value):
    value = re.split(r"[?!\n]", value, maxsplit=1)[0]
    value = _TRAILING_CONTEXT_RE.sub("", value)
    value = value.strip(" \t\r\n.,;:!?()[]{}\"'")
    value = re.sub(r"^(?:(?:le|la|les|un|une|des|du|de l['’])\s+|l['’])", "", value, flags=re.I)
    words = re.findall(r"[\wÀ-ž]+(?:['’-][\wÀ-ž]+)*", value)
    while words and words[-1].casefold() in {"a", "de", "du", "et", "est", "le", "la", "les"}:
        words.pop()
    if not words or words[0].casefold() in _GENERIC_SUBJECTS:
        return ""
    return " ".join(words[:4])


def derive_chat_title(message):
    """Build a short display title from an explicit topic in a user message."""
    text = str(message or "").strip()
    if not text or text.startswith("/"):
        return ""

    weather = _WEATHER_RE.search(text)
    if weather:
        remainder = text[weather.end():]
        place = _PLACE_MARKER_RE.search(remainder)
        subject = _clean_subject(place.group(1)) if place else ""
        return f"Météo à {_title_case(subject)}" if subject else "Météo"

    topic = _TOPIC_MARKER_RE.search(text)
    if topic:
        subject = _clean_subject(topic.group(1))
        if subject:
            return f"Questions sur {_title_case(subject)}"

    names = [
        name for name in _CAPITALIZED_TOPIC_RE.findall(text)
        if name.casefold() not in _NON_TOPIC_CAPITALS
    ]
    if names:
        return f"Questions sur {_title_case(' '.join(names[-2:]))}"
    return ""


def _refresh_chat_title(chat):
    messages = chat.get("messages", [])
    if not isinstance(messages, list):
        return
    latest_user_message = next(
        (
            item.get("content", "")
            for item in reversed(messages)
            if isinstance(item, dict) and item.get("role") == "user"
        ),
        "",
    )
    title = derive_chat_title(latest_user_message)
    if title:
        chat["title"] = title


def _ensure_writer():
    global _WRITE_THREAD
    if _WRITE_THREAD is not None and _WRITE_THREAD.is_alive():
        return
    def worker():
        while True:
            task = _WRITE_QUEUE.get()
            if task is None:
                _WRITE_QUEUE.task_done()
                break
            try:
                task()
            except Exception:
                pass
            finally:
                _WRITE_QUEUE.task_done()
    _WRITE_THREAD = threading.Thread(target=worker, daemon=True)
    _WRITE_THREAD.start()


def flush_writes():
    if _WRITE_QUEUE.qsize() == 0:
        return
    _WRITE_QUEUE.join()


def _write_chat_payload(chat):
    payload = json.loads(json.dumps(chat, ensure_ascii=False))
    chat_path(payload["id"]).write_text(json.dumps(payload, ensure_ascii=False, indent=4), encoding="utf-8")


def init_chats():
    CHAT_DIR.mkdir(parents=True, exist_ok=True)


def chat_path(chat_id):
    return CHAT_DIR / f"{int(chat_id)}.json"


def create_chat():
    init_chats()
    ids = [int(path.stem) for path in CHAT_DIR.glob("*.json") if path.stem.isdigit()]
    now = datetime.now().isoformat()
    chat = {"id": max(ids, default=0) + 1, "created_at": now, "updated_at": now, "title": "", "summary": "", "summary_updated_at": now, "topic": None, "messages": [], "files": []}
    save_chat(chat, async_mode=False)
    return chat


def save_chat(chat, async_mode=True):
    init_chats()
    if not isinstance(chat.get("title"), str):
        chat["title"] = ""
    _refresh_chat_title(chat)
    chat["updated_at"] = datetime.now().isoformat()
    if not isinstance(chat.get("summary_updated_at"), str) or not chat["summary_updated_at"]:
        chat["summary_updated_at"] = chat.get("updated_at")
    if async_mode:
        payload = json.loads(json.dumps(chat, ensure_ascii=False))
        _ensure_writer()
        _WRITE_QUEUE.put(lambda: _write_chat_payload(payload))
        return
    _write_chat_payload(chat)


def load_chat(chat_id):
    flush_writes()
    try:
        chat_id = int(chat_id)
    except (TypeError, ValueError):
        return None
    path = chat_path(chat_id)
    if not path.exists():
        return None
    try:
        chat = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(chat, dict):
        return None
    chat["id"] = chat_id
    if not isinstance(chat.get("summary"), str):
        chat["summary"] = ""
    if not isinstance(chat.get("title"), str):
        chat["title"] = ""
    if not isinstance(chat.get("summary_updated_at"), str):
        chat["summary_updated_at"] = chat.get("updated_at") or datetime.now().isoformat()
    if chat.get("topic") is not None and not isinstance(chat["topic"], str):
        chat["topic"] = None
    if not isinstance(chat.get("messages"), list):
        chat["messages"] = []
    if not isinstance(chat.get("files"), list):
        chat["files"] = []
    return chat


def list_chats():
    init_chats()
    chats = [load_chat(int(path.stem)) for path in CHAT_DIR.glob("*.json") if path.stem.isdigit()]
    return sorted((chat for chat in chats if chat), key=lambda item: int(item["id"]), reverse=True)


def get_chat_history(chat, limit=MAX_HISTORY):
    limit = max(0, int(limit))
    if limit == 0:
        return []
    messages = chat.get("messages", [])
    if not isinstance(messages, list):
        return []
    return [{"role": item["role"], "content": item["content"]} for item in messages[-limit:] if isinstance(item, dict) and item.get("role") in {"user", "assistant"}]


def add_chat_message(chat, role, content):
    chat.setdefault("messages", []).append({"role": role, "content": content, "created_at": datetime.now().isoformat()})
    save_chat(chat)


def clear_chat(chat):
    chat.update({"messages": [], "title": "", "summary": "", "summary_updated_at": datetime.now().isoformat(), "topic": None})
    chat.pop("pending_tool", None)
    chat.pop("pending_command", None)
    save_chat(chat)