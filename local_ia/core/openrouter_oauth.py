"""Connexion OpenRouter par OAuth PKCE pour application locale."""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlsplit

from local_ia.http_client import Request, open_url


AUTHORIZATION_URL = "https://openrouter.ai/auth"
KEY_EXCHANGE_URL = "https://openrouter.ai/api/v1/auth/keys"
DEFAULT_KEY_LABEL = "KAIRO"


def create_pkce_pair():
    verifier = secrets.token_urlsafe(48)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def build_authorization_url(callback_url, challenge, key_label=DEFAULT_KEY_LABEL):
    callback = urlsplit(str(callback_url))
    if callback.scheme != "http" or callback.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("Le retour OAuth doit utiliser une adresse HTTP locale.")
    return AUTHORIZATION_URL + "?" + urlencode({
        "callback_url": str(callback_url),
        "code_challenge": str(challenge),
        "code_challenge_method": "S256",
        "key_label": str(key_label),
    })


def exchange_code_for_key(code, verifier, *, urlopen=None):
    code = str(code or "").strip()
    if not code:
        raise ValueError("OpenRouter n'a pas renvoyé de code d'autorisation.")
    payload = {
        "code": code,
        "code_verifier": verifier,
        "code_challenge_method": "S256",
    }
    request = Request(
        KEY_EXCHANGE_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    opener = urlopen or open_url
    try:
        with opener(request, timeout=30) as response:
            result = json.loads(response.read(1_000_000).decode("utf-8"))
    except HTTPError as error:
        raise RuntimeError(f"OpenRouter a refusé l'autorisation (HTTP {error.code}).") from error
    except (OSError, URLError, json.JSONDecodeError) as error:
        raise RuntimeError(f"Impossible d'échanger le code avec OpenRouter : {error}") from error

    key = result.get("key") if isinstance(result, dict) else None
    if not isinstance(key, str) or not key.strip():
        raise RuntimeError("OpenRouter n'a pas renvoyé de clé API exploitable.")
    return key.strip()


def authorize_openrouter(*, timeout=600, browser_open=None, urlopen=None):
    verifier, challenge = create_pkce_pair()
    callback_path = "/oauth/callback/" + secrets.token_urlsafe(32)
    server = HTTPServer(("127.0.0.1", 0), BaseHTTPRequestHandler)
    server.timeout = 1
    callback_url = f"http://localhost:{server.server_port}{callback_path}"
    server.auth_result = None

    class CallbackHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            parsed = urlsplit(self.path)
            if parsed.path != callback_path:
                self.send_response(404)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return

            query = parse_qs(parsed.query)
            code = query.get("code", [""])[0].strip()
            if query.get("error"):
                server.auth_result = (None, "L'autorisation OpenRouter a été refusée.")
                response_text = "Autorisation refusée. Vous pouvez fermer cette fenêtre."
                status = 400
            elif code:
                server.auth_result = (code, None)
                response_text = "Autorisation réussie. Vous pouvez revenir dans KAIRO."
                status = 200
            else:
                server.auth_result = (None, "OpenRouter n'a pas renvoyé de code d'autorisation.")
                response_text = "Réponse d'autorisation invalide. Vous pouvez fermer cette fenêtre."
                status = 400

            body = (
                "<!doctype html><html lang=\"fr\"><meta charset=\"utf-8\"><title>KAIRO</title>"
                f"<body><p>{response_text}</p></body></html>"
            ).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, _format, *_args):
            return

    server.RequestHandlerClass = CallbackHandler
    try:
        opener = browser_open or webbrowser.open
        auth_url = build_authorization_url(callback_url, challenge)
        if not opener(auth_url, new=1, autoraise=True):
            raise RuntimeError("Impossible d'ouvrir le navigateur pour connecter OpenRouter.")

        deadline = time.monotonic() + max(1, int(timeout))
        while server.auth_result is None and time.monotonic() < deadline:
            server.handle_request()
        if server.auth_result is None:
            raise TimeoutError("Connexion OpenRouter expirée. Relance l'autorisation.")
        code, error = server.auth_result
        if error:
            raise RuntimeError(error)
        return exchange_code_for_key(code, verifier, urlopen=urlopen)
    finally:
        server.server_close()