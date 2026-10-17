
import json
import urllib.request
import urllib.parse
import calendar
import re
from datetime import datetime, date
from pathlib import Path

# ============================================================
# CONFIGURATION
# ============================================================

FICHIER_JSON = Path.home() / ".ia_agent" / "habitudes.json"
ANCIEN_FICHIER_JSON = Path(__file__).resolve().parent / "habitudes.json"

VILLE_PAR_DEFAUT = "Paris"

JOURS_FR = [
    "lundi", "mardi", "mercredi", "jeudi",
    "vendredi", "samedi", "dimanche"
]

JOURS_ALIASES = {
    "lun": "lundi",
    "lundi": "lundi",
    "mar": "mardi",
    "mardi": "mardi",
    "mer": "mercredi",
    "mercredi": "mercredi",
    "jeu": "jeudi",
    "jeudi": "jeudi",
    "ven": "vendredi",
    "vendredi": "vendredi",
    "sam": "samedi",
    "samedi": "samedi",
    "dim": "dimanche",
    "dimanche": "dimanche",
}


# ============================================================
# FICHIER JSON : CHARGEMENT ET SAUVEGARDE
# ============================================================

def structure_vide():
    return {
        "habitudes": [],
        "ville": VILLE_PAR_DEFAUT
    }


def charger():
    """Charge les données sans planter si le fichier est ancien ou absent."""

    source = FICHIER_JSON
    if not source.exists() and ANCIEN_FICHIER_JSON.is_file():
        source = ANCIEN_FICHIER_JSON
    if not source.exists():
        return structure_vide()

    try:
        with open(source, "r", encoding="utf-8") as fichier:
            data = json.load(fichier)
    except (json.JSONDecodeError, OSError):
        print("Attention : impossible de lire habitudes.json.")
        print("Un fichier de données vide va être utilisé.")
        return structure_vide()

    # Compatibilité avec un ancien fichier contenant directement une liste.
    if isinstance(data, list):
        data = {"habitudes": data, "ville": VILLE_PAR_DEFAUT}

    if not isinstance(data, dict):
        return structure_vide()

    data.setdefault("habitudes", [])
    data.setdefault("ville", VILLE_PAR_DEFAUT)

    if not isinstance(data["habitudes"], list):
        data["habitudes"] = []

    data = normaliser_habitudes(data)
    if source != FICHIER_JSON:
        sauver(data)
    return data


def normaliser_habitudes(data):
    """Convertit les anciens noms de champs vers le format actuel."""

    habitudes = []

    for ancienne in data.get("habitudes", []):
        if not isinstance(ancienne, dict):
            continue

        h = dict(ancienne)

        # Nom de la tâche
        if "task" not in h:
            h["task"] = (
                h.get("tache")
                or h.get("habitude")
                or h.get("nom")
                or "Habitude sans nom"
            )

        # Fréquence
        if "frequency" not in h:
            h["frequency"] = h.get("frequence", "daily")

        frequences = {
            "quotidien": "daily",
            "quotidienne": "daily",
            "tous les jours": "daily",
            "chaque jour": "daily",
            "hebdomadaire": "weekly",
            "chaque semaine": "weekly",
            "mensuel": "monthly",
            "mensuelle": "monthly",
            "chaque mois": "monthly",
        }

        frequence = str(h.get("frequency", "daily")).lower().strip()
        h["frequency"] = frequences.get(frequence, frequence)

        if h["frequency"] not in ("daily", "weekly", "monthly"):
            h["frequency"] = "daily"

        # Jours de la semaine
        if "days" not in h:
            h["days"] = h.get("jours", [])

        if isinstance(h["days"], str):
            h["days"] = [
                x.strip().lower()
                for x in re.split(r"[,; ]+", h["days"])
                if x.strip()
            ]

        if not isinstance(h["days"], list):
            h["days"] = []

        h["days"] = [
            JOURS_ALIASES.get(str(j).lower().strip(), str(j).lower().strip())
            for j in h["days"]
        ]

        # Jour du mois
        if "day_of_month" not in h:
            h["day_of_month"] = h.get("jour_mois")

        # Heure
        if "time" not in h:
            h["time"] = h.get("heure")

        # Moment de la journée
        h.setdefault("moment", "anytime")

        # Type : corrige aussi les anciens types "meteo".
        ancien_type = str(h.get("type", "ai")).lower().strip()

        types = {
            "meteo": "weather",
            "météo": "weather",
            "weather": "weather",
            "ia": "ai",
            "ai": "ai",
        }

        h["type"] = types.get(ancien_type, "ai")

        # Activité
        h.setdefault("active", True)

        if isinstance(h["active"], str):
            h["active"] = h["active"].lower() in (
                "true", "oui", "1", "yes", "actif", "active"
            )

        # Dernière exécution
        if "last_occurrence" not in h:
            h["last_occurrence"] = h.get("derniere_execution")

        habitudes.append(h)

    data["habitudes"] = habitudes
    data.setdefault("ville", VILLE_PAR_DEFAUT)

    return data


