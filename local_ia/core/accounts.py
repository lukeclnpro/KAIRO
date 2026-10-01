"""Comptes locaux et stockage chiffre des cles OpenRouter."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken


SESSION_SERVICE = "KAIRO"
SESSION_USERNAME = "active_openrouter_session"


def _keyring():
    try:
        import keyring
    except ImportError as error:
        raise RuntimeError("Le paquet keyring est requis pour mémoriser la connexion.") from error
    return keyring


def accounts_path() -> Path:
    override = os.environ.get("LOCAL_IA_ACCOUNTS_FILE")
    if override:
        return Path(override).expanduser()
    if os.name == "nt":
        data_dir = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    elif sys.platform == "darwin":
        data_dir = Path.home() / "Library" / "Application Support"
    else:
        data_dir = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return data_dir / "local_ia" / "accounts.json"


def list_accounts(path: Path | None = None) -> list[str]:
    return sorted(_load(path).keys(), key=str.casefold)


def save_session(username: str, api_keys: str | list[str]) -> None:
    session = {
        "username": _validate_username(username),
        "api_keys": _normalize_api_keys(api_keys),
    }
    _keyring().set_password(SESSION_SERVICE, SESSION_USERNAME, json.dumps(session, ensure_ascii=False))


def load_saved_session() -> tuple[str, list[str]] | None:
    stored = _keyring().get_password(SESSION_SERVICE, SESSION_USERNAME)
    if not stored:
        return None
    try:
        session = json.loads(stored)
        if not isinstance(session, dict):
            return None
        username = _validate_username(session.get("username", ""))
        api_keys = _normalize_api_keys(session.get("api_keys", []))
    except (TypeError, ValueError):
        return None
    return username, api_keys


def clear_saved_session() -> None:
    keyring = _keyring()
    try:
        keyring.delete_password(SESSION_SERVICE, SESSION_USERNAME)
    except keyring.errors.PasswordDeleteError:
        pass


def create_account(username: str, password: str, api_key: str | list[str], path: Path | None = None) -> None:
    name = _validate_username(username)
    if len(password) < 8:
        raise ValueError("Le mot de passe doit contenir au moins 8 caracteres.")
    api_keys = _normalize_api_keys(api_key)

    accounts = _load(path)
    if _account_key(accounts, name) is not None:
        raise ValueError("Ce nom de compte existe deja.")
    accounts[name] = _encrypt_record(password, api_keys)
    _save(accounts, path)


def authenticate(username: str, password: str, path: Path | None = None) -> str:
    return authenticate_api_keys(username, password, path)[0]


def authenticate_api_keys(username: str, password: str, path: Path | None = None) -> list[str]:
    return [record["key"] for record in authenticate_api_key_records(username, password, path) if record["enabled"]]


def authenticate_api_key_records(
    username: str,
    password: str,
    path: Path | None = None,
) -> list[dict[str, str | bool | int]]:
    accounts = _load(path)
    key = _account_key(accounts, username.strip())
    if key is None:
        raise ValueError("Compte ou mot de passe invalide.")
    record = accounts[key]
    try:
        derived = _derive_key(password, record["salt"])
        cipher = Fernet(derived)
        if "api_keys" in record:
            payload = json.loads(cipher.decrypt(record["api_keys"].encode("ascii")).decode("utf-8"))
            if isinstance(payload, dict):
                values = payload.get("keys", [])
                enabled = payload.get("enabled", [])
            else:
                values = payload
                enabled = []
        else:
            values = cipher.decrypt(record["api_key"].encode("ascii")).decode("utf-8")
            enabled = []
        api_keys = _normalize_api_keys(values)
        if not isinstance(enabled, list) or len(enabled) != len(api_keys):
            enabled = [True] * len(api_keys)
        return [
            {"index": index, "key": api_key, "enabled": bool(enabled[index - 1])}
            for index, api_key in enumerate(api_keys, start=1)
        ]
    except (InvalidToken, KeyError, ValueError, TypeError) as error:
        raise ValueError("Compte ou mot de passe invalide.") from error


def update_api_key(username: str, password: str, api_key: str, path: Path | None = None) -> None:
    new_key = _normalize_api_keys(api_key)[0]
    accounts = _load(path)
    key = _account_key(accounts, username.strip())
    if key is None:
        raise ValueError("Compte ou mot de passe invalide.")
    records = authenticate_api_key_records(key, password, path)
    api_keys = [record["key"] for record in records]
    enabled = [record["enabled"] for record in records]
    api_keys[0] = new_key
    accounts[key] = _encrypt_record(password, api_keys, enabled)
    _save(accounts, path)


def add_api_key(username: str, password: str, api_key: str, path: Path | None = None) -> int:
    new_key = _normalize_api_keys(api_key)[0]
    accounts = _load(path)
    key = _account_key(accounts, username.strip())
    if key is None:
        raise ValueError("Compte ou mot de passe invalide.")
    records = authenticate_api_key_records(key, password, path)
    api_keys = [record["key"] for record in records]
    enabled = [record["enabled"] for record in records]
    if new_key in api_keys:
        raise ValueError("Cette clé API est déjà enregistrée.")
    api_keys.append(new_key)
    enabled.append(True)
    accounts[key] = _encrypt_record(password, api_keys, enabled)
    _save(accounts, path)
    return len(api_keys)


def remove_api_key(username: str, password: str, index: int, path: Path | None = None) -> int:
    accounts = _load(path)
    key = _account_key(accounts, username.strip())
    if key is None:
        raise ValueError("Compte ou mot de passe invalide.")
    records = authenticate_api_key_records(key, password, path)
    api_keys = [record["key"] for record in records]
    enabled = [record["enabled"] for record in records]
    if len(api_keys) <= 1:
        raise ValueError("Le compte doit conserver au moins une clé API.")
    if not 1 <= index <= len(api_keys):
        raise ValueError("Numéro de clé invalide.")
    del api_keys[index - 1]
    del enabled[index - 1]
    if not any(enabled):
        raise ValueError("Le compte doit conserver au moins une clé API active.")
    accounts[key] = _encrypt_record(password, api_keys, enabled)
    _save(accounts, path)
    return len(api_keys)


def set_api_key_enabled(
    username: str,
    password: str,
    index: int,
    enabled: bool,
    path: Path | None = None,
) -> None:
    accounts = _load(path)
    key = _account_key(accounts, username.strip())
    if key is None:
        raise ValueError("Compte ou mot de passe invalide.")
    records = authenticate_api_key_records(key, password, path)
    if not 1 <= index <= len(records):
        raise ValueError("Numéro de clé invalide.")
    records[index - 1]["enabled"] = bool(enabled)
    if not any(record["enabled"] for record in records):
        raise ValueError("Le compte doit conserver au moins une clé API active.")
    accounts[key] = _encrypt_record(
        password,
        [record["key"] for record in records],
        [record["enabled"] for record in records],
    )
    _save(accounts, path)


def delete_account(username: str, password: str, path: Path | None = None) -> None:
    accounts = _load(path)
    key = _account_key(accounts, username.strip())
    if key is None:
        raise ValueError("Compte ou mot de passe invalide.")
    authenticate(key, password, path)
    del accounts[key]
    _save(accounts, path)


def _validate_username(username: str) -> str:
    name = username.strip()
    if not name or len(name) > 64 or any(char in name for char in "\\/\0"):
        raise ValueError("Nom de compte invalide.")
    return name


def _account_key(accounts: dict, username: str) -> str | None:
    folded = username.casefold()
    return next((name for name in accounts if name.casefold() == folded), None)


def _load(path: Path | None) -> dict:
    target = path or accounts_path()
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("Le fichier des comptes locaux est illisible.") from error
    if not isinstance(data, dict):
        raise ValueError("Le fichier des comptes locaux est invalide.")
    return data


def _derive_key(password: str, salt: str) -> bytes:
    key = hashlib.scrypt(
        password.encode("utf-8"),
        salt=base64.urlsafe_b64decode(salt.encode("ascii")),
        n=2**14,
        r=8,
        p=1,
        dklen=32,
    )
    return base64.urlsafe_b64encode(key)


def _normalize_api_keys(api_keys: str | list[str]) -> list[str]:
    values = [api_keys] if isinstance(api_keys, str) else api_keys
    if not isinstance(values, list):
        raise ValueError("Les clés API doivent être une liste de textes.")
    normalized = list(dict.fromkeys(str(value).strip() for value in values if str(value).strip()))
    if not normalized:
        raise ValueError("Une clé API est requise.")
    return normalized


def _encrypt_record(
    password: str,
    api_keys: list[str],
    enabled: list[bool] | None = None,
) -> dict[str, str]:
    salt = base64.urlsafe_b64encode(os.urandom(16)).decode("ascii")
    flags = enabled if enabled is not None else [True] * len(api_keys)
    payload = json.dumps(
        {"keys": api_keys, "enabled": flags},
        ensure_ascii=False,
    ).encode("utf-8")
    encrypted = Fernet(_derive_key(password, salt)).encrypt(payload)
    return {"salt": salt, "api_keys": encrypted.decode("ascii")}


def _save(accounts: dict, path: Path | None) -> None:
    target = path or accounts_path()
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, temporary_name = tempfile.mkstemp(prefix=".accounts-", dir=target.parent)
    try:
        os.chmod(temporary_name, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            json.dump(accounts, output, ensure_ascii=False, indent=2)
            output.write("\n")
        os.replace(temporary_name, target)
        os.chmod(target, 0o600)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)