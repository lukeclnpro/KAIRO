"""Test manuel de connexion OpenRouter, distinct de la suite unitaire."""

from __future__ import annotations

import getpass
import json
import os
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from local_ia.http_client import Request, open_url as urlopen

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


def get_api_key() -> str:
    key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if key:
        return key
    value = getpass.getpass("Entrez votre clé API OpenRouter : ").strip()
    if not value:
        raise ValueError("La clé API OpenRouter est vide.")
    return value


def get_user_question() -> str:
    question = os.environ.get("OPENROUTER_TEST_QUESTION", "").strip()
    if question:
        return question
    value = input("Posez une question à l'IA : ").strip()
    if not value:
        raise ValueError("La question ne peut pas être vide.")
    return value


def ask_openrouter(api_key: str, question: str) -> str:
    payload = {
        "model": "openai/gpt-4o-mini",
        "messages": [{"role": "user", "content": question}],
        "stream": False,
        "max_tokens": 256,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://localhost",
        "X-Title": "Local IA API test",
    }
    request = Request(
        OPENROUTER_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    with urlopen(request, timeout=60) as response:
        result = json.loads(response.read().decode("utf-8"))

    choices = result.get("choices") or []
    if not choices:
        raise RuntimeError(f"Réponse OpenRouter invalide : {result}")
    content = choices[0].get("message", {}).get("content", "")
    if isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, dict):
                text = part.get("text") or part.get("content") or ""
                if text:
                    parts.append(str(text))
        content = "\n".join(parts)
    return str(content).strip() or "Aucune réponse reçue."


def main() -> None:
    try:
        api_key = get_api_key()
        question = get_user_question()
        answer = ask_openrouter(api_key, question)
        now = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        print(f"Heure : {now}")
        print(f"Question : {question}")
        print(f"Réponse : {answer}")
    except Exception as exc:
        print(f"Erreur lors du test OpenRouter : {exc}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()