#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Serveur web local_ia, basé uniquement sur la bibliothèque standard."""

from __future__ import annotations

import json
import mimetypes
import re
import argparse
import base64
import hmac
import ipaddress
import os
import secrets

from local_ia.tools import applications as application_launcher
from local_ia.tools import commands as command_commands
from local_ia.tools import files as file_commands
from local_ia.tools import programs as program_commands
from local_ia.core import conversation as conversation_store
from local_ia.core.agent import LocalAgent
import socket
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse
from local_ia.http_client import Request, open_url as urlopen

BASE_DIR = Path(__file__).resolve().parent
WEB_DIR = BASE_DIR / "web"
CONFIG_PATH = BASE_DIR / "config.json"
CHAT_DIR = BASE_DIR / "chats"
CHAT_LOCK = threading.RLock()
CHAT_AGENTS = {}
CHAT_AGENTS_LOCK = threading.RLock()
OLLAMA_DEFAULT = "http://127.0.0.1:11434"


def read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def config():
    data = read_json(CONFIG_PATH, {})
    if not isinstance(data, dict):
        data = {}
    roots = data.get("file_access_roots", [str(BASE_DIR)])
    if isinstance(roots, str):
        roots = [roots]
    file_commands.set_access_roots(roots)
    return data


def command_execution_config():
    value = config().get("command_execution", {})
    return value if isinstance(value, dict) else {}


def explicit_command_request(message):
    text = str(message or "").strip().lower()
    if text.startswith(("/commande", "/command", "/execute", "/executer")):
        return True
    return any(
        phrase in text
        for phrase in (
            "lance ", "ouvre ", "exécute ", "execute ", "démarre ", "demarre ",
            "baisse le volume", "monte le volume", "augmente le volume",
            "coupe le son", "remets le son",
        )
    )


def authorization_response(message):
    text = str(message or "").strip().lower()
    return text in {
        "oui", "yes", "ok", "d'accord", "d accord", "j'autorise",
        "j autorise", "autorise", "je confirme", "confirme", "lance",
    }


def extract_permission_request(content):
    match = re.search(r"<permission_request>\s*(\{.*?\})\s*</permission_request>", content or "", re.S)
    if not match:
        return None
    try:
        payload = json.loads(match.group(1))
    except json.JSONDecodeError:
        return None
    tool = payload.get("tool", "execute_command")
    if tool == "launch_application" and isinstance(payload.get("name"), str):
        return {"tool": tool, "name": payload["name"], "reason": str(payload.get("reason", ""))}
    argv = payload.get("argv")
    if tool == "execute_command" and isinstance(argv, list) and argv and all(isinstance(x, str) for x in argv):
        return {"tool": tool, "argv": argv, "reason": str(payload.get("reason", ""))}
    return None


def ollama_url():
    value = config().get("ollama", {})
    if isinstance(value, dict):
        url = value.get("url") or OLLAMA_DEFAULT
    else:
        url = OLLAMA_DEFAULT
    url = str(url).rstrip("/")
    # Le client Ollama utilise /api/chat ; l'utilisateur peut fournir localhost:11434.
    if url.endswith("/api"):
        url = url[:-4]
    return url


def installed_models():
    """Retourne toujours un dictionnaire de la forme {models, error}."""
    try:
        req = Request(ollama_url() + "/api/tags", method="GET")
        with urlopen(req, timeout=4) as response:
            data = json.loads(response.read().decode("utf-8"))

        # Ollama renvoie normalement {"models": [...]}. On tolère aussi
        # une réponse directement sous forme de liste pour éviter qu'une
        # réponse atypique fasse planter les endpoints web.
        raw_models = data.get("models", []) if isinstance(data, dict) else data
        if not isinstance(raw_models, list):
            raw_models = []

        models = [
            {
                "name": x.get("name", ""),
                "size": x.get("size", 0),
                "modified_at": x.get("modified_at", ""),
            }
            for x in raw_models
            if isinstance(x, dict) and x.get("name")
        ]
        return {"models": models, "error": None}
    except Exception as exc:
        return {"error": str(exc), "models": []}


def _sync_chat_store():
    global CHAT_DIR
    conversation_store.CHAT_DIR = CHAT_DIR
    return conversation_store


def chats():
    _sync_chat_store()
    return conversation_store.list_chats()


def get_chat(chat_id):
    try:
        cid = int(chat_id)
    except (TypeError, ValueError):
        return None
    with CHAT_LOCK:
        with CHAT_AGENTS_LOCK:
            session = CHAT_AGENTS.get(str(cid))
            if session:
                return session["chat"]
        _sync_chat_store()
        return conversation_store.load_chat(cid)


