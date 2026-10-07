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


def _compact_prompt_block(lines, limit=4):
    items = [str(item).strip() for item in lines if str(item).strip()]
    selected = items[:limit]
    compact = "\n".join(f"- {item[:220]}" for item in selected if item)
    return compact or "Aucune information."


def build_system_prompt(memories, topic, context, external_info=None) -> str:
    language = str(context.get("langue", "français")).strip() or "français"
    instructions = context.get("instructions", [])
    if isinstance(instructions, list):
        instructions = _compact_prompt_block(instructions, limit=3)
    else:
        instructions = str(instructions).strip() or "Aucune instruction spécifique."
        instructions = instructions[:500]
    memories = list(memories)[:2]
    memory_text = "\n".join(f"- {str(item)[:220]}" for item in memories if str(item).strip()) or "Aucune mémoire enregistrée."
    external_summary = str(external_info or "Aucune information externe utilisée.").strip()[:500]
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
{external_summary}

Règles :
- Réponds d'abord au besoin réel, sans répétition.
- Si une donnée manque, dis-le clairement.
- Utilise les outils seulement quand c'est nécessaire.
- N'invente jamais une information.

Réponds uniquement en {language}."""