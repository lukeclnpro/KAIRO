"""Recherche d'informations récentes sur le Web via DuckDuckGo."""

from __future__ import annotations

import json
import re
from html.parser import HTMLParser
from urllib.error import URLError
from urllib.parse import parse_qs, quote_plus, urlencode, urlparse
from local_ia.http_client import Request, open_url as urlopen


SEARCH_URL = "https://html.duckduckgo.com/html/?q="
GOOGLE_SEARCH_URL = "https://www.google.com/search?"
GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search?"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast?"
MAX_RESULTS = 8
SEARCH_CATEGORIES = {"web", "news", "sites", "ads", "weather"}
CATEGORY_ALIASES = {
    "general": "web", "info": "web", "information": "web",
    "actualite": "news", "actualites": "news", "actualité": "news", "actualités": "news",
    "site": "sites", "website": "sites", "annonce": "ads", "annonces": "ads",
    "classifieds": "ads", "meteo": "weather", "météo": "weather",
}
WEATHER_INTENT = re.compile(
    r"\b(?:m[ée]t[ée]o|weather|temps\s+(?:à|a|pour|de|in))\b",
    re.I,
)
WEATHER_CODES = {
    0: "ciel dégagé", 1: "principalement dégagé", 2: "partiellement nuageux",
    3: "couvert", 45: "brouillard", 48: "brouillard givrant",
    51: "bruine légère", 53: "bruine modérée", 55: "bruine dense",
    56: "bruine verglaçante légère", 57: "bruine verglaçante dense",
    61: "pluie légère", 63: "pluie modérée", 65: "forte pluie",
    66: "pluie verglaçante légère", 67: "forte pluie verglaçante",
    71: "neige légère", 73: "neige modérée", 75: "forte neige", 77: "grains de neige",
    80: "averses légères", 81: "averses modérées", 82: "fortes averses",
    85: "averses de neige légères", 86: "fortes averses de neige",
    95: "orage", 96: "orage avec grêle légère", 99: "orage avec forte grêle",
}


class _ResultsParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.results = []
        self._result = None
        self._result_depth = 0
        self._capture = None

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        classes = attributes.get("class", "").split()
        if tag == "div":
            if self._result is None and "result" in classes:
                self._result = {"title": "", "url": "", "snippet": ""}
                self._result_depth = 1
            elif self._result is not None:
                self._result_depth += 1
        if self._result is not None and tag == "a" and "result__a" in classes:
            self._result["url"] = attributes.get("href", "")
            self._capture = "title"
        elif self._result is not None and "result__snippet" in classes:
            self._capture = "snippet"

    def handle_endtag(self, tag):
        if tag == "a" and self._capture == "title":
            self._capture = None
        if tag == "div" and self._result is not None:
            self._result_depth -= 1
            if self._result_depth == 0:
                if self._result["title"] and self._result["url"]:
                    self._result["url"] = self._resolve_url(self._result["url"])
                    self.results.append(self._result)
                self._result = None
                self._capture = None

    def handle_data(self, data):
        if self._result is not None and self._capture:
            self._result[self._capture] += data

    @staticmethod
    def _resolve_url(url):
        if url.startswith("//"):
            url = "https:" + url
        parsed = urlparse(url)
        if parsed.hostname == "duckduckgo.com" and parsed.path == "/l/":
            url = parse_qs(parsed.query).get("uddg", [url])[0]
        return url


class _GoogleResultsParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.results = []
        self._group = None
        self._group_depth = 0
        self._anchor = None
        self._capture = None

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        classes = attributes.get("class", "").split()
        if tag == "div":
            if self._group is None and "MjjYud" in classes:
                self._group = {"results": [], "snippet": ""}
                self._group_depth = 1
            elif self._group is not None:
                self._group_depth += 1
        if self._group is None:
            return
        if tag == "a" and attributes.get("href", "").startswith(("http://", "https://", "/url?")):
            self._anchor = {"title": "", "url": attributes["href"]}
        elif tag == "h3" and self._anchor is not None:
            self._capture = "title"
        elif tag in {"div", "span"} and "VwiC3b" in classes:
            self._capture = "snippet"

    def handle_endtag(self, tag):
        if tag == "h3" and self._capture == "title":
            self._capture = None
        if tag == "a" and self._anchor is not None:
            if self._anchor["title"]:
                self._group["results"].append(self._anchor)
            self._anchor = None
        if tag == "div" and self._group is not None:
            self._group_depth -= 1
            if self._group_depth == 0:
                if self._group["results"]:
                    result = self._group["results"][0]
                    result["url"] = self._resolve_url(result["url"])
                    result["snippet"] = " ".join(self._group["snippet"].split())
                    self.results.append(result)
                self._group = None
                self._anchor = None
                self._capture = None

    def handle_data(self, data):
        if self._capture == "title" and self._anchor is not None:
            self._anchor["title"] += data
        elif self._capture == "snippet" and self._group is not None:
            self._group["snippet"] += data

    @staticmethod
    def _resolve_url(url):
        parsed = urlparse(url)
        if parsed.path == "/url":
            return parse_qs(parsed.query).get("q", parse_qs(parsed.query).get("url", [url]))[0]
        return url


