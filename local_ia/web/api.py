"""API métier web indépendante du serveur HTTP."""

from local_ia.core.agent import LocalAgent


def reply(chat, message, model=None):
    agent = LocalAgent(model=model)
    try:
        return agent.respond(chat, message)
    finally:
        agent.close()