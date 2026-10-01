import os
import base64
import json
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from cryptography.fernet import Fernet

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from local_ia.core import accounts


class LocalAccountsTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.path = Path(self.temp_dir.name) / "accounts.json"

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_api_key_is_encrypted_and_password_protects_login(self):
        accounts.create_account("Alice", "correct horse", "sk-test-private-key", self.path)

        stored = self.path.read_text(encoding="utf-8")
        self.assertNotIn("sk-test-private-key", stored)
        self.assertEqual(accounts.authenticate("alice", "correct horse", self.path), "sk-test-private-key")
        with self.assertRaisesRegex(ValueError, "invalide"):
            accounts.authenticate("alice", "wrong password", self.path)

        if os.name == "posix":
            self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o600)

    def test_saved_session_is_stored_in_system_keyring_and_can_be_cleared(self):
        keyring_data = {}
        keyring = Mock()
        keyring.errors = SimpleNamespace(PasswordDeleteError=type("PasswordDeleteError", (Exception,), {}))

        def save_password(service, username, password):
            keyring_data[(service, username)] = password

        def read_password(service, username):
            return keyring_data.get((service, username))

        def delete_password(service, username):
            keyring_data.pop((service, username), None)

        keyring.set_password.side_effect = save_password
        keyring.get_password.side_effect = read_password
        keyring.delete_password.side_effect = delete_password
        with patch.object(accounts, "_keyring", return_value=keyring):
            accounts.save_session("Alice", ["first-secret", "second-secret"])

            self.assertEqual(accounts.load_saved_session(), ("Alice", ["first-secret", "second-secret"]))
            accounts.clear_saved_session()
            self.assertIsNone(accounts.load_saved_session())

    def test_key_can_be_updated_and_account_deleted(self):
        accounts.create_account("alice", "account-password", "old-key", self.path)
        accounts.update_api_key("ALICE", "account-password", "new-key", self.path)
        self.assertEqual(accounts.authenticate("alice", "account-password", self.path), "new-key")

        accounts.delete_account("alice", "account-password", self.path)
        self.assertEqual(accounts.list_accounts(self.path), [])

    def test_multiple_keys_are_encrypted_and_can_be_added_removed_and_updated(self):
        accounts.create_account("alice", "account-password", ["first-secret", "second-secret"], self.path)
        stored = self.path.read_text(encoding="utf-8")
        self.assertNotIn("first-secret", stored)
        self.assertNotIn("second-secret", stored)
        self.assertEqual(
            accounts.authenticate_api_keys("alice", "account-password", self.path),
            ["first-secret", "second-secret"],
        )

        self.assertEqual(accounts.add_api_key("alice", "account-password", "third-secret", self.path), 3)
        with self.assertRaisesRegex(ValueError, "déjà enregistrée"):
            accounts.add_api_key("alice", "account-password", "third-secret", self.path)
        self.assertEqual(accounts.remove_api_key("alice", "account-password", 2, self.path), 2)
        accounts.update_api_key("alice", "account-password", "new-primary", self.path)
        self.assertEqual(
            accounts.authenticate_api_keys("alice", "account-password", self.path),
            ["new-primary", "third-secret"],
        )
        self.assertEqual(accounts.remove_api_key("alice", "account-password", 1, self.path), 1)
        with self.assertRaisesRegex(ValueError, "au moins une"):
            accounts.remove_api_key("alice", "account-password", 1, self.path)

    def test_existing_single_key_record_remains_authenticatable(self):
        salt = base64.urlsafe_b64encode(os.urandom(16)).decode("ascii")
        encrypted = Fernet(accounts._derive_key("account-password", salt)).encrypt(b"legacy-secret")
        self.path.write_text(
            json.dumps({"alice": {"salt": salt, "api_key": encrypted.decode("ascii")}}),
            encoding="utf-8",
        )
        self.assertEqual(accounts.authenticate("alice", "account-password", self.path), "legacy-secret")
        self.assertEqual(accounts.authenticate_api_keys("alice", "account-password", self.path), ["legacy-secret"])

    def test_api_keys_can_be_disabled_and_reenabled_without_exposing_secrets(self):
        accounts.create_account("alice", "account-password", ["first-secret", "second-secret"], self.path)

        accounts.set_api_key_enabled("alice", "account-password", 1, False, self.path)
        self.assertEqual(
            accounts.authenticate_api_keys("alice", "account-password", self.path),
            ["second-secret"],
        )
        records = accounts.authenticate_api_key_records("alice", "account-password", self.path)
        self.assertEqual([record["enabled"] for record in records], [False, True])

        stored = self.path.read_text(encoding="utf-8")
        self.assertNotIn("first-secret", stored)
        self.assertNotIn("second-secret", stored)

        accounts.set_api_key_enabled("alice", "account-password", 1, True, self.path)
        self.assertEqual(
            accounts.authenticate_api_keys("alice", "account-password", self.path),
            ["first-secret", "second-secret"],
        )

    def test_last_active_api_key_cannot_be_disabled(self):
        accounts.create_account("alice", "account-password", ["first-secret", "second-secret"], self.path)
        accounts.set_api_key_enabled("alice", "account-password", 1, False, self.path)

        with self.assertRaisesRegex(ValueError, "au moins une clé API active"):
            accounts.set_api_key_enabled("alice", "account-password", 2, False, self.path)

        self.assertEqual(
            accounts.authenticate_api_keys("alice", "account-password", self.path),
            ["second-secret"],
        )

    def test_rejects_duplicate_users_weak_passwords_and_empty_keys(self):
        with self.assertRaisesRegex(ValueError, "8 caracteres"):
            accounts.create_account("alice", "short", "key", self.path)
        with self.assertRaisesRegex(ValueError, "requise"):
            accounts.create_account("alice", "long-enough", "  ", self.path)

        accounts.create_account("alice", "long-enough", "key", self.path)
        with self.assertRaisesRegex(ValueError, "existe deja"):
            accounts.create_account("ALICE", "long-enough", "key", self.path)


if __name__ == "__main__":
    unittest.main()