def sauver(data):
    """Sauvegarde les données dans le fichier JSON."""

    try:
        FICHIER_JSON.parent.mkdir(parents=True, exist_ok=True)
        with open(FICHIER_JSON, "w", encoding="utf-8") as fichier:
            json.dump(data, fichier, ensure_ascii=False, indent=4)
        return True
    except OSError as erreur:
        print(f"Erreur lors de la sauvegarde : {erreur}")
        return False


# ============================================================
# AFFICHAGE DES HABITUDES
# ============================================================

def description_frequence(h):
    frequence = h.get("frequency", "daily")

    if frequence == "daily":
        return "tous les jours"

    if frequence == "weekly":
        jours = h.get("days", [])
        if jours:
            return "chaque " + ", ".join(jours)
        return "chaque semaine"

    if frequence == "monthly":
        jour = h.get("day_of_month")
        if jour:
            return f"le {jour} de chaque mois"
        return "chaque mois"

    return frequence


def afficher_habitudes(data, inclure_inactives=True):
    habitudes = data.get("habitudes", [])

    if not habitudes:
        print("Tu n'as encore aucune habitude enregistrée.")
        return

    print("\n========== TES HABITUDES ==========")

    nombre = 0

    for i, h in enumerate(habitudes, start=1):
        if not inclure_inactives and not h.get("active", True):
            continue

        statut = "active" if h.get("active", True) else "désactivée"
        heure = h.get("time") or "heure non définie"

        print(f"\n{i}. {h.get('task', 'Habitude sans nom')}")
        print(f"   Fréquence : {description_frequence(h)}")
        print(f"   Heure     : {heure}")
        print(f"   Statut    : {statut}")

        if h.get("type") == "weather":
            print("   Type      : météo")

        nombre += 1

    if nombre == 0:
        print("Aucune habitude à afficher.")

    print("\n==================================\n")


# ============================================================
# PLANIFICATION
# ============================================================

def heure_valide(heure):
    if not heure:
        return None

    try:
        return datetime.strptime(str(heure).strip(), "%H:%M").time()
    except ValueError:
        return None


def habitude_prevue_aujourd_hui(h, maintenant):
    """Vérifie si l'habitude correspond à la date actuelle."""

    if not h.get("active", True):
        return False

    frequence = h.get("frequency", "daily")

    if frequence == "daily":
        return True

    if frequence == "weekly":
        jours = h.get("days", [])

        if not jours:
            return maintenant.weekday() == 0

        jour_actuel = JOURS_FR[maintenant.weekday()]
        return jour_actuel in jours

    if frequence == "monthly":
        try:
            jour = int(h.get("day_of_month") or 1)
        except (ValueError, TypeError):
            jour = 1

        dernier_jour = calendar.monthrange(
            maintenant.year, maintenant.month
        )[1]

        jour = min(max(jour, 1), dernier_jour)
        return maintenant.day == jour

    return False


def deja_execute_aujourd_hui(h, aujourd_hui):
    derniere = h.get("last_occurrence")

    if not derniere:
        return False

    try:
        return str(derniere)[:10] == aujourd_hui.isoformat()
    except (ValueError, TypeError):
        return False


def deja_notifiee_aujourd_hui(h, aujourd_hui):
    return str(h.get("last_notified") or "")[:10] == aujourd_hui.isoformat()