def save_chat(chat):
    """Sauvegarde une conversation via la couche centrale de conversation."""
    _sync_chat_store()
    with CHAT_LOCK:
        conversation_store.save_chat(chat, async_mode=False)


def create_chat():
    _sync_chat_store()
    with CHAT_LOCK:
        return conversation_store.create_chat()


def model_from_config():
    c = config()
    # Supporte la structure actuelle et l'ancienne structure {"model": "..."}.
    if isinstance(c.get("ollama"), dict) and c["ollama"].get("model"):
        return str(c["ollama"]["model"])
    return str(c.get("model", ""))


def chat_agent(chat, model=None):
    chat_id = str(chat["id"])
    selected_model = str(model or model_from_config()).strip()
    with CHAT_AGENTS_LOCK:
        session = CHAT_AGENTS.get(chat_id)
        if session and session["agent"].model != selected_model:
            with session["lock"]:
                session["agent"].close()
            session = None
        if session is None:
            agent = LocalAgent(model=selected_model)
            agent.prepare_chat(chat)
            session = {"agent": agent, "chat": chat, "lock": threading.RLock()}
            CHAT_AGENTS[chat_id] = session
        else:
            session["chat"] = chat
            session["agent"].prepare_chat(chat)
    return session


def close_chat_agents():
    with CHAT_AGENTS_LOCK:
        sessions = list(CHAT_AGENTS.values())
        CHAT_AGENTS.clear()
    for session in sessions:
        with session["lock"]:
            session["agent"].close()


def close_chat_agent(chat_id):
    with CHAT_AGENTS_LOCK:
        session = CHAT_AGENTS.pop(str(chat_id), None)
    if session:
        with session["lock"]:
            session["agent"].close()


