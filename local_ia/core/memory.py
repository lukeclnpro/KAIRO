"""Mémoire persistante SQLite de l'assistant."""

from __future__ import annotations

import json
import math
import re
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from queue import Queue
from urllib.error import HTTPError
from local_ia.http_client import Request, open_url as urlopen

from local_ia.config.manager import load_config, ollama_base_url

DB_PATH = Path.home() / ".ia_agent" / "memory.db"
MAX_MEMORIES = 20
_EMBEDDING_CACHE = {}
_DEFAULT_EMBEDDING_MODEL = "nomic-embed-text"
_MEMORY_QUEUE = Queue()
_MEMORY_THREAD = None
_MEMORY_PATTERNS = [
    (re.compile(r"\b(?:je\s+pr[eé]f[eè]re|j'aime|je\s+n'aime\s+pas|je\s+veux\s+toujours|je\s+voudrais|je\s+souhaite)\b", re.I), "preference"),
    (re.compile(r"\b(?:j'utilise|je\s+travaille\s+avec|je\s+travaille\s+sur|je\s+pars\s+sur|mon\s+projet|je\s+suis\s+sur|je\s+pratique)\b", re.I), "context"),
    (re.compile(r"\b(?:je\s+m'appelle|mon\s+nom\s+est|j'habite|je\s+viens\s+de|j'ai\s+choisi|je\s+garde|rappelle-toi|souviens-toi)\b", re.I), "identity"),
]


def _terms(text):
    if not text:
        return set()
    text = text.casefold()
    return {
        token for token in re.findall(r"[a-z0-9]+", text)
        if len(token) > 1 and token not in {"de", "des", "le", "la", "les", "un", "une", "et", "ou", "pour", "avec", "sur"}
    }


def _lexical_embedding(text):
    terms = sorted(_terms(text))
    if not terms:
        return []
    dimension = len(terms)
    vector = [0.0] * dimension
    term_to_index = {term: index for index, term in enumerate(terms)}
    for term in terms:
        vector[term_to_index[term]] = 1.0
    return vector


def _cosine_similarity(a, b):
    if not a or not b:
        return 0.0
    if len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def _embedding_model_name():
    config = load_config()
    ollama_config = config.get("ollama", {})
    if not isinstance(ollama_config, dict):
        ollama_config = {}
    return str(
        config.get("embedding_model")
        or ollama_config.get("embedding_model")
        or _DEFAULT_EMBEDDING_MODEL
    ).strip()


def compute_embedding(text, model=None, timeout=None):
    value = str(text or "").strip()
    if not value:
        return []
    selected_model = str(model or "").strip() or _embedding_model_name()
    cache_key = (selected_model, value)
    if cache_key in _EMBEDDING_CACHE:
        return _EMBEDDING_CACHE[cache_key]
    try:
        config = load_config()
        request_timeout = timeout if timeout is not None else int(config.get("ollama", {}).get("timeout", 120))
        payload = json.dumps({"model": selected_model, "input": value}).encode("utf-8")
        request = Request(
            ollama_base_url(config) + "/api/embed",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=max(5, request_timeout)) as response:
            payload = json.loads(response.read().decode("utf-8"))
        embeddings = payload.get("embeddings")
        if isinstance(embeddings, list) and embeddings and isinstance(embeddings[0], list):
            vector = [float(number) for number in embeddings[0]]
            _EMBEDDING_CACHE[cache_key] = vector
            return vector
        embedding = payload.get("embedding")
        if isinstance(embedding, list):
            vector = [float(number) for number in embedding]
            _EMBEDDING_CACHE[cache_key] = vector
            return vector
    except HTTPError as error:
        error.close()
    except Exception:
        pass

    vector = _lexical_embedding(value)
    _EMBEDDING_CACHE[cache_key] = vector
    return vector