def marquer_habitude_notifiee(data, habit, maintenant=None):
    task = str(habit.get("task", "")).strip().casefold()
    target = next(
        (item for item in data.get("habitudes", []) if str(item.get("task", "")).strip().casefold() == task),
        None,
    )
    if target is None:
        return False
    target["last_notified"] = (maintenant or datetime.now()).isoformat(timespec="seconds")
    return sauver(data)


def habitudes_a_faire(data, maintenant=None):
    """Trouve les habitudes dues à l'heure de lancement."""

    maintenant = maintenant or datetime.now()
    aujourd_hui = maintenant.date()
    resultat = []

    for h in data.get("habitudes", []):
        if not habitude_prevue_aujourd_hui(h, maintenant):
            continue

        if deja_execute_aujourd_hui(h, aujourd_hui):
            continue
        if deja_notifiee_aujourd_hui(h, aujourd_hui):
            continue

        heure = heure_valide(h.get("time"))

        # Sans heure précise, l'habitude est considérée comme à faire.
        if heure is None:
            resultat.append(h)
            continue

        heure_actuelle = maintenant.time().replace(second=0, microsecond=0)

        # L'habitude est due lorsque son heure est arrivée ou dépassée.
        if heure <= heure_actuelle:
            resultat.append(h)

    return resultat


def afficher_taches_du_demarrage(data):
    maintenant = datetime.now()

    print("\n" + "=" * 55)
    print("TON ASSISTANT PERSONNEL")
    print(maintenant.strftime("%A %d/%m/%Y à %H:%M"))
    print("=" * 55)

    # Affichage en français du jour.
    jours_anglais = [
        "Monday", "Tuesday", "Wednesday", "Thursday",
        "Friday", "Saturday", "Sunday"
    ]

    jour_fr = JOURS_FR[maintenant.weekday()].capitalize()

    print(f"{jour_fr} {maintenant.strftime('%d/%m/%Y à %H:%M')}")
    print("=" * 55)

    taches = habitudes_a_faire(data, maintenant)

    if not taches:
        print("Aucune habitude prévue à cet instant.")
        return

    print("Voici les habitudes à faire :\n")

    for i, h in enumerate(taches, start=1):
        heure = h.get("time")
        suffixe = f" ({heure})" if heure else ""

        print(f"{i}. {h.get('task', 'Habitude sans nom')}{suffixe}")

        if h.get("type") == "weather":
            print("   ", obtenir_meteo(data.get("ville", VILLE_PAR_DEFAUT)))

        # Une habitude n'est pas marquée comme terminée automatiquement.
        # L'assistant attend la confirmation de l'utilisateur.


# ============================================================
# API OPENROUTER
# ============================================================

def demander_ia(messages):
    """Envoie une conversation à OpenRouter et récupère la réponse."""
    try:
        from local_ia.llm.ollama import ask_openrouter

        return ask_openrouter(messages), None
    except Exception as erreur:
        return None, str(erreur)


def extraire_json(texte):
    """Récupère un objet JSON même si le modèle ajoute des balises."""

    if not texte:
        return None

    texte = texte.strip()
    texte = re.sub(r"^```(?:json)?\s*", "", texte)
    texte = re.sub(r"\s*```$", "", texte)

    try:
        resultat = json.loads(texte)
        if isinstance(resultat, dict):
            return resultat
    except json.JSONDecodeError:
        pass

    debut = texte.find("{")
    fin = texte.rfind("}")

    if debut != -1 and fin > debut:
        try:
            resultat = json.loads(texte[debut:fin + 1])
            if isinstance(resultat, dict):
                return resultat
        except json.JSONDecodeError:
            pass

    return None


# ============================================================
# MÉTÉO RÉELLE AVEC OPEN-METEO
# ============================================================

def requete_json(url):
    requete = urllib.request.Request(
        url,
        headers={"User-Agent": "AssistantHabitudes/1.0"}
    )

    with urllib.request.urlopen(requete, timeout=15) as reponse:
        return json.loads(reponse.read().decode("utf-8"))


