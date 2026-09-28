"""Contexte permanent et construction du prompt système."""

from __future__ import annotations

import json
from pathlib import Path

from local_ia.config.manager import BASE_DIR

CONTEXT_PATH = BASE_DIR / "context.json"
DEFAULT_CONTEXT = {
    "langue": "français",
    "sujet": "assistant personnel généraliste",
    "ton": "naturel, clair et concis",
    "role": "assistant personnel local",
    "style": "conversationnel",
    "instructions": [],
}


def load_context(path: Path | None = None) -> dict:
    target = path or CONTEXT_PATH
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        data = {}
    result = dict(DEFAULT_CONTEXT)
    if isinstance(data, dict):
        result.update(data)
    return result


def build_system_prompt(memories, topic, context, external_info=None) -> str:
    language = str(context.get("langue", "français")).strip() or "français"
    instructions = context.get("instructions", [])
    if isinstance(instructions, list):
        instructions = "\n".join(f"- {item}" for item in instructions if str(item).strip())
    instructions = str(instructions).strip() or "Aucune instruction spécifique."
    memory_text = "\n".join(f"- {item}" for item in memories) or "Aucune mémoire enregistrée."
    return f"""Tu es {context.get('role', DEFAULT_CONTEXT['role'])}.

Langue obligatoire : {language}
Sujet général : {context.get('sujet', DEFAULT_CONTEXT['sujet'])}
Ton : {context.get('ton', DEFAULT_CONTEXT['ton'])}
Style : {context.get('style', DEFAULT_CONTEXT['style'])}
Sujet actuel : {topic or 'Non défini'}

Instructions spécifiques :
{instructions}

Mémoire utilisateur :
{memory_text}

Informations externes :
{external_info or 'Aucune information externe utilisée.'}

Réponds uniquement en {language}. Utilise l'historique et la mémoire
uniquement lorsqu'ils sont pertinents. N'invente aucune information."""