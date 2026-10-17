"""Interface CLI de local_ia."""

from __future__ import annotations

import json
import os
import re
import shlex
import sys
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import ui
from local_ia.config.manager import load_config, model_config
from local_ia.core import code_projects
from local_ia.core.agent import LocalAgent
from local_ia.core.context import CONTEXT_PATH, load_context
from local_ia.core.conversation import (
    add_chat_message,
    clear_chat,
    create_chat,
    list_chats,
    load_chat,
    save_chat,
)
from local_ia.core.memory import (
    clear_memories,
    delete_memory,
    init_database,
    list_memories,
    save_memory,
    save_memory_if_relevant,
)
from local_ia.tools import file as file_tool

LOCAL_CODE_TOOLS = frozenset({"file", "write", "edit", "list", "search", "calculator"})
LOCAL_CODE_READ_TOOLS = frozenset({"file", "list", "search", "calculator"})


def show_help():
    print("""
Commandes disponibles :
  /help              Afficher cette aide
  /memory            Afficher les souvenirs
  /remember <texte>  Enregistrer un souvenir
    /forget <id>       Effacer un souvenir précis (ID visible avec /memory)
    /forget-all        Effacer tous les souvenirs après confirmation
  /context           Afficher le contexte permanent
  /topic [sujet]     Afficher ou définir le sujet
  /chats             Lister les conversations
  /new               Créer une conversation
  /load <id>         Charger une conversation
  /chat              Afficher les informations du chat courant
  /clear             Effacer la conversation courante
  /fichier (chemin)  Lire un fichier et l'ajouter au contexte
    /commande <programme> [arguments]  Exécuter sans shell; confirmation si risqué
    /code <demande>    Créer ou continuer un projet de code
    /code --project "Nom" <demande>  Choisir un projet existant ou en créer un
  /reload            Recharger la configuration
  /exit              Quitter
""".strip())


def render_message(role, content, created_at=None):
    label = "Vous" if role == "user" else "IA"
    color = ui.C.USER if role == "user" else ui.C.IA
    print(ui.colorize(label, color) + "  " + ui.colorize(
        f"[{ui.format_timestamp(created_at)}]", ui.C.TIME
    ))
    print(content)
    print()


def replay_history(chat):
    for message in chat.get("messages", []):
        if message.get("role") in {"user", "assistant"}:
            render_message(message["role"], message.get("content", ""), message.get("created_at"))


def show_context(context):
    print(json.dumps(context, ensure_ascii=False, indent=4))


def _file_command(message):
    match = re.match(r"^/fichier\s*\((.+?)\)\s*$", message, re.S)
    if not match:
        return None
    path = match.group(1).strip().strip("\"'")
    return file_tool.use(path)


def _remember_automatically(connection, message):
    return save_memory_if_relevant(connection, message, async_mode=True)


def _handle_memory_command(connection, agent, message, input_fn=input):
    if message == "/memory":
        memories = list_memories(connection)
        print("\n".join(f"#{item['id']} - {item['content']}" for item in memories) or "Aucun souvenir.")
        return True
    if message.startswith("/remember "):
        save_memory(connection, message[10:].strip())
        agent.reload_memories()
        ui.print_ok("Souvenir enregistré.")
        return True
    if message == "/forget" or message.startswith("/forget "):
        memory_id = message[len("/forget"):].strip()
        if not memory_id.isdecimal() or int(memory_id) < 1:
            ui.print_error("Syntaxe : /forget <id> (utilise /memory pour afficher les ID).")
            return True
        if delete_memory(connection, int(memory_id)):
            agent.reload_memories()
            ui.print_ok(f"Souvenir #{memory_id} oublié.")
        else:
            ui.print_error(f"Souvenir #{memory_id} introuvable.")
        return True
    if message == "/forget-all":
        try:
            answer = input_fn("Effacer définitivement tous les souvenirs ? [o/N] ").strip().casefold()
        except (EOFError, KeyboardInterrupt):
            answer = ""
        if answer not in {"o", "oui", "y", "yes"}:
            print("Suppression des souvenirs annulée.")
            return True
        count = clear_memories(connection)
        if count:
            agent.reload_memories()
        ui.print_ok(f"{count} souvenir(s) effacé(s).")
        return True
    return False


def _chat_info(chat):
    print(f"Chat : {chat['id']}")
    print(f"Créé : {chat.get('created_at', 'inconnu')}")
    print(f"Messages : {len(chat.get('messages', []))}")
    print(f"Nom : {chat.get('topic') or chat.get('title') or 'Conversation sans titre'}")
    print(f"Sujet : {chat.get('topic') or 'aucun'}")
    print(f"Fichiers : {len(chat.get('files', []))}")
    if chat.get("code_project_name"):
        print(f"Projet code : {chat['code_project_name']}")


def _parse_local_code_command(message):
    payload = str(message or "")[len("/code"):].strip()
    if payload.startswith("--project"):
        parts = shlex.split(payload)
        if len(parts) < 2 or parts[0] != "--project":
            raise ValueError('Syntaxe : /code --project "Nom du projet" <demande>')
        project_name = parts[1]
        request = " ".join(parts[2:]).strip()
    else:
        project_name = None
        request = payload
    if not request:
        raise ValueError("Ajoute une demande après /code.")
    return project_name, request