def obtenir_meteo(ville):
    """Récupère la météo actuelle sans clé API météo."""

    try:
        parametres = urllib.parse.urlencode({
            "name": ville,
            "count": 1,
            "language": "fr",
            "format": "json",
        })

        geo_url = (
            "https://geocoding-api.open-meteo.com/v1/search?"
            + parametres
        )

        geographie = requete_json(geo_url)
        lieux = geographie.get("results", [])

        if not lieux:
            return f"Je ne trouve pas la ville « {ville} »."

        lieu = lieux[0]
        latitude = lieu["latitude"]
        longitude = lieu["longitude"]
        nom = lieu.get("name", ville)
        pays = lieu.get("country", "")

        parametres_meteo = urllib.parse.urlencode({
            "latitude": latitude,
            "longitude": longitude,
            "current": (
                "temperature_2m,relative_humidity_2m,"
                "apparent_temperature,is_day,precipitation,"
                "weather_code,wind_speed_10m"
            ),
            "timezone": "auto",
        })

        url_meteo = (
            "https://api.open-meteo.com/v1/forecast?"
            + parametres_meteo
        )

        meteo = requete_json(url_meteo)
        actuel = meteo.get("current", {})

        code = actuel.get("weather_code", -1)
        description = description_meteo(code)

        temperature = actuel.get("temperature_2m", "?")
        ressenti = actuel.get("apparent_temperature", "?")
        humidite = actuel.get("relative_humidity_2m", "?")
        vent = actuel.get("wind_speed_10m", "?")
        pluie = actuel.get("precipitation", "?")
        lieu_complet = f"{nom} ({pays})" if pays else nom

        return (
            f"Il fait {temperature} °C aujourd'hui à {lieu_complet} : {description}. "
            f"Ressenti : {ressenti} °C, "
            f"humidité : {humidite} %, "
            f"vent : {vent} km/h, "
            f"précipitations : {pluie} mm."
        )

    except Exception as erreur:
        return f"Impossible de récupérer la météo : {erreur}"


def generer_resultat_habitude(data, habit):
    """Produit le contenu réel d'une notification d'habitude, sans interaction utilisateur."""
    if str(habit.get("type", "ai")).casefold() == "weather":
        return obtenir_meteo(data.get("ville", VILLE_PAR_DEFAUT))

    task = str(habit.get("task", "une habitude")).strip() or "une habitude"
    prompt = [
        {
            "role": "system",
            "content": (
                "Tu es KAIRO, un assistant personnel. Écris une notification courte, "
                "chaleureuse et utile pour rappeler l'habitude indiquée. Ne prétends jamais "
                "qu'elle a déjà été faite. Réponds en une seule phrase en français."
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "habitude": task,
                    "moment": habit.get("moment", "anytime"),
                    "heure": habit.get("time"),
                    "date_heure_locale": datetime.now().astimezone().isoformat(timespec="minutes"),
                },
                ensure_ascii=False,
            ),
        },
    ]

    try:
        from local_ia.core.accounts import load_saved_session
        from local_ia.config.manager import model_config, openrouter_api_keys, openrouter_model
        from local_ia.llm.ollama import ask_ollama, ask_openrouter

        keys = openrouter_api_keys()
        if not keys:
            session = load_saved_session()
            keys = session[1] if session else []
        if keys:
            result = ask_openrouter(
                prompt,
                model=openrouter_model(),
                timeout=20,
                max_tokens=128,
                api_key=keys[0],
            )
        else:
            result = ask_ollama(prompt, model=model_config(), timeout=20, max_tokens=128)
        if str(result or "").strip():
            return str(result).strip()
    except Exception:
        pass
    return f"C'est le moment de {task}. Prends quelques minutes pour t'en occuper."


def description_meteo(code):
    descriptions = {
        0: "ciel dégagé",
        1: "principalement dégagé",
        2: "partiellement nuageux",
        3: "couvert",
        45: "brouillard",
        48: "brouillard givrant",
        51: "bruine légère",
        53: "bruine modérée",
        55: "bruine forte",
        56: "bruine verglaçante légère",
        57: "bruine verglaçante forte",
        61: "pluie faible",
        63: "pluie modérée",
        65: "pluie forte",
        66: "pluie verglaçante faible",
        67: "pluie verglaçante forte",
        71: "neige faible",
        73: "neige modérée",
        75: "neige forte",
        77: "grains de neige",
        80: "averses faibles",
        81: "averses modérées",
        82: "averses violentes",
        85: "averses de neige faibles",
        86: "averses de neige fortes",
        95: "orage",
        96: "orage avec grêle faible",
        99: "orage avec forte grêle",
    }

    try:
        return descriptions.get(int(code), "conditions inconnues")
    except (ValueError, TypeError):
        return "conditions inconnues"