def init_database(path: Path | None = None):
    target = path or DB_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(target, check_same_thread=False)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS messages (id INTEGER PRIMARY KEY AUTOINCREMENT, conversation_id TEXT, role TEXT NOT NULL, content TEXT NOT NULL, created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS memories (id INTEGER PRIMARY KEY AUTOINCREMENT, content TEXT NOT NULL, created_at TEXT NOT NULL, embedding TEXT, embedding_model TEXT);
        CREATE TABLE IF NOT EXISTS topics (id INTEGER PRIMARY KEY AUTOINCREMENT, topic TEXT NOT NULL, created_at TEXT NOT NULL);
    """)
    memory_columns = {row[1] for row in conn.execute("PRAGMA table_info(memories)")}
    if "embedding" not in memory_columns:
        conn.execute("ALTER TABLE memories ADD COLUMN embedding TEXT")
    if "embedding_model" not in memory_columns:
        conn.execute("ALTER TABLE memories ADD COLUMN embedding_model TEXT")
    conn.commit()
    return conn


def _ensure_memory_writer():
    global _MEMORY_THREAD
    if _MEMORY_THREAD is not None and _MEMORY_THREAD.is_alive():
        return

    def worker():
        while True:
            task = _MEMORY_QUEUE.get()
            if task is None:
                _MEMORY_QUEUE.task_done()
                break
            try:
                task()
            except Exception:
                pass
            finally:
                _MEMORY_QUEUE.task_done()

    _MEMORY_THREAD = threading.Thread(target=worker, daemon=True)
    _MEMORY_THREAD.start()


def flush_memory_writes():
    if _MEMORY_QUEUE.qsize() == 0:
        return
    _MEMORY_QUEUE.join()


def save_memory(conn, content, async_mode=True):
    def write_memory():
        model = _embedding_model_name()
        embedding = json.dumps(compute_embedding(content, model=model), separators=(",", ":"))
        conn.execute(
            "INSERT INTO memories (content, created_at, embedding, embedding_model) VALUES (?, ?, ?, ?)",
            (content, datetime.now().isoformat(), embedding, model),
        )
        conn.commit()

    if async_mode:
        _ensure_memory_writer()
        _MEMORY_QUEUE.put(write_memory)
        return
    write_memory()


def list_memories(conn):
    flush_memory_writes()
    rows = conn.execute("SELECT id, content FROM memories ORDER BY id DESC").fetchall()
    return [{"id": row[0], "content": row[1]} for row in rows]


def delete_memory(conn, memory_id):
    flush_memory_writes()
    cursor = conn.execute("DELETE FROM memories WHERE id = ?", (int(memory_id),))
    conn.commit()
    return cursor.rowcount == 1


def clear_memories(conn):
    flush_memory_writes()
    cursor = conn.execute("DELETE FROM memories")
    conn.commit()
    return cursor.rowcount


def _memory_similarity(a, b):
    left = _terms(a)
    right = _terms(b)
    if not left and not right:
        return 0.0
    if not left or not right:
        return 0.0
    intersection = left & right
    return len(intersection) / max(1, len(left | right))


def extract_memory_candidate(text):
    cleaned = str(text or "").strip()
    if not cleaned or len(cleaned) < 8:
        return None
    if cleaned.endswith("?"):
        return None
    lowered = cleaned.lower()
    max_score = -1
    category = "context"
    for pattern, label in _MEMORY_PATTERNS:
        match = pattern.search(cleaned)
        if not match:
            continue
        score = len(match.group(0))
        if score > max_score:
            max_score = score
            category = label
    if max_score < 0:
        return None
    if any(token in lowered for token in ("bonjour", "salut", "merci", "merci beaucoup", "oui", "non")):
        return None
    return {"memory": cleaned, "category": category, "importance": 1}


def has_similar_memory(conn, candidate_text, threshold=0.6):
    if not candidate_text:
        return False
    for memory in get_memories(conn, limit=MAX_MEMORIES):
        if _memory_similarity(candidate_text, memory) >= threshold:
            return True
    return False


def save_memory_if_relevant(conn, content, async_mode=True):
    candidate = extract_memory_candidate(content)
    if not candidate:
        return False
    if has_similar_memory(conn, candidate["memory"], threshold=0.6):
        return False
    save_memory(conn, candidate["memory"], async_mode=async_mode)
    return True


def get_memories(conn, limit=MAX_MEMORIES, query=None):
    flush_memory_writes()
    limit = max(0, int(limit))
    if limit == 0:
        return []
    rows = conn.execute(
        "SELECT id, content, embedding, embedding_model FROM memories ORDER BY id DESC"
    ).fetchall()
    memories = [row[1] for row in rows]
    if query is None:
        return memories[:limit]

    query_terms = _terms(query)
    if not query_terms:
        return memories[:limit]

    selected_model = _embedding_model_name()
    query_embedding = compute_embedding(query, model=selected_model)
    ranked = []
    for index, (memory_id, item, stored_embedding, stored_model) in enumerate(rows):
        lexical_score = len(query_terms & _terms(item))
        semantic_score = 0.0
        item_embedding = None
        if stored_embedding and stored_model == selected_model:
            try:
                parsed_embedding = json.loads(stored_embedding)
                if isinstance(parsed_embedding, list):
                    item_embedding = [float(number) for number in parsed_embedding]
            except (TypeError, ValueError):
                item_embedding = None
        if item_embedding is None:
            item_embedding = compute_embedding(item, model=selected_model)
            conn.execute(
                "UPDATE memories SET embedding = ?, embedding_model = ? WHERE id = ?",
                (json.dumps(item_embedding, separators=(",", ":")), selected_model, memory_id),
            )
        if query_embedding and item_embedding:
            semantic_score = _cosine_similarity(query_embedding, item_embedding)
        total_score = lexical_score * 2.5 + semantic_score * 5.0
        if lexical_score or semantic_score > 0.15:
            ranked.append((total_score, lexical_score, index, item))

    if ranked:
        ranked.sort(key=lambda entry: (-entry[0], -entry[1], entry[2]))
        selected = [item for _, _, _, item in ranked[:limit]]
        if len(selected) < limit:
            seen = set(selected)
            for item in list(reversed(memories)):
                if item not in seen:
                    selected.append(item)
                    seen.add(item)
                if len(selected) >= limit:
                    break
            conn.commit()
        return selected

    selected = []
    seen = set()
    for item in list(reversed(memories)):
        if item in seen:
            continue
        selected.append(item)
        seen.add(item)
        if len(selected) >= limit:
            break
    conn.commit()
    return selected


def save_message(conn, conversation_id, role, content, async_mode=True):
    if async_mode:
        _ensure_memory_writer()
        _MEMORY_QUEUE.put(lambda: conn.execute("INSERT INTO messages (conversation_id, role, content, created_at) VALUES (?, ?, ?, ?)", (conversation_id, role, content, datetime.now().isoformat())) and conn.commit())
        return
    conn.execute("INSERT INTO messages (conversation_id, role, content, created_at) VALUES (?, ?, ?, ?)", (conversation_id, role, content, datetime.now().isoformat()))
    conn.commit()


def get_history(conn, conversation_id, limit=MAX_MEMORIES):
    flush_memory_writes()
    limit = max(0, int(limit))
    if limit == 0:
        return []
    rows = conn.execute("SELECT role, content FROM messages WHERE conversation_id = ? ORDER BY id DESC LIMIT ?", (conversation_id, limit)).fetchall()
    return [{"role": role, "content": content} for role, content in reversed(rows)]