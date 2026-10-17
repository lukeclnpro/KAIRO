"""Outil de détection et de lancement d'une application locale."""

from local_ia.tools.app_detector_and_launcher import (
    find_application,
    launch_app,
    scan_installed_apps,
)


def launch_application(name):
    application = find_application(name)
    if not application:
        raise FileNotFoundError(f"Application introuvable : {name}")
    launch_app(application)
    return {"name": application["name"], "path": application["launch_value"]}


def use(name, confirmed=False):
    application = find_application(name)
    if not application:
        raise FileNotFoundError(f"Application introuvable : {name}")
    if not confirmed:
        return {
            "confirmation_required": True,
            "name": application["name"],
            "message": f"J'ai trouvé {application['name']}. Voulez-vous le lancer ?",
        }
    return launch_application(application["name"])