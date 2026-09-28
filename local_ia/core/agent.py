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

import application_launcher
from local_ia.config.manager import model_config
from local_ia.core.context import build_system_prompt, load_context
from local_ia.core.context_compiler import ContextCompiler
from local_ia.core.conversation import get_chat_history
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
    "execute_command": "command", "run_command": "command", "run": "command",
    "volume": "system", "install": "system", "update": "system",
}
PAYLOAD_KEYS = (
    "name", "argv", "path", "content", "extension", "action", "value", "amount",
    "old", "new", "replace_all", "pattern", "cwd", "timeout", "max_results",
)

MAX_TOOL_STEPS = 4
MAX_TOOL_RESULT_CHARS = 2500
MAX_TOOL_STEPS_BY_MODE = {"tool": 3, "agent": MAX_TOOL_STEPS, "chat": 0, "direct": 0}
CONFIRMATIONS = {
    "oui", "yes", "ok", "d'accord", "d accord", "je confirme", "confirme", "confirmé",
    "oui je confirme", "vas-y", "go", "c'est bon",
}
# Mots qui montrent que l'utilisateur attend autre chose que l'action elle-même.
FOLLOW_UP_RE = re.compile(
    r"\b(puis|ensuite|apr[eè]s|et dis|dis-moi|montre-moi|et montre|et affiche|then)\b", re.I
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
        return [{"role": "system", "content": prompt}, *get_chat_history(chat), {"role": "user", "content": message}]

    # ------------------------------------------------------------------
    # Voie rapide : aucune génération, l'action est faite tout de suite.
    # ------------------------------------------------------------------
    def fast_path(self, message, allowed_tools=None):
        """Exécute directement les demandes simples. Retourne None si le modèle doit décider."""
        text = str(message or "").strip()
        if not text or "\n" in text:
            return None

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

        match = _LAUNCH_RE.fullmatch(text)
        if not match:
            return None
        name = _NAME_PREFIX_RE.sub("", match.group("name").strip()).strip(" .!?\"'")
        if (
            not name
            or "/" in name or "\\" in name
            or _NOT_AN_APP.match(name)
            or _FILE_EXTENSION_RE.search(name)
            or len(name.split()) > 4
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
        match = re.search(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", content or "", re.S)
        wrapper_name = None
        if not match:
            # Tolère les balises simplifiées émises par certains petits modèles,
            # par exemple : <write{"tool":"file",...})
            match = re.search(
                r"<(write(?:\.py)?|file|launch|command|system|edit|list|search)\s*(\{.*)",
                content or "",
                re.S | re.I,
            )
            if match:
                wrapper_name = match.group(1).lower()
        if not match:
            return None
        raw_payload = match.group(2) if wrapper_name else match.group(1)
        try:
            payload = json.loads(raw_payload)
        except json.JSONDecodeError:
            try:
                # Accepte une accolade finale en trop et les apostrophes
                # échappées comme dans une chaîne Python.
                payload, _ = json.JSONDecoder().raw_decode(raw_payload.replace("\\'", "'"))
            except json.JSONDecodeError:
                return None
        if not isinstance(payload, dict):
            return None
        raw_tool = wrapper_name or payload.get("tool")
        if not isinstance(raw_tool, str):
            return None
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
    def _tool_message(tool_name, payload):
        text = ToolManager.compact_result(payload, MAX_TOOL_RESULT_CHARS)
        return {"role": "tool", "content": f"Résultat de l'outil {tool_name} :\n{text}"}

    @staticmethod
    def _summary(tool_call, result):
        """Phrase de confirmation sans rappeler le modèle (actions simples)."""
        if tool_call["tool"] == "write" and isinstance(result, dict):
            return f"Fichier créé ou modifié : {result.get('path', 'chemin inconnu')}"
        if tool_call["tool"] == "launch" and isinstance(result, dict):
            return f"{result.get('name', tool_call['arguments'].get('name', 'Application'))} lancé."
        return None

    # ------------------------------------------------------------------
    # Réponse à un message
    # ------------------------------------------------------------------
    def respond(self, chat, message, external_info=None, allowed_tools=None, stream=False):
        normalized_message = str(message or "").strip().lower().rstrip(" .!")
        # Une confirmation en attente ne vaut que pour le message qui suit
        # immédiatement : tout autre message l'annule (pas de « oui » tardif).
        pending_tool = chat.pop("pending_tool", None)
        if normalized_message not in CONFIRMATIONS:
            pending_tool = None

        if not pending_tool:
            route = self.router.route(message, self.fast_path, allowed_tools)
            self.last_route = route
            logging.getLogger(__name__).debug(
                "Requête IA routée : mode=%s action=%s outils=%s",
                route["mode"], route["action"], route["tools"],
            )
            if route["mode"] == "direct":
                return route["answer"]
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

        messages = self.build_messages(chat, message, external_info, tools=selected_tools, route=route)
        if pending_tool:
            tool_call = pending_tool
            tool_call["arguments"]["confirmed"] = True
            if allowed_tools is not None:
                allowed_tools = set(allowed_tools) | {tool_call["tool"]}
            answer = "<tool_call>" + json.dumps(tool_call, ensure_ascii=False) + "</tool_call>"
        else:
            answer = ask_ollama(list(messages), model=self.model, stream=bool(stream) and not pending_tool)
            tool_call = self.parse_tool_call(answer if isinstance(answer, str) else "".join(answer))
            if not tool_call:
                if isinstance(answer, str):
                    return answer
                return "".join(answer)

        seen = set()
        last_call, last_result, last_error = tool_call, None, None
        tool_limit = self.get_max_tool_steps(route)
        for step in range(tool_limit):
            key = self.normalize_tool_call(tool_call)
            if key in seen:
                break  # le modèle tourne en rond : on s'arrête
            seen.add(key)
            last_call = tool_call
            try:
                result = self.execute_tool(tool_call, chat, allowed_tools=selected_tools)
                payload, last_error = result, None
            except Exception as error:
                result, payload, last_error = None, {"error": str(error)}, str(error)
            last_result = result

            if isinstance(result, dict) and result.get("confirmation_required"):
                chat["pending_tool"] = tool_call
                return f"{result.get('message', 'Confirmation nécessaire.')}\nRéponds « oui » pour confirmer."

            if step == 0 and not pending_tool and last_error is None and not FOLLOW_UP_RE.search(str(message)):
                summary = self._summary(tool_call, result)
                if summary:
                    return summary  # action simple : inutile de rappeler le modèle

            messages.append({"role": "assistant", "content": answer})
            messages.append(self._tool_message(tool_call["tool"], payload))
            answer = ask_ollama(list(messages), model=self.model)
            tool_call = self.parse_tool_call(answer)
            if not tool_call:
                return answer

        if last_error:
            return f"L'action {last_call['tool']} a échoué : {last_error}"
        summary = self._summary(last_call, last_result)
        return summary or f"Action {last_call['tool']} exécutée."

    def close(self):
        self.connection.close()
