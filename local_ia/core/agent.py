"""Facade métier composant contexte, mémoire, conversations et Ollama.

Pour agir vite sur le PC, l'agent a trois niveaux :
1. la « voie rapide » : « ouvre firefox », « baisse le volume » sont exécutés
   directement, sans appeler le modèle (réponse instantanée) ;
2. une boucle d'outils : le modèle enchaîne plusieurs outils (lire, corriger,
   relancer…) jusqu'à avoir terminé ;
3. une confirmation avant les actions risquées (suppression, sudo, install…).
"""

from __future__ import annotations

import json
import logging
import re
import unicodedata
from datetime import date
from pathlib import Path

import application_launcher
import command_commands
import program_commands
from local_ia.config.manager import model_config, openrouter_api_keys
from local_ia.core.context import load_context
from local_ia.core.context_compiler import ContextCompiler
from local_ia.core.conversation import get_weighted_chat_history
from local_ia.core.memory import get_memories, init_database
from local_ia.core.router import RequestRouter
from local_ia.llm.ollama import ask_ollama
from local_ia.tools import download as download_tool, system
from local_ia.core.tool_manager import ToolManager

TOOL_NAMES = set(ToolManager.ALL_TOOLS)
TOOL_INSTRUCTIONS = ToolManager.build_prompt(TOOL_NAMES)
TOOL_ALIASES = {
    "read_file": "file", "read": "file",
    "create_file": "write", "write_file": "write",
    "edit_file": "edit", "replace": "edit", "patch": "edit", "modify_file": "edit",
    "list_dir": "list", "list_directory": "list", "listing": "list", "ls": "list", "dir": "list",
    "grep": "search", "find": "search", "search_files": "search",
    "launch_application": "launch",
    "open_url": "open_page", "open_website": "open_page", "browse_page": "open_page",
    "execute_command": "command", "run_command": "command", "run": "command",
    "volume": "system", "install": "system", "update": "system",
}
PAYLOAD_KEYS = (
    "name", "argv", "path", "content", "extension", "action", "value", "amount",
    "old", "new", "replace_all", "append", "pattern", "cwd", "timeout", "max_results", "query", "category", "url",
)

MAX_TOOL_STEPS = 4
MAX_CHUNKED_WRITE_STEPS = 128
MAX_TOOL_RESULT_CHARS = 2500
LOCAL_CODE_MAX_RESPONSE_TOKENS = 4096
MAX_MULTI_KEY_STAGES = 8
MAX_TOOL_STEPS_BY_MODE = {
    "tool": 3,
    "code": 8,
    "agent": MAX_TOOL_STEPS,
    "local_code": 12,
    "chat": 0,
    "command_suggestion": 0,
    "direct": 0,
}
CONFIRMATIONS = {
    "oui", "yes", "ok", "d'accord", "d accord", "je confirme", "confirme", "confirmé",
    "oui je confirme", "vas-y", "go", "c'est bon",
}
# Mots qui montrent que l'utilisateur attend autre chose que l'action elle-même.
FOLLOW_UP_RE = re.compile(
    r"\b(puis|ensuite|apr[eè]s|et dis|dis-moi|montre-moi|et montre|et affiche|then)\b", re.I
)
_CREATED_FILE_RE = re.compile(
    r"^\s*Fichier\s+(?:créé\s+ou\s+modifié|créé|modifié)\s*:\s*(?P<path>.+?)\s*$",
    re.I | re.M,
)
MULTI_PART_WRITE_RE = re.compile(
    r"\b(?:plusieurs|multiples|diff[ée]rents?)\s+(?:blocs?|parties|segments)\b", re.I
)
LARGE_FILE_REQUEST_RE = re.compile(
    r"\b(?:tr[eè]s\s+grand|gros|grosse|[ée]norme|immense|gigantesque|volumineux|sans\s+limite)\b",
    re.I,
)

_POLITE = r"(?:(?:peux-tu|pourrais-tu|tu peux|je veux|je voudrais|j'aimerais|s'il te pla[iî]t)\s+)*"
_LAUNCH_RE = re.compile(
    _POLITE + r"(?:lance|lancer|ouvre|ouvrir|d[ée]marre|d[ée]marrer)\s+(?P<name>.+?)"
    r"\s*(?:s'il te pla[iî]t|stp)?[.!?]*$",
    re.I,
)
_NAME_PREFIX_RE = re.compile(
    r"^(?:l'|le |la |les |un |une |mon |ma |application |appli |app |programme |logiciel )+", re.I
)
_NOT_AN_APP = re.compile(r"^(?:fichier|dossier|r[ée]pertoire|document|lien|site|page|url|http)", re.I)
_FILE_EXTENSION_RE = re.compile(r"\.[A-Za-z0-9]{1,5}$")
_AMOUNT = r"(?:\s+de\s+(?P<amount>\d{1,3})\s*%?)?[.!]*$"
_SYSTEM_INFO_RE = re.compile(
    r"^(?:quel(?:le)?(?: est)?\s+(?:mon\s+)?(?:syst[eè]me(?: d'exploitation)?|os)"
    r"(?:\s+(?:j'utilise|utilise-je|sur mon pc))?|quelle version (?:de )?(?:mon )?(?:syst[eè]me|os))\s*[?.!]*$",
    re.I,
)
_DATE_RE = re.compile(
    r"^(?:on est quel jour|quel jour (?:sommes-nous|est-on|on est|est-il)|"
    r"quelle est la date|quelle date(?: sommes-nous| est-on| du jour)?|on est le combien)"
    r"(?: aujourd'hui)?\s*[?.!]*$",
    re.I,
)
_APP_PATH_RE = re.compile(
    r"(?P<path>(?:~[/\\]|/|[A-Za-z]:[\\/]|\.{1,2}[/\\])[^<>\r\n]+)"
)
_APP_PATH_CONTEXT_RE = re.compile(
    r"\b(?:application|appli|app|logiciel|chemin|install[ée]e?|se trouve|ici)\b",
    re.I,
)
_APP_ALIAS_RE = re.compile(
    r"^(?:le\s+)?(?:chemin|alias|nom)\s+(?:de|pour)\s+"
    r"(?:(?:l['’])?(?:application|appli|app)\s+)?"
    r"(?P<alias>[\w][\w .'-]*?)\s+(?:c['’]est|est|=|:)\s+(?P<target>.+?)\s*[.!?]*$",
    re.I,
)
_APP_PC_ALIAS_RE = re.compile(
    r"^(?:sur|dans)\s+(?:mon|le)\s+pc\s*[,;:]?\s*"
    r"(?P<alias>[\w][\w .'-]*?)\s+(?:c['’]est|est|=|s'appelle|correspond à)\s+"
    r"(?P<target>.+?)\s*[.!?]*$",
    re.I,
)
_APP_CORRECTION_RE = re.compile(
    r"^(?:c['’]est|(?:elle|il)\s+s['’]app?elle|(?:son|leur)\s+nom\s+est)\s+"
    r"(?P<name>.+?)\s*[.!?]*$",
    re.I,
)
_FAILED_LAUNCH_RE = re.compile(
    r"\b(?:introuvable|ne\s+\w+\s+pas|pas\s+(?:install[ée]e?|reconnu|accessible)|"
    r"impossible|[ée]chou[ée])\b",
    re.I,
)
_VOLUME_RULES = (
    (re.compile(_POLITE + r"(?:baisse|diminue|r[ée]duis)\s+(?:un peu\s+)?le\s+(?:volume|son)" + _AMOUNT, re.I),
     "down", "Volume baissé."),
    (re.compile(_POLITE + r"(?:monte|augmente)\s+(?:un peu\s+)?le\s+(?:volume|son)" + _AMOUNT, re.I),
     "up", "Volume augmenté."),
    (re.compile(_POLITE + r"(?:coupe le (?:son|volume)|mets? en sourdine|mute)[.!]*$", re.I),
     "mute", "Son coupé."),
    (re.compile(_POLITE + r"(?:remets? le son|r[ée]active le son|d[ée]sactive la sourdine|unmute)[.!]*$", re.I),
     "unmute", "Son rétabli."),
)


