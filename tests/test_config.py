#!/usr/bin/env python3
"""Tests de chargement et de sélection de configuration."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from local_ia.config.manager import DEFAULT_CONFIG, model_config, ollama_base_url


class ConfigTest(unittest.TestCase):
    def test_empty_model_config_uses_defaults_not_global_config(self):
        with patch(
            "local_ia.config.manager.load_config",
            return_value={"model": "global-model", "ollama": {"url": "http://global"}},
        ):
            self.assertEqual(model_config({}), DEFAULT_CONFIG["model"])

    def test_empty_url_config_uses_default_not_global_config(self):
        with patch(
            "local_ia.config.manager.load_config",
            return_value={"model": "global-model", "ollama": {"url": "http://global"}},
        ):
            self.assertEqual(ollama_base_url({}), DEFAULT_CONFIG["ollama"]["url"])


if __name__ == "__main__":
    unittest.main()
