"""Interface CLI de local_ia."""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import ui
from local_ia.config.manager import load_config, model_config
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
from local_ia.core.memory import get_memories, init_database, save_memory, save_memory_if_relevant
from local_ia.tools import file as file_tool


def show_help():
    print("""
Commandes disponibles :
  /help              Afficher cette aide
  /memory            Afficher les souvenirs
  /remember <texte>  Enregistrer un souvenir
  /context           Afficher le contexte permanent
  /topic [sujet]     Afficher ou définir le sujet
  /chats             Lister les conversations
  /new               Créer une conversation
  /load <id>         Charger une conversation
  /chat              Afficher les informations du chat courant
  /clear             Effacer la conversation courante
  /fichier (chemin)  Lire un fichier et l'ajouter au contexte
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


def _chat_info(chat):
    print(f"Chat : {chat['id']}")
    print(f"Créé : {chat.get('created_at', 'inconnu')}")
    print(f"Messages : {len(chat.get('messages', []))}")
    print(f"Nom : {chat.get('topic') or chat.get('title') or 'Conversation sans titre'}")
    print(f"Sujet : {chat.get('topic') or 'aucun'}")
    print(f"Fichiers : {len(chat.get('files', []))}")


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
        ui.section_title("IA AGENT LOCAL", clear=False)
        print("Préparation en cours…", flush=True)
        agent = LocalAgent(model=model_config(load_config()))
        agent.prepare_chat(chat)
        ui.clear_screen()
        ui.section_title("IA AGENT LOCAL", clear=False)
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
            if user_message == "/memory":
                memories = get_memories(connection)
                print("\n".join(f"- {item}" for item in memories) or "Aucun souvenir.")
                continue
            if user_message.startswith("/remember "):
                save_memory(connection, user_message[10:].strip())
                agent.reload_memories()
                ui.print_ok("Souvenir enregistré.")
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

            if _remember_automatically(connection, user_message):
                agent.reload_memories()
            sys.stdout.write(ui.colorize("IA  Préparation en cours…", ui.C.INFO))
            sys.stdout.flush()
            try:
                answer = agent.respond(chat, user_message)
            except Exception as error:
                answer = f"Erreur lors de l'utilisation de l'IA : {error}"
            finally:
                sys.stdout.write("\r\033[2K")
                sys.stdout.flush()
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


if __name__ == "__main__":
    main()