def ask_ollama(model, messages):
    payload = {"model": model, "messages": messages, "stream": False}
    raw = json.dumps(payload).encode("utf-8")
    req = Request(
        ollama_url() + "/api/chat",
        data=raw,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    timeout = 120
    try:
        timeout = int(config().get("ollama", {}).get("timeout", 120))
    except Exception:
        pass
    with urlopen(req, timeout=max(5, timeout)) as response:
        result = json.loads(response.read().decode("utf-8"))
    return result.get("message", {}).get("content", "").strip()


def extract_command_tool(content):
    tool = extract_tool_call(content)
    if tool and tool.get("name") == "execute_command":
        return tool["arguments"].get("argv")
    return None


def extract_tool_call(content):
    match = re.search(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", content or "", re.S)
    if not match:
        return None
    try:
        payload = json.loads(match.group(1))
    except json.JSONDecodeError:
        return None
    if payload.get("name") not in ("execute_command", "launch_application"):
        return None
    arguments = payload.get("arguments", {})
    if not isinstance(arguments, dict):
        return None
    if payload["name"] == "execute_command":
        argv = arguments.get("argv")
        if not isinstance(argv, list) or not argv or not all(isinstance(x, str) for x in argv):
            return None
    elif not isinstance(arguments.get("name"), str) or not arguments["name"].strip():
        return None
    return {"name": payload["name"], "arguments": arguments}


def chat_with_model(model, chat, file_context=None, execution_context=None, allow_command_tool=False, allow_launch_tool=True, session=None):
    messages = chat.get("messages", [])
    current_message = messages[-1].get("content", "") if messages else ""
    history_chat = dict(chat)
    history_chat["messages"] = messages[:-1] if messages else []
    extra_context = "".join(part for part in (file_context, execution_context) if part)
    if extra_context:
        current_message += "\n\n" + extra_context

    allowed_tools = {"memory", "context", "file", "write", "edit", "list", "search", "web", "launch", "open_page"}
    if not allow_launch_tool:
        allowed_tools.discard("launch")
    if allow_command_tool:
        allowed_tools.update({"launch", "command", "system"})

    owns_agent = session is None
    agent = LocalAgent(model=model) if owns_agent else session["agent"]
    try:
        if session is None:
            return agent.respond(history_chat, current_message, allowed_tools=allowed_tools)
        with session["lock"]:
            return agent.respond(history_chat, current_message, allowed_tools=allowed_tools)
    finally:
        if owns_agent:
            agent.close()


def json_out(handler, data, status=200):
    body = json.dumps(data, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(body)


class Handler(BaseHTTPRequestHandler):
    server_version = "local_ia/2.0"
    POST_ROUTES = {
        ("POST", "/api/chats/new"): "_post_new_chat",
        ("POST", "/api/chat"): "_post_chat",
    }

    def _is_local_client(self):
        try:
            address = ipaddress.ip_address(self.client_address[0].split("%", 1)[0])
            if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
                address = address.ipv4_mapped
            return address.is_loopback
        except (AttributeError, ValueError):
            return False

    def _is_authorized(self):
        token = getattr(self.server, "auth_token", None)
        if not token:
            return True

        authorization = self.headers.get("Authorization", "")
        supplied = None
        scheme, _, credentials = authorization.partition(" ")
        if scheme.lower() == "bearer":
            supplied = credentials
        elif scheme.lower() == "basic":
            try:
                decoded = base64.b64decode(credentials, validate=True).decode("utf-8")
                username, separator, password = decoded.partition(":")
                if separator and username == "kairo":
                    supplied = password
            except (ValueError, UnicodeDecodeError):
                pass

        if supplied is not None and hmac.compare_digest(supplied, token):
            return True

        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="KAIRO", charset="UTF-8"')
        self.send_header("Content-Length", "0")
        self.end_headers()
        return False

    def _execute_local_command(self, message, command_config):
        if not self._is_local_client():
            return None
        return command_commands.execute_command(
            message,
            timeout=command_config.get("timeout", command_commands.DEFAULT_TIMEOUT),
        )

    def log_message(self, fmt, *args):
        # Le serveur tourne en continu : ne pas empiler les logs HTTP dans
        # la console interactive. L'interface web reste la source d'affichage.
        return

    def static(self, relative):
        root = WEB_DIR.resolve()
        target = (WEB_DIR / relative).resolve()
        if root not in target.parents and target != root:
            self.send_error(403)
            return
        if not target.is_file():
            self.send_error(404)
            return
        data = target.read_bytes()
        content_type = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        if target.suffix == ".js":
            content_type = "application/javascript"
        self.send_response(200)
        self.send_header("Content-Type", content_type + ("" if "charset" in content_type else "; charset=utf-8"))
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if not self._is_authorized():
            return
        path = urlparse(self.path).path
        if path == "/":
            return self.static("index.html")
        if path in ("/app.js", "/style.css"):
            return self.static(path[1:])
        if path == "/api/status":
            models = installed_models()
            return json_out(self, {
                "ok": not bool(models.get("error")),
                "ollama": ollama_url(),
                "model": model_from_config(),
                "models": models.get("models", []),
                "error": models.get("error"),
            })
        if path == "/api/models":
            models = installed_models()
            return json_out(self, {
                "installed": models.get("models", []),
                "error": models.get("error"),
            })
        if path == "/api/chats":
            return json_out(self, {"chats": chats()})
        if path.startswith("/api/chats/"):
            chat = get_chat(path.rsplit("/", 1)[-1])
            if chat:
                chat_agent(chat)
            return json_out(self, {"chat": chat})
        if path == "/api/config-info":
            c = config()
            return json_out(self, {
                "model": model_from_config(),
                "ollama_url": ollama_url(),
                "language": c.get("utilisateur", {}).get("langue", "français") if isinstance(c.get("utilisateur"), dict) else "français",
            })
        self.send_error(404)

    def do_POST(self):
        if not self._is_authorized():
            return
        path = urlparse(self.path).path
        try:
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
        except Exception:
            return json_out(self, {"error": "JSON invalide."}, 400)

        if path.startswith("/api/chats/") and path.endswith("/close"):
            return self._post_close_chat(path)

        route = self.POST_ROUTES.get(("POST", path))
        if route is None:
            return self.send_error(404)
        return getattr(self, route)(body)

    def _post_new_chat(self, body):
        chat = create_chat()
        chat_agent(chat)
        return json_out(self, {"chat": chat})

    def _post_close_chat(self, path):
        close_chat_agent(path.split("/")[-2])
        return json_out(self, {"ok": True})

    def _post_chat(self, body):
        message = str(body.get("message", "")).strip()
        if not message:
            return json_out(self, {"error": "Message vide."}, 400)
        chat = get_chat(body.get("chat_id"))
        if chat is None:
            return json_out(self, {"error": "Conversation introuvable."}, 404)
        command_config = command_execution_config()

        pending = chat.get("pending_command")
        if pending and authorization_response(message):
            if not self._is_local_client():
                return json_out(self, {"error": "Les commandes sont réservées aux clients locaux."}, 403)
            try:
                if pending.get("tool") == "launch_application":
                    application = application_launcher.launch_application(pending["name"])
                    command_result = {
                        "returncode": 0,
                        "command": application["argv"],
                        "stdout": "Application lancée.",
                        "stderr": "",
                    }
                else:
                    command_result = command_commands.execute_argv(
                        pending["argv"],
                        timeout=command_config.get("timeout", command_commands.DEFAULT_TIMEOUT),
                    )
            except Exception as exc:
                return json_out(self, {"error": f"Commande : {exc}"}, 400)
            chat.pop("pending_command", None)
            output = command_result["stdout"]
            if command_result["stderr"]:
                output += ("\n" if output else "") + command_result["stderr"]
            answer = (
                f"Commande autorisée et terminée avec le code {command_result['returncode']} : "
                f"`{' '.join(command_result['command'])}`\n\n"
                f"{output or '(aucune sortie)'}"
            )
            chat.setdefault("messages", []).extend([
                {"role": "user", "content": message},
                {"role": "assistant", "content": answer},
            ])
            save_chat(chat)
            return json_out(self, {
                "ok": command_result["returncode"] == 0,
                "answer": answer,
                "chat": chat,
                "command": command_result,
            })

        program_result = None
        if self._is_local_client():
            try:
                program_result = program_commands.execute_command(message)
            except Exception as exc:
                return json_out(self, {"error": f"Exécution : {exc}"}, 400)
        if program_result:
            return self._post_program_result(chat, message, program_result)

        try:
            command_result = self._execute_local_command(message, command_config)
        except Exception as exc:
            return json_out(self, {"error": f"Commande : {exc}"}, 400)
        if command_result:
            return self._post_command_result(chat, message, command_result, "Commande terminée")

        model = str(body.get("model") or model_from_config()).strip()
        models = installed_models()
        if models.get("error"):
            return json_out(self, {"error": "Ollama inaccessible : " + str(models["error"])}, 503)
        if not any(item["name"] == model for item in models["models"]):
            return json_out(self, {"error": f"Le modèle '{model}' n'est pas installé."}, 400)

        try:
            file_result = file_commands.execute_command(message)
        except Exception as exc:
            return json_out(self, {"error": f"Commande /fichier : {exc}"}, 400)

        chat.setdefault("messages", []).append({"role": "user", "content": message})
        if file_result and file_result["command"]["action"] in ("create", "edit"):
            data = file_result["result"]
            verb = "créé" if file_result["command"]["action"] == "create" else "modifié"
            answer = f"Fichier {verb} : `{data['path']}` ({data['size']} octets)."
            chat["messages"].append({"role": "assistant", "content": answer})
            save_chat(chat)
            return json_out(self, {"ok": True, "answer": answer, "chat": chat, "file": data})

        file_context = file_commands.prompt_block(file_result) if file_result else None
        local_client = self._is_local_client()
        allow_command_tool = local_client and bool(
            command_config.get("enabled", False) or explicit_command_request(message)
        )
        session = chat_agent(chat, model)
        try:
            answer = chat_with_model(
                model,
                chat,
                file_context=file_context,
                allow_command_tool=allow_command_tool,
                allow_launch_tool=local_client,
                session=session,
            )
            tool_call = extract_tool_call(answer) if allow_command_tool else None
            if tool_call and tool_call["name"] == "launch_application":
                application_name = tool_call["arguments"]["name"]
                application = application_launcher.launch_application(application_name)
                execution_context = (
                    f"Résultat de l'outil launch_application : l'application "
                    f"{application_name} a été lancée."
                )
                answer = chat_with_model(
                    model,
                    chat,
                    file_context=file_context,
                    execution_context=execution_context,
                    allow_command_tool=False,
                    allow_launch_tool=local_client,
                    session=session,
                )
            elif tool_call and tool_call["name"] == "execute_command":
                tool_argv = tool_call["arguments"]["argv"]
                tool_result = command_commands.execute_argv(
                    tool_argv,
                    timeout=command_config.get("timeout", command_commands.DEFAULT_TIMEOUT),
                )
                tool_output = tool_result["stdout"]
                if tool_result["stderr"]:
                    tool_output += ("\n" if tool_output else "") + tool_result["stderr"]
                execution_context = (
                    "Résultat de l'outil execute_command (ne relance pas une commande):\n"
                    f"code retour: {tool_result['returncode']}\n"
                    f"sortie:\n{tool_output or '(aucune sortie)'}"
                )
                answer = chat_with_model(
                    model,
                    chat,
                    file_context=file_context,
                    execution_context=execution_context,
                    allow_command_tool=False,
                    allow_launch_tool=local_client,
                    session=session,
                )
            else:
                permission = extract_permission_request(answer)
                if permission:
                    chat["pending_command"] = permission
                    answer = re.sub(
                        r"\s*<permission_request>.*?</permission_request>",
                        "",
                        answer,
                        flags=re.S,
                    ).strip()
                    if permission["tool"] == "launch_application":
                        description = f"ouvrir {permission['name']}"
                    else:
                        description = f"exécuter `{' '.join(permission['argv'])}`"
                    answer += f"\n\nAutorisation requise pour {description}. Répondez « oui » pour confirmer."
        except Exception as exc:
            chat["messages"].pop()
            return json_out(self, {"error": f"Erreur Ollama : {exc}"}, 502)
        chat["messages"].append({"role": "assistant", "content": answer})
        save_chat(chat)
        return json_out(self, {
            "ok": True,
            "answer": answer,
            "chat": chat,
            "file": file_result["result"] if file_result else None,
        })

    def _post_program_result(self, chat, message, program_result):
        result = program_result["result"]
        output = result["stdout"]
        if result["stderr"]:
            output += ("\n" if output else "") + result["stderr"]
        answer = (
            f"Programme terminé avec le code {result['returncode']} : "
            f"`{result['path']}`\n\n{output or '(aucune sortie)'}"
        )
        return self._save_execution_result(chat, message, answer, result, "program")

    def _post_command_result(self, chat, message, result, heading):
        output = result["stdout"]
        if result["stderr"]:
            output += ("\n" if output else "") + result["stderr"]
        answer = (
            f"{heading} avec le code {result['returncode']} : "
            f"`{' '.join(result['command'])}`\n\n{output or '(aucune sortie)'}"
        )
        return self._save_execution_result(chat, message, answer, result, "command")

    def _save_execution_result(self, chat, message, answer, result, result_key):
        chat.setdefault("messages", []).extend([
            {"role": "user", "content": message},
            {"role": "assistant", "content": answer},
        ])
        save_chat(chat)
        return json_out(self, {
            "ok": result["returncode"] == 0,
            "answer": answer,
            "chat": chat,
            result_key: result,
        })


class KairoHTTPServer(ThreadingHTTPServer):
    auth_token: str | None = None


def network_urls(port):
    urls = [f"http://127.0.0.1:{port}"]
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = str(info[4][0])
            if not ip.startswith("127.") and ip != "0.0.0.0":
                url = f"http://{ip}:{port}"
                if url not in urls:
                    urls.append(url)
    except OSError:
        pass
    return urls


def is_loopback_host(host):
    if str(host).lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def run_server(port=8080, host="127.0.0.1", token=None):
    if not WEB_DIR.is_dir() or not (WEB_DIR / "index.html").is_file():
        raise RuntimeError(f"Interface web introuvable : {WEB_DIR}")
    port = int(port)
    if not 1 <= port <= 65535:
        raise ValueError("Le port doit être compris entre 1 et 65535.")

    if not is_loopback_host(host):
        token = token or os.environ.get("LOCAL_IA_SERVER_TOKEN") or secrets.token_urlsafe(32)
        if len(token) < 32:
            raise ValueError("Le jeton serveur doit contenir au moins 32 caractères.")

    httpd = KairoHTTPServer((host, port), Handler)
    httpd.auth_token = token if not is_loopback_host(host) else None
    print("\n" + "=" * 60)
    print("LOCAL_IA — SERVEUR WEB")
    print("=" * 60)
    print(f"Écoute : http://{host}:{port}")
    if httpd.auth_token:
        print(f"Jeton d'accès (HTTP Basic, utilisateur kairo) : {httpd.auth_token}")
        if host in ("0.0.0.0", ""):
            for url in network_urls(port):
                print(f"Adresse : {url}")
    print("Ctrl+C pour arrêter le serveur.")
    print("=" * 60 + "\n")
    try:
        httpd.serve_forever()
    finally:
        httpd.server_close()
        close_chat_agents()


if __name__ == "__main__":
    try:
        parser = argparse.ArgumentParser(description="Serveur web local KAIRO")
        parser.add_argument("port", nargs="?", type=int)
        parser.add_argument("--host", default="127.0.0.1")
        parser.add_argument("--token", default=None)
        arguments = parser.parse_args()
        port = arguments.port
        if port is None and sys.stdin.isatty():
            value = input("Port HTTP (8080 par défaut) : ").strip()
            port = int(value) if value else 8080
        run_server(port or 8080, host=arguments.host, token=arguments.token)
    except KeyboardInterrupt:
        print("\nServeur arrêté.")
    except Exception as exc:
        print(f"Erreur : {exc}", file=sys.stderr)
        sys.exit(1)