def _prepare_local_code(message, chat):
    requested_project, request = _parse_local_code_command(message)
    project = None
    if requested_project:
        project = code_projects.create_or_open_project(requested_project)
    elif chat.get("code_project_path"):
        try:
            project = code_projects.resolve_active_project(chat["code_project_path"])
        except (OSError, ValueError):
            project = None

    if project is None:
        project_name = code_projects.suggest_project_name(request)
        project = code_projects.create_or_open_project(project_name)
        print(f"Nouveau projet Local Code : {project.name}")

    chat["code_project_name"] = project.name
    chat["code_project_path"] = str(project)
    code_projects.install_code_examples(project)
    save_chat(chat, async_mode=False)
    return request, project


def _local_code_tools(config):
    tools = set(LOCAL_CODE_TOOLS)
    command_config = config.get("command_execution", {})
    if isinstance(command_config, dict) and command_config.get("enabled"):
        tools.add("command")
    return tools


def _local_code_instructions(project, command_enabled):
    command_guidance = (
        "Tu peux lancer des commandes de test/build; elles s'exécutent dans le dossier du projet."
        if command_enabled
        else "L'exécution de commandes est désactivée; modifie uniquement les fichiers et indique les tests à lancer."
    )
    return (
        "MODE LOCAL_CODE : tu es l'assistant de développement de l'utilisateur.\n"
        f"Projet : {project.name}\nRacine autorisée : {project}\n"
        "Agis comme un agent de développement autonome : analyse la demande, choisis les détails raisonnables manquants, "
        "puis réalise le travail avec les outils jusqu'à obtenir un résultat complet. Ne t'arrête pas après avoir annoncé "
        "un plan ou créé le premier fichier. Ne demande pas à l'utilisateur de répondre pour choisir un nom, une structure "
        "ou un style sans enjeu; pose une question uniquement si une information indispensable manque ou si une décision "
        "à risque ne peut pas être prise sans lui.\n"
        "Utilise exclusivement les outils de fichiers avec des chemins relatifs à la racine du projet. "
        "N'accède et n'écris jamais en dehors de cette racine. Lis les fichiers existants avant de les modifier, "
        "consulte d'abord exemple/README.md pour réutiliser une fonction adaptée et lis le fichier d'exemple concerné. "
        "Copie seulement les fonctions utiles dans les fichiers du projet, sans modifier les exemples d'origine. "
        "préserve le travail présent, relis les fichiers créés ou modifiés et vérifie le résultat avec les moyens disponibles, "
        "puis résume les fichiers changés, les vérifications effectuées et toute limite importante.\n"
        f"{command_guidance}"
    )


def _local_code_proposal_instructions(project):
    return (
        "MODE COMMANDE LOCAL_CODE : analyse le projet et prépare les modifications de fichiers nécessaires, "
        "avec une commande write/edit par sous-tâche. "
        f"Projet : {project.name}\nRacine autorisée : {project}\n"
        "Utilise file, list et search pour comprendre le code existant. Puis retourne uniquement un appel "
        'un appel <tool_call> valide, avec tool="write" ou tool="edit", des arguments JSON et un chemin relatif à la racine. '
        "Ne modifie aucun fichier avant approbation. N'ajoute ni diagnostic, ni diff, ni commentaire, ni texte autour de l'appel. "
        "N'utilise pas command pour créer ou modifier un fichier."
    )


def _run_local_code_loop(
    agent,
    chat,
    request,
    project,
    tools,
    *,
    input_fn=input,
    display=render_message,
    respond=None,
):
    respond = respond or agent.respond
    proposal_tools = {"file", "list", "search"} | ({"write", "edit"} & set(tools))
    proposal = respond(
        chat,
        request,
        external_info=_local_code_proposal_instructions(project),
        allowed_tools=proposal_tools,
        local_code=True,
        defer_file_actions=True,
    )
    display("assistant", proposal)
    try:
        approval = input_fn("Appliquer ces modifications au projet ? [o/N] ").strip().casefold()
    except (EOFError, KeyboardInterrupt):
        approval = ""
    if approval not in {"o", "oui", "y", "yes"}:
        return "Proposition refusée ou annulée. Aucun fichier n'a été modifié."

    result = agent.apply_approved_file_call(proposal, chat, allowed_tools=tools)
    display("assistant", result)
    return result


