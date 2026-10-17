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


def _fallback_session_paths() -> tuple[Path, Path]:
    path = accounts_path()
    return path.with_name("auth_jey.cript"), path.with_name("session.key")


def _write_private_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, temporary_name = tempfile.mkstemp(prefix=".session-", dir=path.parent)
    try:
        os.chmod(temporary_name, 0o600)
        with os.fdopen(descriptor, "wb") as output:
            output.write(content)
        os.replace(temporary_name, path)
        os.chmod(path, 0o600)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)


def _save_fallback_session(session: dict) -> None:
    session_path, key_path = _fallback_session_paths()
    session_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        key = key_path.read_bytes()
    except FileNotFoundError:
        key = Fernet.generate_key()
        try:
            descriptor = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            key = key_path.read_bytes()
        else:
            with os.fdopen(descriptor, "wb") as output:
                output.write(key)
            os.chmod(key_path, 0o600)
    encrypted = Fernet(key).encrypt(json.dumps(session, ensure_ascii=False).encode("utf-8"))
    _write_private_bytes(session_path, encrypted)


def _load_fallback_session() -> dict | None:
    session_path, key_path = _fallback_session_paths()
    legacy_session_path = session_path.with_name("session.enc")
    try:
        key = key_path.read_bytes()
        source_path = session_path if session_path.exists() else legacy_session_path
        encrypted = source_path.read_bytes()
        session = json.loads(Fernet(key).decrypt(encrypted).decode("utf-8"))
    except FileNotFoundError:
        return None
    except (InvalidToken, OSError, TypeError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(session, dict):
        return None
    if source_path == legacy_session_path:
        try:
            _save_fallback_session(session)
        except OSError:
            return None
        legacy_session_path.unlink(missing_ok=True)
    return session


def _clear_fallback_session() -> None:
    for path in _fallback_session_paths():
        try:
            path.unlink()
        except FileNotFoundError:
            pass


def _load_session_data() -> dict | None:
    session_path, _key_path = _fallback_session_paths()
    if not session_path.exists():
        return _load_fallback_session()
    try:
        stored = _keyring().get_password(SESSION_SERVICE, SESSION_USERNAME)
        session = json.loads(stored) if stored else None
    except Exception:
        session = None
    if isinstance(session, dict):
        return session
    return _load_fallback_session()


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


def save_session(username: str, api_keys: str | list[str], password: str | None = None) -> None:
    name = _validate_username(username)
    session = {
        "username": name,
        "api_keys": _normalize_api_keys(api_keys),
    }
    if isinstance(password, str) and password:
        session["account_password"] = password
    else:
        previous = _load_session_data()
        if (
            isinstance(previous, dict)
            and str(previous.get("username", "")).casefold() == name.casefold()
            and isinstance(previous.get("account_password"), str)
            and previous["account_password"]
        ):
            session["account_password"] = previous["account_password"]
    serialized = json.dumps(session, ensure_ascii=False)
    _save_fallback_session(session)
    try:
        _keyring().set_password(SESSION_SERVICE, SESSION_USERNAME, serialized)
    except Exception:
        return


def load_saved_session() -> tuple[str, list[str]] | None:
    session = _load_session_data()
    if not session:
        return None
    try:
        username = _validate_username(session.get("username", ""))
        api_keys = _normalize_api_keys(session.get("api_keys", []))
    except (TypeError, ValueError):
        return None
    return username, api_keys


def load_saved_account_password(username: str | None = None) -> str:
    session = _load_session_data()
    if not session:
        return ""
    try:
        saved_username = _validate_username(session.get("username", ""))
        if username and saved_username.casefold() != str(username).strip().casefold():
            return ""
        password = session.get("account_password", "")
    except (TypeError, ValueError):
        return ""
    return password if isinstance(password, str) else ""


def clear_saved_session() -> None:
    keyring_error = None
    try:
        keyring = _keyring()
    except Exception:
        keyring = None
    if keyring is not None:
        try:
            keyring.delete_password(SESSION_SERVICE, SESSION_USERNAME)
        except keyring.errors.PasswordDeleteError:
            pass
        except Exception as error:
            keyring_error = error
    _clear_fallback_session()
    if keyring_error:
        raise RuntimeError("Le trousseau système n'a pas pu être effacé.") from keyring_error


def create_account(
    username: str,
    password: str,
    api_key: str | list[str],
    path: Path | None = None,
    *,
    email: str = "",
    avatar: str = "",
) -> None:
    name = _validate_username(username)
    if len(password) < 8:
        raise ValueError("Le mot de passe doit contenir au moins 8 caracteres.")
    email = _validate_email(email)
    api_keys = _normalize_api_keys(api_key)

    accounts = _load(path)
    if _account_key(accounts, name) is not None:
        raise ValueError("Ce nom de compte existe deja.")
    if email and any(
        str(record.get("email", "")).casefold() == email.casefold()
        for record in accounts.values()
        if isinstance(record, dict)
    ):
        raise ValueError("Cette adresse e-mail est déjà utilisée.")
    record = _encrypt_record(password, api_keys)
    if email:
        record["email"] = email
    if avatar:
        record["avatar"] = str(avatar)
    accounts[name] = record
    _save(accounts, path)


def account_profile(username_or_email: str, path: Path | None = None) -> dict[str, str]:
    stored = _load(path)
    name = _account_key(stored, username_or_email.strip())
    if name is None:
        raise ValueError("Compte introuvable.")
    record = stored[name]
    return {
        "username": name,
        "email": str(record.get("email", "")),
        "avatar": str(record.get("avatar", "")),
    }


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


def _validate_email(email: str) -> str:
    value = str(email).strip()
    if value and ("@" not in value or any(char.isspace() for char in value)):
        raise ValueError("Adresse e-mail invalide.")
    if value:
        local, separator, domain = value.partition("@")
        if not separator or not local or "." not in domain or domain.startswith(".") or domain.endswith("."):
            raise ValueError("Adresse e-mail invalide.")
    return value


def _account_key(accounts: dict, username: str) -> str | None:
    folded = username.casefold()
    return next(
        (
            name
            for name, record in accounts.items()
            if name.casefold() == folded
            or (isinstance(record, dict) and str(record.get("email", "")).casefold() == folded)
        ),
        None,
    )


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