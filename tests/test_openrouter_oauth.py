import base64
import hashlib
import json
import threading
import unittest
from urllib.parse import parse_qs, urlsplit
from urllib.request import urlopen as request_urlopen
from unittest.mock import MagicMock, patch

from local_ia.core import openrouter_oauth


class OpenRouterOAuthTest(unittest.TestCase):
    def test_pkce_pair_uses_s256(self):
        verifier, challenge = openrouter_oauth.create_pkce_pair()
        expected = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest())
        expected = expected.rstrip(b"=").decode("ascii")

        self.assertEqual(challenge, expected)
        self.assertGreaterEqual(len(verifier), 43)

    def test_authorization_url_contains_local_callback_and_key_label(self):
        url = openrouter_oauth.build_authorization_url(
            "http://localhost:12345/callback/secret", "challenge-value"
        )
        query = parse_qs(urlsplit(url).query)

        self.assertEqual(urlsplit(url).scheme, "https")
        self.assertEqual(query["callback_url"], ["http://localhost:12345/callback/secret"])
        self.assertEqual(query["code_challenge"], ["challenge-value"])
        self.assertEqual(query["code_challenge_method"], ["S256"])
        self.assertEqual(query["key_label"], ["KAIRO"])

    def test_authorization_rejects_non_local_callback(self):
        with self.assertRaisesRegex(ValueError, "adresse HTTP locale"):
            openrouter_oauth.build_authorization_url("http://example.com/callback", "challenge")

    def test_code_exchange_sends_pkce_verifier_and_returns_key(self):
        response = MagicMock()
        response.__enter__.return_value.read.return_value = b'{"key":"sk-or-created"}'
        with patch.object(openrouter_oauth, "open_url", return_value=response) as open_url:
            key = openrouter_oauth.exchange_code_for_key("authorization-code", "secret-verifier")

        request = open_url.call_args.args[0]
        payload = json.loads(request.data)
        self.assertEqual(key, "sk-or-created")
        self.assertEqual(request.full_url, openrouter_oauth.KEY_EXCHANGE_URL)
        self.assertEqual(payload, {
            "code": "authorization-code",
            "code_verifier": "secret-verifier",
            "code_challenge_method": "S256",
        })

    def test_localhost_callback_exchanges_code_for_key(self):
        requests = []

        def open_browser(auth_url, **_kwargs):
            callback_url = parse_qs(urlsplit(auth_url).query)["callback_url"][0]

            def complete_authorization():
                with request_urlopen(callback_url + "?code=oauth-code", timeout=2) as response:
                    requests.append(response.status)

            threading.Thread(target=complete_authorization, daemon=True).start()
            return True

        with patch.object(openrouter_oauth, "exchange_code_for_key", return_value="sk-or-created") as exchange:
            result = openrouter_oauth.authorize_openrouter(
                timeout=3,
                browser_open=open_browser,
            )

        self.assertEqual(result, "sk-or-created")
        self.assertEqual(requests, [200])
        self.assertEqual(exchange.call_args.args[0], "oauth-code")
        self.assertTrue(exchange.call_args.args[1])


if __name__ == "__main__":
    unittest.main()