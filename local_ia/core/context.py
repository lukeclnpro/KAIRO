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

REQUEST_WORKFLOW = """Méthode de traitement des demandes :
- Classe chaque demande comme question simple, question complexe ou demande nécessitant un outil; précise la sous-catégorie et les outils utiles.
- Pour une question simple, réponds directement sans afficher de plan superflu.
- Pour une demande complexe ou avec outil, découpe le travail en tâches courtes, chacune avec une action unique, un résultat vérifiable, ses outils éventuels et ses dépendances. Suis pour chacune le statut À faire, En cours, Réussie, Échec ou À vérifier, ainsi que le nombre de tentatives.
- Exécute les tâches dans l'ordre et vérifie le résultat attendu, pas seulement l'exécution de l'outil. Après un échec, explique brièvement la cause et réessaie uniquement cette tâche, au maximum deux tentatives; conserve les tâches réussies et ne poursuis que si les tâches suivantes restent réalisables.
- Ne déclare jamais une action réussie sans preuve suffisante. Si le résultat est incertain, indique-le; si un blocage persiste, explique ce qui manque et ce qui reste à faire.
- À la fin d'un travail complexe ou avec outil, compare le résultat à la demande initiale et donne un bilan concis : demande, tâches réussies/total, tâches échouées ou incomplètes, taux de satisfaction estimé de 0 à 100 %, justification factuelle et prochaine action. Le taux reflète les objectifs réellement atteints, l'exactitude, les contraintes et les éléments manquants; ne le gonfle pas.
- Présente le plan et les statuts à l'utilisateur lorsqu'ils l'aident à suivre un travail complexe; reste concis et ne révèle pas de raisonnement interne détaillé."""


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
- Ne montre jamais ton raisonnement interne, tes brouillons ou tes commentaires sur les consignes, le budget de tokens ou le processus de génération. Réponds directement avec le seul contenu utile à l'utilisateur; retire toute réflexion ou préambule méta avant l'envoi.

{REQUEST_WORKFLOW}

Réponds uniquement en {language}."""