class RequestKeySequence:
    def __init__(self, keys):
        self.keys = tuple(str(key).strip() for key in keys if str(key).strip())
        self.index = 0

    def key_for_stage(self, stage):
        if not self.keys:
            return None
        return self.keys[max(0, int(stage)) % len(self.keys)]

    def next_key(self):
        key = self.key_for_stage(self.index)
        if self.keys:
            self.index += 1
        return key


class LocalAgent:
    @staticmethod
    def _contextual_app_correction(chat, message, allowed_tools=None):
        if allowed_tools is not None and "launch" not in allowed_tools:
            return None
        correction = _APP_CORRECTION_RE.fullmatch(str(message or "").strip())
        if not correction:
            return None
        corrected_name = correction.group("name").strip(" .!?\"'")

        messages = chat.get("messages", [])
        for index in range(len(messages) - 1, -1, -1):
            item = messages[index]
            if item.get("role") != "user":
                continue
            launch_request = _LAUNCH_RE.fullmatch(str(item.get("content", "")).strip())
            if not launch_request:
                continue
            assistant_reply = next(
                (entry.get("content", "") for entry in messages[index + 1:] if entry.get("role") == "assistant"),
                "",
            )
            if not _FAILED_LAUNCH_RE.search(assistant_reply):
                return None

            requested_name = _NAME_PREFIX_RE.sub(
                "", launch_request.group("name").strip()
            ).strip(" .!?\"'")
            try:
                application_launcher.register_application_alias(requested_name, corrected_name)
                launched = application_launcher.launch_application(requested_name)
            except (FileNotFoundError, OSError, ValueError) as error:
                return f"J'ai compris que {requested_name} s'appelle {corrected_name}, mais le lancement a échoué : {error}"
            return f"{launched.get('name', corrected_name)} associé à {requested_name} et lancé."
        return None

    @staticmethod
    def normalize_tool_call(tool_call):
        if not isinstance(tool_call, dict):
            return ""
        payload = {"tool": str(tool_call.get("tool", "")), "arguments": tool_call.get("arguments", {})}
        return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)

    @staticmethod
    def get_max_tool_steps(route=None):
        mode = str((route or {}).get("mode") or "agent").lower()
        if mode in MAX_TOOL_STEPS_BY_MODE:
            return MAX_TOOL_STEPS_BY_MODE[mode]
        return MAX_TOOL_STEPS

    @staticmethod
    def _cache_signature(value):
        return json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)

    def __init__(self, model=None):
        self.model = model or model_config()
        self.context = load_context()
        self.connection = init_database()
        self.memories = get_memories(self.connection)
        self.router = RequestRouter()
        self.context_compiler = ContextCompiler()
        self._prepared_prompts = {}
        self._tool_cache = {}
        self._context_cache = {}
        self.generated_downloads = []

    def reload_context(self):
        self.context = load_context()
        self._prepared_prompts.clear()
        self._context_cache.clear()
        self._tool_cache.clear()

    def reload_memories(self):
        self.memories = get_memories(self.connection)
        self._prepared_prompts.clear()
        self._context_cache.clear()
        self._tool_cache.clear()

    def prepare_chat(self, chat, message="", route=None, tools=None):
        if not hasattr(self, "_prepared_prompts"):
            self._prepared_prompts = {}
        if not hasattr(self, "_tool_cache"):
            self._tool_cache = {}
        if not hasattr(self, "_context_cache"):
            self._context_cache = {}

        selected_tools = set(TOOL_NAMES if tools is None else tools)
        route = route or {"mode": "agent", "tools": tuple(sorted(selected_tools))}
        context_sig = self._cache_signature(self.context)
        memory_sig = self._cache_signature(self.memories)
        tool_key = tuple(sorted(selected_tools))
        tool_prompt = self._tool_cache.get(tool_key)
        if tool_prompt is None:
            tool_prompt = ToolManager.build_prompt(selected_tools)
            self._tool_cache[tool_key] = tool_prompt

        key = (
            chat.get("id"),
            chat.get("topic"),
            str(message or "") if route.get("mode") in {"code", "local_code"} else None,
            tool_key,
            str(route).lower(),
            context_sig,
            memory_sig,
            self.model,
        )
        if key not in self._prepared_prompts:
            prompt = self.context_compiler.compile(
                chat,
                self.context,
                self.memories,
                message=message,
                route=route,
                allow_tools=selected_tools,
                tool_prompt=tool_prompt,
            )
            self._prepared_prompts[key] = (prompt, prompt)
        return self._prepared_prompts[key]

    def build_messages(self, chat, message, external_info=None, include_tools=True, tools=None, route=None):
        selected_tools = (TOOL_NAMES if tools is None else set(tools)) if include_tools else set()
        route = route or {"mode": "agent", "tools": tuple(sorted(selected_tools))}
        prompts = self.prepare_chat(chat, message=message, route=route, tools=selected_tools)
        prompt = prompts[1 if include_tools else 0]
        if external_info:
            prompt += "\n\n" + str(external_info)
        history = [] if route.get("mode") in {"code", "local_code"} else get_weighted_chat_history(chat)
        return [{"role": "system", "content": prompt}, *history, {"role": "user", "content": message}]

    # ------------------------------------------------------------------
    # Voie rapide : aucune génération, l'action est faite tout de suite.
    # ------------------------------------------------------------------
    def fast_path(self, message, allowed_tools=None):
        """Exécute directement les demandes simples. Retourne None si le modèle doit décider."""
        text = str(message or "").strip()
        if not text or "\n" in text:
            return None

        if "<tool_call>" in text.casefold():
            return None

        handlers = (
            self._fast_path_application_alias,
            self._fast_path_application_path,
            self._fast_path_date,
            self._fast_path_volume,
            self._fast_path_system_info,
            self._fast_path_launch,
        )
        for handler in handlers:
            answer = handler(text, allowed_tools)
            if answer is not None:
                return answer
        return None

    def _fast_path_application_alias(self, text, allowed_tools):
        alias_match = _APP_ALIAS_RE.fullmatch(text) or _APP_PC_ALIAS_RE.fullmatch(text)
        if not alias_match:
            return None

        alias = alias_match.group("alias").strip(" .!?\"'")
        target = alias_match.group("target").strip().strip("\"'`").rstrip(".,;:!?")
        try:
            target_path = Path(target).expanduser()
            target_is_path = (
                target_path.is_absolute()
                or target_path.exists()
                or bool(re.match(r"^[A-Za-z]:[\\/]", target))
            )
        except (OSError, ValueError):
            target_is_path = bool(re.match(r"^[A-Za-z]:[\\/]", target))
        try:
            application = application_launcher.register_application_alias(alias, target)
        except (FileNotFoundError, OSError, ValueError) as error:
            return f"Je n'ai pas pu associer {alias} à {target} : {error}"
        if target_is_path:
            return f"Chemin de {application['name']} enregistré sous le nom {alias}."
        return f"{alias} associé à {application['name']} pour les prochains lancements."

    def _fast_path_application_path(self, text, allowed_tools):
        if _LAUNCH_RE.fullmatch(text) or not _APP_PATH_CONTEXT_RE.search(text):
            return None
        path_match = _APP_PATH_RE.search(text)
        if not path_match:
            return None

        application_path = path_match.group("path").strip().strip("\"'`").rstrip(".,;:!?")
        try:
            application = application_launcher.register_application("", application_path)
        except (FileNotFoundError, OSError, ValueError) as error:
            return f"Je n'ai pas pu enregistrer ce chemin d'application : {error}"
        return f"Chemin de {application['name']} enregistré pour les prochains lancements."

    def _fast_path_date(self, text, allowed_tools):
        if _DATE_RE.fullmatch(text):
            today = date.today()
            weekdays = (
                "lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche",
            )
            months = (
                "janvier", "février", "mars", "avril", "mai", "juin",
                "juillet", "août", "septembre", "octobre", "novembre", "décembre",
            )
            return (
                f"Aujourd'hui, nous sommes le {weekdays[today.weekday()]} "
                f"{today.day} {months[today.month - 1]} {today.year}."
            )
        return None

    def _fast_path_volume(self, text, allowed_tools):
        for pattern, action, answer in _VOLUME_RULES:
            match = pattern.fullmatch(text)
            if not match:
                continue
            if allowed_tools is not None and "system" not in allowed_tools:
                return None
            amount = int(match.groupdict().get("amount") or 5)
            try:
                result = system.use(action, None, amount)
            except Exception as error:
                return f"Action impossible : {error}"
            if isinstance(result, dict) and result.get("returncode"):
                return f"Le volume n'a pas pu être modifié : {result.get('stderr') or 'erreur inconnue'}"
            return answer
        return None

    def _fast_path_system_info(self, text, allowed_tools):
        if _SYSTEM_INFO_RE.fullmatch(text):
            if allowed_tools is not None and "system" not in allowed_tools:
                return None
            try:
                info = system.use("info")
            except Exception as error:
                return f"Informations système indisponibles : {error}"
            return (
                f"Système : {info.get('system', 'inconnu')} "
                f"{info.get('release', '')} ({info.get('machine', 'architecture inconnue')})"
            ).strip()
        return None

    def _fast_path_launch(self, text, allowed_tools):
        match = _LAUNCH_RE.fullmatch(text)
        if not match:
            return None
        name = _NAME_PREFIX_RE.sub("", match.group("name").strip()).strip(" .!?\"'")
        try:
            requested_path = Path(name).expanduser()
            is_path = requested_path.is_absolute() or requested_path.exists()
        except (OSError, ValueError):
            is_path = bool(re.match(r"^[A-Za-z]:[\\/]", name))
        if (
            not name
            or (("/" in name or "\\" in name) and not is_path)
            or _NOT_AN_APP.match(name)
            or (_FILE_EXTENSION_RE.search(name) and not is_path)
            or (len(name.split()) > 4 and not is_path)
        ):
            return None
        if allowed_tools is not None and "launch" not in allowed_tools:
            return None
        try:
            found = application_launcher.find_application(name)
        except Exception:
            return None
        if not found:
            return None  # inconnu : le modèle décidera (fichier, site, faute de frappe…)
        try:
            launched = application_launcher.launch_application(name)
        except Exception as error:
            return f"Impossible de lancer {found.get('name', name)} : {error}"
        return f"{(launched or found).get('name', name)} lancé."

    # ------------------------------------------------------------------
    # Lecture des appels d'outils écrits par le modèle
    # ------------------------------------------------------------------
    @staticmethod
    def parse_tool_call(content):
        text = str(content or "")
        match = re.search(r"<tool_call>\s*(.*?)(?:</tool_call>|$)", text, re.S | re.I)
        wrapper_name = None
        if match:
            raw_payload = match.group(1).strip()
            raw_payload = re.sub(r"^```(?:json)?\s*", "", raw_payload, flags=re.I)
            raw_payload = re.sub(r"\s*```\s*$", "", raw_payload)
        else:
            # Tolère les balises simplifiées émises par certains petits modèles,
            # par exemple : <write{"tool":"file",...})
            match = re.search(
                r"<(write(?:\.py)?|file|launch|open_page|open_url|command|system|edit|list|search|web)\s*(\{.*)",
                text,
                re.S | re.I,
            )
            if match:
                wrapper_name = match.group(1).lower()
        if not match:
            return None
        if wrapper_name:
            raw_payload = match.group(2)
        decode_input = raw_payload.lstrip()
        try:
            payload, end = json.JSONDecoder().raw_decode(decode_input)
        except json.JSONDecodeError:
            try:
                # Accepte une accolade finale en trop et les apostrophes
                # échappées comme dans une chaîne Python.
                decode_input = decode_input.replace("\\'", "'")
                payload, end = json.JSONDecoder().raw_decode(decode_input)
            except json.JSONDecodeError:
                return None
        trailing = decode_input[end:].strip()
        if trailing and not (wrapper_name and trailing == "}"):
            return None
        if not isinstance(payload, dict):
            return None
        raw_tool = wrapper_name or payload.get("tool") or payload.get("name")
        if not isinstance(raw_tool, str):
            return None
        inferred_name = not wrapper_name and not payload.get("tool") and payload.get("name") == raw_tool
        if raw_tool.endswith(".py"):
            raw_tool = raw_tool[:-3]
        if wrapper_name == "write" and payload.get("content") is not None:
            raw_tool = "write"
        tool_name = TOOL_ALIASES.get(raw_tool, raw_tool)
        if tool_name not in TOOL_NAMES:
            return None
        arguments = payload.get("arguments", {})
        arguments = dict(arguments) if isinstance(arguments, dict) else {}
        # Certains modèles placent les paramètres directement dans l'appel.
        for key in PAYLOAD_KEYS:
            if key == "name" and inferred_name:
                continue
            if key in payload and key not in arguments:
                arguments[key] = payload[key]
        if raw_tool == "volume":
            arguments.setdefault("action", arguments.get("value", "up"))
        elif raw_tool == "install":
            arguments.setdefault("action", "install")
        elif raw_tool == "update":
            arguments.setdefault("action", "update")
        return {"tool": tool_name, "arguments": arguments}

    # ------------------------------------------------------------------
    # Exécution des outils
    # ------------------------------------------------------------------
    def execute_tool(self, tool_call, chat, allowed_tools=None):
        return ToolManager.execute(tool_call, chat, self.connection, allowed_tools)

    @staticmethod
    def _tool_message(tool_name, payload, verification=None):
        text = ToolManager.compact_result(payload, MAX_TOOL_RESULT_CHARS)
        if verification is not None:
            receipt = ToolManager.compact_result(verification, 600)
            text += f"\nVérification indépendante :\n{receipt}"
        return {"role": "tool", "content": f"Résultat de l'outil {tool_name} :\n{text}"}

    @staticmethod
    def _report_progress(progress_callback, message):
        if progress_callback is None:
            return
        try:
            progress_callback(str(message))
        except Exception as error:
            logging.getLogger(__name__).debug(
                "Le retour de progression a échoué (%s)", type(error).__name__
            )

    def _ask_with_api_key(self, messages, api_key=None, max_tokens=None, stream=None):
        options = {"model": self.model}
        if max_tokens is not None:
            options["max_tokens"] = max_tokens
        if stream is not None:
            options["stream"] = stream
        if api_key:
            options["api_key"] = api_key
        return ask_ollama(list(messages), **options)

    @staticmethod
    def _parse_stage_plan(response, request, stage_limit):
        text = str(response or "").strip()
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.I)
        match = re.search(r"\{.*\}", text, re.S)
        try:
            payload = json.loads(match.group(0)) if match else {}
        except json.JSONDecodeError:
            payload = {}
        steps = payload.get("steps") if isinstance(payload, dict) else None
        if not isinstance(steps, list):
            return [request]
        normalized = [str(step).strip() for step in steps if isinstance(step, str) and step.strip()]
        return normalized[:max(1, min(int(stage_limit), MAX_MULTI_KEY_STAGES))] or [request]

    def _plan_tool_stages(self, message, messages, key_sequence, progress_callback=None):
        if len(key_sequence.keys) <= 1:
            return []
        self._report_progress(progress_callback, "Découpage en étapes selon les clés disponibles…")
        planner_messages = [
            {
                "role": "system",
                "content": (
                    "Prépare un plan interne, sans exécuter d'outil et sans répondre à l'utilisateur. "
                    "Découpe la demande en nombre MINIMAL d'étapes logiques, au maximum "
                    f"{min(len(key_sequence.keys), MAX_MULTI_KEY_STAGES)}. "
                    "Pour une modification de code, regroupe toutes les modifications d'un même fichier dans une étape "
                    "et répartis les fichiers indépendants entre les étapes. "
                    'Retourne uniquement un JSON: {"steps":["étape 1", "étape 2"]}. '
                    "Si une seule étape suffit, n'en retourne qu'une."
                ),
            },
            {
                "role": "user",
                "content": json.dumps({"request": message}, ensure_ascii=False),
            },
        ]
        plan = self._ask_with_api_key(
            planner_messages,
            api_key=key_sequence.next_key(),
            max_tokens=1000,
        )
        steps = self._parse_stage_plan(plan, message, len(key_sequence.keys))
        messages.append({
            "role": "assistant",
            "content": "Plan interne minimal : " + json.dumps(steps, ensure_ascii=False),
        })
        return steps

    def _generate_deferred_file_commands(
        self,
        messages,
        request,
        steps,
        chat,
        allowed_tools,
        key_sequence,
        progress_callback=None,
    ):
        commands = []
        target_paths = set()
        for index, step_request in enumerate(steps):
            key_index = (index + 1) % len(key_sequence.keys)
            api_key = key_sequence.key_for_stage(index + 1)
            self._report_progress(
                progress_callback,
                f"Sous-tâche {index + 1}/{len(steps)} attribuée à la clé {key_index + 1}/{len(key_sequence.keys)}…",
            )
            stage_messages = [dict(item) for item in messages]
            stage_messages.insert(
                len(stage_messages) - 1,
                {
                    "role": "system",
                    "content": (
                        f"SOUS-TÂCHE {index + 1}/{len(steps)} : {step_request}\n"
                        "Cette tâche t'est attribuée indépendamment. Traite uniquement cette sous-tâche, "
                        "en tenant compte des autres tâches prévues. Lis les fichiers nécessaires avec file/list/search. "
                        "Termine par exactement un appel write ou edit, sans l'exécuter et sans texte autour. "
                        "Les changements du même fichier doivent être regroupés dans une seule sous-tâche."
                    ),
                },
            )
            stage_messages[-1] = {
                "role": "user",
                "content": (
                    f"Demande complète : {request}\n"
                    f"Plan des sous-tâches : {json.dumps(steps, ensure_ascii=False)}\n"
                    f"Sous-tâche attribuée : {step_request}\n"
                    "Retourne une seule commande de création ou modification de fichier."
                ),
            }

            initial_stage_messages = [dict(item) for item in stage_messages]
            for attempt in range(MAX_TOOL_STEPS * 2):
                if attempt == MAX_TOOL_STEPS:
                    api_key = key_sequence.key_for_stage(index + 2)
                    stage_messages = [dict(item) for item in initial_stage_messages]
                    stage_messages.append({
                        "role": "user",
                        "content": (
                            f"La sous-tâche précédente n'a pas abouti. Recommence uniquement cette sous-tâche "
                            f"({index + 1}/{len(steps)}) : {step_request}. Produis une commande complète "
                            "<tool_call> JSON valide utilisant write ou edit, avec le chemin et tout le contenu "
                            "nécessaire. Aucun texte autour."
                        ),
                    })
                    self._report_progress(
                        progress_callback,
                        f"Reprise de la sous-tâche {index + 1}/{len(steps)} sur une nouvelle génération…",
                    )
                if len(steps) == 1:
                    tool_call, answer = self._generate_tool_call(
                        stage_messages,
                        {"mode": "local_code"},
                        stream=False,
                        api_key=api_key,
                        defer_file_actions=True,
                    )
                else:
                    answer = self._ask_with_api_key(
                        stage_messages,
                        api_key=api_key,
                        max_tokens=LOCAL_CODE_MAX_RESPONSE_TOKENS,
                    )
                    answer_text = answer if isinstance(answer, str) else "".join(answer)
                    tool_call = self.parse_tool_call(answer_text)
                answer_text = answer if isinstance(answer, str) else "".join(answer)
                if tool_call is None:
                    stage_messages.extend((
                        {"role": "assistant", "content": answer_text},
                        {
                            "role": "user",
                            "content": (
                                "Réponds maintenant uniquement avec un appel <tool_call> JSON valide à write ou edit. "
                                "Aucun texte avant ou après."
                            ),
                        },
                    ))
                    continue

                tool_name = tool_call.get("tool")
                if tool_name in {"write", "edit"}:
                    if tool_name not in allowed_tools:
                        return "Plan refusé : l'écriture est désactivée pour ce projet. Aucun fichier n'a été modifié."
                    arguments = tool_call.get("arguments")
                    path = str(arguments.get("path") or "").replace("\\", "/").strip() if isinstance(arguments, dict) else ""
                    if not path or path.casefold() in target_paths:
                        return "Plan refusé : chaque sous-tâche doit viser un fichier distinct et fournir un chemin. Aucun fichier n'a été modifié."
                    target_paths.add(path.casefold())
                    commands.append(tool_call)
                    break
                if tool_name not in {"file", "list", "search"} or tool_name not in allowed_tools:
                    return "Plan refusé : une sous-tâche a demandé un outil non autorisé. Aucun fichier n'a été modifié."

                result, verification, confirmation = self._execute_and_verify(tool_call, chat, allowed_tools)
                if confirmation is not None or not verification or not verification["verified"] or not verification["success"]:
                    return "Plan interrompu : une lecture de projet a échoué. Aucun fichier n'a été modifié."
                stage_messages.extend((
                    {"role": "assistant", "content": answer_text},
                    self._tool_message(tool_name, result, verification),
                ))
            else:
                return (
                    "Plan interrompu : la reprise de la sous-tâche n'a pas produit de commande "
                    "write/edit valide. Aucun fichier n'a été modifié."
                )

        return commands

    @staticmethod
    def parse_file_command_plan(content):
        text = str(content or "").strip()
        match = re.fullmatch(r"<file_plan>\s*(.*?)\s*</file_plan>", text, re.S | re.I)
        if match:
            try:
                commands = json.loads(match.group(1))
            except json.JSONDecodeError:
                return None
            if not isinstance(commands, list) or not commands:
                return None
            if any(not isinstance(item, dict) or item.get("tool") not in {"write", "edit"} for item in commands):
                return None
            return commands
        tool_call = LocalAgent.parse_tool_call(text)
        return [tool_call] if isinstance(tool_call, dict) and tool_call.get("tool") in {"write", "edit"} else None

    @classmethod
    def _serialize_file_command_plan(cls, commands):
        if len(commands) == 1:
            return cls._serialize_tool_call(commands[0])
        return "<file_plan>" + json.dumps(commands, ensure_ascii=False, separators=(",", ":")) + "</file_plan>"

    @staticmethod
    def _parse_global_verification(response):
        text = str(response or "").strip()
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.I)
        match = re.search(r"\{.*\}", text, re.S)
        if not match:
            return False, ["Le résultat de vérification n'est pas exploitable."]
        try:
            payload = json.loads(match.group(0))
        except json.JSONDecodeError:
            return False, ["Le résultat de vérification n'est pas un JSON valide."]
        if not isinstance(payload, dict):
            return False, ["Le résultat de vérification n'est pas structuré."]
        correct = payload.get("correct") is True or str(payload.get("status", "")).casefold() in {
            "correct", "complete", "verified", "ok"
        }
        issues = payload.get("issues", [])
        if isinstance(issues, str):
            issues = [issues]
        if not isinstance(issues, list):
            issues = []
        return correct, [str(issue).strip() for issue in issues if str(issue).strip()]

    def _verify_and_repair_answer(
        self,
        request,
        draft,
        *,
        key_sequence,
        progress_callback=None,
        evidence_messages=None,
    ):
        if not key_sequence.keys:
            return draft
        evidence = [
            str(item.get("content", ""))[:3500]
            for item in (evidence_messages or [])
            if isinstance(item, dict) and item.get("role") == "tool"
        ][-MAX_MULTI_KEY_STAGES:]
        verification_prompt = [
            {
                "role": "system",
                "content": (
                    "Tu es vérificateur final indépendant. Compare la réponse à la demande et aux preuves fournies. "
                    "Vérifie que toutes les étapes nécessaires sont traitées, qu'aucun résultat d'outil n'est inventé "
                    "et que les affirmations respectent les preuves. Retourne uniquement un JSON: "
                    '{"correct":true|false,"issues":["..."],"answer":"..."}. '
                    "Si une réponse est correcte et complète, correct=true. En cas de doute, correct=false."
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {"request": request, "draft": draft, "verified_tool_results": evidence},
                    ensure_ascii=False,
                ),
            },
        ]
        self._report_progress(progress_callback, "Vérification globale de la réponse…")
        first_review = self._ask_with_api_key(
            verification_prompt,
            api_key=key_sequence.next_key(),
            max_tokens=1200,
        )
        correct, issues = self._parse_global_verification(first_review)
        if correct:
            self._report_progress(progress_callback, "Réponse vérifiée globalement.")
            return draft

        self._report_progress(progress_callback, "Écart détecté; seconde phase de correction…")
        repair_prompt = [
            {
                "role": "system",
                "content": (
                    "Corrige la réponse en couvrant les lacunes listées. Utilise uniquement la demande, le brouillon "
                    "et les preuves vérifiées fournis. N'exécute aucune action et n'invente aucun résultat. "
                    "Retourne uniquement la réponse finale corrigée."
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "request": request,
                        "draft": draft,
                        "issues": issues,
                        "verified_tool_results": evidence,
                    },
                    ensure_ascii=False,
                ),
            },
        ]
        repaired = str(
            self._ask_with_api_key(
                repair_prompt,
                api_key=key_sequence.next_key(),
                max_tokens=LOCAL_CODE_MAX_RESPONSE_TOKENS,
            )
            or ""
        ).strip()
        if not repaired:
            repaired = draft

        repair_review_prompt = [
            verification_prompt[0],
            {
                "role": "user",
                "content": json.dumps(
                    {"request": request, "draft": repaired, "verified_tool_results": evidence},
                    ensure_ascii=False,
                ),
            },
        ]
        second_review = self._ask_with_api_key(
            repair_review_prompt,
            api_key=key_sequence.next_key(),
            max_tokens=1200,
        )
        repair_is_correct, remaining_issues = self._parse_global_verification(second_review)
        if repair_is_correct:
            self._report_progress(progress_callback, "Réponse corrigée puis vérifiée.")
            return repaired
        issue_text = "; ".join(remaining_issues or issues) or "la vérification reste incertaine"
        self._report_progress(progress_callback, "Réponse partielle; la vérification reste incertaine.")
        return f"Réponse partielle — vérification à confirmer : {issue_text}\n\n{repaired}"

    def _respond_staged_chat(
        self,
        chat,
        request,
        external_info,
        route,
        key_sequence,
        progress_callback=None,
    ):
        keys = key_sequence.keys
        base_messages = self.build_messages(chat, request, external_info, tools=set(), route=route)
        if len(keys) > 1:
            planner_messages = [dict(message) for message in base_messages]
            planner_messages[0] = dict(planner_messages[0])
            planner_messages[0]["content"] += (
                "\n\n[PLAN_MULTI_CLE] Avant de répondre, décompose la demande en le nombre MINIMAL d'étapes "
                f"nécessaires, au maximum {min(len(keys), MAX_MULTI_KEY_STAGES)}. "
                'Retourne uniquement un JSON de la forme {"steps":["étape 1", "étape 2"]}. '
                "Si la demande se résout en une étape, ne produis qu'une étape."
            )
            planner_answer = self._ask_with_api_key(
                planner_messages,
                api_key=key_sequence.key_for_stage(0),
                max_tokens=1000,
            )
            steps = self._parse_stage_plan(planner_answer, request, len(keys))
        else:
            steps = [request]

        results = []
        for index, step_request in enumerate(steps):
            key_index = (index + 1) % len(keys)
            self._report_progress(
                progress_callback,
                f"Étape {index + 1}/{len(steps)} attribuée à la clé {key_index + 1}/{len(keys)}…",
            )
            step_messages = [dict(message) for message in base_messages]
            step_messages[-1] = {
                "role": "user",
                "content": (
                    f"Demande complète : {request}\n"
                    f"Étapes prévues : {json.dumps(steps, ensure_ascii=False)}\n"
                    f"Étape à résoudre maintenant ({index + 1}/{len(steps)}) : {step_request}\n"
                    f"Résultats des étapes précédentes : {json.dumps(results, ensure_ascii=False)}\n"
                    "Réponds à cette étape sans répéter les étapes déjà résolues."
                ),
            }
            result = str(
                self._ask_with_api_key(
                    step_messages,
                    api_key=key_sequence.key_for_stage(index + 1),
                    max_tokens=LOCAL_CODE_MAX_RESPONSE_TOKENS,
                )
                or ""
            ).strip()
            if self.parse_tool_call(result):
                result = "Cette étape a demandé une action qui n'est pas autorisée dans le mode réponse directe."
            results.append({"step": step_request, "result": result})

        if len(results) == 1:
            draft = results[0]["result"]
        else:
            draft = "\n\n".join(
                f"Étape {index + 1} — {item['step']}\n{item['result']}"
                for index, item in enumerate(results)
            )
        key_sequence.index = (len(results) + 1) % len(keys)
        return self._verify_and_repair_answer(
            request,
            draft,
            key_sequence=key_sequence,
            progress_callback=progress_callback,
        )

    @staticmethod
    def _verification_failure(tool_name, verification):
        if tool_name == "write":
            return "Je n'ai pas pu confirmer que le contenu attendu est bien enregistré; je ne peux pas annoncer la création comme terminée."
        if tool_name == "edit":
            return "Je n'ai pas pu confirmer la modification sur disque; je ne peux pas annoncer la correction comme terminée."
        if tool_name == "command":
            return "La commande n'a pas réussi ou son résultat n'a pas pu être vérifié."
        if tool_name == "launch":
            return "La demande a été envoyée au lanceur, mais je ne peux pas confirmer que l'application est effectivement ouverte."
        return "L'action n'a pas réussi ou son résultat n'a pas pu être vérifié."

    @staticmethod
    def _summary(tool_call, result):
        """Phrase de confirmation sans rappeler le modèle (actions simples)."""
        if tool_call["tool"] == "write" and isinstance(result, dict):
            return f"Fichier créé ou modifié : {result.get('path', 'chemin inconnu')}"
        if tool_call["tool"] == "create_download" and isinstance(result, dict):
            return f"Fichier prêt à télécharger : {result.get('filename', 'fichier')}"
        if tool_call["tool"] == "launch" and isinstance(result, dict):
            return f"Demande de lancement envoyée pour {result.get('name', tool_call['arguments'].get('name', 'l’application'))}."
        if tool_call["tool"] == "open_page" and isinstance(result, dict):
            return f"Page ouverte dans le navigateur : {result.get('url', 'URL inconnue')}"
        return None

    def _record_generated_download(self, filename, content):
        try:
            artifact = download_tool.use(filename, content)
        except (OSError, ValueError):
            return None
        self.generated_downloads.append({
            "artifact_id": artifact["artifact_id"],
            "filename": artifact["filename"],
            "size": artifact["size"],
        })
        return artifact

    def _cache_code_response(self, request, answer):
        match = re.search(r"```([\w+.-]*)[^\S\n]*\n(.*?)```", str(answer or ""), re.DOTALL)
        if not match or not match.group(2).strip():
            return
        language = match.group(1).casefold()
        extensions = {
            "py": "py", "python": "py", "python3": "py",
            "js": "js", "javascript": "js", "ts": "ts", "typescript": "ts",
            "html": "html", "css": "css", "json": "json", "sh": "sh", "bash": "sh",
        }
        normalized_request = unicodedata.normalize("NFKD", str(request).casefold())
        request_ascii = normalized_request.encode("ascii", "ignore").decode("ascii")
        extension = extensions.get(language, "py" if "python" in request_ascii else "txt")
        ignored = {
            "cree", "creer", "ecris", "ecrire", "genere", "generer", "fais", "faire",
            "un", "une", "le", "la", "les", "de", "du", "des", "pour", "qui", "avec",
            "script", "programme", "fichier", "code", "python", "javascript", "typescript",
        }
        words = [word for word in re.findall(r"[a-z0-9]+", request_ascii) if word not in ignored]
        basename = "-".join(words[-3:])[:48].strip("-") or "script"
        content = match.group(2).strip("\r\n") + "\n"
        self._record_generated_download(f"{basename}.{extension}", content)

    def _explicit_command(self, message, chat, allowed_tools):
        """Exécute /commande directement, sans demander au modèle de reconstruire argv."""
        try:
            argv = command_commands.parse_command(str(message or ""))
        except ValueError:
            self.last_route = {"mode": "direct", "action": "command", "tools": (), "answer": None}
            return 'Syntaxe : /commande "programme" [arguments].'
        if argv is None:
            return None

        self.last_route = {"mode": "direct", "action": "command", "tools": (), "answer": None}
        if allowed_tools is not None and "command" not in allowed_tools:
            return "L'exécution de commandes est désactivée pour cette requête."

        tool_call = {"tool": "command", "arguments": {"argv": argv}}
        try:
            result = self.execute_tool(tool_call, chat, allowed_tools=allowed_tools)
        except Exception as error:
            logging.getLogger(__name__).warning(
                "Échec d'une commande explicite (%s)", type(error).__name__
            )
            return "Je n'ai pas pu exécuter cette commande. Vérifie le programme, ses arguments et les autorisations."

        if isinstance(result, dict) and result.get("confirmation_required"):
            chat["pending_tool"] = tool_call
            return f"{result.get('message', 'Confirmation nécessaire.')}\nRéponds « oui » pour confirmer."

        verification = ToolManager.verify_result(tool_call, result, chat)
        if not verification["verified"]:
            return self._verification_failure("command", verification)
        if not isinstance(result, dict):
            return "La commande n'a pas renvoyé de résultat exploitable."
        output = str(result.get("stdout") or "").strip()
        stderr = str(result.get("stderr") or "").strip()
        details = output or stderr or "(aucune sortie)"
        command_text = " ".join(argv)
        if result.get("returncode", 1) != 0:
            return f"La commande « {command_text} » s'est terminée avec le code {result['returncode']}.\n{details}"
        return f"Commande terminée : {command_text}\n{details}"

    # ------------------------------------------------------------------
    # Réponse à un message
    # ------------------------------------------------------------------
    def respond(
        self,
        chat,
        message,
        external_info=None,
        allowed_tools=None,
        stream=False,
        local_code=False,
        defer_file_actions=False,
        progress_callback=None,
    ):
        self.generated_downloads = []
        pending_tool, route, selected_tools, direct_answer = self._resolve_response_route(
            chat, message, allowed_tools, local_code
        )
        if direct_answer is not None:
            self._report_progress(progress_callback, "Réponse directe prête.")
            return direct_answer
        assert route is not None and selected_tools is not None
        key_sequence = RequestKeySequence(openrouter_api_keys())
        if route.get("mode") in {"chat", "command_suggestion"} and len(key_sequence.keys) > 1:
            return self._respond_staged_chat(
                chat,
                message,
                external_info,
                route,
                key_sequence,
                progress_callback=progress_callback,
            )
        route_messages = {
            "code_artifact": "Préparation du fichier de code…",
            "command_suggestion": "Préparation de la commande à copier…",
            "install_application": "Vérification de l'application et de la méthode d'installation…",
            "web": "Recherche des informations…",
            "chat": "Préparation de la réponse…",
        }
        self._report_progress(
            progress_callback,
            route_messages.get(route.get("action"), "Analyse de la demande…"),
        )

        messages = self.build_messages(chat, message, external_info, tools=selected_tools, route=route)
        if len(key_sequence.keys) > 1 and (
            defer_file_actions or route.get("action") == "code_artifact"
        ):
            planned_steps = self._plan_tool_stages(
                message,
                messages,
                key_sequence,
                progress_callback=progress_callback,
            )
            commands = self._generate_deferred_file_commands(
                messages,
                message,
                planned_steps,
                chat,
                selected_tools,
                key_sequence,
                progress_callback=progress_callback,
            )
            if isinstance(commands, str):
                return commands
            if defer_file_actions:
                return self._serialize_file_command_plan(commands)
            answer = self.apply_approved_file_call(commands, chat, allowed_tools=selected_tools)
            self._report_progress(progress_callback, "Sous-tâches terminées et vérifiées.")
            return answer

        planned_steps = [] if defer_file_actions else self._plan_tool_stages(
            message,
            messages,
            key_sequence,
            progress_callback=progress_callback,
        )
        if pending_tool:
            tool_call = pending_tool
            tool_call["arguments"]["confirmed"] = True
            if allowed_tools is not None:
                allowed_tools = set(allowed_tools) | {tool_call["tool"]}
            answer = "<tool_call>" + json.dumps(tool_call, ensure_ascii=False) + "</tool_call>"
        else:
            tool_call, answer = self._generate_tool_call(
                messages,
                route,
                stream,
                api_key=key_sequence.next_key(),
                defer_file_actions=defer_file_actions,
            )
            if tool_call is None:
                if defer_file_actions:
                    return "Aucune commande write/edit valide n'a été produite; aucun fichier n'a été modifié."
                if route.get("action") == "code_artifact" and not local_code:
                    self._cache_code_response(message, answer)
                self._report_progress(progress_callback, "Réponse prête.")
                if len(key_sequence.keys) > 1:
                    return self._verify_and_repair_answer(
                        message,
                        str(answer or ""),
                        key_sequence=key_sequence,
                        progress_callback=progress_callback,
                    )
                return answer
            if route.get("mode") == "command_suggestion":
                if tool_call.get("tool") == "command":
                    argv = tool_call.get("arguments", {}).get("argv")
                elif tool_call.get("tool") == "launch":
                    name = tool_call.get("arguments", {}).get("name")
                    argv = [name] if isinstance(name, str) else None
                else:
                    argv = None
                if isinstance(argv, list) and argv and all(isinstance(item, str) and item for item in argv):
                    self._report_progress(progress_callback, "Commande prête à copier; aucune commande exécutée.")
                    copyable_answer = f"Commande à copier :\n```sh\n{program_commands.format_command(argv)}\n```"
                    if len(key_sequence.keys) > 1:
                        return self._verify_and_repair_answer(
                            message,
                            copyable_answer,
                            key_sequence=key_sequence,
                            progress_callback=progress_callback,
                        )
                    return copyable_answer
                self._report_progress(progress_callback, "Commande non reconnue; aucune commande exécutée.")
                return "Je n'ai exécuté aucune commande. Précise l'application ou l'action pour que je fournisse une commande copiable."

        seen = set()
        stage_context = (
            f"Étapes planifiées (minimum nécessaire) : {json.dumps(planned_steps, ensure_ascii=False)}. "
            "Traite-les dans l'ordre, avec une seule action par étape logique, sans répéter le travail déjà vérifié."
            if planned_steps
            else ""
        )
        if stage_context:
            messages.append({"role": "system", "content": stage_context})
        last_call, last_result, last_error = tool_call, None, None
        verification_failures = []
        tool_limit = self.get_max_tool_steps(route)
        chunked_write = tool_call["tool"] == "write" and bool(tool_call["arguments"].get("append"))
        if chunked_write:
            tool_limit = max(tool_limit, MAX_CHUNKED_WRITE_STEPS)
        step = 0
        loop_detected = False
        while step < tool_limit:
            if defer_file_actions:
                if tool_call["tool"] in {"write", "edit"}:
                    if tool_call["tool"] in selected_tools:
                        return self._serialize_tool_call(tool_call)
                    return "Commande refusée : l'écriture de fichiers est désactivée pour ce projet."
                if tool_call["tool"] not in {"file", "list", "search"}:
                    return "Commande refusée : le mode Code n'accepte que la lecture ou une commande write/edit."
            key = self.normalize_tool_call(tool_call)
            if key in seen:
                loop_detected = True
                self._report_progress(progress_callback, "Répétition détectée; arrêt des actions.")
                break  # le modèle tourne en rond : on s'arrête
            seen.add(key)
            last_call = tool_call
            tool_labels = {
                "file": "Lecture de fichier",
                "write": "Écriture de fichier",
                "edit": "Modification de fichier",
                "list": "Liste des fichiers",
                "search": "Recherche dans les fichiers",
                "command": "Exécution de commande",
                "system": "Action système",
                "launch": "Lancement d'application",
                "web": "Recherche Web",
                "calculator": "Calcul",
                "open_page": "Ouverture de page",
            }
            tool_label = tool_labels.get(tool_call["tool"], "Action")
            self._report_progress(progress_callback, f"Étape {step + 1}/{tool_limit} : {tool_label}…")
            result, verification, confirmation_message = self._execute_and_verify(
                tool_call, chat, selected_tools
            )
            last_result = result

            if confirmation_message is not None:
                chat["pending_tool"] = tool_call
                self._report_progress(progress_callback, "En attente de confirmation avant l'action.")
                return f"{confirmation_message}\nRéponds « oui » pour confirmer."
            assert verification is not None
            if tool_call["tool"] == "create_download" and verification["success"] and isinstance(result, dict):
                self.generated_downloads.append({
                    "artifact_id": result["artifact_id"],
                    "filename": result["filename"],
                    "size": result["size"],
                })
            elif (
                route.get("action") == "code_artifact"
                and not local_code
                and tool_call["tool"] == "write"
                and verification["success"]
                and isinstance(result, dict)
            ):
                try:
                    created_path = Path(result.get("path", ""))
                    if created_path.stat().st_size <= download_tool.MAX_DOWNLOAD_BYTES:
                        self._record_generated_download(
                            created_path.name,
                            created_path.read_text(encoding="utf-8"),
                        )
                except (OSError, UnicodeError, ValueError):
                    pass
            self._report_progress(
                progress_callback,
                f"{tool_label} terminé et vérifié." if verification["success"] else f"{tool_label} bloqué ou non vérifié.",
            )

            payload = result if result is not None else {"error": "L'appel à cet outil n'a pas abouti. Vérifie les arguments et réessaie."}
            if not verification["verified"] or not verification["success"]:
                verification_failures.append((tool_call["tool"], verification))
            last_error = None if verification["success"] else True

            if (
                step == 0
                and route.get("mode") != "local_code"
                and not pending_tool
                and last_error is None
                and not FOLLOW_UP_RE.search(str(message))
                and not MULTI_PART_WRITE_RE.search(str(message))
                and not (
                    tool_call["tool"] == "write"
                    and LARGE_FILE_REQUEST_RE.search(str(message))
                )
            ):
                summary = self._summary(tool_call, result) if verification["success"] else None
                if summary:
                    self._report_progress(progress_callback, "Action terminée; résultat vérifié.")
                    if len(key_sequence.keys) > 1:
                        return self._verify_and_repair_answer(
                            message,
                            summary,
                            key_sequence=key_sequence,
                            progress_callback=progress_callback,
                            evidence_messages=[self._tool_message(tool_call["tool"], payload, verification)],
                        )
                    return summary  # action simple : inutile de rappeler le modèle

            messages.append({"role": "assistant", "content": answer})
            messages.append(self._tool_message(tool_call["tool"], payload, verification))
            answer = self._ask_with_api_key(
                messages,
                api_key=key_sequence.next_key(),
                max_tokens=LOCAL_CODE_MAX_RESPONSE_TOKENS if route.get("mode") in {"local_code", "code"} else None,
            )
            tool_call = self.parse_tool_call(answer)
            if not tool_call:
                if defer_file_actions:
                    return "Aucune commande write/edit valide n'a été produite; aucun fichier n'a été modifié."
                if route.get("action") == "code_artifact" and not local_code:
                    self._cache_code_response(message, answer)
                if verification_failures:
                    failed_tool, failed_verification = verification_failures[-1]
                    self._report_progress(progress_callback, "Action interrompue après une vérification négative.")
                    return self._verification_failure(failed_tool, failed_verification)
                self._report_progress(progress_callback, "Réponse finale prête.")
                if len(key_sequence.keys) > 1:
                    return self._verify_and_repair_answer(
                        message,
                        str(answer or ""),
                        key_sequence=key_sequence,
                        progress_callback=progress_callback,
                        evidence_messages=messages,
                    )
                return answer
            step += 1
            if (
                not chunked_write
                and tool_call["tool"] == "write"
                and bool(tool_call["arguments"].get("append"))
            ):
                chunked_write = True
                tool_limit = max(tool_limit, step + MAX_CHUNKED_WRITE_STEPS)

        if chunked_write and tool_call is not None and step >= tool_limit:
            path = tool_call["arguments"].get("path") or last_call["arguments"].get("path", "le fichier")
            self._report_progress(progress_callback, "Écriture incomplète; une suite est nécessaire.")
            return f"L'écriture de {path} continue au-delà des blocs traités dans cette réponse. Demande-moi de la continuer."
        if not chunked_write and not loop_detected and step >= tool_limit and tool_call is not None:
            self._report_progress(progress_callback, "Limite d'actions atteinte; demande non confirmée comme terminée.")
            return (
                f"Je me suis arrêté après {tool_limit} actions consécutives pour éviter de tourner en rond. "
                "La demande n'est pas confirmée comme terminée; découpe-la en étapes plus petites."
            )
        if verification_failures:
            failed_tool, failed_verification = verification_failures[-1]
            self._report_progress(progress_callback, "Action interrompue après une vérification négative.")
            return self._verification_failure(failed_tool, failed_verification)
        if loop_detected:
            summary = self._summary(last_call, last_result)
            self._report_progress(progress_callback, "Arrêt après répétition détectée.")
            return summary or f"J'ai arrêté l'action {last_call['tool']} après une répétition pour éviter de tourner en rond."
        if last_error:
            self._report_progress(progress_callback, "Action échouée.")
            if last_call["tool"] == "command":
                return "Je n'ai pas pu exécuter cette commande. Vérifie le programme, ses arguments et les autorisations."
            return "Je n'ai pas pu terminer cette action. Vérifie les informations fournies et réessaie."
        summary = self._summary(last_call, last_result)
        self._report_progress(progress_callback, "Action terminée." if summary else "Réponse prête.")
        return summary or f"Action {last_call['tool']} exécutée."

    def _execute_and_verify(self, tool_call, chat, allowed_tools):
        try:
            result = self.execute_tool(tool_call, chat, allowed_tools=allowed_tools)
        except Exception as error:
            logging.getLogger(__name__).warning(
                "Échec de l'outil %s (%s)", tool_call["tool"], type(error).__name__
            )
            result = None

        if isinstance(result, dict) and result.get("confirmation_required"):
            return result, None, result.get("message", "Confirmation nécessaire.")
        return result, ToolManager.verify_result(tool_call, result, chat), None

    def apply_approved_file_call(self, tool_call, chat, allowed_tools=None):
        if isinstance(tool_call, str):
            tool_calls = self.parse_file_command_plan(tool_call)
        elif isinstance(tool_call, dict):
            tool_calls = [tool_call]
        else:
            tool_calls = tool_call
        if not isinstance(tool_calls, list) or not tool_calls or any(
            not isinstance(item, dict) or item.get("tool") not in {"write", "edit"}
            for item in tool_calls
        ):
            raise ValueError("La proposition approuvée doit contenir des appels write/edit valides.")

        summaries = []
        for item in tool_calls:
            result, verification, confirmation = self._execute_and_verify(item, chat, allowed_tools)
            if confirmation is not None:
                raise ValueError(confirmation)
            if not verification or not verification["verified"] or not verification["success"]:
                raise ValueError(self._verification_failure(item["tool"], verification or {}))
            summaries.append(self._summary(item, result))
            if item["tool"] == "write" and not chat.get("code_project_path") and isinstance(result, dict):
                try:
                    created_path = Path(result.get("path", ""))
                    if created_path.stat().st_size <= download_tool.MAX_DOWNLOAD_BYTES:
                        self._record_generated_download(
                            created_path.name,
                            created_path.read_text(encoding="utf-8"),
                        )
                except (OSError, UnicodeError, ValueError):
                    pass
        return "\n".join(summaries)

    @staticmethod
    def _serialize_tool_call(tool_call):
        payload = json.dumps(tool_call, ensure_ascii=False, separators=(",", ":"))
        return f"<tool_call>{payload}</tool_call>"

    def _generate_tool_call(self, messages, route, stream, api_key=None, defer_file_actions=False):
        answer = self._ask_with_api_key(
            messages,
            api_key=api_key,
            stream=bool(stream),
            max_tokens=LOCAL_CODE_MAX_RESPONSE_TOKENS if route.get("mode") in {"local_code", "code"} else None,
        )
        tool_call = self.parse_tool_call(answer if isinstance(answer, str) else "".join(answer))
        if not tool_call and route.get("mode") in {"local_code", "code"}:
            answer_text = answer if isinstance(answer, str) else "".join(answer)
            messages.append({"role": "assistant", "content": answer_text})
            messages.append({
                "role": "user",
                "content": (
                    "Retourne maintenant un seul appel <tool_call> JSON valide à write ou edit, sans aucun texte "
                    "avant ni après. N'exécute pas de commande shell."
                    if defer_file_actions or route.get("mode") == "code"
                    else "Tu as décrit un plan, mais tu n'as pas encore agi. Continue maintenant sans attendre "
                    "de réponse de l'utilisateur : utilise les outils autorisés pour réaliser la demande. "
                    "Ne renvoie un texte que si une information réellement indispensable bloque le travail."
                ),
            })
            answer = self._ask_with_api_key(
                messages,
                api_key=api_key,
                max_tokens=LOCAL_CODE_MAX_RESPONSE_TOKENS,
            )
            tool_call = self.parse_tool_call(answer if isinstance(answer, str) else "".join(answer))
        if tool_call:
            return tool_call, answer

        answer_text = answer if isinstance(answer, str) else "".join(answer)
        if "<tool_call>" in answer_text.casefold():
            return None, "Je n'ai pas pu comprendre l'action demandée. Reformule la commande ou précise ses arguments."
        return None, answer_text

    def _resolve_response_route(self, chat, message, allowed_tools, local_code):
        normalized_message = str(message or "").strip().lower().rstrip(" .!")
        # Une confirmation en attente ne vaut que pour le message qui suit
        # immédiatement : tout autre message l'annule (pas de « oui » tardif).
        pending_tool = chat.pop("pending_tool", None)
        if normalized_message not in CONFIRMATIONS:
            pending_tool = None

        if not pending_tool and not local_code:
            command_answer = self._explicit_command(message, chat, allowed_tools)
            if command_answer is not None:
                return None, None, None, command_answer

        if not pending_tool and local_code:
            selected_tools = set(allowed_tools) if allowed_tools is not None else set(TOOL_NAMES)
            route = {
                "mode": "local_code",
                "action": "local_code",
                "tools": tuple(sorted(selected_tools)),
                "answer": None,
            }
            self.last_route = route
        elif not pending_tool:
            existing_code_file = self._recent_created_file(chat)
            route = self.router.route(
                message,
                lambda current_message, tools: (
                    self.fast_path(current_message, tools)
                    or self._contextual_app_correction(chat, current_message, tools)
                ),
                allowed_tools,
                existing_code_file=existing_code_file,
            )
            self.last_route = route
            logging.getLogger(__name__).debug(
                "Requête IA routée : mode=%s action=%s outils=%s",
                route["mode"], route["action"], route["tools"],
            )
            if route["mode"] == "direct":
                return None, None, None, route["answer"]
            selected_tools = ToolManager.get_tools(route, allowed_tools)
        else:
            selected_tools = set(allowed_tools) if allowed_tools is not None else set(TOOL_NAMES)
            selected_tools.add(pending_tool["tool"])
            route = {
                "mode": "tool",
                "action": "confirmation",
                "tools": tuple(sorted(selected_tools)),
                "answer": None,
            }
            self.last_route = route

        return pending_tool, route, selected_tools, None

    @staticmethod
    def _recent_created_file(chat):
        messages = chat.get("messages", []) if isinstance(chat, dict) else []
        for entry in reversed(messages):
            if not isinstance(entry, dict) or entry.get("role") != "assistant":
                continue
            match = _CREATED_FILE_RE.search(str(entry.get("content", "")))
            if not match:
                continue
            path = Path(match.group("path").strip().strip('"`'))
            try:
                if path.is_file():
                    return str(path.resolve())
            except (OSError, RuntimeError, ValueError):
                continue
        return None

    def close(self):
        self.connection.close()