def _search_query(query, category):
    if category == "news":
        return f"{query} actualités récentes"
    if category == "sites":
        return f"site officiel {query}"
    if category == "ads":
        marketplaces = (
            "site:leboncoin.fr OR site:paruvendu.fr OR site:seloger.com "
            "OR site:autoscout24.fr OR site:lacentrale.fr"
        )
        return f"{query} ({marketplaces})"
    return query


def _google_search(query, category, limit):
    parameters = {"q": _search_query(query, category), "num": str(limit), "hl": "fr"}
    if category == "news":
        parameters["tbm"] = "nws"
    request = Request(
        GOOGLE_SEARCH_URL + urlencode(parameters),
        headers={
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/131.0 Safari/537.36"
            ),
            "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
        },
    )
    try:
        with urlopen(request, timeout=5) as response:
            html = response.read(1_000_000).decode("utf-8", errors="replace")
    except (OSError, URLError):
        return []
    parser = _GoogleResultsParser()
    parser.feed(html)
    return [
        {
            "title": " ".join(result["title"].split()),
            "url": result["url"],
            "snippet": result["snippet"],
        }
        for result in parser.results[:limit]
    ]


def _duckduckgo_search(query, limit):
    request = Request(
        SEARCH_URL + quote_plus(query),
        headers={"User-Agent": "Mozilla/5.0 (compatible; LocalIA/1.0)"},
    )
    try:
        with urlopen(request, timeout=8) as response:
            html = response.read(1_000_000).decode("utf-8", errors="replace")
    except (OSError, URLError) as error:
        raise RuntimeError(f"Recherche Web indisponible : {error}") from error

    parser = _ResultsParser()
    parser.feed(html)
    return [
        {
            "title": " ".join(result["title"].split()),
            "url": result["url"],
            "snippet": " ".join(result["snippet"].split()),
        }
        for result in parser.results[:limit]
    ]


def search(query, max_results=5, category="web"):
    """Search Google by category, falling back to DuckDuckGo when necessary."""
    query = str(query or "").strip()
    if not query:
        raise ValueError("La recherche Web ne peut pas être vide.")

    category = CATEGORY_ALIASES.get(str(category or "web").strip().casefold(), str(category or "web").strip().casefold())
    if category not in SEARCH_CATEGORIES:
        raise ValueError(f"Catégorie de recherche inconnue : {category}")
    if category == "weather" or (category == "web" and WEATHER_INTENT.search(query)):
        return _weather(query)

    limit = max(1, min(int(max_results), MAX_RESULTS))
    search_query = _search_query(query, category)
    results = _google_search(query, category, limit)
    engine = "Google"
    if not results:
        results = _duckduckgo_search(search_query, limit)
        engine = "DuckDuckGo (repli)"
    return {
        "query": query,
        "category": category,
        "engine": engine,
        "results": results,
        "count": len(results),
    }


def _weather_location(query):
    tail = WEATHER_INTENT.sub(" ", query, count=1).strip()
    connectors = list(re.finditer(r"\b(?:à|a|pour|in|for)\s+", tail, re.I))
    if connectors:
        location = tail[connectors[-1].end():]
    else:
        location = tail
        location = re.sub(r"^(?:de|du|des|the)\s+", "", location, flags=re.I)
    location = re.split(
        r"\b(?:aujourd'hui|demain|ce soir|ce matin|cette nuit|maintenant|actuellement)\b|[?!.]",
        location,
        maxsplit=1,
        flags=re.I,
    )[0]
    return location.strip(" ,;:-")


def _get_json(url, description):
    request = Request(url, headers={"User-Agent": "LocalIA/1.0"})
    try:
        with urlopen(request, timeout=8) as response:
            return json.loads(response.read(1_000_000).decode("utf-8"))
    except (OSError, URLError, json.JSONDecodeError) as error:
        raise RuntimeError(f"{description} indisponible : {error}") from error


def _weather(query):
    location_query = _weather_location(query)
    if not location_query:
        raise ValueError("Précise une ville pour obtenir la météo.")

    geocoding = _get_json(
        GEOCODING_URL + urlencode({
            "name": location_query,
            "count": 1,
            "language": "fr",
            "format": "json",
        }),
        "Géolocalisation météo",
    )
    places = geocoding.get("results") or []
    if not places:
        raise ValueError(f"Ville introuvable pour la météo : {location_query}.")
    place = places[0]

    forecast = _get_json(
        FORECAST_URL + urlencode({
            "latitude": place["latitude"],
            "longitude": place["longitude"],
            "current": (
                "temperature_2m,relative_humidity_2m,apparent_temperature,"
                "precipitation,weather_code,wind_speed_10m"
            ),
            "timezone": "auto",
        }),
        "Service météo",
    )
    current = forecast.get("current") or {}
    if "temperature_2m" not in current:
        raise RuntimeError("Le service météo n'a pas fourni les conditions actuelles.")

    return {
        "query": query,
        "type": "weather",
        "location": ", ".join(
            item for item in (place.get("name"), place.get("country")) if item
        ),
        "current": {
            "observed_at": current.get("time"),
            "conditions": WEATHER_CODES.get(current.get("weather_code"), "conditions inconnues"),
            "temperature_c": current.get("temperature_2m"),
            "feels_like_c": current.get("apparent_temperature"),
            "humidity_percent": current.get("relative_humidity_2m"),
            "precipitation_mm": current.get("precipitation"),
            "wind_speed_kmh": current.get("wind_speed_10m"),
        },
        "source": "Open-Meteo",
        "source_url": "https://open-meteo.com/",
    }