# ============================================================
# INSTRUCTIONS DONNÉES À L'IA
# ============================================================

def construire_prompt(data):
    maintenant = datetime.now()

    return f"""
Tu es KAIRO, un assistant personnel qui parle français.
Tu aides l'utilisateur à gérer ses habitudes et ses tâches.

Date et heure actuelles : {maintenant.strftime('%Y-%m-%d %H:%M')}.
Ville actuelle pour la météo : {data.get('ville', VILLE_PAR_DEFAUT)}.

Habitudes actuellement enregistrées :
{json.dumps(data.get('habitudes', []), ensure_ascii=False, indent=2)}

Tu dois répondre UNIQUEMENT avec un objet JSON valide.
Ne mets pas de balises Markdown autour du JSON.

Format général :
{{
  "action": "chat",
  "message": "Ta réponse à l'utilisateur"
}}

Actions possibles :

1. Pour une conversation normale :
{{
  "action": "chat",
  "message": "Réponse en français"
}}

2. Ajouter une habitude :
{{
  "action": "add",
  "message": "Confirmation",
  "habit": {{
    "task": "Faire du sport",
    "frequency": "daily",
    "days": [],
    "day_of_month": null,
    "moment": "morning",
    "time": "08:00",
    "type": "ai",
    "active": true,
    "last_occurrence": null
  }}
}}

Valeurs de frequency : daily, weekly, monthly.
Valeurs de type : ai, weather.
Valeurs de moment : morning, afternoon, evening, anytime.
time doit être au format HH:MM ou null.
Pour une fréquence weekly, days contient les jours en français :
lundi, mardi, mercredi, jeudi, vendredi, samedi, dimanche.
Pour une fréquence monthly, day_of_month contient un nombre de 1 à 31.
Si l'utilisateur ne précise pas d'heure, utilise null.

3. Lister les habitudes :
{{"action":"list","message":"Voici tes habitudes"}}

4. Supprimer une habitude :
{{"action":"delete","task":"texte ou nom de l'habitude","message":"Confirmation"}}

5. Modifier une habitude :
{{"action":"update","task":"nom actuel","habit":{{"task":"nouveau nom"}},"message":"Confirmation"}}
Dans update, habit ne contient que les champs à modifier.
Tu peux modifier frequency, days, day_of_month, moment, time, type ou task.

6. Activer une habitude :
{{"action":"activate","task":"nom de l'habitude","message":"Confirmation"}}

7. Désactiver une habitude :
{{"action":"deactivate","task":"nom de l'habitude","message":"Confirmation"}}

8. Changer la ville :
{{"action":"set_city","city":"Lyon","message":"Ville modifiée"}}

9. Demander la météo actuelle :
{{"action":"weather_now","message":"Voici la météo"}}

10. Marquer une habitude comme terminée :
{{"action":"complete","task":"nom de l'habitude","message":"Bravo !"}}

Règles :
- Comprends les demandes formulées naturellement, même avec des fautes.
- Si l'utilisateur demande "j'ai quoi comme tâche ?", utilise list.
- Si l'utilisateur veut ajouter, supprimer ou modifier une habitude, choisis l'action correspondante.
- N'invente jamais une habitude comme si elle était déjà enregistrée.
- Pour une demande ambiguë, utilise chat et pose une question.
- La météo doit être obtenue par l'action weather_now ou une habitude de type weather.
- N'ajoute pas d'autres champs inutiles au JSON.
"""


# ============================================================
# GESTION DES ACTIONS DE L'IA
# ============================================================

def trouver_habitude(data, nom):
    if not nom:
        return None

    nom = str(nom).strip().lower()

    for h in data.get("habitudes", []):
        if str(h.get("task", "")).strip().lower() == nom:
            return h

    # Recherche approximative si le nom complet n'est pas donné.
    for h in data.get("habitudes", []):
        nom_habitude = str(h.get("task", "")).strip().lower()

        if nom in nom_habitude or nom_habitude in nom:
            return h

    return None


