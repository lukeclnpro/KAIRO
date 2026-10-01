"""Stockage JSON des conversations."""

from __future__ import annotations

import copy
import json
import re
import threading
from datetime import datetime
from queue import Queue

from local_ia.config.manager import BASE_DIR

CHAT_DIR = BASE_DIR / "chats"
MAX_HISTORY = 8
HISTORY_IMPORTANCE_DECAY = 0.75
_WRITE_QUEUE = Queue()
_WRITE_THREAD = None
_TOPIC_MARKER_RE = re.compile(
    r"\b(?:à\s+propos\s+de|au\s+sujet\s+de|concernant|sur|about|regarding|parle[- ]moi\s+de)\s+(.+)",
    re.I,
)
_WEATHER_RE = re.compile(r"\b(?:m[ée]t[ée]o|weather|pr[ée]visions?)\b", re.I)
_PLACE_MARKER_RE = re.compile(r"\b(?:à|a|au|dans|in|at)\s+(.+)", re.I)
_GREETING_RE = re.compile(r"^(?:bonjour|bonsoir|salut|hello|hey|coucou)\b[\s,!.:;-]*", re.I)
_TITLE_PREFIXES = (
    re.compile(r"^(?:s'il te plaît|s'il vous plaît|svp)\b[\s,!.:;-]*", re.I),
    re.compile(r"^(?:peux|pourrais|voudrais)[- ]tu\s+", re.I),
    re.compile(r"^(?:tu peux|tu pourrais|est-ce que tu peux)\s+", re.I),
    re.compile(r"^(?:m'aider|m'expliquer|m'indiquer)\s+(?:[àa]\s+)?", re.I),
    re.compile(r"^(?:explique(?:-moi)?|explique moi)\s+", re.I),
    re.compile(r"^(?:parle(?:-moi)?|parle moi)\s+(?:de\s+)?", re.I),
    re.compile(r"^(?:raconte(?:-moi)?|raconte moi)\s+", re.I),
    re.compile(r"^(?:dis[- ]moi|donne[- ]moi)\s+", re.I),
    re.compile(r"^aide[- ]moi\s+[àa]\s+", re.I),
    re.compile(r"^(?:j'aimerais|je voudrais|je veux)\s+(?:savoir|comprendre)\s+", re.I),
)
_QUESTION_PREFIX_RE = re.compile(
    r"^(?:quelle?\s+(?:est|sont)\s+|quels?\s+(?:est|sont)\s+|"
    r"comment\s+(?:fonctionne|marche|utiliser|faire)\s+|"
    r"comment\s+|pourquoi\s+|o[uù]\s+|quand\s+|qui\s+)",
    re.I,
)
_GENERIC_SUBJECTS = {
    "a", "au", "aux", "ce", "cela", "celle", "celui", "ces", "cette", "comment",
    "des", "du", "elle", "elles", "en", "il", "ils", "la", "le", "les", "leur",
    "leurs", "lui", "ma", "mes", "mon", "sa", "ses", "son", "ça", "the", "they",
}
_TRAILING_CONTEXT_RE = re.compile(
    r"\b(?:aujourd'hui|demain|maintenant|actuellement|ce soir|ce matin|cette nuit)\b.*$",
    re.I,
)


def _title_case(value, capitalize_words=True):
    small_words = {
        "à", "au", "aux", "avec", "dans", "de", "des", "du", "en", "et",
        "la", "le", "les", "pour", "un", "une",
    }
    words = value.split()
    titled = []
    for index, word in enumerate(words):
        if word.isupper():
            titled.append(word)
        elif index and (
            word.casefold() in small_words
            or word.casefold().startswith(("d'", "d’", "l'", "l’"))
        ):
            titled.append(word.casefold())
        elif index and not capitalize_words:
            titled.append(word)
        else:
            titled.append(word[:1].upper() + word[1:].lower())
    return " ".join(titled)


def _clean_subject(value):
    value = re.split(r"[?!\n]", value, maxsplit=1)[0]
    value = _TRAILING_CONTEXT_RE.sub("", value)
    value = value.strip(" \t\r\n.,;:!?()[]{}\"'")
    article = re.compile(r"^(?:le|la|les|un|une|des|du|de l['’])\s+|^l['’]", re.I)
    while article.search(value):
        value = article.sub("", value, count=1).strip()
    words = re.findall(r"[\wÀ-ž]+(?:['’-][\wÀ-ž]+)*", value)
    while words and words[-1].casefold() in {"a", "à", "de", "du", "et", "est", "le", "la", "les", "pour", "sur"}:
        words.pop()
    if not words or words[0].casefold() in _GENERIC_SUBJECTS:
        return ""
    return " ".join(words[:6])


def _remove_title_openers(text):
    value = _GREETING_RE.sub("", text).strip()
    while value:
        shortened = value
        for pattern in _TITLE_PREFIXES:
            shortened = pattern.sub("", value, count=1)
            if shortened != value:
                break
        else:
            shortened = _QUESTION_PREFIX_RE.sub("", value, count=1)
        if shortened == value:
            break
        value = shortened.strip(" \t,.:;-!")
    return value


def derive_chat_title(message):
    """Build a short display title from the subject of a user message."""
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

    subject = _remove_title_openers(text)
    subject = re.sub(r"^(?:qu'est-ce que|est-ce que)\s+", "", subject, flags=re.I)
    subject = _clean_subject(subject)
    return _title_case(subject, capitalize_words=False) if subject else ""


def _refresh_chat_title(chat):
    messages = chat.get("messages", [])
    if not isinstance(messages, list):
        return
    for item in messages:
        if not isinstance(item, dict) or item.get("role") != "user":
            continue
        title = derive_chat_title(item.get("content", ""))
        if title:
            chat["title"] = title
            return


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
    chat_path(chat["id"]).write_text(
        json.dumps(chat, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )


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
        payload = copy.deepcopy(chat)
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


def get_weighted_chat_history(chat, limit=MAX_HISTORY):
    """Return a copy of recent messages annotated with recency importance."""
    history = get_chat_history(chat, limit=limit)
    message_count = len(history)
    weighted_history = []
    for index, item in enumerate(history):
        age = message_count - index - 1
        importance = int(100 * HISTORY_IMPORTANCE_DECAY ** age)
        weighted_history.append({
            "role": item["role"],
            "content": f"[Importance: {importance}%] {item['content']}",
        })
    return weighted_history


def add_chat_message(chat, role, content):
    chat.setdefault("messages", []).append({"role": role, "content": content, "created_at": datetime.now().isoformat()})
    save_chat(chat)


def clear_chat(chat):
    chat.update({"messages": [], "title": "", "summary": "", "summary_updated_at": datetime.now().isoformat(), "topic": None})
    chat.pop("pending_tool", None)
    chat.pop("pending_command", None)
    save_chat(chat)