def main():
    connection = init_database()
    context = load_context()
    chat_mode = os.environ.get("LOCAL_IA_CHAT_MODE", "new")
    requested_id = os.environ.get("LOCAL_IA_CHAT_ID")
    chat = load_chat(int(requested_id)) if chat_mode == "load" and requested_id and requested_id.isdigit() else None
    if chat is None:
        chat = create_chat()

    agent = None
    try:
        ui.clear_screen()
        ui.brand_logo()
        ui.section_title(f"{ui.PRODUCT_NAME} · ASSISTANT LOCAL", clear=False)
        print("Préparation en cours…", flush=True)
        agent = LocalAgent(model=model_config(load_config()))
        agent.prepare_chat(chat)
        ui.clear_screen()
        ui.brand_logo()
        ui.section_title(f"{ui.PRODUCT_NAME} · ASSISTANT LOCAL", clear=False)
        print(f"Modèle : {model_config(load_config())}")
        print(f"Contexte : {CONTEXT_PATH}")
        conversation_title = chat.get("topic") or chat.get("title") or "sans titre"
        print(f"Conversation : {chat['id']} | {conversation_title}")
        print("Tapez /help pour afficher les commandes.\n")
        replay_history(chat)

        while True:
            try:
                user_message = input(ui.colorize("> ", ui.C.USER)).strip()
            except (KeyboardInterrupt, EOFError):
                print("\nAu revoir.")
                break
            if not user_message:
                continue
            if user_message == "/exit":
                print("Au revoir.")
                break
            if user_message == "/help":
                show_help()
                continue
            local_code = user_message == "/code" or user_message.startswith("/code ")
            code_request = user_message
            code_instructions = None
            code_tools = None
            if local_code:
                try:
                    code_request, project = _prepare_local_code(user_message, chat)
                    config = load_config()
                    code_tools = _local_code_tools(config)
                    code_instructions = _local_code_instructions(
                        project,
                        command_enabled="command" in code_tools,
                    )
                except (OSError, ValueError) as error:
                    ui.print_error(str(error))
                    continue
            if _handle_memory_command(connection, agent, user_message):
                continue
            if user_message == "/context":
                show_context(context)
                continue
            if user_message == "/topic":
                print(chat.get("topic") or chat.get("title") or "Aucun sujet défini.")
                continue
            if user_message.startswith("/topic "):
                chat["topic"] = user_message[7:].strip()
                save_chat(chat)
                continue
            if user_message == "/chats":
                for item in list_chats():
                    title = item.get("topic") or item.get("title") or item.get("summary") or "sans titre"
                    print(f"{item['id']} | {title} | {len(item.get('messages', []))} messages")
                continue
            if user_message == "/new":
                chat = create_chat()
                print(f"Nouvelle conversation : {chat['id']}")
                continue
            if user_message.startswith("/load ") and user_message[6:].isdigit():
                loaded = load_chat(int(user_message[6:]))
                if loaded:
                    chat = loaded
                    replay_history(chat)
                else:
                    ui.print_error("Conversation introuvable.")
                continue
            if user_message == "/chat":
                _chat_info(chat)
                continue
            if user_message == "/clear":
                clear_chat(chat)
                print("Conversation effacée.")
                continue
            if user_message == "/reload":
                context = load_context()
                agent.reload_context()
                print("Contexte rechargé.")
                continue
            if user_message.startswith("/fichier"):
                try:
                    file_info = _file_command(user_message)
                    if file_info is None:
                        raise ValueError("Syntaxe : /fichier (chemin)")
                    chat.setdefault("files", []).append({
                        "path": file_info["path"],
                        "name": file_info["path"].rsplit("/", 1)[-1],
                        "extension": file_info["extension"],
                        "size": file_info["size"],
                        "created_at": datetime.now().isoformat(),
                        "content": file_info["content"],
                    })
                    save_chat(chat)
                    print(f"Fichier ajouté : {file_info['path']}")
                except (OSError, ValueError, PermissionError) as error:
                    ui.print_error(str(error))
                continue

            if not local_code and _remember_automatically(connection, user_message):
                agent.reload_memories()
            try:
                if local_code:
                    answer = _run_local_code_loop(
                        agent,
                        chat,
                        code_request,
                        project,
                        code_tools,
                        respond=lambda *args, **kwargs: _respond_with_status(agent, *args, **kwargs),
                    )
                else:
                    answer = _respond_with_status(
                        agent,
                        chat,
                        code_request,
                        external_info=code_instructions,
                        allowed_tools=code_tools,
                        local_code=False,
                    )
            except Exception as error:
                answer = f"Erreur lors de l'utilisation de l'IA : {error}"
            add_chat_message(chat, "user", user_message)
            add_chat_message(chat, "assistant", answer)
            conversation_title = chat.get("topic") or chat.get("title")
            if conversation_title:
                print(f"Conversation : {chat['id']} | {conversation_title}")
            render_message("assistant", answer)
    finally:
        if agent is not None:
            agent.close()
        connection.close()


def _respond_with_status(agent, *args, **kwargs):
    def show_progress(message):
        text = ui.colorize(f"IA  {message}", ui.C.INFO)
        sys.stdout.write("\r\033[2K" + text)
        sys.stdout.flush()

    kwargs["progress_callback"] = show_progress
    sys.stdout.write(ui.colorize("IA  Préparation en cours…", ui.C.INFO))
    sys.stdout.flush()
    try:
        return agent.respond(*args, **kwargs)
    finally:
        sys.stdout.write("\r\033[2K")
        sys.stdout.flush()


if __name__ == "__main__":
    main()