def ajouter_habitude(data, habit):
    if not isinstance(habit, dict):
        print("L'IA n'a pas fourni une habitude valide.")
        return

    task = str(
        habit.get("task")
        or habit.get("tache")
        or habit.get("nom")
        or ""
    ).strip()

    if not task:
        print("Il manque le nom de l'habitude.")
        return

    if trouver_habitude(data, task):
        print(f"L'habitude « {task} » existe déjà.")
        return

    nouvelle = {
        "task": task,
        "frequency": habit.get("frequency", "daily"),
        "days": habit.get("days", []),
        "day_of_month": habit.get("day_of_month"),
        "moment": habit.get("moment", "anytime"),
        "time": habit.get("time"),
        "type": habit.get("type", "ai"),
        "active": True,
        "last_occurrence": None,
    }

    normalise = normaliser_habitudes({
        "habitudes": [nouvelle],
        "ville": data.get("ville", VILLE_PAR_DEFAUT),
    })

    data["habitudes"].append(normalise["habitudes"][0])
    sauver(data)

    print(f"Habitude ajoutée : {task}")


def modifier_habitude(data, nom, modifications):
    h = trouver_habitude(data, nom)

    if h is None:
        print(f"Je ne trouve pas l'habitude « {nom} ».")
        return

    if not isinstance(modifications, dict):
        print("Les modifications ne sont pas valides.")
        return

    correspondances = {
        "tache": "task",
        "nom": "task",
        "frequence": "frequency",
        "jours": "days",
        "jour_mois": "day_of_month",
        "heure": "time",
    }

    for cle, valeur in modifications.items():
        cle = correspondances.get(cle, cle)

        if cle in (
            "task", "frequency", "days", "day_of_month",
            "moment", "time", "type", "active"
        ):
            h[cle] = valeur

    resultat = normaliser_habitudes({
        "habitudes": [h],
        "ville": data.get("ville", VILLE_PAR_DEFAUT),
    })

    h.clear()
    h.update(resultat["habitudes"][0])

    sauver(data)
    print(f"Habitude mise à jour : {h['task']}")


