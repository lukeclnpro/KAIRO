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
from datetime import date
from pathlib import Path

import application_launcher
import command_commands
from local_ia.config.manager import model_config
from local_ia.core.context import load_context
from local_ia.core.context_compiler import ContextCompiler
from local_ia.core.conversation import get_weighted_chat_history
from local_ia.core.memory import get_memories, init_database
from local_ia.core.router import RequestRouter
from local_ia.llm.ollama import ask_ollama
from local_ia.tools import system
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
MAX_TOOL_STEPS_BY_MODE = {"tool": 3, "agent": MAX_TOOL_STEPS, "local_code": 12, "chat": 0, "direct": 0}
CONFIRMATIONS = {
    "oui", "yes", "ok", "d'accord", "d accord", "je confirme", "confirme", "confirmé",
    "oui je confirme", "vas-y", "go", "c'est bon",
}
# Mots qui montrent que l'utilisateur attend autre chose que l'action elle-même.
FOLLOW_UP_RE = re.compile(
    r"\b(puis|ensuite|apr[eè]s|et dis|dis-moi|montre-moi|et montre|et affiche|then)\b", re.I
)
MULTI_PART_WRITE_RE = re.compile(
    r"\b(?:plusieurs|multiples|diff[ée]rents?)\s+(?:blocs?|parties|segments)\b", re.I
)
LARGE_FILE_REQUEST_RE = re.compile(
    r"\b(?:tr[eè]s\s+grand|gros|grosse|[ée]norme|immense|gigantesque|volumineux|sans\s+limite)\b",
    re.I,
)

_POLITE = r"(?:(?:peux-tu|pourrais-tu|tu peux|s'il te pla[iî]t)\s+)*"
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
        return [{"role": "system", "content": prompt}, *get_weighted_chat_history(chat), {"role": "user", "content": message}]

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
        if tool_call["tool"] == "launch" and isinstance(result, dict):
            return f"Demande de lancement envoyée pour {result.get('name', tool_call['arguments'].get('name', 'l’application'))}."
        if tool_call["tool"] == "open_page" and isinstance(result, dict):
            return f"Page ouverte dans le navigateur : {result.get('url', 'URL inconnue')}"
        return None

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
    def respond(self, chat, message, external_info=None, allowed_tools=None, stream=False, local_code=False):
        pending_tool, route, selected_tools, direct_answer = self._resolve_response_route(
            chat, message, allowed_tools, local_code
        )
        if direct_answer is not None:
            return direct_answer
        assert route is not None and selected_tools is not None

        messages = self.build_messages(chat, message, external_info, tools=selected_tools, route=route)
        if pending_tool:
            tool_call = pending_tool
            tool_call["arguments"]["confirmed"] = True
            if allowed_tools is not None:
                allowed_tools = set(allowed_tools) | {tool_call["tool"]}
            answer = "<tool_call>" + json.dumps(tool_call, ensure_ascii=False) + "</tool_call>"
        else:
            tool_call, answer = self._generate_tool_call(messages, route, stream)
            if tool_call is None:
                return answer

        seen = set()
        last_call, last_result, last_error = tool_call, None, None
        verification_failures = []
        tool_limit = self.get_max_tool_steps(route)
        chunked_write = tool_call["tool"] == "write" and bool(tool_call["arguments"].get("append"))
        if chunked_write:
            tool_limit = max(tool_limit, MAX_CHUNKED_WRITE_STEPS)
        step = 0
        while step < tool_limit:
            key = self.normalize_tool_call(tool_call)
            if key in seen:
                break  # le modèle tourne en rond : on s'arrête
            seen.add(key)
            last_call = tool_call
            result, verification, confirmation_message = self._execute_and_verify(
                tool_call, chat, selected_tools
            )
            last_result = result

            if confirmation_message is not None:
                chat["pending_tool"] = tool_call
                return f"{confirmation_message}\nRéponds « oui » pour confirmer."
            assert verification is not None

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
                    return summary  # action simple : inutile de rappeler le modèle

            messages.append({"role": "assistant", "content": answer})
            messages.append(self._tool_message(tool_call["tool"], payload, verification))
            answer = ask_ollama(
                list(messages),
                model=self.model,
                max_tokens=LOCAL_CODE_MAX_RESPONSE_TOKENS if route.get("mode") == "local_code" else None,
            )
            tool_call = self.parse_tool_call(answer)
            if not tool_call:
                if verification_failures:
                    failed_tool, failed_verification = verification_failures[-1]
                    return self._verification_failure(failed_tool, failed_verification)
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
            return f"L'écriture de {path} continue au-delà des blocs traités dans cette réponse. Demande-moi de la continuer."
        if verification_failures:
            failed_tool, failed_verification = verification_failures[-1]
            return self._verification_failure(failed_tool, failed_verification)
        if last_error:
            if last_call["tool"] == "command":
                return "Je n'ai pas pu exécuter cette commande. Vérifie le programme, ses arguments et les autorisations."
            return "Je n'ai pas pu terminer cette action. Vérifie les informations fournies et réessaie."
        summary = self._summary(last_call, last_result)
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

    def _generate_tool_call(self, messages, route, stream):
        answer = ask_ollama(
            list(messages),
            model=self.model,
            stream=bool(stream),
            max_tokens=LOCAL_CODE_MAX_RESPONSE_TOKENS if route.get("mode") == "local_code" else None,
        )
        tool_call = self.parse_tool_call(answer if isinstance(answer, str) else "".join(answer))
        if not tool_call and route.get("mode") == "local_code":
            answer_text = answer if isinstance(answer, str) else "".join(answer)
            messages.append({"role": "assistant", "content": answer_text})
            messages.append({
                "role": "user",
                "content": (
                    "Tu as décrit un plan, mais tu n'as pas encore agi. Continue maintenant sans attendre "
                    "de réponse de l'utilisateur : utilise les outils autorisés pour réaliser la demande. "
                    "Ne renvoie un texte que si une information réellement indispensable bloque le travail."
                ),
            })
            answer = ask_ollama(
                list(messages),
                model=self.model,
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
            route = self.router.route(
                message,
                lambda current_message, tools: (
                    self.fast_path(current_message, tools)
                    or self._contextual_app_correction(chat, current_message, tools)
                ),
                allowed_tools,
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

    def close(self):
        self.connection.close()
