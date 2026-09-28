#!/usr/bin/env python3
"""Tests du client HTTP Ollama sans accès réseau."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from local_ia.llm.ollama import OllamaSession, ask_ollama, key_usage_percent, openrouter_usage_status


class OllamaClientTest(unittest.TestCase):
    def setUp(self):
        self.config = {
            "model": "fallback-model",
            "ollama": {
                "url": "http://127.0.0.1:11434",
                "model": "configured-model",
                "timeout": 90,
                "keep_alive": "30m",
            },
        }
        self.response_context = MagicMock()
        self.response_context.__enter__.return_value.read.return_value = b'{"message":{"content":"ok"}}'

    def test_blank_model_uses_configured_model(self):
        with patch("local_ia.llm.ollama.load_config", return_value=self.config), patch(
            "local_ia.llm.ollama.urlopen", return_value=self.response_context
        ) as urlopen:
            self.assertEqual(ask_ollama([], model="  "), "ok")
        payload = json.loads(urlopen.call_args.args[0].data)
        self.assertEqual(payload["model"], "configured-model")

    def test_explicit_zero_timeout_uses_minimum_timeout(self):
        with patch("local_ia.llm.ollama.load_config", return_value=self.config), patch(
            "local_ia.llm.ollama.urlopen", return_value=self.response_context
        ) as urlopen:
            ask_ollama([], model="test-model", timeout=0)
        self.assertEqual(urlopen.call_args.kwargs["timeout"], 5)

    def test_openrouter_ignores_local_model_when_openrouter_model_is_missing(self):
        config = {
            "model": "llama3.2:3b",
            "ollama": {"url": "http://127.0.0.1:11434", "model": "configured-model"},
            "openrouter": {"api_key": "secret-key", "base_url": "https://openrouter.ai/api/v1", "timeout": 30},
        }
        response_context = MagicMock()
        response_context.__enter__.return_value.read.return_value = (
            b'{"choices":[{"message":{"content":"openrouter-default-model-ok"}}]}'
        )

        with patch("local_ia.llm.ollama.load_config", return_value=config), patch(
            "local_ia.llm.ollama.urlopen", return_value=response_context
        ) as urlopen:
            self.assertEqual(ask_ollama([], model="llama3.2:3b"), "openrouter-default-model-ok")

        payload = json.loads(urlopen.call_args.args[0].data)
        self.assertEqual(payload["model"], "openai/gpt-4o-mini")

    def test_openrouter_api_key_uses_openrouter_endpoint(self):
        config = {
            "model": "fallback-model",
            "ollama": {"url": "http://127.0.0.1:11434", "model": "configured-model"},
            "openrouter": {
                "api_key": "secret-key",
                "model": "openai/gpt-4o-mini",
                "base_url": "https://openrouter.ai/api/v1",
                "timeout": 30,
            },
        }
        response_context = MagicMock()
        response_context.__enter__.return_value.read.return_value = (
            b'{"choices":[{"message":{"content":"bonjour depuis openrouter"}}]}'
        )

        with patch("local_ia.llm.ollama.load_config", return_value=config), patch(
            "local_ia.llm.ollama.urlopen", return_value=response_context
        ) as urlopen:
            self.assertEqual(ask_ollama([], model="  "), "bonjour depuis openrouter")

        self.assertIn("openrouter.ai/api/v1/chat/completions", urlopen.call_args.args[0].full_url)
        self.assertEqual(urlopen.call_args.args[0].headers["Authorization"], "Bearer secret-key")
        payload = json.loads(urlopen.call_args.args[0].data)
        self.assertEqual(payload["model"], "openai/gpt-4o-mini")

    def test_runtime_openrouter_key_overrides_stored_config(self):
        config = {
            "model": "fallback-model",
            "ollama": {"url": "http://127.0.0.1:11434", "model": "configured-model"},
            "openrouter": {"api_key": "stored-key", "model": "openai/gpt-4o-mini"},
        }
        response_context = MagicMock()
        response_context.__enter__.return_value.read.return_value = (
            b'{"choices":[{"message":{"content":"runtime-key-ok"}}]}'
        )

        with patch.dict("os.environ", {"LOCAL_IA_OPENROUTER_KEY": "runtime-key"}, clear=False), patch(
            "local_ia.llm.ollama.load_config", return_value=config
        ), patch("local_ia.llm.ollama.urlopen", return_value=response_context) as urlopen:
            self.assertEqual(ask_ollama([], model="  "), "runtime-key-ok")

        self.assertEqual(urlopen.call_args.args[0].headers["Authorization"], "Bearer runtime-key")

    def test_openrouter_uses_chunked_requests_under_2000_tokens(self):
        config = {
            "model": "fallback-model",
            "ollama": {"url": "http://127.0.0.1:11434", "model": "configured-model"},
            "openrouter": {
                "api_key": "secret-key",
                "model": "openai/gpt-4o-mini",
                "base_url": "https://openrouter.ai/api/v1",
                "timeout": 30,
            },
        }

        large_text = "phrase de test " * 1200
        messages = [{"role": "user", "content": large_text}, {"role": "assistant", "content": large_text}]

        def fake_urlopen(request, timeout=None):
            ctx = MagicMock()
            if request.full_url.endswith("/chat/completions"):
                ctx.__enter__.return_value.read.return_value = (
                    b'{"choices":[{"message":{"content":"bloc reponse"}}]}'
                )
                return ctx
            raise AssertionError(f"Unexpected URL: {request.full_url}")

        with patch("local_ia.llm.ollama.load_config", return_value=config), patch(
            "local_ia.llm.ollama.urlopen", side_effect=fake_urlopen
        ) as urlopen:
            response = ask_ollama(messages, model="openai/gpt-4o-mini")

        self.assertIn("bloc reponse", response)
        self.assertGreaterEqual(len(urlopen.call_args_list), 2)

    def test_openrouter_request_does_not_send_internal_usage_tracking_fields(self):
        config = {
            "model": "fallback-model",
            "ollama": {"url": "http://127.0.0.1:11434", "model": "configured-model"},
            "openrouter": {
                "api_key": "secret-key",
                "model": "openai/gpt-4o-mini",
                "base_url": "https://openrouter.ai/api/v1",
                "timeout": 30,
            },
        }
        response_context = MagicMock()
        response_context.__enter__.return_value.read.return_value = (
            b'{"choices":[{"message":{"content":"ok from openrouter payload"}}]}'
        )

        with patch("local_ia.llm.ollama.load_config", return_value=config), patch(
            "local_ia.llm.ollama.urlopen", return_value=response_context
        ) as urlopen:
            self.assertEqual(
                ask_ollama([{"role": "user", "content": "bonjour"}], model="  "),
                "ok from openrouter payload",
            )

        payload = json.loads(urlopen.call_args.args[0].data)
        self.assertNotIn("usage_percent", payload)
        self.assertIn("messages", payload)
        self.assertIn("model", payload)

    def test_openrouter_normalizes_nonstandard_messages_before_request(self):
        config = {
            "model": "fallback-model",
            "ollama": {"url": "http://127.0.0.1:11434", "model": "configured-model"},
            "openrouter": {
                "api_key": "secret-key",
                "model": "openai/gpt-4o-mini",
                "base_url": "https://openrouter.ai/api/v1",
                "timeout": 30,
            },
        }
        response_context = MagicMock()
        response_context.__enter__.return_value.read.return_value = (
            b'{"choices":[{"message":{"content":"reponse normalisee"}}]}'
        )

        malformed = [{"role": "user", "content": [{"text": "bonjour"}, {"content": " monde "}]}]

        with patch("local_ia.llm.ollama.load_config", return_value=config), patch(
            "local_ia.llm.ollama.urlopen", return_value=response_context
        ) as urlopen:
            self.assertEqual(ask_ollama(malformed, model="openai/gpt-4o-mini"), "reponse normalisee")

        payload = json.loads(urlopen.call_args.args[0].data)
        self.assertEqual(payload["messages"][0]["content"], "bonjour\nmonde")

    def test_key_usage_percent_tracks_request_budget(self):
        messages = [{"role": "user", "content": "phrase de test " * 100}]
        usage = openrouter_usage_status(messages)
        self.assertGreater(usage["percent"], 0)
        self.assertLessEqual(usage["percent"], 100)
        self.assertTrue(usage["safe"])
        self.assertEqual(key_usage_percent(messages), usage["percent"])

    def test_session_is_singleton_and_keeps_model_alive(self):
        first = OllamaSession.get_instance()
        second = OllamaSession.get_instance()
        self.assertIs(first, second)
        self.assertEqual(first.keep_alive, "30m")

    def test_stream_mode_yields_final_response_chunks(self):
        config = {
            "model": "fallback-model",
            "ollama": {
                "url": "http://127.0.0.1:11434",
                "model": "configured-model",
                "timeout": 90,
                "keep_alive": "30m",
                "stream": True,
            },
        }
        response_context = MagicMock()
        response_context.__enter__.return_value.__iter__.return_value = [
            b'{"message":{"content":"salut "}}',
            b'{"message":{"content":"monde"}}',
        ]

        with patch("local_ia.llm.ollama.load_config", return_value=config), patch(
            "local_ia.llm.ollama.urlopen", return_value=response_context
        ):
            chunks = list(ask_ollama([], model="test-model", stream=True))

        self.assertEqual(chunks, ["salut ", "monde"])


if __name__ == "__main__":
    unittest.main()