def use(arguments):
    """Exécute une action d'habitudes sans interaction terminal."""
    action = str(arguments.get("action", "")).strip().casefold()
    aliases = {
        "ajouter": "add", "liste": "list", "lister": "list",
        "supprimer": "delete", "modifier": "update", "activer": "activate",
        "désactiver": "deactivate", "desactiver": "deactivate",
        "terminer": "complete", "changer_ville": "set_city", "météo": "weather_now",
        "météo_quotidienne": "weather_daily", "meteo_quotidienne": "weather_daily",
    }
    action = aliases.get(action, action)
    supported = {"add", "list", "update", "delete", "activate", "deactivate", "complete", "set_city", "weather_now", "weather_daily", "preview"}
    if action not in supported:
        raise ValueError("Action d'habitude inconnue : utilise add, list, update, delete, activate, deactivate, complete, set_city, weather_now ou weather_daily.")

    data = charger()
    if action == "list":
        return {"action": action, "habits": data["habitudes"], "city": data.get("ville", VILLE_PAR_DEFAUT)}
    if action == "preview":
        task = str(arguments.get("task", "")).strip()
        habit = trouver_habitude(data, task)
        if habit is None:
            raise ValueError(f"Je ne trouve pas l'habitude « {task} ».")
        return {
            "action": action,
            "task": habit["task"],
            "preview": generer_resultat_habitude(data, habit),
        }
    if action == "weather_now":
        weather = obtenir_meteo(data.get("ville", VILLE_PAR_DEFAUT))
        return {"action": action, "weather": weather, "error": weather.startswith("Impossible")}
    if action == "weather_daily":
        task = "Météo du matin"
        city = str(data.get("ville", VILLE_PAR_DEFAUT) or VILLE_PAR_DEFAUT)
        habit = next(
            (
                item for item in data["habitudes"]
                if str(item.get("task", "")).strip().casefold() == task.casefold()
            ),
            None,
        )
        configured = {
            "task": task,
            "frequency": "daily",
            "days": [],
            "day_of_month": None,
            "time": "08:00",
            "moment": "morning",
            "type": "weather",
            "active": True,
        }
        normalized = normaliser_habitudes({"habitudes": [configured], "ville": city})["habitudes"][0]
        if habit is None:
            data["habitudes"].append(normalized)
            habit = normalized
        else:
            habit.update(normalized)

        weather = obtenir_meteo(city)
        weather_error = weather.startswith(("Impossible", "Je ne trouve pas"))
        if not weather_error:
            habit["last_notified"] = datetime.now().isoformat(timespec="seconds")
        if not sauver(data):
            return {"action": action, "error": "Impossible d'enregistrer l'habitude météo."}
        return {
            "action": action,
            "habit": habit,
            "city": city,
            "weather": weather,
            "weather_error": weather_error,
        }
    if action == "set_city":
        city = str(arguments.get("city", "")).strip()
        if not city:
            raise ValueError("Indique la ville à utiliser.")
        data["ville"] = city
        result = {"action": action, "city": city}
    else:
        task = str(arguments.get("task", "")).strip()
        habit = trouver_habitude(data, task)
        if action == "add":
            new_habit = arguments.get("habit")
            if not isinstance(new_habit, dict):
                raise ValueError("L'action add requiert un objet habit.")
            name = str(new_habit.get("task") or new_habit.get("tache") or new_habit.get("nom") or "").strip()
            if not name:
                raise ValueError("Indique le nom de l'habitude.")
            if trouver_habitude(data, name):
                raise ValueError(f"L'habitude « {name} » existe déjà.")
            normalized = normaliser_habitudes({"habitudes": [new_habit], "ville": data.get("ville", VILLE_PAR_DEFAUT)})
            data["habitudes"].append(normalized["habitudes"][0])
            result = {"action": action, "habit": normalized["habitudes"][0]}
        else:
            if habit is None:
                raise ValueError(f"Je ne trouve pas l'habitude « {task} ».")
            if action == "delete":
                data["habitudes"].remove(habit)
                result = {"action": action, "task": task, "deleted": True}
            elif action in {"activate", "deactivate"}:
                habit["active"] = action == "activate"
                result = {"action": action, "habit": habit}
            elif action == "complete":
                habit["last_occurrence"] = date.today().isoformat()
                result = {"action": action, "habit": habit}
            else:
                changes = arguments.get("habit", arguments.get("modifications"))
                if not isinstance(changes, dict):
                    raise ValueError("L'action update requiert un objet habit avec les changements.")
                allowed_fields = {"task", "tache", "nom", "frequency", "frequence", "days", "jours", "day_of_month", "jour_mois", "moment", "time", "heure", "type", "active"}
                if not changes or not set(changes).issubset(allowed_fields):
                    raise ValueError("Les champs de modification de l'habitude ne sont pas valides.")
                old_name = habit["task"]
                candidate = dict(habit)
                candidate.update(changes)
                normalized = normaliser_habitudes({"habitudes": [candidate], "ville": data.get("ville", VILLE_PAR_DEFAUT)})["habitudes"][0]
                duplicate = trouver_habitude(data, normalized["task"])
                if duplicate is not None and duplicate is not habit and normalized["task"].casefold() != old_name.casefold():
                    raise ValueError(f"L'habitude « {normalized['task']} » existe déjà.")
                habit.clear()
                habit.update(normalized)
                result = {"action": action, "habit": habit}

    if not sauver(data):
        return {"action": action, "error": "Impossible d'enregistrer les habitudes."}
    return result


