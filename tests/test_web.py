#!/usr/bin/env python3
"""Tests de l'outil de recherche Web."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from local_ia.tools import web
from local_ia.core.tool_manager import ToolManager


class WebSearchTest(unittest.TestCase):
    def test_search_extracts_results_and_limits_count(self):
        page = b"""
        <div class="result">
          <a class="result__a" href="https://example.com/news"> Headline </a>
          <a class="result__snippet"> Latest details </a>
        </div>
        <div class="result">
          <a class="result__a" href="https://example.com/weather">Forecast</a>
        </div>
        """
        with patch("local_ia.tools.web.urlopen") as open_url:
            open_url.return_value.__enter__.return_value.read.return_value = page
            result = web.search("latest technology news", max_results=1)

        self.assertEqual(result["query"], "latest technology news")
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["results"][0]["title"], "Headline")
        self.assertEqual(result["results"][0]["url"], "https://example.com/news")
        self.assertEqual(result["results"][0]["snippet"], "Latest details")
        self.assertEqual(result["engine"], "DuckDuckGo (repli)")
        self.assertEqual(open_url.call_count, 2)

    def test_google_results_are_used_when_available(self):
        page = b"""
        <div class="MjjYud"><div>
          <a href="https://example.com/macron"><h3>Macron - Profile</h3></a>
          <div class="VwiC3b">Latest profile details</div>
        </div></div>
        """
        with patch("local_ia.tools.web.urlopen") as open_url:
            open_url.return_value.__enter__.return_value.read.return_value = page
            result = web.search("Macron", category="web")

        self.assertEqual(result["engine"], "Google")
        self.assertEqual(result["results"][0]["title"], "Macron - Profile")
        self.assertEqual(result["results"][0]["url"], "https://example.com/macron")
        self.assertEqual(result["results"][0]["snippet"], "Latest profile details")
        self.assertEqual(open_url.call_count, 1)

    def test_categories_customize_search_queries(self):
        self.assertEqual(web._search_query("Macron", "news"), "Macron actualités récentes")
        self.assertEqual(web._search_query("mairie de Metz", "sites"), "site officiel mairie de Metz")
        ads_query = web._search_query("vélo à Metz", "ads")
        self.assertIn("leboncoin.fr", ads_query)
        self.assertIn("vélo à Metz", ads_query)

    def test_explicit_weather_category_uses_weather_service(self):
        with patch("local_ia.tools.web._weather", return_value={"type": "weather"}) as weather:
            self.assertEqual(web.search("Metz", category="weather"), {"type": "weather"})
        weather.assert_called_once_with("Metz")

    def test_search_rejects_unknown_category(self):
        with self.assertRaisesRegex(ValueError, "Catégorie de recherche inconnue"):
            web.search("Macron", category="videos")

    def test_tool_manager_forwards_selected_category(self):
        with patch("local_ia.core.tool_manager.web.search", return_value={"count": 1}) as search:
            result = ToolManager.execute(
                {
                    "tool": "web",
                    "arguments": {"query": "voiture occasion Metz", "category": "ads", "max_results": 4},
                },
                chat={},
                connection=None,
            )

        self.assertEqual(result, {"count": 1})
        search.assert_called_once_with("voiture occasion Metz", 4, "ads")

    def test_web_tool_prompt_lists_search_categories(self):
        prompt = ToolManager.build_prompt({"web"})
        for category in ("news", "sites", "ads", "weather"):
            self.assertIn(category, prompt)

    def test_search_rejects_empty_query(self):
        with self.assertRaises(ValueError):
            web.search("  ")

    def test_weather_query_geocodes_city_and_returns_current_conditions(self):
        geocoding = {
            "results": [{
                "name": "Metz", "country": "France", "latitude": 49.1191,
                "longitude": 6.1727,
            }],
        }
        forecast = {
            "current": {
                "time": "2026-09-28T14:00", "temperature_2m": 17.4,
                "relative_humidity_2m": 62, "apparent_temperature": 17.1,
                "precipitation": 0.1, "weather_code": 63, "wind_speed_10m": 12.3,
            },
        }
        responses = []
        for payload in (geocoding, forecast):
            response = MagicMock()
            response.__enter__.return_value.read.return_value = json.dumps(payload).encode()
            responses.append(response)

        with patch("local_ia.tools.web.urlopen", side_effect=responses) as open_url:
            result = web.search("meteo a metz")

        self.assertEqual(open_url.call_count, 2)
        self.assertEqual(result["type"], "weather")
        self.assertEqual(result["location"], "Metz, France")
        self.assertEqual(result["current"]["conditions"], "pluie modérée")
        self.assertEqual(result["current"]["temperature_c"], 17.4)
        self.assertEqual(result["source"], "Open-Meteo")

    def test_weather_query_without_city_requests_clarification(self):
        with patch("local_ia.tools.web.urlopen") as open_url:
            with self.assertRaisesRegex(ValueError, "Précise une ville"):
                web.search("météo aujourd'hui")
        open_url.assert_not_called()


if __name__ == "__main__":
    unittest.main()