from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtCore import QSettings, QTimer
    from PySide6.QtWidgets import QApplication, QCheckBox, QComboBox, QPushButton, QTabWidget, QTreeView
    from PySide6.QtTest import QTest
except ImportError:
    QApplication = None

from local_ia import gui_workspace


@unittest.skipUnless(QApplication is not None, "PySide6 n'est pas installé")
class GuiWorkspaceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        class FakeAgent:
            def prepare_chat(self, chat):
                pass

            def close(self):
                pass

        class FakeConnection:
            def close(self):
                pass

        self.chat = {"id": 777, "messages": [], "title": "", "topic": None}
        self.patches = [
            patch.object(gui_workspace, "LocalAgent", return_value=FakeAgent()),
            patch.object(gui_workspace, "init_database", return_value=FakeConnection()),
            patch.object(gui_workspace, "create_chat", return_value=self.chat),
            patch.object(gui_workspace, "list_chats", return_value=[]),
            patch.object(gui_workspace.accounts, "load_saved_session", return_value=None),
        ]
        for active_patch in self.patches:
            active_patch.start()
        self.window = gui_workspace.KairoWorkspace()

    def tearDown(self):
        self.window.close()
        for active_patch in reversed(self.patches):
            active_patch.stop()

    def test_workspace_exposes_connection_chat_code_and_terminal_actions(self):
        labels = [button.text() for button in self.window.findChildren(QPushButton)]

        self.assertIn("⤴   Connexion OpenRouter", labels)
        self.assertIn("＋   Nouveau chat", labels)
        self.assertIn("⌘   Mode Code", labels)
        self.assertIn("▣   Ouvrir le terminal", labels)
        self.assertEqual(labels.count("⚙   Paramètres"), 1)
        self.assertIsInstance(self.window.file_tree, QTreeView)

    def test_saved_account_session_is_restored_without_password_prompt(self):
        with patch.dict(os.environ, {}, clear=True):
            with patch.object(
                gui_workspace,
                "openrouter_api_keys",
                side_effect=lambda: gui_workspace.json.loads(os.environ.get("LOCAL_IA_OPENROUTER_KEYS", "[]")),
            ):
                with patch.object(
                    gui_workspace.accounts,
                    "load_saved_session",
                    return_value=("alice", ["saved-key"]),
                ):
                    self.window._restore_saved_session()
                    self.assertEqual(os.environ["LOCAL_IA_ACCOUNT"], "alice")
                    self.assertEqual(os.environ["LOCAL_IA_OPENROUTER_KEYS"], '["saved-key"]')
                    self.assertEqual(self.window.connect_button.text(), "●   API connectée")

    def test_new_chat_action_calls_shared_conversation_storage(self):
        new_chat = {"id": 778, "messages": [], "title": "", "topic": None}
        with patch.object(gui_workspace, "create_chat", return_value=new_chat) as create:
            self.window._new_chat()

        create.assert_called_once_with()
        self.assertEqual(self.window.chat["id"], 778)

    def test_editor_saves_changes_and_creates_backup(self):
        with tempfile.TemporaryDirectory() as directory:
            self.window.project_root = Path(directory)
            source = self.window.project_root / "app.py"
            source.write_text("print('before')\n", encoding="utf-8")
            self.assertTrue(self.window._open_code_file(source))

            self.window.code_editor.setPlainText("print('after')\n")
            self.assertEqual(self.window.current_file, source)
            self.assertNotEqual(self.window._saved_hash, gui_workspace.hashlib.sha256(b"print('after')\n").hexdigest())
            QTest.qWait(800)

            self.assertEqual(source.read_text(encoding="utf-8"), "print('after')\n")
            backups = list((self.window.project_root / ".local_ia_backups").glob("*.py"))
            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0].read_text(encoding="utf-8"), "print('before')\n")

    def test_ai_prompt_is_blocked_until_openrouter_is_connected(self):
        with patch.object(gui_workspace, "openrouter_api_keys", return_value=[]), \
             patch.object(gui_workspace.QMessageBox, "information") as information:
            self.window._set_connection_status()
            self.window.prompt.setText("bonjour")
            self.window._send_message()

        information.assert_called_once()
        self.assertEqual(self.window.prompt.text(), "bonjour")
        self.assertFalse(self.window.send_button.isEnabled())

    def test_send_message_starts_agent_task_without_enabling_commands_by_default(self):
        with patch.object(gui_workspace, "openrouter_api_keys", return_value=["key"]), \
             patch.object(gui_workspace, "AgentTask") as agent_task:
            agent_task.return_value.completed.connect = Mock()
            agent_task.return_value.isRunning.return_value = False
            self.window.prompt.setText("Bonjour")
            self.window._send_message()

        self.assertIn("file", agent_task.call_args.kwargs["allowed_tools"])
        self.assertNotIn("command", agent_task.call_args.kwargs["allowed_tools"])
        self.assertFalse(agent_task.call_args.kwargs["command_enabled"])
        agent_task.return_value.start.assert_called_once_with()

    def test_code_mode_keeps_selected_project_active(self):
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(self.window, "_choose_project", return_value=Path(directory)), \
             patch.object(gui_workspace.code_projects, "install_code_examples"):
            self.window._toggle_code_mode(True)

        self.assertEqual(self.window.project_root, Path(directory))
        self.assertEqual(self.window.chat["code_project_path"], str(Path(directory)))

    def test_external_single_file_is_opened_and_attached_to_chat_context(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "notes.py"
            source.write_text("def greet():\n    return 'bonjour'\n", encoding="utf-8")
            self.assertTrue(self.window._open_code_file(source, single_file=True))
            self.assertIsNone(self.window.project_root)
            self.assertTrue(self.window.single_file_mode)

            context = self.window._single_file_context()

        self.assertIn("def greet()", context)
        self.assertIn(str(source), context)
        self.assertIn("contexte limité à ce fichier", context)

    def test_single_file_ai_diff_requires_approval_then_saves_with_backup(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "notes.py"
            original = "def greet():\n    return 'bonjour'\n"
            source.write_text(original, encoding="utf-8")
            self.assertTrue(self.window._open_code_file(source, single_file=True))
            proposed = "def greet():\n    return 'salut'\n"
            answer = (
                "<<<KAIRO_FILE_CONTENT>>>\n"
                + proposed
                + "<<<END_KAIRO_FILE_CONTENT>>>"
            )

            def approve_diff():
                dialog = QApplication.activeModalWidget()
                buttons = dialog.findChild(gui_workspace.QDialogButtonBox)
                buttons.button(gui_workspace.QDialogButtonBox.StandardButton.Apply).click()

            QTimer.singleShot(0, approve_diff)
            self.window._single_file_edit_finished(
                "change le salut",
                original,
                gui_workspace.hashlib.sha256(original.encode("utf-8")).hexdigest(),
                True,
                answer,
            )

            self.assertEqual(source.read_text(encoding="utf-8"), proposed)
            backups = list((Path(directory) / ".local_ia_backups").glob("*.py"))
            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0].read_text(encoding="utf-8"), original)

    def test_model_presets_are_available_and_selection_persists(self):
        model_ids = [
            self.window.model_picker.itemData(index)
            for index in range(self.window.model_picker.count())
        ]

        self.assertIn("openai/gpt-4o-mini", model_ids)
        self.assertIn("anthropic/claude-3.5-sonnet", model_ids)
        self.assertIn("__custom__", model_ids)

        with patch.object(gui_workspace, "save_config") as save, \
             patch.object(gui_workspace, "LocalAgent", return_value=type("Agent", (), {"close": lambda self: None})()), \
             patch.dict(os.environ, {}, clear=True):
            self.assertTrue(self.window._apply_model("anthropic/claude-3.5-sonnet"))
            self.assertEqual(os.environ["LOCAL_IA_OPENROUTER_MODEL"], "anthropic/claude-3.5-sonnet")

        self.assertEqual(self.window.config["openrouter"]["model"], "anthropic/claude-3.5-sonnet")
        save.assert_called_once_with(self.window.config)

    def test_api_key_manager_adds_key_then_refreshes_connected_session(self):
        initial_records = [{"index": 1, "key": "first-secret-key", "enabled": True}]
        updated_records = [
            {"index": 1, "key": "first-secret-key", "enabled": True},
            {"index": 2, "key": "second-secret-key", "enabled": True},
        ]
        opened_dialogs = []

        def add_from_dialog(dialog):
            opened_dialogs.append(dialog)
            dialog.add_button.click()
            return 0

        with patch.dict(os.environ, {"LOCAL_IA_ACCOUNT": "alice"}), \
             patch.object(gui_workspace.accounts, "authenticate_api_key_records", side_effect=(
                 initial_records,
                 updated_records,
             )), \
             patch.object(
                 gui_workspace.accounts,
                 "authenticate_api_keys",
                 return_value=["first-secret-key", "second-secret-key"],
             ), \
             patch.object(gui_workspace.accounts, "add_api_key") as add_key, \
             patch.object(
                 gui_workspace.QInputDialog,
                 "getText",
                 side_effect=(("account-password", True), ("second-secret-key", True)),
             ), \
             patch.object(gui_workspace.ApiKeyManagerDialog, "exec", new=add_from_dialog), \
             patch.object(self.window, "_set_provider") as set_provider:
            self.window._manage_api_keys()

        add_key.assert_called_once_with("alice", "account-password", "second-secret-key")
        set_provider.assert_called_once_with("alice", ["first-secret-key", "second-secret-key"])
        self.assertEqual(opened_dialogs[0].table.item(0, 0).text(), "first-se…-key")
        self.assertEqual(opened_dialogs[0].table.item(0, 1).text(), "Activée")

    def test_api_key_manager_disables_selected_key_and_refreshes_runtime_keys(self):
        initial_records = [
            {"index": 1, "key": "first-secret-key", "enabled": True},
            {"index": 2, "key": "second-secret-key", "enabled": True},
        ]
        updated_records = [
            {"index": 1, "key": "first-secret-key", "enabled": False},
            {"index": 2, "key": "second-secret-key", "enabled": True},
        ]
        opened_dialogs = []

        def disable_from_dialog(dialog):
            opened_dialogs.append(dialog)
            dialog.toggle_button.click()
            return 0

        with patch.dict(os.environ, {"LOCAL_IA_ACCOUNT": "alice"}), \
             patch.object(gui_workspace.accounts, "authenticate_api_key_records", side_effect=(
                 initial_records, updated_records,
             )), \
             patch.object(gui_workspace.accounts, "authenticate_api_keys", return_value=["second-secret-key"]), \
             patch.object(gui_workspace.accounts, "set_api_key_enabled") as set_enabled, \
             patch.object(gui_workspace.QInputDialog, "getText", return_value=("account-password", True)), \
             patch.object(gui_workspace.ApiKeyManagerDialog, "exec", new=disable_from_dialog), \
             patch.object(self.window, "_set_provider") as set_provider:
            self.window._manage_api_keys()

        set_enabled.assert_called_once_with("alice", "account-password", 1, False)
        set_provider.assert_called_once_with("alice", ["second-secret-key"])
        self.assertEqual(opened_dialogs[0].table.item(0, 1).text(), "Désactivée")

    def test_api_key_manager_removes_selected_key_after_confirmation(self):
        initial_records = [
            {"index": 1, "key": "first-secret-key", "enabled": True},
            {"index": 2, "key": "second-secret-key", "enabled": True},
        ]
        remaining_records = [{"index": 1, "key": "second-secret-key", "enabled": True}]

        def remove_from_dialog(dialog):
            dialog.table.selectRow(0)
            dialog.remove_button.click()
            return 0

        with patch.dict(os.environ, {"LOCAL_IA_ACCOUNT": "alice"}), \
             patch.object(gui_workspace.accounts, "authenticate_api_key_records", side_effect=(
                 initial_records, remaining_records,
             )), \
             patch.object(gui_workspace.accounts, "authenticate_api_keys", return_value=["second-secret-key"]), \
             patch.object(gui_workspace.accounts, "remove_api_key", return_value=1) as remove_key, \
             patch.object(gui_workspace.QInputDialog, "getText", return_value=("account-password", True)), \
             patch.object(gui_workspace.QMessageBox, "question", return_value=gui_workspace.QMessageBox.StandardButton.Yes), \
             patch.object(gui_workspace.ApiKeyManagerDialog, "exec", new=remove_from_dialog), \
             patch.object(self.window, "_set_provider") as set_provider:
            self.window._manage_api_keys()

        remove_key.assert_called_once_with("alice", "account-password", 1)
        set_provider.assert_called_once_with("alice", ["second-secret-key"])

    def test_api_key_manager_shows_usage_for_selected_key(self):
        records = [{"index": 1, "key": "first-secret-key", "enabled": True}]

        def show_from_dialog(dialog):
            dialog.usage_button.click()
            return 0

        with patch.dict(os.environ, {"LOCAL_IA_ACCOUNT": "alice"}), \
             patch.object(gui_workspace.accounts, "authenticate_api_key_records", return_value=records), \
             patch.object(gui_workspace.QInputDialog, "getText", return_value=("account-password", True)), \
             patch.object(gui_workspace, "get_openrouter_key_usage", return_value={
                 "usage": 1.25,
                 "limit": 10,
                 "limit_remaining": 8.75,
             }) as get_usage, \
             patch.object(gui_workspace.QMessageBox, "information") as information, \
             patch.object(gui_workspace.ApiKeyManagerDialog, "exec", new=show_from_dialog):
            self.window._manage_api_keys()

        get_usage.assert_called_once_with(api_key="first-secret-key")
        self.assertIn("8.75", information.call_args.args[2])

    def test_settings_persist_theme_and_notification_sound(self):
        with tempfile.TemporaryDirectory() as directory:
            self.window.ui_settings = QSettings(str(Path(directory) / "gui.ini"), QSettings.Format.IniFormat)

            def set_preferences_and_accept():
                dialog = QApplication.activeModalWidget()
                tabs = dialog.findChild(QTabWidget)
                theme_picker = tabs.widget(0).findChild(QComboBox)
                theme_picker.setCurrentIndex(theme_picker.findData("light"))
                sound_toggle = tabs.widget(3).findChild(QCheckBox)
                sound_toggle.setChecked(False)
                dialog.accept()

            QTimer.singleShot(0, set_preferences_and_accept)
            self.window._open_settings()

            self.assertEqual(self.window.ui_settings.value("appearance/theme"), "light")
            self.assertFalse(self.window.ui_settings.value("notifications/sound", type=bool))
            self.assertIn("#eef3ef", self.window.styleSheet())

    def test_refusing_memory_deletion_keeps_all_memories(self):
        with patch.object(
            gui_workspace.QMessageBox,
            "question",
            return_value=gui_workspace.QMessageBox.StandardButton.No,
        ), patch.object(gui_workspace, "clear_memories") as clear:
            self.window._clear_all_memories()

        clear.assert_not_called()


if __name__ == "__main__":
    unittest.main()