def traiter_action(data, resultat):
    action = str(resultat.get("action", "chat")).lower()
    message = resultat.get("message", "")

    if action == "add":
        ajouter_habitude(data, resultat.get("habit", {}))
        if message:
            print(message)

    elif action == "list":
        afficher_habitudes(data)

    elif action == "delete":
        nom = resultat.get("task", "")
        h = trouver_habitude(data, nom)

        if h is None:
            print(f"Je ne trouve pas l'habitude « {nom} ».")
        else:
            data["habitudes"].remove(h)
            sauver(data)
            print(f"Habitude supprimée : {h['task']}")

        if message:
            print(message)

    elif action == "update":
        modifier_habitude(
            data,
            resultat.get("task", ""),
            resultat.get("habit", {})
        )

        if message:
            print(message)

    elif action in ("activate", "deactivate"):
        nom = resultat.get("task", "")
        h = trouver_habitude(data, nom)

        if h is None:
            print(f"Je ne trouve pas l'habitude « {nom} ».")
        else:
            h["active"] = action == "activate"
            sauver(data)

            statut = "activée" if h["active"] else "désactivée"
            print(f"Habitude {statut} : {h['task']}")

        if message:
            print(message)

    elif action == "set_city":
        ville = str(resultat.get("city", "")).strip()

        if ville:
            data["ville"] = ville
            sauver(data)
            print(f"Ville de référence modifiée : {ville}")
        else:
            print("Précise le nom de la ville.")

        if message:
            print(message)

    elif action == "weather_now":
        print(obtenir_meteo(data.get("ville", VILLE_PAR_DEFAUT)))

        if message:
            print(message)

    elif action == "complete":
        nom = resultat.get("task", "")
        h = trouver_habitude(data, nom)

        if h is None:
            print(f"Je ne trouve pas l'habitude « {nom} ».")
        else:
            h["last_occurrence"] = date.today().isoformat()
            sauver(data)
            print(f"Bravo ! « {h['task']} » est marquée comme terminée.")

        if message:
            print(message)

    else:
        print(message or "Je suis là. Que veux-tu faire ?")


# ============================================================
# BOUCLE DE CONVERSATION
# ============================================================

def lancer_conversation(data):
    messages = [
        {
            "role": "system",
            "content": construire_prompt(data),
        }
    ]

    print("\nTu peux me parler normalement.")
    print('Exemple : « Ajoute la météo tous les matins. »')
    print('Tu peux aussi demander : « J’ai quoi comme tâche déjà ? »')
    print('Écris « au revoir » pour terminer.\n')

    while True:
        try:
            texte = input("Toi : ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nÀ bientôt !")
            break

        if not texte:
            continue

        if texte.lower() in (
            "au revoir", "quit", "exit", "quitter", "bye"
        ):
            print("Assistant : À bientôt !")
            break

        # Commandes locales disponibles même sans connexion à l'IA.
        texte_minuscule = texte.lower().strip()

        if texte_minuscule in (
            "liste", "mes habitudes", "liste mes habitudes",
            "affiche mes habitudes", "quelles sont mes habitudes"
        ):
            afficher_habitudes(data)
            continue

        if texte_minuscule in (
            "météo", "la météo", "météo maintenant",
            "quelle est la météo"
        ):
            print(obtenir_meteo(data.get("ville", VILLE_PAR_DEFAUT)))
            continue

        messages.append({
            "role": "user",
            "content": texte,
        })

        reponse, erreur = demander_ia(messages)

        if erreur:
            print(f"Assistant : {erreur}")

            # Retire le dernier message pour éviter une conversation
            # incohérente si l'appel API échoue.
            messages.pop()
            continue

        if not isinstance(reponse, str) or not reponse.strip():
            print("Assistant : aucune réponse n'a été reçue.")
            messages.pop()
            continue

        resultat = extraire_json(reponse)

        if resultat is None:
            # Repli si le modèle ne respecte pas le format JSON.
            print(f"Assistant : {reponse}")
            messages.append({
                "role": "assistant",
                "content": reponse,
            })
            continue

        # Actualise le contexte avec la réponse de l'IA.
        messages.append({
            "role": "assistant",
            "content": reponse,
        })

        # Garde un historique limité pour éviter des requêtes trop longues.
        if len(messages) > 21:
            messages = [messages[0]] + messages[-20:]

        print("Assistant : ", end="")
        traiter_action(data, resultat)

        # Rafraîchit les habitudes connues par l'IA après chaque action.
        messages[0] = {
            "role": "system",
            "content": construire_prompt(data),
        }


# ============================================================
# PROGRAMME PRINCIPAL
# ============================================================

def main():
    data = charger()

    # Sauvegarde immédiatement les éventuelles conversions d'ancien format.
    sauver(data)

    afficher_taches_du_demarrage(data)
    lancer_conversation(data)


if __name__ == "__main__":
    main()
