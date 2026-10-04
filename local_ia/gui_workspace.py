"""Interface graphique KAIRO partageant moteur et donnees avec le CLI."""

from __future__ import annotations

import json
import ast
import difflib
import hashlib
import os
import shutil
import shlex
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import QEventLoop, QIODevice, QProcess, QPropertyAnimation, QRegularExpression, QSaveFile, QSettings, QThread, QTimer, Qt, Signal
from PySide6.QtGui import QColor, QFont, QKeySequence, QPixmap, QShortcut, QTextCharFormat, QSyntaxHighlighter
from PySide6.QtWidgets import (
    QApplication,
    QAbstractItemView,
    QFileSystemModel,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QComboBox,
    QCheckBox,
    QDialog as _QtDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox as _QtMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
        QStackedWidget,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextBrowser,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from local_ia.config.manager import (
    load_config,
    model_config,
    openrouter_api_keys,
    openrouter_base_url,
    openrouter_model,
    save_config,
)
from local_ia import updater
from local_ia.core import accounts, code_projects, conversation as conversation_store
from local_ia.core.agent import LocalAgent, TOOL_NAMES
from local_ia.core.context import load_context
from local_ia.core.tool_manager import ToolManager
from local_ia.core.openrouter_oauth import authorize_openrouter
from local_ia.llm.ollama import get_openrouter_key_usage
from local_ia.core.conversation import (
    CHAT_DIR,
    add_chat_message,
    clear_chat,
    create_chat,
    flush_writes,
    list_chats,
    load_chat,
    save_chat,
)
from local_ia.core.memory import (
    clear_memories,
    delete_memory,
    init_database,
    list_memories,
    save_memory,
)
from local_ia.tools import download as download_tool, file as file_tool
from local_ia.tools.edit import backup_file
import file_commands
import program_commands

BASE_DIR = Path(__file__).resolve().parents[1]
LOCAL_CODE_TOOLS = frozenset({"file", "write", "edit", "list", "search", "calculator"})
LOCAL_CODE_READ_TOOLS = frozenset({"file", "list", "search", "calculator"})
MAX_PREVIEW_BYTES = 1_000_000
MAX_SINGLE_FILE_AI_BYTES = 64_000
OPENROUTER_MODEL_PRESETS = (
    ("OpenAI · rapide et polyvalent", "openai/gpt-4o-mini"),
    ("Anthropic · code et raisonnement", "anthropic/claude-3.5-sonnet"),
)


def _exec_embedded_dialog(dialog, parent, object_name="embeddedDialog"):
    if parent is None or not parent.isVisible():
        return _QtDialog.exec(dialog)

    backdrop = QWidget(parent)
    backdrop.setObjectName("embeddedDialogBackdrop")
    backdrop.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    backdrop.setStyleSheet("background-color: rgba(0, 0, 0, 150);")
    backdrop.setGeometry(parent.rect())
    backdrop.show()
    backdrop.raise_()

    dialog.setParent(backdrop)
    dialog.setWindowFlags(Qt.WindowType.Widget)
    dialog.setObjectName(object_name)
    dialog.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    dialog.setStyleSheet(
        "QDialog#embeddedDialog, QFileDialog#embeddedFileDialog { background: #1c2925; color: #e6efea; "
        "border: 1px solid #456057; border-radius: 10px; }"
    )
    dialog.adjustSize()
    bounds = backdrop.rect()
    width = min(max(dialog.width(), dialog.minimumWidth()), max(320, bounds.width() - 40))
    height = min(max(dialog.height(), dialog.minimumHeight()), max(220, bounds.height() - 40))
    dialog.setGeometry((bounds.width() - width) // 2, (bounds.height() - height) // 2, width, height)
    event_loop = QEventLoop(dialog)

    def finish_event_loop(_result):
        event_loop.quit()

    dialog.finished.connect(finish_event_loop)
    dialog.show()
    dialog.raise_()
    event_loop.exec()
    dialog.finished.disconnect(finish_event_loop)
    result = dialog.result()
    dialog.setParent(parent)
    dialog.setWindowFlags(Qt.WindowType.Widget)
    backdrop.hide()
    backdrop.deleteLater()
    return result


class QDialog(_QtDialog):
    """Modal content rendered as an overlay inside its parent widget."""

    DialogCode = _QtDialog.DialogCode

    def exec(self):
        return _exec_embedded_dialog(
            self,
            self.parentWidget(),
            self.objectName() or "embeddedDialog",
        )


class QInputDialog:
    @staticmethod
    def getText(parent, title, label, echo=QLineEdit.EchoMode.Normal, text="", *_args, **_kwargs):
        if parent is None:
            from PySide6.QtWidgets import QInputDialog as NativeInputDialog

            return NativeInputDialog.getText(parent, title, label, echo, text)
        dialog = QDialog(parent)
        dialog.setObjectName("embeddedInputDialog")
        dialog.setWindowTitle(title)
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel(label))
        field = QLineEdit()
        field.setEchoMode(echo)
        field.setText(text)
        layout.addWidget(field)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            Qt.Orientation.Horizontal,
            dialog,
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        accepted = dialog.exec() == QDialog.DialogCode.Accepted
        return field.text(), accepted

    @staticmethod
    def getItem(parent, title, label, items, current=0, editable=False, *_args, **_kwargs):
        if parent is None:
            from PySide6.QtWidgets import QInputDialog as NativeInputDialog

            return NativeInputDialog.getItem(parent, title, label, items, current, editable)
        dialog = QDialog(parent)
        dialog.setObjectName("embeddedInputDialog")
        dialog.setWindowTitle(title)
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel(label))
        picker = QComboBox()
        picker.addItems([str(item) for item in items])
        picker.setEditable(editable)
        if picker.count():
            picker.setCurrentIndex(min(max(int(current), 0), picker.count() - 1))
        layout.addWidget(picker)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            Qt.Orientation.Horizontal,
            dialog,
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        accepted = dialog.exec() == QDialog.DialogCode.Accepted
        return picker.currentText(), accepted


class QMessageBox:
    StandardButton = _QtMessageBox.StandardButton

    @classmethod
    def _show(cls, parent, title, text, buttons, default_button):
        if parent is None:
            return _QtMessageBox.question(parent, title, text, buttons, default_button)
        dialog = QDialog(parent)
        dialog.setObjectName("embeddedMessageDialog")
        dialog.setWindowTitle(title)
        dialog.setMinimumWidth(380)
        layout = QVBoxLayout(dialog)
        label = QLabel(str(text))
        label.setWordWrap(True)
        layout.addWidget(label)
        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton(buttons.value),
            Qt.Orientation.Horizontal,
            dialog,
        )
        result = [default_button]

        def choose(button):
            result[0] = cls.StandardButton(button_box.standardButton(button).value)
            dialog.accept()

        button_box.clicked.connect(choose)
        default = button_box.button(QDialogButtonBox.StandardButton(default_button.value))
        if default:
            default.setDefault(True)
        layout.addWidget(button_box)
        dialog.exec()
        return result[0]

    @classmethod
    def question(cls, parent, title, text, buttons=None, defaultButton=None):
        buttons = buttons or (cls.StandardButton.Yes | cls.StandardButton.No)
        defaultButton = defaultButton or cls.StandardButton.No
        return cls._show(parent, title, text, buttons, defaultButton)

    @classmethod
    def information(cls, parent, title, text, buttons=None, defaultButton=None):
        buttons = buttons or cls.StandardButton.Ok
        defaultButton = defaultButton or cls.StandardButton.Ok
        return cls._show(parent, title, text, buttons, defaultButton)

    @classmethod
    def warning(cls, parent, title, text, buttons=None, defaultButton=None):
        buttons = buttons or cls.StandardButton.Ok
        defaultButton = defaultButton or cls.StandardButton.Ok
        return cls._show(parent, title, text, buttons, defaultButton)


class CodeHighlighter(QSyntaxHighlighter):
    RULES = (
        (r"\b(class|def|return|if|elif|else|for|while|try|except|finally|with|as|import|from|pass|raise|yield|async|await|True|False|None|const|let|var|function|new|this|public|private|static)\b", "#c792ea"),
        (r"\b(print|len|range|str|int|float|list|dict|set|tuple|open|super|self)\b", "#82aaff"),
        (r"\b\d+(?:\.\d+)?\b", "#f78c6c"),
        (r"#[^\n]*|//[^\n]*", "#71877f"),
        (r"\"[^\"]*\"|'[^']*'|`[^`]*`", "#c3e88d"),
    )

    def __init__(self, document):
        super().__init__(document)
        self.rules = []
        for pattern, color in self.RULES:
            text_format = QTextCharFormat()
            text_format.setForeground(QColor(color))
            self.rules.append((QRegularExpression(pattern), text_format))

    def highlightBlock(self, text):
        for expression, text_format in self.rules:
            matches = expression.globalMatch(text)
            while matches.hasNext():
                match = matches.next()
                self.setFormat(match.capturedStart(), match.capturedLength(), text_format)


class ActionButton(QPushButton):
    """Button with an animated glow on hover and a pressed state."""

    def __init__(self, label, object_name="actionButton", parent=None):
        super().__init__(label, parent)
        self.setObjectName(object_name)
        effect = QGraphicsDropShadowEffect(self)
        effect.setBlurRadius(0)
        effect.setOffset(0, 2)
        effect.setColor(Qt.GlobalColor.transparent)
        self.setGraphicsEffect(effect)
        self._glow = effect
        self._animation = QPropertyAnimation(effect, b"blurRadius", self)
        self._animation.setDuration(150)

    def enterEvent(self, event):
        self._animation.stop()
        self._animation.setStartValue(self._glow.blurRadius())
        self._animation.setEndValue(15)
        self._animation.start()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._animation.stop()
        self._animation.setStartValue(self._glow.blurRadius())
        self._animation.setEndValue(0)
        self._animation.start()
        super().leaveEvent(event)


class ConversationMessagesDialog(QDialog):
    def __init__(self, chat, parent=None):
        super().__init__(parent)
        self.chat = json.loads(json.dumps(chat, ensure_ascii=False))
        self.setWindowTitle("Modifier les messages")
        self.resize(760, 560)
        layout = QVBoxLayout(self)
        self.messages_list = QListWidget()
        self.messages_list.currentRowChanged.connect(self._select_message)
        layout.addWidget(self.messages_list, stretch=1)

        form = QFormLayout()
        self.role_picker = QComboBox()
        self.role_picker.addItems(("user", "assistant", "system", "tool"))
        self.content_editor = QPlainTextEdit()
        self.content_editor.setPlaceholderText("Contenu du message")
        form.addRow("Rôle", self.role_picker)
        form.addRow("Contenu", self.content_editor)
        layout.addLayout(form)

        actions = QHBoxLayout()
        self.add_button = QPushButton("Ajouter un message")
        self.save_message_button = QPushButton("Enregistrer le message")
        self.delete_message_button = QPushButton("Supprimer le message")
        actions.addWidget(self.add_button)
        actions.addWidget(self.save_message_button)
        actions.addWidget(self.delete_message_button)
        layout.addLayout(actions)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.add_button.clicked.connect(self._add_message)
        self.save_message_button.clicked.connect(self._save_message)
        self.delete_message_button.clicked.connect(self._delete_message)
        self._refresh_messages()

    def _refresh_messages(self, select_row=0):
        self.messages_list.clear()
        for message in self.chat.get("messages", []):
            preview = " ".join(str(message.get("content", "")).split())[:100]
            self.messages_list.addItem(f"{message.get('role', 'user')} · {preview}")
        if self.messages_list.count():
            self.messages_list.setCurrentRow(min(max(select_row, 0), self.messages_list.count() - 1))
        else:
            self.content_editor.clear()
            self.save_message_button.setEnabled(False)
            self.delete_message_button.setEnabled(False)

    def _select_message(self, row):
        messages = self.chat.get("messages", [])
        if not 0 <= row < len(messages):
            return
        message = messages[row]
        role_index = self.role_picker.findText(str(message.get("role", "user")))
        self.role_picker.setCurrentIndex(max(role_index, 0))
        self.content_editor.setPlainText(str(message.get("content", "")))
        self.save_message_button.setEnabled(True)
        self.delete_message_button.setEnabled(True)

    def _add_message(self):
        messages = self.chat.setdefault("messages", [])
        messages.append({"role": "user", "content": ""})
        self._refresh_messages(len(messages) - 1)
        self.content_editor.setFocus()

    def _save_message(self):
        row = self.messages_list.currentRow()
        messages = self.chat.get("messages", [])
        if not 0 <= row < len(messages):
            return
        messages[row]["role"] = self.role_picker.currentText()
        messages[row]["content"] = self.content_editor.toPlainText()
        self._refresh_messages(row)

    def _delete_message(self):
        row = self.messages_list.currentRow()
        messages = self.chat.get("messages", [])
        if not 0 <= row < len(messages):
            return
        answer = QMessageBox.question(
            self,
            "Supprimer le message",
            "Supprimer définitivement ce message de la conversation ?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        del messages[row]
        self._refresh_messages(max(0, row - 1))


class ConversationManagerDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Gestion des conversations")
        self.resize(920, 610)
        layout = QVBoxLayout(self)

        filters = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Rechercher par nom, catégorie ou message…")
        self.category_filter = QComboBox()
        filters.addWidget(self.search_input, stretch=1)
        filters.addWidget(self.category_filter)
        layout.addLayout(filters)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(("Conversation", "Catégorie", "Messages", "Modifiée"))
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.verticalHeader().hide()
        self.table.doubleClicked.connect(self._open_selected)
        layout.addWidget(self.table, stretch=1)

        actions = QHBoxLayout()
        self.open_button = QPushButton("Ouvrir")
        self.rename_button = QPushButton("Renommer")
        self.edit_button = QPushButton("Modifier")
        self.category_button = QPushButton("Classer")
        self.copy_button = QPushButton("Copier")
        self.export_button = QPushButton("Exporter")
        self.import_button = QPushButton("Importer")
        self.delete_button = QPushButton("Supprimer")
        for button in (
            self.open_button,
            self.rename_button,
            self.edit_button,
            self.category_button,
            self.copy_button,
            self.export_button,
            self.import_button,
            self.delete_button,
        ):
            actions.addWidget(button)
        layout.addLayout(actions)

        close_buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close_buttons.rejected.connect(self.reject)
        close_buttons.button(QDialogButtonBox.StandardButton.Close).clicked.connect(self.accept)
        layout.addWidget(close_buttons)

        self.search_input.textChanged.connect(self._refresh)
        self.category_filter.currentTextChanged.connect(self._refresh)
        self.open_button.clicked.connect(self._open_selected)
        self.rename_button.clicked.connect(self._rename_selected)
        self.edit_button.clicked.connect(self._edit_selected)
        self.category_button.clicked.connect(self._classify_selected)
        self.copy_button.clicked.connect(self._copy_selected)
        self.export_button.clicked.connect(self._export_selected)
        self.import_button.clicked.connect(self._import_conversation)
        self.delete_button.clicked.connect(self._delete_selected)
        self._refresh()

    def _refresh(self, *_args, selected_id=None):
        chats = conversation_store.list_chats()
        category = self.category_filter.currentText() if self.category_filter.count() else "Toutes les catégories"
        categories = sorted({chat.get("category", "").strip() for chat in chats if chat.get("category", "").strip()}, key=str.casefold)
        self.category_filter.blockSignals(True)
        self.category_filter.clear()
        self.category_filter.addItem("Toutes les catégories")
        self.category_filter.addItems(categories)
        self.category_filter.setCurrentText(category if category in {"Toutes les catégories", *categories} else "Toutes les catégories")
        self.category_filter.blockSignals(False)

        query = self.search_input.text().strip().casefold()
        selected_row = -1
        self.table.setRowCount(0)
        for chat in chats:
            title = self._display_title(chat)
            chat_category = str(chat.get("category") or "")
            if self.category_filter.currentText() != "Toutes les catégories" and chat_category != self.category_filter.currentText():
                continue
            searchable = " ".join(
                [title, chat_category, *(str(item.get("content", "")) for item in chat.get("messages", []))]
            ).casefold()
            if query and query not in searchable:
                continue
            row = self.table.rowCount()
            self.table.insertRow(row)
            title_item = QTableWidgetItem(title)
            title_item.setData(Qt.ItemDataRole.UserRole, int(chat["id"]))
            self.table.setItem(row, 0, title_item)
            self.table.setItem(row, 1, QTableWidgetItem(chat_category or "—"))
            self.table.setItem(row, 2, QTableWidgetItem(str(len(chat.get("messages", [])))))
            self.table.setItem(row, 3, QTableWidgetItem(str(chat.get("updated_at") or "")))
            if selected_id is not None and chat["id"] == selected_id:
                selected_row = row
        if self.table.rowCount():
            self.table.selectRow(selected_row if selected_row >= 0 else 0)

    @staticmethod
    def _display_title(chat):
        return str(chat.get("custom_title") or chat.get("topic") or chat.get("title") or f"Conversation #{chat['id']}")

    def _selected_id(self):
        row = self.table.currentRow()
        item = self.table.item(row, 0) if row >= 0 else None
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _selected_chat(self):
        chat_id = self._selected_id()
        return conversation_store.load_chat(chat_id) if chat_id is not None else None

    def _sync_parent(self, chat_id):
        parent = self.parent()
        if not parent or parent.chat.get("id") != chat_id:
            return
        parent.chat = conversation_store.load_chat(chat_id)
        if parent.chat is not None:
            parent.agent.prepare_chat(parent.chat)
            parent._load_chat_into_view()
            parent._refresh_chat_list()

    def _open_selected(self, *_args):
        chat_id = self._selected_id()
        if chat_id is None:
            return
        self.parent()._open_conversation_id(chat_id)
        self.accept()

    def _rename_selected(self):
        chat = self._selected_chat()
        if chat is None:
            return
        title, accepted = QInputDialog.getText(
            self, "Renommer la conversation", "Nouveau nom", text=self._display_title(chat)
        )
        if not accepted:
            return
        try:
            conversation_store.rename_chat(chat["id"], title)
        except (OSError, ValueError) as error:
            QMessageBox.warning(self, "Renommage impossible", str(error))
            return
        self._sync_parent(chat["id"])
        self._refresh(selected_id=chat["id"])

    def _classify_selected(self):
        chat = self._selected_chat()
        if chat is None:
            return
        category, accepted = QInputDialog.getText(
            self,
            "Classer la conversation",
            "Catégorie (laisser vide pour retirer)",
            text=str(chat.get("category") or ""),
        )
        if not accepted:
            return
        try:
            conversation_store.set_chat_category(chat["id"], category)
        except (OSError, ValueError) as error:
            QMessageBox.warning(self, "Classement impossible", str(error))
            return
        self._sync_parent(chat["id"])
        self._refresh(selected_id=chat["id"])

    def _edit_selected(self):
        chat = self._selected_chat()
        if chat is None:
            return
        dialog = ConversationMessagesDialog(chat, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            conversation_store.save_chat(dialog.chat, async_mode=False)
        except OSError as error:
            QMessageBox.warning(self, "Modification impossible", str(error))
            return
        self._sync_parent(chat["id"])
        self._refresh(selected_id=chat["id"])

    def _copy_selected(self):
        chat_id = self._selected_id()
        if chat_id is None:
            return
        try:
            duplicate = conversation_store.copy_chat(chat_id)
        except (OSError, ValueError) as error:
            QMessageBox.warning(self, "Copie impossible", str(error))
            return
        self._refresh(selected_id=duplicate["id"])

    def _export_selected(self):
        chat = self._selected_chat()
        if chat is None:
            return
        suggested_name = f"conversation-{chat['id']}.json"
        destination, _selected_filter = QFileDialog.getSaveFileName(
            self, "Exporter la conversation", suggested_name, "Conversations JSON (*.json)"
        )
        if not destination:
            return
        try:
            conversation_store.export_chat(chat["id"], destination)
        except (OSError, ValueError) as error:
            QMessageBox.warning(self, "Export impossible", str(error))
            return
        QMessageBox.information(self, "Export terminé", "La conversation a été exportée.")

    def _import_conversation(self):
        source, _selected_filter = QFileDialog.getOpenFileName(
            self, "Importer une conversation", "", "Conversations JSON (*.json)"
        )
        if not source:
            return
        try:
            chat = conversation_store.import_chat(source)
        except (OSError, ValueError) as error:
            QMessageBox.warning(self, "Import impossible", str(error))
            return
        self._refresh(selected_id=chat["id"])

    def _delete_selected(self):
        chat_id = self._selected_id()
        if chat_id is None:
            return
        answer = QMessageBox.question(
            self,
            "Supprimer la conversation",
            "Supprimer définitivement cette conversation et tous ses messages ?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        if not conversation_store.delete_chat(chat_id):
            QMessageBox.warning(self, "Suppression impossible", "Cette conversation est introuvable.")
            self._refresh()
            return
        parent = self.parent()
        parent_chat = getattr(parent, "chat", None)
        new_chat = getattr(parent, "_new_chat", None)
        if isinstance(parent_chat, dict) and parent_chat.get("id") == chat_id and callable(new_chat):
            new_chat()
        self._refresh()


class CodeProjectManagerDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Gestion des projets de code")
        self.resize(700, 480)
        layout = QVBoxLayout(self)

        filters = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Rechercher par nom ou catégorie…")
        self.category_filter = QComboBox()
        filters.addWidget(self.search_input, stretch=1)
        filters.addWidget(self.category_filter)
        layout.addLayout(filters)

        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(("Projet", "Catégorie"))
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.verticalHeader().hide()
        self.table.doubleClicked.connect(self._open_selected)
        layout.addWidget(self.table, stretch=1)

        actions = QHBoxLayout()
        self.create_button = QPushButton("Nouveau")
        self.open_button = QPushButton("Ouvrir")
        self.category_button = QPushButton("Classer")
        self.export_button = QPushButton("Exporter")
        self.import_button = QPushButton("Importer")
        self.delete_button = QPushButton("Supprimer")
        actions.addWidget(self.create_button)
        actions.addWidget(self.open_button)
        actions.addWidget(self.category_button)
        actions.addWidget(self.export_button)
        actions.addWidget(self.import_button)
        actions.addWidget(self.delete_button)
        layout.addLayout(actions)

        close_buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close_buttons.rejected.connect(self.reject)
        close_buttons.button(QDialogButtonBox.StandardButton.Close).clicked.connect(self.accept)
        layout.addWidget(close_buttons)

        self.search_input.textChanged.connect(self._refresh)
        self.category_filter.currentTextChanged.connect(self._refresh)
        self.create_button.clicked.connect(self._create_project)
        self.open_button.clicked.connect(self._open_selected)
        self.category_button.clicked.connect(self._classify_selected)
        self.export_button.clicked.connect(self._export_selected)
        self.import_button.clicked.connect(self._import_project)
        self.delete_button.clicked.connect(self._delete_selected)
        self._refresh()

    def _refresh(self, *_args, selected_path=None):
        projects = code_projects.list_projects()
        project_categories = [(project, code_projects.get_project_category(project)) for project in projects]
        category = self.category_filter.currentText() if self.category_filter.count() else "Toutes les catégories"
        categories = sorted({value for _project, value in project_categories if value}, key=str.casefold)
        self.category_filter.blockSignals(True)
        self.category_filter.clear()
        self.category_filter.addItem("Toutes les catégories")
        self.category_filter.addItems(categories)
        self.category_filter.setCurrentText(
            category if category in {"Toutes les catégories", *categories} else "Toutes les catégories"
        )
        self.category_filter.blockSignals(False)

        query = self.search_input.text().strip().casefold()
        selected_row = -1
        self.table.setRowCount(0)
        for project, project_category in project_categories:
            if self.category_filter.currentText() != "Toutes les catégories" and project_category != self.category_filter.currentText():
                continue
            if query and query not in f"{project.name} {project_category}".casefold():
                continue
            row = self.table.rowCount()
            self.table.insertRow(row)
            project_item = QTableWidgetItem(project.name)
            project_item.setData(Qt.ItemDataRole.UserRole, str(project))
            self.table.setItem(row, 0, project_item)
            self.table.setItem(row, 1, QTableWidgetItem(project_category or "—"))
            if selected_path is not None and str(project) == selected_path:
                selected_row = row
        if self.table.rowCount():
            self.table.selectRow(selected_row if selected_row >= 0 else 0)

    def _selected_project(self):
        row = self.table.currentRow()
        item = self.table.item(row, 0) if row >= 0 else None
        path = item.data(Qt.ItemDataRole.UserRole) if item else None
        return Path(path) if path else None

    def _classify_selected(self):
        project = self._selected_project()
        if project is None:
            return
        category, accepted = QInputDialog.getText(
            self,
            "Classer le projet",
            "Catégorie (laisser vide pour retirer)",
            text=code_projects.get_project_category(project),
        )
        if not accepted:
            return
        try:
            code_projects.set_project_category(project, category)
        except (OSError, ValueError) as error:
            QMessageBox.warning(self, "Classement impossible", str(error))
            return
        self._refresh(selected_path=str(project))

    def _open_selected(self, *_args):
        project = self._selected_project()
        parent = self.parent()
        activate_project = getattr(parent, "_activate_code_project", None)
        if project is None or not callable(activate_project):
            return
        activate_project(project)
        self.accept()

    def _create_project(self):
        name, accepted = QInputDialog.getText(self, "Nouveau projet", "Nom du projet")
        if not accepted or not name.strip():
            return
        try:
            project = code_projects.create_or_open_project(name)
        except (OSError, ValueError) as error:
            QMessageBox.warning(self, "Création impossible", str(error))
            return
        self._refresh(selected_path=str(project))

    def _export_selected(self):
        project = self._selected_project()
        if project is None:
            return
        destination, _selected_filter = QFileDialog.getSaveFileName(
            self, "Exporter le projet", f"{project.name}.zip", "Archives ZIP (*.zip)"
        )
        if not destination:
            return
        try:
            code_projects.export_project(project, destination)
        except (OSError, ValueError) as error:
            QMessageBox.warning(self, "Export impossible", str(error))
            return
        QMessageBox.information(self, "Export terminé", "Le projet a été exporté.")

    def _import_project(self):
        source, _selected_filter = QFileDialog.getOpenFileName(
            self, "Importer un projet", "", "Archives ZIP (*.zip)"
        )
        if not source:
            return
        try:
            project = code_projects.import_project(source)
        except (OSError, ValueError, RuntimeError) as error:
            QMessageBox.warning(self, "Import impossible", str(error))
            return
        self._refresh(selected_path=str(project))

    def _delete_selected(self):
        project = self._selected_project()
        if project is None:
            return
        answer = QMessageBox.question(
            self,
            "Supprimer le projet",
            f"Supprimer définitivement le projet « {project.name} » et tous ses fichiers ?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            code_projects.delete_project(project)
        except (OSError, ValueError) as error:
            QMessageBox.warning(self, "Suppression impossible", str(error))
            return
        parent = self.parent()
        forget_project = getattr(parent, "_forget_deleted_code_project", None)
        if callable(forget_project):
            forget_project(project)
        self._refresh()


class ToolManagerDialog(QDialog):
    def __init__(self, parent, settings, project=None):
        super().__init__(parent)
        self.settings = settings
        self.project = Path(project).resolve() if project else None
        self.setWindowTitle("Gestion des outils")
        self.resize(820, 620)
        layout = QVBoxLayout(self)
        self.scope = QComboBox()
        self.scope.addItem("Tous les chats", "global")
        if self.project:
            self.scope.addItem(f"Projet : {self.project.name}", "project")
        layout.addWidget(self.scope)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(("Actif", "Outil", "Description"))
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.verticalHeader().hide()
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.checkboxes = {}
        for row, name in enumerate(sorted(ToolManager.ALL_TOOLS)):
            self.table.insertRow(row)
            checkbox = QCheckBox()
            checkbox.setToolTip(f"Autoriser l'outil {name}")
            self.checkboxes[name] = checkbox
            self.table.setCellWidget(row, 0, checkbox)
            self.table.setItem(row, 1, QTableWidgetItem(name))
            self.table.setItem(row, 2, QTableWidgetItem(ToolManager.TOOL_DESCRIPTIONS.get(name, "Description manquante")))
        self.table.resizeColumnsToContents()
        layout.addWidget(self.table, stretch=1)

        actions = QHBoxLayout()
        self.test_button = QPushButton("Tester le registre")
        self.test_button.clicked.connect(self._test_registry)
        actions.addWidget(self.test_button)
        actions.addStretch(1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        actions.addWidget(buttons)
        layout.addLayout(actions)

        self.scope.currentIndexChanged.connect(self._load_scope)
        self._load_scope()

    def _global_disabled(self):
        try:
            configured = json.loads(str(self.settings.value("tools/disabled", "[]")))
        except (TypeError, json.JSONDecodeError):
            configured = []
        if not isinstance(configured, list):
            return set()
        return {name for name in configured if isinstance(name, str)} & set(ToolManager.ALL_TOOLS)

    def _load_scope(self, *_args):
        global_disabled = self._global_disabled()
        project_disabled = (
            code_projects.get_project_disabled_tools(self.project)
            if self.scope.currentData() == "project" and self.project
            else set()
        )
        for name, checkbox in self.checkboxes.items():
            checkbox.setChecked(name not in global_disabled and name not in project_disabled)
            checkbox.setEnabled(self.scope.currentData() != "project" or name not in global_disabled)

    def _test_registry(self):
        missing_descriptions = ToolManager.ALL_TOOLS - set(ToolManager.TOOL_DESCRIPTIONS)
        if missing_descriptions:
            QMessageBox.warning(
                self,
                "Registre incomplet",
                "Descriptions manquantes : " + ", ".join(sorted(missing_descriptions)),
            )
            return
        enabled = {name for name, checkbox in self.checkboxes.items() if checkbox.isChecked()}
        prompt = ToolManager.build_prompt(enabled)
        if enabled and not prompt:
            QMessageBox.warning(self, "Test échoué", "La liste active n'a pas pu être compilée.")
            return
        QMessageBox.information(
            self,
            "Registre valide",
            f"{len(ToolManager.ALL_TOOLS)} outils enregistrés; {len(enabled)} autorisés dans cette portée. Aucun outil n'a été exécuté.",
        )

    def _save(self):
        selected = {name for name, checkbox in self.checkboxes.items() if checkbox.isChecked()}
        if self.scope.currentData() == "project" and self.project:
            project_disabled = (set(ToolManager.ALL_TOOLS) - self._global_disabled()) - selected
            code_projects.set_project_disabled_tools(self.project, project_disabled)
        else:
            disabled = set(ToolManager.ALL_TOOLS) - selected
            self.settings.setValue("tools/disabled", json.dumps(sorted(disabled)))
            self.settings.sync()
        self.accept()


class ApiKeyManagerDialog(QDialog):
    def __init__(self, username, records, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Gestion des clés API")
        self.setMinimumSize(620, 370)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"Compte local : {username}"))

        self.table = QTableWidget(0, 2, self)
        self.table.setHorizontalHeaderLabels(("Clé API · début et fin", "État"))
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.verticalHeader().hide()
        layout.addWidget(self.table, stretch=1)

        actions = QHBoxLayout()
        self.usage_button = QPushButton("Voir l’usage")
        self.add_button = QPushButton("Ajouter une clé")
        self.create_button = QPushButton("Créer via OpenRouter")
        self.toggle_button = QPushButton("Désactiver")
        self.remove_button = QPushButton("Supprimer")
        self.close_button = QPushButton("Fermer")
        for button in (
            self.usage_button,
            self.add_button,
            self.create_button,
            self.toggle_button,
            self.remove_button,
            self.close_button,
        ):
            actions.addWidget(button)
        layout.addLayout(actions)
        self.table.currentCellChanged.connect(self._update_toggle_button)
        self.close_button.clicked.connect(self.accept)
        self.set_records(records)

    @staticmethod
    def _preview(key):
        if len(key) <= 12:
            return f"{key[:2]}…{key[-2:]}"
        return f"{key[:8]}…{key[-4:]}"

    def set_records(self, records):
        selected_row = self.table.currentRow()
        self.records = records
        self.table.setRowCount(len(records))
        for row, record in enumerate(records):
            self.table.setItem(row, 0, QTableWidgetItem(self._preview(record["key"])))
            self.table.setItem(
                row,
                1,
                QTableWidgetItem("Activée" if record["enabled"] else "Désactivée"),
            )
        if records:
            self.table.selectRow(min(max(0, selected_row), len(records) - 1))
        self._update_toggle_button()

    def selected_record(self):
        row = self.table.currentRow()
        return self.records[row] if 0 <= row < len(self.records) else None

    def _update_toggle_button(self, *_):
        record = self.selected_record() if hasattr(self, "records") else None
        self.toggle_button.setText("Désactiver" if record and record["enabled"] else "Activer")
        self.usage_button.setEnabled(record is not None)
        self.toggle_button.setEnabled(record is not None)
        self.remove_button.setEnabled(record is not None)


class AgentTask(QThread):
    completed = Signal(bool, str)
    progress = Signal(str)
    downloads_ready = Signal(object)

    def __init__(
        self,
        agent,
        chat,
        request,
        *,
        code_mode=False,
        project=None,
        command_enabled=False,
        proposal=None,
        approved_tool_call=None,
        external_info=None,
        allowed_tools=None,
        file_edit_content=None,
        file_path=None,
    ):
        super().__init__()
        self.agent = agent
        self.chat = chat
        self.request = request
        self.code_mode = code_mode
        self.project = project
        self.command_enabled = command_enabled
        self.proposal = proposal
        self.approved_tool_call = approved_tool_call
        self.external_info = external_info
        self.allowed_tools = allowed_tools
        self.file_edit_content = file_edit_content
        self.file_path = file_path

    def run(self):
        try:
            if self.approved_tool_call is not None:
                answer = self.agent.apply_approved_file_call(
                    self.approved_tool_call,
                    self.chat,
                    allowed_tools=self._write_tools(),
                )
                self.completed.emit(True, str(answer or "").strip())
                return
            if not openrouter_api_keys():
                raise RuntimeError("Connecte-toi à un compte OpenRouter pour utiliser l'IA dans le GUI.")
            if self.file_edit_content is not None:
                external_info = (
                    "MODE FICHIER UNIQUE : tu aides à modifier uniquement le fichier sélectionné, hors du mode Code.\n"
                    f"Fichier : {self.file_path}\n"
                    "Retourne le fichier complet modifié entre ces marqueurs exacts, sans bloc Markdown ni explication hors marqueurs :\n"
                    "<<<KAIRO_FILE_CONTENT>>>\n"
                    "contenu complet du fichier\n"
                    "<<<END_KAIRO_FILE_CONTENT>>>\n"
                    "Le contenu actuel du fichier suit. Préserve tout ce qui n'est pas concerné par la demande.\n"
                    "--- CONTENU ACTUEL ---\n"
                    f"{self.file_edit_content}"
                )
                answer = self.agent.respond(
                    self.chat,
                    self.request,
                    external_info=external_info,
                    allowed_tools=set(),
                    stream=False,
                    progress_callback=self.progress.emit,
                )
            elif self.proposal is not None:
                from local_ia.cli.interface import _local_code_instructions

                instructions = _local_code_instructions(
                    self.project,
                    command_enabled=self.command_enabled,
                )
                instructions += "\nApplique uniquement la proposition approuvée, puis exécute les tests pertinents si la commande est autorisée."
                answer = self.agent.respond(
                    self.chat,
                    f"{self.request}\n\nProposition approuvée par l'utilisateur :\n{self.proposal}",
                    external_info=instructions,
                    allowed_tools=self._write_tools(),
                    local_code=True,
                    progress_callback=self.progress.emit,
                )
            elif self.code_mode:
                from local_ia.cli.interface import _local_code_proposal_instructions

                instructions = _local_code_proposal_instructions(self.project)
                if self.external_info:
                    instructions += "\n\n" + self.external_info
                allowed_tools = {"file", "list", "search", "write", "edit"}
                if self.allowed_tools is not None:
                    allowed_tools.intersection_update(self.allowed_tools)
                answer = self.agent.respond(
                    self.chat,
                    self.request,
                    external_info=instructions,
                    allowed_tools=allowed_tools,
                    local_code=True,
                    defer_file_actions=True,
                    progress_callback=self.progress.emit,
                )
            else:
                answer = self.agent.respond(
                    self.chat,
                    self.request,
                    external_info=self.external_info,
                    allowed_tools=self.allowed_tools,
                    stream=False,
                    progress_callback=self.progress.emit,
                )
            self.downloads_ready.emit(list(getattr(self.agent, "generated_downloads", [])))
            self.completed.emit(True, str(answer or "").strip())
        except Exception as error:
            self.downloads_ready.emit(list(getattr(self.agent, "generated_downloads", [])))
            self.completed.emit(False, f"{type(error).__name__}: {error}")

    def _write_tools(self):
        tools = set(LOCAL_CODE_TOOLS)
        if self.command_enabled:
            tools.add("command")
        if self.allowed_tools is not None:
            tools.intersection_update(self.allowed_tools)
        return tools


class OpenRouterKeyTask(QThread):
    completed = Signal(bool, str)
    progress = Signal(str)

    def run(self):
        try:
            self.progress.emit("Ouverture d'OpenRouter dans le navigateur…")
            api_key = authorize_openrouter()
            self.completed.emit(True, api_key)
        except Exception as error:
            self.completed.emit(False, str(error))


class GitUpdateTask(QThread):
    completed = Signal(bool, str)

    def __init__(self, target_version, parent=None):
        super().__init__(parent)
        self.target_version = target_version

    def run(self):
        try:
            result = updater.update_from_archive(BASE_DIR, self.target_version)
            message = (
                f"Version {result['version']} installée ({result['files_updated']} fichiers mis à jour).\n\n"
                "Redémarrez KAIRO pour charger les nouveaux fichiers."
            )
            self.completed.emit(True, message)
        except Exception as error:
            self.completed.emit(False, str(error))


class KairoWorkspace(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("KAIRO · Espace de travail")
        self.setMinimumSize(1080, 680)
        self.resize(1480, 900)
        self.config = load_config()
        self.ui_settings = QSettings("KAIRO", "LocalIA")
        self.connection = init_database()
        self.agent = self._new_agent()
        self.chat = create_chat()
        self.project_root = None
        self.single_file_mode = False
        self.current_file = None
        self.editor_project_root = None
        self._saved_hash = None
        self._loading_editor = False
        self._backed_up_files = set()
        self.code_armed = False
        self.worker = None
        self.oauth_task = None
        self.git_update_task = None
        self.git_update_button = None
        self.install_process = None
        self.python_process = None
        self._python_output = ""
        self._python_filename = ""
        self._install_output = ""
        self._install_prompt_buffer = ""
        self.code_mode_active = False
        self.save_timer = QTimer(self)
        self.save_timer.setSingleShot(True)
        self.save_timer.setInterval(700)
        self.save_timer.timeout.connect(self._save_open_file)
        self._build_ui()
        self._apply_mode(False)
        self._apply_style()
        self._refresh_chat_list()
        self._load_chat_into_view()
        self._populate_model_picker()
        self._restore_saved_session()
        self._set_connection_status()

    def _new_agent(self):
        config = load_config()
        model = openrouter_model(config) if openrouter_api_keys() else model_config(config)
        agent = LocalAgent(model=model)
        return agent

    def _build_ui(self):
        root = QWidget()
        root.setObjectName("root")
        root_layout = QHBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        sidebar = QWidget()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(244)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(18, 22, 16, 18)
        side.setSpacing(9)

        brand = QLabel("◈  KAIRO")
        brand.setObjectName("brand")
        side.addWidget(brand)
        tagline = QLabel("ESPACE API · BÊTA 10")
        tagline.setObjectName("tagline")
        side.addWidget(tagline)
        side.addSpacing(20)

        self.notifications_button = ActionButton("♧   Gérer les notifications")
        self.notifications_button.clicked.connect(self._open_notification_settings)
        side.addWidget(self.notifications_button)

        self.conversation_section = QWidget(sidebar)
        conversation_layout = QVBoxLayout(self.conversation_section)
        conversation_layout.setContentsMargins(0, 0, 0, 0)
        conversation_layout.setSpacing(9)
        self.new_chat_button = ActionButton("＋   Nouveau chat")
        self.new_chat_button.clicked.connect(self._new_chat)
        conversation_layout.addWidget(self.new_chat_button)
        self.manage_conversations_button = ActionButton("☷   Gérer les conversations")
        self.manage_conversations_button.clicked.connect(self._manage_conversations)
        conversation_layout.addWidget(self.manage_conversations_button)
        self.chat_search = QLineEdit()
        self.chat_search.setPlaceholderText("Rechercher une conversation")
        self.chat_search.textChanged.connect(self._refresh_chat_list)
        conversation_layout.addWidget(self.chat_search)
        chat_heading = QLabel("CONVERSATIONS")
        chat_heading.setObjectName("sectionLabel")
        conversation_layout.addWidget(chat_heading)
        self.chat_list = QListWidget()
        self.chat_list.setObjectName("chatList")
        self.chat_list.itemActivated.connect(self._open_chat_item)
        self.chat_list.itemClicked.connect(self._open_chat_item)
        conversation_layout.addWidget(self.chat_list, stretch=1)
        side.addWidget(self.conversation_section, stretch=1)

        self.files_section = QWidget(sidebar)
        files_layout = QVBoxLayout(self.files_section)
        files_layout.setContentsMargins(0, 0, 0, 0)
        files_layout.setSpacing(8)
        files_heading = QLabel("EXPLORATEUR DE PROJET")
        files_heading.setObjectName("sectionLabel")
        files_layout.addWidget(files_heading)
        self.files_hint = QLabel("Active Mode Code pour choisir ou créer un projet.")
        self.files_hint.setObjectName("mutedText")
        self.files_hint.setWordWrap(True)
        files_layout.addWidget(self.files_hint)
        file_actions = QHBoxLayout()
        self.create_entry_button = QPushButton("＋")
        self.create_entry_button.setToolTip("Créer un fichier ou un dossier")
        self.create_entry_button.clicked.connect(self._create_project_entry)
        self.rename_entry_button = QPushButton("Renommer")
        self.rename_entry_button.clicked.connect(self._rename_project_entry)
        self.delete_entry_button = QPushButton("Supprimer")
        self.delete_entry_button.clicked.connect(self._delete_project_entry)
        file_actions.addWidget(self.create_entry_button)
        file_actions.addWidget(self.rename_entry_button)
        file_actions.addWidget(self.delete_entry_button)
        files_layout.addLayout(file_actions)
        self.file_model = QFileSystemModel(self)
        self.file_model.setRootPath("")
        self.file_tree = QTreeView()
        self.file_tree.setObjectName("fileTree")
        self.file_tree.setModel(self.file_model)
        self.file_tree.setRootIndex(self.file_model.index(""))
        self.file_tree.setHeaderHidden(True)
        for column in range(1, 4):
            self.file_tree.hideColumn(column)
        self.file_tree.doubleClicked.connect(self._preview_file)
        self.file_tree.setMinimumHeight(165)
        files_layout.addWidget(self.file_tree, stretch=1)
        side.addWidget(self.files_section, stretch=1)

        self.manage_keys_button = ActionButton("⚿   Gérer les clés API", parent=self)
        self.manage_keys_button.clicked.connect(self._manage_api_keys)
        self.manage_keys_button.hide()
        self.manage_code_projects_button = ActionButton("▦   Gérer les projets de code", parent=self)
        self.manage_code_projects_button.clicked.connect(self._manage_code_projects)
        self.manage_code_projects_button.hide()
        self.open_file_button = ActionButton("▤   Ouvrir un fichier", parent=self)
        self.open_file_button.clicked.connect(self._open_single_file)
        self.open_file_button.hide()
        self.terminal_button = ActionButton("▣   Ouvrir le terminal", parent=self)
        self.terminal_button.clicked.connect(self._open_terminal)
        self.terminal_button.hide()
        self.install_button = ActionButton("↓   Installer une application", parent=self)
        self.install_button.clicked.connect(self._install_catalog_application)
        self.install_button.hide()
        self.settings_button = ActionButton("⚙   Paramètres")
        self.settings_button.clicked.connect(self._open_settings)
        side.addStretch(1)
        side.addWidget(self.settings_button)
        root_layout.addWidget(sidebar)

        main = QWidget()
        main.setObjectName("mainPanel")
        main_layout = QVBoxLayout(main)
        main_layout.setContentsMargins(25, 20, 25, 20)
        main_layout.setSpacing(14)
        header = QHBoxLayout()
        titles = QVBoxLayout()
        self.chat_title = QLabel("Nouvelle conversation")
        self.chat_title.setObjectName("pageTitle")
        self.page_subtitle = QLabel("Les conversations et réglages sont partagés avec l'invite de commande.")
        self.page_subtitle.setObjectName("subtitle")
        titles.addWidget(self.chat_title)
        titles.addWidget(self.page_subtitle)
        header.addLayout(titles)
        header.addStretch(1)
        self.model_picker = QComboBox()
        self.model_picker.setObjectName("modelPicker")
        self.model_picker.setToolTip("Modèle OpenRouter utilisé par le GUI et enregistré dans config.json")
        self.model_picker.activated.connect(self._model_choice)
        header.addWidget(self.model_picker, alignment=Qt.AlignmentFlag.AlignVCenter)
        self.profile_avatar = QLabel()
        self.profile_avatar.setObjectName("profileAvatar")
        self.profile_avatar.setFixedSize(38, 38)
        self.profile_avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.profile_avatar.hide()
        header.addWidget(self.profile_avatar, alignment=Qt.AlignmentFlag.AlignVCenter)
        self.status = QLabel("●  Connexion OpenRouter requise")
        self.status.setObjectName("status")
        header.addWidget(self.status, alignment=Qt.AlignmentFlag.AlignVCenter)
        self.connect_button = ActionButton("Se connecter", "connectButton")
        self.connect_button.clicked.connect(self._connect_account)
        header.addWidget(self.connect_button, alignment=Qt.AlignmentFlag.AlignVCenter)
        main_layout.addLayout(header)

        self.workspace_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.workspace_splitter.setObjectName("workspaceSplitter")
        self.chat_panel = QWidget()
        self.chat_panel.setObjectName("chatPanel")
        chat_layout = QVBoxLayout(self.chat_panel)
        chat_layout.setContentsMargins(0, 0, 8, 0)
        chat_layout.setSpacing(12)

        self.transcript = QPlainTextEdit()
        self.transcript.setObjectName("transcript")
        self.transcript.setReadOnly(True)
        self.transcript.setFont(QFont("Noto Sans", 11))
        self.transcript.setPlaceholderText("Pose une question ou choisis une action à gauche.")
        chat_layout.addWidget(self.transcript, stretch=1)
        self.downloads_panel = QWidget()
        downloads_layout = QHBoxLayout(self.downloads_panel)
        downloads_layout.setContentsMargins(0, 0, 0, 0)
        downloads_layout.addWidget(QLabel("Fichiers prêts"))
        self.download_buttons_host = QWidget()
        self.download_buttons_layout = QHBoxLayout(self.download_buttons_host)
        self.download_buttons_layout.setContentsMargins(0, 0, 0, 0)
        self.download_buttons_layout.addStretch(1)
        downloads_layout.addWidget(self.download_buttons_host, stretch=1)
        self.downloads_panel.hide()
        chat_layout.addWidget(self.downloads_panel)
        self.notice = QLabel("Prêt")
        self.notice.setObjectName("notice")
        chat_layout.addWidget(self.notice)
        composer = QHBoxLayout()
        composer.setSpacing(10)
        self.prompt = QLineEdit()
        self.prompt.setObjectName("composer")
        self.prompt.setPlaceholderText("Écris une demande, /help, /commande …")
        self.prompt.returnPressed.connect(self._send_message)
        self.send_button = ActionButton("Envoyer  ↵", "sendButton")
        self.send_button.clicked.connect(self._send_message)
        composer.addWidget(self.prompt, stretch=1)
        composer.addWidget(self.send_button)
        chat_layout.addLayout(composer)
        self.workspace_splitter.addWidget(self.chat_panel)

        self.editor_panel = QWidget()
        self.editor_panel.setObjectName("editorPanel")
        editor_layout = QVBoxLayout(self.editor_panel)
        editor_layout.setContentsMargins(8, 0, 0, 0)
        editor_layout.setSpacing(10)
        editor_header = QHBoxLayout()
        self.editor_file_label = QLabel("Aperçu du code")
        self.editor_file_label.setObjectName("editorFileLabel")
        editor_header.addWidget(self.editor_file_label, stretch=1)
        self.save_button = ActionButton("Enregistrer", "saveButton")
        self.save_button.clicked.connect(self._save_open_file)
        editor_header.addWidget(self.save_button)
        self.run_python_button = ActionButton("▶   Lancer Python", "saveButton")
        self.run_python_button.setEnabled(False)
        self.run_python_button.setToolTip("Exécuter le fichier Python ouvert dans le projet actif")
        self.run_python_button.clicked.connect(self._run_current_python_file)
        editor_header.addWidget(self.run_python_button)
        self.ai_file_button = ActionButton("Proposer avec l'IA", "saveButton")
        self.ai_file_button.setEnabled(False)
        self.ai_file_button.clicked.connect(self._request_single_file_edit)
        editor_header.addWidget(self.ai_file_button)
        editor_layout.addLayout(editor_header)
        self.code_editor = QPlainTextEdit()
        self.code_editor.setObjectName("codeEditor")
        self.code_editor.setFont(QFont("Noto Sans Mono", 10))
        self.code_editor.setPlaceholderText("Double-clique un fichier du projet pour le lire et le modifier ici.")
        self.code_editor.textChanged.connect(self._editor_changed)
        self.code_editor.textChanged.connect(self._update_preview)
        self.highlighter = CodeHighlighter(self.code_editor.document())
        self.save_shortcut = QShortcut(QKeySequence.StandardKey.Save, self.code_editor)
        self.save_shortcut.activated.connect(self._save_open_file)
        self.editor_tabs = QTabWidget()
        self.editor_tabs.addTab(self.code_editor, "Code")
        self.preview_browser = QTextBrowser()
        self.preview_browser.setObjectName("filePreview")
        self.preview_browser.setOpenExternalLinks(False)
        self.preview_browser.setOpenLinks(False)
        self.editor_tabs.addTab(self.preview_browser, "Aperçu")
        self.editor_tabs.setTabVisible(1, False)
        editor_layout.addWidget(self.editor_tabs, stretch=1)
        self.editor_status = QLabel("Aucun fichier ouvert")
        self.editor_status.setObjectName("editorStatus")
        editor_layout.addWidget(self.editor_status)
        self.workspace_splitter.addWidget(self.editor_panel)
        self.workspace_splitter.setStretchFactor(0, 3)
        self.workspace_splitter.setStretchFactor(1, 2)
        self.workspace_splitter.setSizes([690, 520])
        main_layout.addWidget(self.workspace_splitter, stretch=1)
        mode_footer = QHBoxLayout()
        mode_footer.addStretch(1)
        self.code_button = ActionButton("⌘   Mode Code")
        self.code_button.setCheckable(True)
        self.code_button.clicked.connect(self._toggle_code_mode)
        mode_footer.addWidget(self.code_button)
        main_layout.addLayout(mode_footer)
        root_layout.addWidget(main, stretch=1)
        self.page_stack = QStackedWidget()
        self.page_stack.addWidget(root)
        self._build_auth_page()
        self.setCentralWidget(self.page_stack)

    def _build_auth_page(self):
        page = QWidget()
        page.setObjectName("authPage")
        outer = QVBoxLayout(page)
        outer.setContentsMargins(44, 34, 44, 34)
        outer.addWidget(QLabel("◈  KAIRO"))
        outer.addStretch(1)

        panel = QWidget()
        panel.setObjectName("authPanel")
        panel.setMaximumWidth(560)
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(34, 30, 34, 30)
        panel_layout.setSpacing(16)
        panel_layout.addWidget(QLabel("Votre espace KAIRO"))
        panel_layout.addWidget(QLabel("Connectez-vous à votre compte local."))

        mode_row = QHBoxLayout()
        self.login_mode_button = QPushButton("Connexion")
        self.login_mode_button.setCheckable(True)
        self.login_mode_button.clicked.connect(lambda: self._set_auth_mode("login"))
        self.signup_mode_button = QPushButton("Créer un compte")
        self.signup_mode_button.setCheckable(True)
        self.signup_mode_button.clicked.connect(lambda: self._set_auth_mode("signup"))
        mode_row.addWidget(self.login_mode_button)
        mode_row.addWidget(self.signup_mode_button)
        panel_layout.addLayout(mode_row)

        self.auth_form_stack = QStackedWidget()
        login_page = QWidget()
        login_layout = QFormLayout(login_page)
        self.login_identifier = QLineEdit()
        self.login_identifier.setPlaceholderText("nom@exemple.fr ou nom de compte")
        self.login_password = QLineEdit()
        self.login_password.setEchoMode(QLineEdit.EchoMode.Password)
        self.login_password.setPlaceholderText("Mot de passe")
        login_layout.addRow("E-mail ou compte", self.login_identifier)
        login_layout.addRow("Mot de passe", self.login_password)
        self.login_error = QLabel("")
        self.login_error.setObjectName("authError")
        self.login_error.setWordWrap(True)
        login_layout.addRow(self.login_error)
        login_button = QPushButton("Se connecter")
        login_button.setObjectName("authPrimaryButton")
        login_button.clicked.connect(self._submit_login)
        login_layout.addRow(login_button)
        self.login_password.returnPressed.connect(self._submit_login)
        self.auth_form_stack.addWidget(login_page)

        signup_page = QWidget()
        signup_layout = QVBoxLayout(signup_page)
        signup_form = QFormLayout()
        self.signup_username = QLineEdit()
        self.signup_username.setPlaceholderText("Nom affiché dans KAIRO")
        self.signup_email = QLineEdit()
        self.signup_email.setPlaceholderText("vous@exemple.fr")
        self.signup_password = QLineEdit()
        self.signup_password.setEchoMode(QLineEdit.EchoMode.Password)
        self.signup_password.setPlaceholderText("8 caractères minimum")
        signup_form.addRow("Nom du compte", self.signup_username)
        signup_form.addRow("E-mail", self.signup_email)
        signup_form.addRow("Mot de passe", self.signup_password)
        signup_layout.addLayout(signup_form)

        avatar_row = QHBoxLayout()
        self.avatar_preview = QLabel("＋")
        self.avatar_preview.setObjectName("avatarPreview")
        self.avatar_preview.setFixedSize(72, 72)
        self.avatar_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.avatar_picker_button = QPushButton("Choisir une photo de profil")
        self.avatar_picker_button.clicked.connect(self._choose_profile_avatar)
        avatar_row.addWidget(self.avatar_preview)
        avatar_row.addWidget(self.avatar_picker_button)
        avatar_row.addStretch(1)
        signup_layout.addLayout(avatar_row)

        self.signup_api_key = QLineEdit()
        self.signup_api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.signup_api_key.setPlaceholderText("Clé API OpenRouter")
        signup_layout.addWidget(self.signup_api_key)
        authorize_button = QPushButton("Autoriser OpenRouter dans le navigateur")
        authorize_button.clicked.connect(
            lambda: self._start_openrouter_key_creation(self.signup_api_key.setText)
        )
        signup_layout.addWidget(authorize_button)
        self.signup_error = QLabel("")
        self.signup_error.setObjectName("authError")
        self.signup_error.setWordWrap(True)
        signup_layout.addWidget(self.signup_error)
        signup_button = QPushButton("Créer mon compte")
        signup_button.setObjectName("authPrimaryButton")
        signup_button.clicked.connect(self._submit_registration)
        signup_layout.addWidget(signup_button)
        self.auth_form_stack.addWidget(signup_page)
        panel_layout.addWidget(self.auth_form_stack)

        self.auth_back_button = QPushButton("Retour à l’espace de travail")
        self.auth_back_button.clicked.connect(lambda: self.page_stack.setCurrentIndex(0))
        panel_layout.addWidget(self.auth_back_button)
        outer.addWidget(panel, alignment=Qt.AlignmentFlag.AlignHCenter)
        outer.addStretch(1)
        self.auth_page = page
        self.page_stack.addWidget(page)
        self.auth_mode = "login"
        self._set_auth_mode("signup" if not accounts.list_accounts() else "login")

    def _set_auth_mode(self, mode):
        self.auth_mode = mode
        is_signup = mode == "signup"
        self.auth_form_stack.setCurrentIndex(1 if is_signup else 0)
        self.signup_mode_button.setChecked(is_signup)
        self.login_mode_button.setChecked(not is_signup)

    def _choose_profile_avatar(self):
        image_path, _filter = QFileDialog.getOpenFileName(
            self,
            "Choisir une photo de profil",
            "",
            "Images (*.png *.jpg *.jpeg *.webp *.bmp)",
        )
        if not image_path:
            return
        pixmap = QPixmap(image_path)
        if pixmap.isNull():
            self.signup_error.setText("Impossible de lire cette image.")
            return
        self._auth_avatar_source = image_path
        self.avatar_preview.setPixmap(
            pixmap.scaled(72, 72, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
        )
        self.avatar_preview.setText("")

    def _store_profile_avatar(self, username):
        source = getattr(self, "_auth_avatar_source", "")
        if not source:
            return ""
        source_path = Path(source)
        suffix = source_path.suffix.lower()
        if suffix not in {".png", ".jpg", ".jpeg", ".webp", ".bmp"}:
            suffix = ".png"
        avatar_dir = accounts.accounts_path().parent / "avatars"
        avatar_dir.mkdir(parents=True, exist_ok=True)
        name = hashlib.sha256(username.casefold().encode("utf-8")).hexdigest()
        destination = avatar_dir / f"{name}{suffix}"
        shutil.copy2(source_path, destination)
        return str(destination)

    def _submit_login(self):
        identifier = self.login_identifier.text().strip()
        password = self.login_password.text()
        try:
            profile = accounts.account_profile(identifier)
            api_keys = accounts.authenticate_api_keys(identifier, password)
        except (OSError, ValueError) as error:
            self.login_error.setText(str(error) if identifier and password else "Saisissez votre e-mail ou compte et votre mot de passe.")
            return
        self.login_error.clear()
        self._set_provider(profile["username"], api_keys, account_password=password)

    def _submit_registration(self):
        username = self.signup_username.text().strip()
        email = self.signup_email.text().strip()
        password = self.signup_password.text()
        api_key = self.signup_api_key.text().strip()
        if not all((username, email, password, api_key)):
            self.signup_error.setText("Complétez le nom, l’e-mail, le mot de passe et la clé OpenRouter.")
            return
        try:
            avatar = self._store_profile_avatar(username)
            accounts.create_account(username, password, api_key, email=email, avatar=avatar)
            api_keys = accounts.authenticate_api_keys(username, password)
        except (OSError, ValueError) as error:
            self.signup_error.setText(str(error))
            return
        self.signup_error.clear()
        self._set_provider(username, api_keys, account_password=password)

    def _apply_mode(self, code_mode):
        self.code_mode_active = bool(code_mode)
        self._update_python_run_button()
        self.code_button.blockSignals(True)
        self.code_button.setChecked(self.code_mode_active)
        self.code_button.setText("⌘   Mode Conversation" if self.code_mode_active else "⌘   Mode Code")
        self.code_button.blockSignals(False)
        self.conversation_section.setVisible(not self.code_mode_active)
        self.files_section.setVisible(self.code_mode_active)
        if self.code_mode_active:
            self.workspace_splitter.insertWidget(0, self.editor_panel)
            self.editor_panel.show()
            self.chat_panel.show()
            self.workspace_splitter.setStretchFactor(0, 3)
            self.workspace_splitter.setStretchFactor(1, 2)
            self.workspace_splitter.setSizes([700, 390])
            project_name = self.project_root.name if self.project_root else "Projet"
            self.page_subtitle.setText(f"{project_name} · éditeur et assistant IA")
        else:
            self.workspace_splitter.insertWidget(0, self.chat_panel)
            self.chat_panel.show()
            self.editor_panel.hide()
            self.workspace_splitter.setSizes([self.workspace_splitter.width(), 0])
            self.page_subtitle.setText("Votre espace de discussion avec KAIRO")

    def _apply_style(self):
        style = """
            QWidget#root { background: #10191b; color: #e6efea; }
            QWidget#sidebar { background: #152326; border-right: 1px solid #2c3c3b; }
            QWidget#mainPanel { background: #10191b; }
            QLabel#brand { color: #b5efc8; font-size: 25px; font-weight: 800; }
            QLabel#tagline, QLabel#sectionLabel { color: #82978d; font-size: 10px; font-weight: 800; }
            QLabel#sectionLabel { margin-top: 7px; }
            QLabel#pageTitle { color: #f1f5f1; font-size: 23px; font-weight: 700; }
            QLabel#subtitle, QLabel#mutedText { color: #91a69c; font-size: 11px; }
            QLabel#status { color: #b5efc8; background: #1e332a; border: 1px solid #3d5e49; border-radius: 9px; padding: 8px 12px; font-size: 11px; }
            QComboBox#modelPicker { background: #192729; color: #dce9e1; border: 1px solid #3c554c; border-radius: 7px; padding: 8px 10px; min-width: 230px; }
            QComboBox#modelPicker QAbstractItemView { background: #192729; color: #e1ebe5; selection-background-color: #355f4a; }
            QLabel#notice { color: #9bb0a5; font-size: 11px; }
            QListWidget#chatList, QTreeView#fileTree { background: #111d1f; color: #c8d8cf; border: 1px solid #2b3c39; border-radius: 7px; padding: 4px; }
            QListWidget#chatList::item { padding: 8px; border-radius: 5px; }
            QListWidget#chatList::item:selected { background: #264137; color: #e8fff0; }
            QPlainTextEdit#transcript { background: #0c1416; color: #e1ebe5; border: 1px solid #2c403c; border-radius: 9px; padding: 16px; selection-background-color: #355f4a; }
            QWidget#editorPanel { background: #121d1f; border: 1px solid #2b3c39; border-radius: 9px; }
            QLabel#editorFileLabel { color: #cfe0d6; font-family: 'Noto Sans Mono'; font-size: 11px; }
            QLabel#editorStatus { color: #82978d; font-size: 10px; }
            QWidget#authPage { background: #10191b; }
            QWidget#authPanel { background: #172426; border: 1px solid #344843; border-radius: 10px; }
            QLabel#authError { color: #ff9d8e; }
            QLabel#avatarPreview { color: #dce9e1; background: #294238; border: 1px solid #557664; border-radius: 36px; font-size: 24px; }
            QLabel#profileAvatar { color: #dce9e1; background: #294238; border: 1px solid #557664; border-radius: 19px; font-weight: 700; }
            QPushButton#authPrimaryButton { color: #14261b; background: #a5e8b9; border-color: #b7f0c7; text-align: center; }
            QPlainTextEdit#codeEditor { background: #0b1214; color: #dce9e1; border: 0; border-radius: 8px; padding: 14px; selection-background-color: #355f4a; }
            QLineEdit#composer { background: #182628; color: #f0f6f2; border: 1px solid #3c554c; border-radius: 8px; padding: 14px; selection-background-color: #355f4a; }
            QPushButton { color: #dce9e1; background: #20312e; border: 1px solid #365047; border-radius: 7px; padding: 11px 12px; font-weight: 700; text-align: left; }
            QPushButton:hover { color: #f2fff6; background: #2a4538; border-color: #75bd91; }
            QPushButton:pressed { background: #183027; padding-top: 13px; padding-bottom: 9px; }
            QPushButton:checked { color: #10251a; background: #a6e8b9; border-color: #c6f5d2; }
            QPushButton#connectButton { background: #264735; border-color: #5a936b; }
            QPushButton#sendButton { color: #14261b; background: #a5e8b9; border-color: #b7f0c7; min-width: 110px; text-align: center; }
            QPushButton#sendButton:hover { background: #c3f4ce; }
            QPushButton#saveButton { color: #14261b; background: #a5e8b9; border-color: #b7f0c7; text-align: center; }
            QPushButton:disabled { color: #697c73; background: #1a2524; border-color: #293633; }
        """
        if self.ui_settings.value("appearance/theme", "dark") == "light":
            style += """
                QWidget#root { background: #eef3ef; color: #1d2b25; }
                QWidget#sidebar { background: #dfe9e2; border-right: 1px solid #c4d3c9; }
                QWidget#mainPanel { background: #eef3ef; }
                QLabel#brand, QLabel#pageTitle { color: #173a2a; }
                QLabel#tagline, QLabel#sectionLabel, QLabel#subtitle, QLabel#mutedText,
                QLabel#notice, QLabel#editorStatus { color: #53695d; }
                QLabel#status { color: #245738; background: #d9eddf; border-color: #a5cbb0; }
                QListWidget#chatList, QTreeView#fileTree { background: #f8fbf8; color: #263a2f; border-color: #cbd9ce; }
                QListWidget#chatList::item:selected { background: #d2e8d8; color: #163d25; }
                QPlainTextEdit#transcript { background: #fbfdfb; color: #25372d; border-color: #c9d8ce; }
                QWidget#editorPanel { background: #f6faf6; border-color: #c9d8ce; }
                QLabel#editorFileLabel { color: #2b4936; }
                QWidget#authPage { background: #f3f8f4; }
                QWidget#authPanel { background: #fbfdfb; border-color: #c9d8ce; }
                QLabel#avatarPreview { color: #244030; background: #d2e8d8; border-color: #9bc2a4; }
                QLabel#profileAvatar { color: #244030; background: #d2e8d8; border-color: #9bc2a4; }
                QPlainTextEdit#codeEditor { background: #fbfdfb; color: #273a30; }
                QLineEdit#composer { background: #fbfdfb; color: #23372b; border-color: #b9cdbf; }
                QPushButton { color: #244030; background: #e0ebe2; border-color: #b9cdbf; }
                QPushButton:hover { color: #173c27; background: #cee5d4; border-color: #79aa88; }
                QPushButton:checked, QPushButton#sendButton, QPushButton#saveButton { color: #173722; background: #a5dcb4; border-color: #8bc69d; }
                QPushButton#connectButton { background: #d0e8d6; border-color: #9bc2a4; }
                QComboBox#modelPicker { background: #fbfdfb; color: #263a2f; border-color: #b9cdbf; }
                QComboBox#modelPicker QAbstractItemView { background: #fbfdfb; color: #263a2f; selection-background-color: #d2e8d8; }
            """
        self.setStyleSheet(style)

    def _open_notification_settings(self):
        self._open_settings("Notifications")

    def _open_settings(self, initial_tab=None):
        dialog = QDialog(self)
        dialog.setWindowTitle("Paramètres KAIRO")
        dialog.setMinimumWidth(510)
        layout = QVBoxLayout(dialog)
        tabs = QTabWidget()
        layout.addWidget(tabs)

        appearance = QWidget()
        appearance_form = QFormLayout(appearance)
        theme_picker = QComboBox()
        theme_picker.addItem("Sombre", "dark")
        theme_picker.addItem("Clair", "light")
        current_theme = self.ui_settings.value("appearance/theme", "dark")
        theme_picker.setCurrentIndex(max(0, theme_picker.findData(current_theme)))
        appearance_form.addRow("Thème", theme_picker)
        tabs.addTab(appearance, "Apparence")

        account_page = QWidget()
        account_layout = QVBoxLayout(account_page)
        account_name = os.environ.get("LOCAL_IA_ACCOUNT", "")
        account_keys = openrouter_api_keys()
        account_info = QLabel(
            f"Compte : {account_name or 'non connecté'}\n"
            f"Fournisseur : {'OpenRouter' if account_keys else 'aucun'}\n"
            f"Clés chargées : {len(account_keys)}"
        )
        account_info.setWordWrap(True)
        account_layout.addWidget(account_info)
        account_actions = QHBoxLayout()
        connect_button = QPushButton("Connexion / création")

        def open_connection_page():
            dialog.accept()
            self._connect_account()

        connect_button.clicked.connect(open_connection_page)
        manage_button = QPushButton("Gérer les clés API")
        manage_button.clicked.connect(self._manage_api_keys)
        disconnect_button = QPushButton("Déconnexion")
        disconnect_button.clicked.connect(self._disconnect_account)
        account_actions.addWidget(connect_button)
        account_actions.addWidget(manage_button)
        account_actions.addWidget(disconnect_button)
        account_layout.addLayout(account_actions)
        account_layout.addStretch(1)
        tabs.addTab(account_page, "Compte")

        data_page = QWidget()
        data_layout = QVBoxLayout(data_page)
        data_note = QLabel("Ces actions suppriment des données partagées avec le terminal.")
        data_note.setWordWrap(True)
        data_layout.addWidget(data_note)
        clear_current_button = QPushButton("Effacer cette conversation")
        clear_current_button.clicked.connect(self._clear_current_conversation)
        clear_all_button = QPushButton("Effacer toutes les conversations")
        clear_all_button.clicked.connect(self._clear_all_conversations)
        clear_memory_button = QPushButton("Effacer tous les souvenirs")
        clear_memory_button.clicked.connect(self._clear_all_memories)
        data_layout.addWidget(clear_current_button)
        data_layout.addWidget(clear_all_button)
        data_layout.addWidget(clear_memory_button)
        data_layout.addStretch(1)
        tabs.addTab(data_page, "Données")

        notifications = QWidget()
        notification_layout = QVBoxLayout(notifications)
        sound_enabled = QCheckBox("Son à la fin d’une réponse")
        sound_enabled.setChecked(self.ui_settings.value("notifications/sound", True, type=bool))
        notification_layout.addWidget(sound_enabled)
        test_sound = QPushButton("Tester le son")
        test_sound.clicked.connect(QApplication.beep)
        notification_layout.addWidget(test_sound)
        notification_layout.addStretch(1)
        tabs.addTab(notifications, "Notifications")

        update_page = QWidget()
        update_layout = QVBoxLayout(update_page)
        update_note = QLabel(
            "Télécharge les fichiers de l’application depuis GitHub sans remplacer vos données ni vos fichiers personnels."
        )
        update_note.setWordWrap(True)
        update_layout.addWidget(update_note)
        git_update_button = QPushButton("Mettre à jour via Git")
        git_update_button.setEnabled(not (self.git_update_task and self.git_update_task.isRunning()))
        git_update_button.clicked.connect(
            lambda _checked=False, button=git_update_button: self._start_git_update(button)
        )
        self.git_update_button = git_update_button
        update_layout.addWidget(git_update_button)
        update_layout.addStretch(1)
        tabs.addTab(update_page, "Mise à jour")
        if initial_tab:
            tabs.setCurrentWidget(notifications)

        tools_page = QWidget()
        tools_layout = QVBoxLayout(tools_page)
        manage_keys = QPushButton("Gérer les clés API")
        manage_keys.clicked.connect(self._manage_api_keys)
        open_terminal = QPushButton("Ouvrir le terminal")
        open_terminal.clicked.connect(self._open_terminal)
        install_application = QPushButton("Installer une application")
        install_application.clicked.connect(self._install_catalog_application)
        manage_projects = QPushButton("Gérer les projets")
        manage_projects.clicked.connect(self._manage_code_projects)
        open_file = QPushButton("Ouvrir un fichier")
        open_file.clicked.connect(self._open_single_file)
        for action in (manage_keys, open_terminal, install_application, manage_projects, open_file):
            tools_layout.addWidget(action)
        manage_tools = QPushButton("Gérer les outils et permissions")
        manage_tools.clicked.connect(self._manage_tools)
        tools_layout.addWidget(manage_tools)
        tools_layout.addStretch(1)
        tabs.addTab(tools_page, "Outils")

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.ui_settings.setValue("appearance/theme", theme_picker.currentData())
            self.ui_settings.setValue("notifications/sound", sound_enabled.isChecked())
            self._apply_style()

    def _start_git_update(self, button=None):
        if self.git_update_task and self.git_update_task.isRunning():
            return
        try:
            current_version = updater.get_current_version(BASE_DIR / "version.json")
            target_version = updater.fetch_remote_version()
        except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as error:
            QMessageBox.warning(self, "Mise à jour Git impossible", str(error))
            return
        answer = QMessageBox.question(
            self,
            "Confirmer la mise à jour",
            f"Version actuelle : {current_version}\n"
            f"Version à installer : {target_version}\n\n"
            "Installer cette mise à jour depuis GitHub ?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        if button is not None:
            button.setEnabled(False)
            button.setText("Mise à jour en cours…")
        self.git_update_task = GitUpdateTask(target_version, self)
        self.git_update_task.completed.connect(self._git_update_finished)
        self.git_update_task.start()

    def _git_update_finished(self, success, message):
        button = self.git_update_button
        if button is not None:
            try:
                button.setEnabled(True)
                button.setText("Mettre à jour via Git")
            except RuntimeError:
                self.git_update_button = None
        self.notice.setText("Mise à jour Git terminée." if success else "Échec de la mise à jour Git.")
        if success:
            QMessageBox.information(self, "Mise à jour terminée", message)
        else:
            QMessageBox.warning(self, "Mise à jour impossible", message)

    def _disconnect_account(self):
        try:
            accounts.clear_saved_session()
            persistence_warning = ""
        except Exception:
            persistence_warning = " Le trousseau système n'a pas pu être effacé."
        for variable in (
            "LOCAL_IA_PROVIDER",
            "LOCAL_IA_ACCOUNT",
            "LOCAL_IA_OPENROUTER_KEY",
            "LOCAL_IA_OPENROUTER_KEYS",
            "OPENROUTER_API_KEY",
        ):
            os.environ.pop(variable, None)
        self.agent.close()
        self.agent = self._new_agent()
        self._set_connection_status()
        self.notice.setText("GUI déconnecté." + persistence_warning + " Les clés chiffrées du compte sont conservées.")

    def _clear_current_conversation(self):
        answer = QMessageBox.question(
            self,
            "Effacer la conversation",
            "Effacer les messages de la conversation courante ?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        clear_chat(self.chat)
        self._load_chat_into_view()
        self._refresh_chat_list()

    def _clear_all_conversations(self):
        answer = QMessageBox.question(
            self,
            "Effacer les conversations",
            "Supprimer définitivement toutes les conversations partagées avec le terminal ?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        flush_writes()
        deleted = 0
        failures = []
        for path in CHAT_DIR.glob("*.json"):
            if path.stem.isdigit():
                try:
                    path.unlink(missing_ok=True)
                    deleted += 1
                except OSError as error:
                    failures.append(f"{path.name}: {error}")
        self.chat = create_chat()
        self.agent.prepare_chat(self.chat)
        self.project_root = None
        self._set_project_root(None)
        self._load_chat_into_view()
        self._refresh_chat_list()
        suffix = f" · {len(failures)} échec(s)" if failures else ""
        self.notice.setText(f"{deleted} conversation(s) effacée(s){suffix}.")
        if failures:
            QMessageBox.warning(self, "Suppression partielle", "\n".join(failures))

    def _clear_all_memories(self):
        answer = QMessageBox.question(
            self,
            "Effacer les souvenirs",
            "Supprimer définitivement tous les souvenirs partagés avec le terminal ?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        count = clear_memories(self.connection)
        self.agent.reload_memories()
        self.notice.setText(f"{count} souvenir(s) effacé(s).")

    def _notify_completion(self):
        if self.ui_settings.value("notifications/sound", True, type=bool):
            QApplication.beep()

    def _populate_model_picker(self):
        current_model = str(self.config.get("openrouter", {}).get("model") or "openai/gpt-4o-mini").strip()
        self.model_picker.blockSignals(True)
        self.model_picker.clear()
        for label, model_id in OPENROUTER_MODEL_PRESETS:
            self.model_picker.addItem(label, model_id)
        preset_ids = {model_id for _, model_id in OPENROUTER_MODEL_PRESETS}
        if current_model not in preset_ids:
            self.model_picker.addItem(f"Personnalisé · {current_model}", current_model)
        self.model_picker.addItem("Saisir un modèle personnalisé…", "__custom__")
        index = self.model_picker.findData(current_model)
        self.model_picker.setCurrentIndex(max(0, index))
        self.model_picker.blockSignals(False)

    def _model_choice(self, index):
        model_id = self.model_picker.itemData(index)
        if model_id == "__custom__":
            model_id, accepted = QInputDialog.getText(
                self,
                "Modèle OpenRouter personnalisé",
                "Identifiant exact du modèle (ex. fournisseur/modele)",
                text=str(self.config.get("openrouter", {}).get("model", "")),
            )
            if not accepted or not model_id.strip():
                self._populate_model_picker()
                return
            model_id = model_id.strip()
            self.model_picker.insertItem(self.model_picker.count() - 1, f"Personnalisé · {model_id}", model_id)
            index = self.model_picker.findData(model_id)
            self.model_picker.setCurrentIndex(index)
        self._apply_model(model_id)

    def _apply_model(self, model_id):
        model_id = str(model_id or "").strip()
        if not model_id:
            return False
        self.config.setdefault("openrouter", {})["model"] = model_id
        try:
            save_config(self.config)
        except OSError as error:
            QMessageBox.warning(self, "Modèle non enregistré", str(error))
            self._populate_model_picker()
            return False
        os.environ["LOCAL_IA_OPENROUTER_MODEL"] = model_id
        self.agent.close()
        self.agent = self._new_agent()
        self.notice.setText(f"Modèle actif : {model_id} · partagé via config.json")
        return True

    def _set_connection_status(self):
        account = os.environ.get("LOCAL_IA_ACCOUNT", "")
        if openrouter_api_keys():
            self.status.setText("●  Connecté")
            self.connect_button.setText(f"●  {account or 'OpenRouter'}")
            self.prompt.setEnabled(True)
            self.send_button.setEnabled(True)
            if hasattr(self, "page_stack"):
                self.page_stack.setCurrentIndex(0)
                self.auth_back_button.show()
                self._refresh_profile_avatar()
        else:
            self.status.setText("●  Déconnecté")
            self.connect_button.setText("Se connecter")
            self.prompt.setEnabled(False)
            self.send_button.setEnabled(False)
            if hasattr(self, "page_stack"):
                self.page_stack.setCurrentIndex(1)
                self.auth_back_button.hide()
                self.profile_avatar.hide()

    def _refresh_profile_avatar(self):
        try:
            profile = accounts.account_profile(os.environ.get("LOCAL_IA_ACCOUNT", ""))
        except (OSError, ValueError):
            self.profile_avatar.setText(os.environ.get("LOCAL_IA_ACCOUNT", "K")[:1].upper())
            self.profile_avatar.show()
            return
        pixmap = QPixmap(profile["avatar"])
        if not pixmap.isNull():
            self.profile_avatar.setPixmap(
                pixmap.scaled(38, 38, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
            )
        else:
            self.profile_avatar.setText(profile["username"][:1].upper())
        self.profile_avatar.show()

    def _restore_saved_session(self):
        if openrouter_api_keys():
            return
        try:
            session = accounts.load_saved_session()
        except Exception:
            return
        if session:
            self._set_provider(*session, remember=False)

    def _connect_account(self):
        if not openrouter_api_keys():
            self.page_stack.setCurrentWidget(self.auth_page)
            self._set_auth_mode("login")

    def _create_account(self):
        self.page_stack.setCurrentWidget(self.auth_page)
        self._set_auth_mode("signup")

    def _set_provider(self, username, api_keys, remember=True, account_password=None):
        os.environ["LOCAL_IA_PROVIDER"] = "openrouter"
        os.environ["LOCAL_IA_ACCOUNT"] = username
        os.environ["LOCAL_IA_OPENROUTER_KEYS"] = json.dumps(api_keys)
        os.environ.pop("LOCAL_IA_OPENROUTER_KEY", None)
        os.environ["LOCAL_IA_OPENROUTER_MODEL"] = str(
            self.config.get("openrouter", {}).get("model") or "openai/gpt-4o-mini"
        )
        os.environ["LOCAL_IA_OPENROUTER_BASE_URL"] = openrouter_base_url(self.config)
        self.agent.close()
        self.agent = self._new_agent()
        self._set_connection_status()
        if remember:
            try:
                accounts.save_session(username, api_keys, password=account_password)
            except Exception:
                self.notice.setText(f"Connecté au compte {username}; session non mémorisée par le trousseau système.")
                return
        self.notice.setText(f"Connecté au compte {username}; reconnexion automatique activée.")

    def _manage_api_keys(self):
        username = os.environ.get("LOCAL_IA_ACCOUNT", "").strip()
        if not username:
            QMessageBox.information(self, "Connexion requise", "Connecte-toi d'abord à un compte local.")
            return
        try:
            password = accounts.load_saved_account_password(username)
        except Exception:
            password = ""
        if not password:
            password, accepted = QInputDialog.getText(
                self,
                "Gérer les clés API",
                f"Mot de passe du compte {username}",
                QLineEdit.EchoMode.Password,
            )
            if not accepted:
                return
            try:
                accounts.save_session(username, openrouter_api_keys(), password=password)
            except Exception:
                self.notice.setText("Mot de passe non mémorisé; le trousseau système est indisponible.")
        try:
            records = accounts.authenticate_api_key_records(username, password)
        except ValueError as error:
            QMessageBox.warning(self, "Authentification refusée", str(error))
            return

        dialog = ApiKeyManagerDialog(username, records, self)

        def refresh_keys():
            updated_records = accounts.authenticate_api_key_records(username, password)
            active_keys = accounts.authenticate_api_keys(username, password)
            self._set_provider(username, active_keys)
            dialog.set_records(updated_records)
            self.notice.setText("Clés API mises à jour et chiffrées dans le compte local.")

        def add_key():
            new_key, accepted = QInputDialog.getText(
                dialog,
                "Ajouter une clé API",
                "Clé OpenRouter",
                QLineEdit.EchoMode.Password,
            )
            if not accepted or not new_key.strip():
                return
            try:
                accounts.add_api_key(username, password, new_key.strip())
                refresh_keys()
            except (OSError, ValueError) as error:
                QMessageBox.warning(dialog, "Ajout impossible", str(error))

        def add_openrouter_key(api_key):
            try:
                accounts.add_api_key(username, password, api_key)
                refresh_keys()
            except (OSError, ValueError) as error:
                QMessageBox.warning(dialog, "Ajout impossible", str(error))

        def remove_key():
            record = dialog.selected_record()
            if record is None:
                return
            confirmation = QMessageBox.question(
                dialog,
                "Supprimer une clé API",
                f"Supprimer la clé {dialog._preview(record['key'])} ?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if confirmation != QMessageBox.StandardButton.Yes:
                return
            try:
                accounts.remove_api_key(username, password, record["index"])
                refresh_keys()
            except (OSError, ValueError) as error:
                QMessageBox.warning(dialog, "Suppression impossible", str(error))

        def toggle_key():
            record = dialog.selected_record()
            if record is None:
                return
            try:
                accounts.set_api_key_enabled(
                    username,
                    password,
                    record["index"],
                    not record["enabled"],
                )
                refresh_keys()
            except (OSError, ValueError) as error:
                QMessageBox.warning(dialog, "État impossible à modifier", str(error))

        def show_usage():
            record = dialog.selected_record()
            if record is None:
                return
            try:
                usage = get_openrouter_key_usage(api_key=record["key"])
                details = [f"Clé : {dialog._preview(record['key'])}"]
                for field, label in (
                    ("usage", "Utilisation"),
                    ("limit", "Limite"),
                    ("limit_remaining", "Limite restante"),
                ):
                    if usage.get(field) is not None:
                        details.append(f"{label} : {usage[field]}")
                QMessageBox.information(dialog, "Usage OpenRouter", "\n".join(details))
            except Exception as error:
                QMessageBox.warning(dialog, "Usage indisponible", str(error))

        dialog.add_button.clicked.connect(add_key)
        dialog.create_button.clicked.connect(
            lambda: self._start_openrouter_key_creation(add_openrouter_key)
        )
        dialog.remove_button.clicked.connect(remove_key)
        dialog.toggle_button.clicked.connect(toggle_key)
        dialog.usage_button.clicked.connect(show_usage)
        dialog.exec()

    def _start_openrouter_key_creation(self, on_key_created):
        if self.oauth_task and self.oauth_task.isRunning():
            return
        task = OpenRouterKeyTask(self)
        self.oauth_task = task
        task.progress.connect(self.notice.setText)
        task.completed.connect(
            lambda success, result: self._finish_openrouter_key_creation(
                success, result, on_key_created
            )
        )
        self.notice.setText("Connexion sécurisée à OpenRouter en préparation…")
        task.start()

    def _finish_openrouter_key_creation(self, success, result, on_key_created):
        self.oauth_task = None
        if not success:
            self.notice.setText("Création de clé OpenRouter interrompue.")
            QMessageBox.warning(self, "Connexion OpenRouter impossible", result)
            return
        try:
            on_key_created(result)
        except Exception as error:
            QMessageBox.warning(self, "Enregistrement impossible", str(error))

    def _new_chat(self):
        self.chat = create_chat()
        self._refresh_download_buttons()
        self.project_root = None
        self.agent.prepare_chat(self.chat)
        self._load_chat_into_view()
        self._refresh_chat_list()
        self._set_project_root(None)
        self.notice.setText("Nouvelle conversation créée et partagée avec le CLI.")

    def _manage_conversations(self):
        ConversationManagerDialog(self).exec()
        self._refresh_chat_list()

    def _refresh_chat_list(self):
        current_id = self.chat.get("id") if hasattr(self, "chat") else None
        query = self.chat_search.text().strip().casefold()
        self.chat_list.clear()
        for chat in list_chats():
            title = chat.get("custom_title") or chat.get("topic") or chat.get("title") or "Conversation sans titre"
            category = str(chat.get("category") or "").strip()
            if query:
                searchable = " ".join(
                    [title, category, *(str(item.get("content", "")) for item in chat.get("messages", []))]
                ).casefold()
                if query not in searchable:
                    continue
            category_label = f" · {category}" if category else ""
            item = QListWidgetItem(f"{title}\n#{chat['id']} · {len(chat.get('messages', []))} messages{category_label}")
            item.setData(Qt.ItemDataRole.UserRole, int(chat["id"]))
            self.chat_list.addItem(item)
            if current_id == chat["id"]:
                self.chat_list.setCurrentItem(item)

    def _open_chat_item(self, item):
        chat_id = item.data(Qt.ItemDataRole.UserRole)
        self._open_conversation_id(chat_id)

    def _open_conversation_id(self, chat_id):
        loaded = load_chat(chat_id)
        if loaded is None:
            self.notice.setText("Cette conversation est introuvable.")
            self._refresh_chat_list()
            return
        self.chat = loaded
        self._refresh_download_buttons()
        self.agent.prepare_chat(self.chat)
        self.project_root = None
        if self.chat.get("code_project_path"):
            try:
                self.project_root = code_projects.resolve_active_project(self.chat["code_project_path"])
            except (OSError, ValueError):
                self.project_root = None
        self._load_chat_into_view()
        self._refresh_chat_list()
        self._set_project_root(self.project_root)

    def _load_chat_into_view(self):
        title = self.chat.get("custom_title") or self.chat.get("topic") or self.chat.get("title") or f"Conversation #{self.chat['id']}"
        self.chat_title.setText(title)
        self.transcript.clear()
        for message in self.chat.get("messages", []):
            if message.get("role") in {"user", "assistant"}:
                self._append_message(message["role"], message.get("content", ""))

    def _toggle_code_mode(self, checked):
        if not checked:
            self.code_armed = False
            self.prompt.setPlaceholderText("Écris une demande, /help, /commande …")
            self._apply_mode(False)
            return
        project = self.project_root
        if project:
            try:
                project = code_projects.resolve_active_project(project)
            except (OSError, ValueError):
                project = None
        if project is None:
            project = self._choose_project()
        if project is None:
            self.code_button.setChecked(False)
            return
        self._activate_code_project(project)

    def _activate_code_project(self, project):
        self.project_root = code_projects.resolve_active_project(project)
        self.code_armed = True
        self._apply_mode(True)
        self.chat["code_project_name"] = self.project_root.name
        self.chat["code_project_path"] = str(self.project_root)
        save_chat(self.chat, async_mode=False)
        code_projects.install_code_examples(self.project_root)
        self._set_project_root(self.project_root)
        self.prompt.setPlaceholderText("Décris le changement à proposer; le diff sera soumis à approbation…")
        self.notice.setText(f"Mode Code · {self.project_root.name} · modifications après approbation")

    def _manage_code_projects(self):
        CodeProjectManagerDialog(self).exec()

    def _manage_tools(self):
        ToolManagerDialog(self, self.ui_settings, self.project_root if self.code_mode_active else None).exec()

    def _forget_deleted_code_project(self, project):
        project = Path(project).resolve()
        editor_root = Path(self.editor_project_root).resolve() if self.editor_project_root else None
        if editor_root == project:
            self.save_timer.stop()
            self._close_editor_file()
        active_root = Path(self.project_root).resolve() if self.project_root else None
        chat_project = self.chat.get("code_project_path")
        if active_root == project or chat_project and Path(chat_project).resolve() == project:
            self.project_root = None
            self.code_armed = False
            self.code_button.setChecked(False)
            self.chat.pop("code_project_path", None)
            self.chat.pop("code_project_name", None)
            save_chat(self.chat, async_mode=False)
            self._apply_mode(False)
            self._set_project_root(None)
            self.prompt.setPlaceholderText("Écris une demande, /help, /commande …")
            self.notice.setText("Projet supprimé; le Mode Code a été désactivé.")

    def _choose_project(self):
        projects = code_projects.list_projects()
        options = ["Créer un projet…", *[project.name for project in projects]]
        selected, accepted = QInputDialog.getItem(self, "Projet de code", "Projet actif", options, 0, False)
        if not accepted:
            return None
        if selected != options[0]:
            return code_projects.create_or_open_project(selected)
        description, accepted = QInputDialog.getText(
            self,
            "Nouveau projet",
            "Nom ou sujet du projet",
            text="nouveau-projet",
        )
        if not accepted or not description.strip():
            return None
        name = code_projects.suggest_project_name(description)
        return code_projects.create_or_open_project(name)

    def _set_project_root(self, project):
        resolved_project = Path(project).resolve() if project is not None else None
        should_switch_editor = (
            self.current_file
            and resolved_project != self.editor_project_root
            and (resolved_project is not None or not self.single_file_mode)
        )
        if should_switch_editor:
            self.save_timer.stop()
            if not self._save_open_file():
                return False
            self._close_editor_file()
        if project is None:
            self.files_hint.setText("Active Mode Code pour choisir ou créer un projet.")
            self.file_tree.setRootIndex(self.file_model.index(""))
            return True
        project = resolved_project
        self.files_hint.setText(project.name)
        self.file_model.setRootPath(str(project))
        self.file_tree.setRootIndex(self.file_model.index(str(project)))
        self.file_tree.expandToDepth(1)
        return True

    def _selected_project_entry(self):
        if not self.project_root:
            return None
        index = self.file_tree.currentIndex()
        if not index.isValid():
            return None
        root = Path(self.project_root).resolve()
        path = Path(self.file_model.filePath(index))
        if path != root and root not in path.parents:
            return None
        return path

    def _create_project_entry(self):
        if not self.project_root:
            return
        kind, accepted = QInputDialog.getItem(self, "Créer dans le projet", "Type", ("Fichier", "Dossier"), 0, False)
        if not accepted:
            return
        name, accepted = QInputDialog.getText(self, "Créer dans le projet", "Nom")
        if not accepted or not name.strip() or "/" in name or "\\" in name:
            return
        root = Path(self.project_root).resolve()
        selected = self._selected_project_entry()
        parent = selected if selected and selected.is_dir() else selected.parent if selected else root
        target = parent / name.strip()
        try:
            code_projects.resolve_project_path(root, target)
            if target.exists():
                raise FileExistsError(f"Un élément existe déjà : {target.name}")
            if kind == "Dossier":
                target.mkdir()
            else:
                target.touch(exist_ok=False)
        except (OSError, ValueError, PermissionError) as error:
            QMessageBox.warning(self, "Création impossible", str(error))
            return
        self.file_model.setRootPath(str(root))
        if kind == "Fichier":
            self._open_code_file(target)

    def _rename_project_entry(self):
        source = self._selected_project_entry()
        if source is None or source == Path(self.project_root).resolve():
            return
        name, accepted = QInputDialog.getText(self, "Renommer", "Nouveau nom", text=source.name)
        if not accepted or not name.strip() or "/" in name or "\\" in name:
            return
        target = source.with_name(name.strip())
        try:
            code_projects.resolve_project_path(self.project_root, target)
            if target.exists():
                raise FileExistsError(f"Un élément existe déjà : {target.name}")
            if self.current_file and (self.current_file == source or source in self.current_file.parents):
                if not self._save_open_file():
                    return
            source.rename(target)
        except (OSError, ValueError, PermissionError) as error:
            QMessageBox.warning(self, "Renommage impossible", str(error))
            return
        if self.current_file == source:
            self.current_file = target
            self.editor_file_label.setText(target.relative_to(Path(self.project_root)).as_posix())
        elif self.current_file and source in self.current_file.parents:
            self.current_file = target / self.current_file.relative_to(source)
            self.editor_file_label.setText(self.current_file.relative_to(Path(self.project_root)).as_posix())
        self.file_model.setRootPath(str(self.project_root))

    def _delete_project_entry(self):
        target = self._selected_project_entry()
        root = Path(self.project_root).resolve() if self.project_root else None
        if target is None or target == root:
            return
        answer = QMessageBox.question(
            self,
            "Supprimer l’élément",
            f"Supprimer définitivement « {target.name} » ?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            code_projects.resolve_project_path(root, target)
            if self.current_file and (self.current_file == target or target in self.current_file.parents):
                self.save_timer.stop()
                self._close_editor_file()
            if target.is_symlink() or target.is_file():
                target.unlink()
            else:
                shutil.rmtree(target)
        except (OSError, ValueError, PermissionError) as error:
            QMessageBox.warning(self, "Suppression impossible", str(error))
            return
        self.file_model.setRootPath(str(root))

    def _preview_file(self, index):
        path = Path(self.file_model.filePath(index)).resolve()
        if not self.project_root or (path != self.project_root and self.project_root not in path.parents):
            return
        if not path.is_file():
            return
        self._open_code_file(path)

    def _open_single_file(self):
        initial_path = str(self.current_file.parent) if self.current_file else str(Path.home())
        selected, _ = QFileDialog.getOpenFileName(
            self,
            "Ouvrir un fichier",
            initial_path,
            "Tous les fichiers (*);;Fichiers courants (*.py *.js *.ts *.html *.css *.json *.md *.txt)",
        )
        if not selected:
            return
        self.code_armed = False
        self.project_root = None
        self._apply_mode(True)
        self._open_code_file(Path(selected), single_file=True)

    def _open_code_file(self, path, *, single_file=False):
        path = Path(path).resolve()
        if self.project_root:
            root = Path(self.project_root).resolve()
            if path != root and root not in path.parents:
                return False
        elif single_file:
            root = path.parent
        else:
            return False
        if self.current_file and not self._save_open_file():
            return False
        try:
            if path.stat().st_size > MAX_PREVIEW_BYTES:
                raise ValueError("Fichier trop volumineux pour l'éditeur (maximum 1 Mo).")
            result = file_tool.use(str(path), allowed_roots=[root])
            if result.get("kind") != "text":
                raise ValueError("L'éditeur ne peut ouvrir que des fichiers texte.")
            content = result.get("content", "")
        except (OSError, PermissionError, ValueError) as error:
            QMessageBox.warning(self, "Lecture impossible", str(error))
            return False
        self.save_timer.stop()
        self.current_file = path
        self.editor_project_root = root
        self.single_file_mode = single_file
        self._backed_up_files = set()
        self._loading_editor = True
        self.code_editor.setPlainText(content)
        self.code_editor.document().setModified(False)
        self._loading_editor = False
        self._saved_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        self.editor_file_label.setText(path.relative_to(root).as_posix())
        mode_label = "Fichier isolé" if single_file else "Projet"
        self.editor_status.setText(f"{mode_label} · sauvegarde auto active · Ctrl+S")
        self.ai_file_button.setEnabled(single_file and bool(openrouter_api_keys()))
        self._update_python_run_button()
        if single_file:
            self.files_hint.setText(f"Fichier isolé · {path.name}")
        else:
            self.file_model.setRootPath(str(root))
            self.file_tree.setRootIndex(self.file_model.index(str(root)))
            self.files_hint.setText(f"{mode_label} · {root}")
        return True

    def _editor_changed(self):
        if self._loading_editor or self.current_file is None:
            return
        self.code_editor.document().setModified(True)
        self.editor_status.setText("Modifications non enregistrées…")
        self.save_timer.start()

    def _save_open_file(self):
        if self._loading_editor or self.current_file is None:
            return True
        target = Path(self.current_file).resolve()
        root = Path(self.editor_project_root).resolve()
        if target != root and root not in target.parents:
            self.editor_status.setText("Sauvegarde refusée · chemin hors du projet")
            return False
        content = self.code_editor.toPlainText()
        raw = content.encode("utf-8")
        content_hash = hashlib.sha256(raw).hexdigest()
        if content_hash == self._saved_hash:
            return True
        if len(raw) > file_commands.MAX_WRITE_BYTES:
            self.editor_status.setText("Sauvegarde refusée · fichier supérieur à 2 Mo")
            return False
        if target.suffix.casefold() == ".py":
            try:
                ast.parse(content)
            except SyntaxError as error:
                self.editor_status.setText(f"Syntaxe Python invalide · ligne {error.lineno or '?'}; corrigée avant sauvegarde")
                return False
        try:
            if target not in self._backed_up_files:
                backup_file(target, backup_dir=root / ".local_ia_backups")
                self._backed_up_files.add(target)
            output = QSaveFile(str(target))
            if not output.open(QIODevice.OpenModeFlag.WriteOnly):
                raise OSError(output.errorString())
            if output.write(raw) != len(raw):
                output.cancelWriting()
                raise OSError(output.errorString())
            if not output.commit():
                raise OSError(output.errorString())
        except (OSError, ValueError) as error:
            self.editor_status.setText(f"Erreur de sauvegarde · {error}")
            return False
        self.code_editor.document().setModified(False)
        self._saved_hash = content_hash
        self.editor_status.setText("Enregistré · backup créé dans .local_ia_backups")
        return True

    def _update_python_run_button(self):
        button = getattr(self, "run_python_button", None)
        if button is None:
            return
        process = getattr(self, "python_process", None)
        process_running = process is not None and process.state() != QProcess.ProcessState.NotRunning
        enabled = (
            self.code_mode_active
            and not self.single_file_mode
            and bool(self.project_root)
            and self.current_file is not None
            and Path(self.current_file).suffix.casefold() == ".py"
            and not process_running
        )
        button.setEnabled(enabled)

    def _run_current_python_file(self):
        if not self.run_python_button.isEnabled() or not self._save_open_file():
            return
        try:
            root = code_projects.resolve_active_project(self.project_root)
            target = code_projects.resolve_project_path(root, self.current_file)
            if not target.is_file() or target.suffix.casefold() != ".py":
                raise ValueError("Le fichier Python actif est introuvable dans le projet.")
        except (OSError, ValueError) as error:
            QMessageBox.warning(self, "Lancement impossible", str(error))
            return
        answer = QMessageBox.question(
            self,
            "Exécuter le fichier Python ?",
            f"Lancer {target.relative_to(root).as_posix()} avec les droits de votre compte ?\n\n"
            "Le script peut modifier des fichiers ou démarrer d'autres programmes.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        process = QProcess(self)
        process.setWorkingDirectory(str(root))
        process.setProgram(sys.executable)
        process.setArguments([str(target)])
        process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        process.readyReadStandardOutput.connect(self._read_python_output)
        process.finished.connect(self._python_run_finished)
        process.errorOccurred.connect(self._python_run_error)
        self.python_process = process
        self._python_output = ""
        self._python_filename = target.name
        self.run_python_button.setEnabled(False)
        self.code_editor.setEnabled(False)
        self.save_button.setEnabled(False)
        self.notice.setText(f"Exécution de {target.name}…")
        process.start()

    def _read_python_output(self):
        if not self.python_process:
            return
        chunk = bytes(self.python_process.readAllStandardOutput()).decode("utf-8", errors="replace")
        self._python_output = (self._python_output + chunk)[-128_000:]

    def _python_run_finished(self, exit_code, _exit_status):
        self._read_python_output()
        filename = self._python_filename
        output = self._python_output.strip() or "(aucune sortie)"
        self.python_process = None
        self.code_editor.setEnabled(True)
        self.save_button.setEnabled(True)
        self._update_python_run_button()
        self.notice.setText(f"{filename} terminé · code {exit_code}")

        dialog = QDialog(self)
        dialog.setWindowTitle(f"Exécution Python · {filename}")
        dialog.resize(760, 520)
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel(f"Code de sortie : {exit_code}"))
        result = QPlainTextEdit()
        result.setReadOnly(True)
        result.setPlainText(output)
        layout.addWidget(result, stretch=1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(dialog.reject)
        buttons.accepted.connect(dialog.accept)
        layout.addWidget(buttons)
        dialog.exec()

    def _python_run_error(self, error):
        if error != QProcess.ProcessError.FailedToStart:
            return
        self.python_process = None
        self.code_editor.setEnabled(True)
        self.save_button.setEnabled(True)
        self._update_python_run_button()
        QMessageBox.warning(self, "Lancement impossible", "L'interpréteur Python n'a pas pu démarrer.")

    def _close_editor_file(self):
        self.current_file = None
        self.single_file_mode = False
        self.editor_project_root = None
        self._saved_hash = None
        self._backed_up_files = set()
        self._loading_editor = True
        self.code_editor.clear()
        self.preview_browser.clear()
        self.editor_tabs.setCurrentIndex(0)
        self.editor_tabs.setTabVisible(1, False)
        self.code_editor.document().setModified(False)
        self._loading_editor = False
        self.editor_file_label.setText("Aperçu du code")
        self._update_python_run_button()
        self.editor_status.setText("Aucun fichier ouvert")
        self.ai_file_button.setEnabled(False)

    def _update_preview(self):
        if self.current_file is None:
            self.editor_tabs.setTabVisible(1, False)
            return
        extension = Path(self.current_file).suffix.casefold()
        content = self.code_editor.toPlainText()
        if extension in {".html", ".htm"}:
            self.preview_browser.setHtml(content)
        elif extension == ".md":
            self.preview_browser.setMarkdown(content)
        self.editor_tabs.setTabVisible(1, extension in {".html", ".htm", ".md"})

    def _request_single_file_edit(self):
        if not self.single_file_mode or not self.current_file:
            return
        if not openrouter_api_keys():
            QMessageBox.information(self, "Connexion requise", "Connecte-toi à OpenRouter pour modifier un fichier avec l'IA.")
            return
        original = self.code_editor.toPlainText()
        if len(original.encode("utf-8")) > MAX_SINGLE_FILE_AI_BYTES:
            QMessageBox.warning(
                self,
                "Fichier trop volumineux",
                "La modification IA d'un fichier isolé est limitée à 64 Ko; utilise le Mode Code pour travailler sur un projet.",
            )
            return
        request, accepted = QInputDialog.getText(
            self,
            "Modifier un fichier avec l'IA",
            f"Modification souhaitée pour {self.current_file.name}",
        )
        if not accepted or not request.strip():
            return
        original_hash = hashlib.sha256(original.encode("utf-8")).hexdigest()
        self._append_message("user", request.strip())
        self.notice.setText(f"Préparation d'une proposition pour {self.current_file.name}…")
        self._set_busy(True)
        self.worker = AgentTask(
            self.agent,
            self.chat,
            request.strip(),
            file_edit_content=original,
            file_path=self.current_file,
        )
        self.worker.progress.connect(self._show_task_progress)
        self.worker.completed.connect(
            lambda success, answer: self._single_file_edit_finished(
                request.strip(), original, original_hash, success, answer
            )
        )
        self.worker.start()

    def _single_file_edit_finished(self, request, original, original_hash, success, answer):
        self._set_busy(False)
        if not success:
            self._append_message("assistant", f"Erreur : {answer}")
            self.notice.setText("La proposition a échoué.")
            return
        start_marker = "<<<KAIRO_FILE_CONTENT>>>"
        end_marker = "<<<END_KAIRO_FILE_CONTENT>>>"
        start = answer.find(start_marker)
        end = answer.rfind(end_marker)
        if start < 0 or end < start:
            self._append_message("assistant", "Réponse inexploitable; le fichier n'a pas été modifié.")
            self.notice.setText("Proposition illisible; fichier inchangé.")
            return
        proposed = answer[start + len(start_marker):end]
        if proposed.startswith("\r\n"):
            proposed = proposed[2:]
        elif proposed.startswith("\n"):
            proposed = proposed[1:]
        if proposed.endswith("\r\n"):
            proposed = proposed[:-2]
        elif proposed.endswith("\n"):
            proposed = proposed[:-1]
        if original.endswith("\r\n") and not proposed.endswith("\r\n"):
            proposed += "\r\n"
        elif original.endswith("\n") and not proposed.endswith("\n"):
            proposed += "\n"
        if hashlib.sha256(self.code_editor.toPlainText().encode("utf-8")).hexdigest() != original_hash:
            self._append_message("assistant", "Le fichier a changé pendant la génération; proposition annulée.")
            self.notice.setText("Fichier modifié en parallèle; aucune proposition appliquée.")
            return

        diff = "".join(difflib.unified_diff(
            original.splitlines(keepends=True),
            proposed.splitlines(keepends=True),
            fromfile=f"a/{self.current_file.name}",
            tofile=f"b/{self.current_file.name}",
        ))
        if not diff:
            self._append_message("assistant", "Aucun changement proposé.")
            self.notice.setText("Aucun changement nécessaire.")
            return

        dialog = QDialog(self)
        dialog.setWindowTitle(f"Vérifier le diff · {self.current_file.name}")
        dialog.resize(900, 650)
        layout = QVBoxLayout(dialog)
        diff_view = QPlainTextEdit()
        diff_view.setReadOnly(True)
        diff_view.setFont(QFont("Noto Sans Mono", 10))
        diff_view.setPlainText(diff)
        layout.addWidget(diff_view, stretch=1)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Apply | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Apply).clicked.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            self._append_message("assistant", "Proposition refusée; fichier inchangé.")
            self.notice.setText("Proposition refusée.")
            return

        self.code_editor.setPlainText(proposed)
        if not self._save_open_file():
            self._append_message("assistant", "Sauvegarde refusée; le fichier n'a pas été remplacé.")
            self.notice.setText("Sauvegarde refusée; corrige le fichier avant de réessayer.")
            return
        result = f"Modification approuvée et appliquée à {self.current_file.name}."
        add_chat_message(self.chat, "user", request)
        add_chat_message(self.chat, "assistant", result)
        self._append_message("assistant", result)
        self._refresh_chat_list()
        self.notice.setText("Modification appliquée et sauvegardée.")
        self._notify_completion()

    def _single_file_context(self):
        if not self.single_file_mode or not self.current_file:
            return None
        return (
            "Fichier actif en mode fichier unique (contexte limité à ce fichier) :\n"
            f"Chemin : {self.current_file}\n"
            "Utilise ce contenu pour répondre. Pour proposer de modifier ce fichier, l'utilisateur doit utiliser le bouton dédié; ne prétends pas l'avoir changé.\n"
            f"```text\n{self.code_editor.toPlainText()}\n```"
        )

    def _active_code_file_context(self):
        if not self.project_root or not self.current_file:
            return None
        root = Path(self.project_root).resolve()
        path = Path(self.current_file).resolve()
        if root not in path.parents:
            return None
        content = self.code_editor.toPlainText()
        if len(content.encode("utf-8")) > 64_000:
            return f"Fichier sélectionné : {path}\nLe contenu dépasse 64 Ko; lis-le avec l’outil file avant de répondre."
        return f"Fichier sélectionné : {path}\nContenu actuel de l’éditeur :\n```text\n{content}\n```"

    def _send_message(self):
        request = self.prompt.text().strip()
        if not request or (self.worker and self.worker.isRunning()):
            return
        if self._handle_local_command(request):
            self.prompt.clear()
            return
        if not openrouter_api_keys():
            QMessageBox.information(
                self,
                "Connexion OpenRouter requise",
                "Le GUI utilise uniquement l'API. Connecte-toi à un compte OpenRouter avant d'envoyer une demande.",
            )
            return
        self.prompt.clear()
        code_mode = (self.code_mode_active and not self.single_file_mode) or request.startswith("/code ")
        if request.startswith("/code "):
            request = request[6:].strip()
        if request == "/code":
            self._toggle_code_mode(True)
            return
        if code_mode and not self.project_root:
            project = self._choose_project()
            if project is None:
                return
            self._activate_code_project(project)
        self._append_message("user", request)
        self.notice.setText("Analyse du projet…" if code_mode else "KAIRO réfléchit…")
        self._set_busy(True)
        external_info = self._active_code_file_context() if code_mode else self._single_file_context()
        command_enabled = self._commands_enabled()
        allowed_tools = self._allowed_tools_for_current_context()
        self.worker = AgentTask(
            self.agent,
            self.chat,
            request,
            code_mode=code_mode,
            project=self.project_root,
            command_enabled=command_enabled,
            external_info=external_info,
            allowed_tools=allowed_tools,
        )
        self.worker.progress.connect(self._show_task_progress)
        self.worker.downloads_ready.connect(self._show_download_artifacts)
        self.worker.completed.connect(lambda success, answer: self._proposal_finished(request, code_mode, success, answer))
        self.worker.start()

    def _preview_file_command(self, answer):
        tool_calls = LocalAgent.parse_file_command_plan(answer)
        if not isinstance(tool_calls, list) or not tool_calls:
            return None, "L'IA n'a pas renvoyé de commande write/edit valide. Aucun fichier n'a été modifié."
        try:
            root = code_projects.resolve_active_project(self.project_root)
            file_states = {}
            for tool_call in tool_calls:
                arguments = tool_call.get("arguments")
                if not isinstance(arguments, dict) or not arguments.get("path"):
                    raise ValueError("Une commande fichier ne contient pas de chemin valide.")
                target = code_projects.resolve_project_path(root, arguments["path"])
                if target.exists() and not target.is_file():
                    raise ValueError("Un chemin cible existe déjà et n'est pas un fichier.")
                relative = target.relative_to(root).as_posix()
                if relative not in file_states:
                    if target.is_file() and target.stat().st_size > MAX_PREVIEW_BYTES:
                        raise ValueError(f"{relative} dépasse la limite de prévisualisation.")
                    original = target.read_text(encoding="utf-8") if target.is_file() else ""
                    file_states[relative] = [original, original]
                original, current = file_states[relative]
                if tool_call["tool"] == "write":
                    content = arguments.get("content")
                    if not isinstance(content, str):
                        raise ValueError("La commande write ne contient pas de contenu texte.")
                    updated = current + content if arguments.get("append") else content
                else:
                    old = arguments.get("old")
                    new = arguments.get("new")
                    if not isinstance(old, str) or not old or not isinstance(new, str):
                        raise ValueError("La commande edit ne contient pas un remplacement valide.")
                    if "\r\n" in current and "\r\n" not in old:
                        old, new = old.replace("\n", "\r\n"), new.replace("\n", "\r\n")
                    occurrences = current.count(old)
                    if not occurrences or (occurrences > 1 and not arguments.get("replace_all")):
                        raise ValueError(f"Le texte ciblé est absent ou ambigu dans {relative}.")
                    updated = current.replace(old, new)
                file_states[relative] = [original, updated]

            diff = "".join(
                "".join(difflib.unified_diff(
                    original.splitlines(keepends=True),
                    updated.splitlines(keepends=True),
                    fromfile=f"a/{relative}",
                    tofile=f"b/{relative}",
                ))
                for relative, (original, updated) in file_states.items()
            )
            if not diff.strip():
                raise ValueError("La commande ne produit aucun changement.")
            return tool_calls, diff
        except (OSError, UnicodeError, ValueError) as error:
            return None, f"Commande fichier refusée : {error} Aucun fichier n'a été modifié."

    def _proposal_finished(self, request, code_mode, success, answer):
        self._set_busy(False)
        if not success:
            self._append_message("assistant", f"Erreur : {answer}")
            self.notice.setText("La demande a échoué.")
            return
        if code_mode:
            tool_call, diff = self._preview_file_command(answer)
            if tool_call is None:
                self._append_message("assistant", diff)
                add_chat_message(self.chat, "user", request)
                add_chat_message(self.chat, "assistant", diff)
                self._refresh_chat_list()
                self.notice.setText("Aucune commande fichier valide; aucun fichier modifié.")
                self.code_armed = False
                return
            proposal = f"Diff proposé :\n```diff\n{diff}```"
            self._append_message("assistant", proposal)
            approved = QMessageBox.question(
                self,
                "Appliquer la proposition ?",
                "Appliquer ces modifications au projet ?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            ) == QMessageBox.StandardButton.Yes
            if not approved:
                add_chat_message(self.chat, "user", request)
                add_chat_message(self.chat, "assistant", proposal + "\n\nProposition refusée; aucun fichier modifié.")
                self._refresh_chat_list()
                self.notice.setText("Proposition refusée; aucun fichier modifié.")
                self.code_armed = False
                return
            self.notice.setText("Application du diff et vérifications…")
            self._set_busy(True)
            self.worker = AgentTask(
                self.agent,
                self.chat,
                request,
                approved_tool_call=tool_call,
                project=self.project_root,
                command_enabled=self._commands_enabled(),
                allowed_tools=self._allowed_tools_for_current_context(),
            )
            self.worker.progress.connect(self._show_task_progress)
            self.worker.completed.connect(lambda applied, result: self._apply_finished(request, answer, applied, result))
            self.worker.start()
            return
        add_chat_message(self.chat, "user", request)
        add_chat_message(self.chat, "assistant", answer)
        self._append_message("assistant", answer)
        self._refresh_chat_list()
        self.notice.setText("Réponse terminée")
        self._notify_completion()

    def _apply_finished(self, request, proposal, success, answer):
        self._set_busy(False)
        if success:
            add_chat_message(self.chat, "user", request)
            add_chat_message(self.chat, "assistant", answer)
            self._append_message("assistant", answer)
            self.notice.setText("Correctif terminé")
        else:
            self._append_message("assistant", f"Échec de l'application : {answer}")
            add_chat_message(self.chat, "user", request)
            add_chat_message(self.chat, "assistant", f"Proposition :\n{proposal}\n\nÉchec : {answer}")
            self.notice.setText("Échec de l'application")
        self.code_armed = self.code_mode_active
        self._refresh_chat_list()
        self._notify_completion()

    def _handle_local_command(self, request):
        if request == "/help":
            self._append_message(
                "assistant",
                "Commandes : /new, /chats, /load <id>, /clear, /topic <sujet>, /context, /memory, /remember <texte>, /forget <id>, /forget-all, /code <demande>, /commande <commande>.",
            )
            return True
        if request == "/new":
            self._new_chat()
            return True
        if request == "/chats":
            self._refresh_chat_list()
            self._append_message("assistant", "Liste actualisée dans la barre latérale.")
            return True
        if request.startswith("/load ") and request[6:].isdigit():
            chat = load_chat(int(request[6:]))
            if chat is None:
                self.notice.setText("Conversation introuvable")
            else:
                self.chat = chat
                self._refresh_download_buttons()
                self.agent.prepare_chat(chat)
                self._load_chat_into_view()
                self._refresh_chat_list()
            return True
        if request == "/clear":
            clear_chat(self.chat)
            self._load_chat_into_view()
            self._refresh_chat_list()
            return True
        if request.startswith("/topic "):
            self.chat["topic"] = request[7:].strip()
            save_chat(self.chat, async_mode=False)
            self._load_chat_into_view()
            self._refresh_chat_list()
            return True
        if request == "/context":
            self._append_message("assistant", json.dumps(load_context(), ensure_ascii=False, indent=2))
            return True
        if self._handle_memory_command(request):
            return True
        return False

    def _handle_memory_command(self, request):
        if request == "/memory":
            entries = list_memories(self.connection)
            text = "\n".join(f"#{entry['id']} · {entry['content']}" for entry in entries) or "Aucun souvenir."
            self._append_message("assistant", text)
            return True
        if request.startswith("/remember "):
            save_memory(self.connection, request[10:].strip(), async_mode=False)
            self.agent.reload_memories()
            self._append_message("assistant", "Souvenir enregistré.")
            return True
        if request.startswith("/forget "):
            value = request[8:].strip()
            if not value.isdecimal() or int(value) < 1:
                self.notice.setText("Syntaxe : /forget <id>")
            elif delete_memory(self.connection, int(value)):
                self.agent.reload_memories()
                self._append_message("assistant", f"Souvenir #{value} oublié.")
            else:
                self.notice.setText(f"Souvenir #{value} introuvable.")
            return True
        if request == "/forget-all":
            answer = QMessageBox.question(
                self,
                "Effacer la mémoire ?",
                "Effacer définitivement tous les souvenirs ?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer == QMessageBox.StandardButton.Yes:
                count = clear_memories(self.connection)
                self.agent.reload_memories()
                self._append_message("assistant", f"{count} souvenir(s) effacé(s).")
            return True
        return False

    def _append_message(self, role, content):
        label = "TOI" if role == "user" else "KAIRO"
        self.transcript.appendPlainText(f"{label}\n{content}\n")
        scrollbar = self.transcript.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def _show_download_artifacts(self, artifacts):
        saved_artifacts = self.chat.setdefault("download_artifacts", [])
        known_ids = {
            item.get("artifact_id")
            for item in saved_artifacts
            if isinstance(item, dict)
        }
        changed = False
        for artifact in artifacts:
            if not isinstance(artifact, dict):
                continue
            artifact_id = artifact.get("artifact_id")
            filename = artifact.get("filename")
            if not isinstance(artifact_id, str) or not isinstance(filename, str) or artifact_id in known_ids:
                continue
            saved_artifacts.append({
                "artifact_id": artifact_id,
                "filename": filename,
                "size": artifact.get("size"),
            })
            known_ids.add(artifact_id)
            changed = True
        if changed:
            save_chat(self.chat, async_mode=False)
        self._refresh_download_buttons()

    def _refresh_download_buttons(self):
        while self.download_buttons_layout.count():
            item = self.download_buttons_layout.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        self.download_buttons_layout.addStretch(1)
        available = []
        for artifact in self.chat.get("download_artifacts", []):
            if not isinstance(artifact, dict):
                continue
            artifact_id = artifact.get("artifact_id")
            filename = artifact.get("filename")
            try:
                download_tool.resolve_cached_file(artifact_id, filename)
            except (OSError, TypeError, ValueError):
                continue
            available.append(artifact)
            button = QPushButton(f"↓  {filename}")
            button.setObjectName("downloadButton")
            button.setToolTip(f"Enregistrer {filename}…")
            button.setMaximumWidth(260)
            button.clicked.connect(
                lambda _checked=False, item=dict(artifact): self._save_generated_download(item)
            )
            self.download_buttons_layout.insertWidget(self.download_buttons_layout.count() - 1, button)
        self.downloads_panel.setVisible(bool(available))

    def _save_generated_download(self, artifact):
        filename = artifact.get("filename", "fichier")
        destination, _selected_filter = QFileDialog.getSaveFileName(
            self, "Enregistrer le fichier", filename, "Tous les fichiers (*)"
        )
        if not destination:
            return
        try:
            download_tool.copy_to(artifact.get("artifact_id"), filename, destination)
        except (OSError, TypeError, ValueError) as error:
            QMessageBox.warning(self, "Téléchargement impossible", str(error))
            return
        self.notice.setText(f"Fichier enregistré : {destination}")

    def _set_busy(self, busy):
        connected = bool(openrouter_api_keys())
        self.send_button.setEnabled(not busy and connected)
        self.prompt.setEnabled(not busy and connected)
        self.new_chat_button.setEnabled(not busy)
        self.code_button.setEnabled(True)
        self.chat_list.setEnabled(not busy)
        self.file_tree.setEnabled(not busy)
        self.create_entry_button.setEnabled(not busy)
        self.rename_entry_button.setEnabled(not busy)
        self.delete_entry_button.setEnabled(not busy)
        self.code_editor.setEnabled(not busy)
        self.save_button.setEnabled(not busy)

    def _show_task_progress(self, message):
        self.notice.setText(str(message))

    def _commands_enabled(self):
        value = load_config().get("command_execution", {})
        return isinstance(value, dict) and bool(value.get("enabled"))

    def _allowed_tools_for_current_context(self):
        allowed = set(TOOL_NAMES)
        try:
            global_disabled = json.loads(str(self.ui_settings.value("tools/disabled", "[]")))
        except (TypeError, json.JSONDecodeError):
            global_disabled = []
        if isinstance(global_disabled, list):
            allowed.difference_update(name for name in global_disabled if isinstance(name, str))
        if self.code_mode_active and self.project_root:
            allowed.difference_update(code_projects.get_project_disabled_tools(self.project_root))
        if not self._commands_enabled():
            allowed.discard("command")
        return allowed

    def _install_catalog_application(self):
        if self.install_process and self.install_process.state() != QProcess.ProcessState.NotRunning:
            return
        try:
            programs = program_commands.get_catalog_programs()
        except ValueError as error:
            QMessageBox.warning(self, "Catalogue indisponible", str(error))
            return

        labels = [f"{item['name']} · {item.get('category', 'Autre')}" for item in programs]
        selection, accepted = QInputDialog.getItem(
            self, "Installer une application", "Application", labels, 0, False
        )
        if not accepted:
            return
        selected_index = labels.index(selection)
        program = programs[selected_index]
        try:
            plan = program_commands.get_installation_plan(program["id"])
        except (KeyError, ValueError) as error:
            QMessageBox.warning(self, "Installation indisponible", str(error))
            return

        details = [
            f"Application : {program['name']}",
            f"Gestionnaire : {plan['manager']}",
            f"Commande : {shlex.join(plan['command'])}",
        ]
        if plan["requires"]:
            details.append("Prérequis : " + ", ".join(plan["requires"]))
        answer = QMessageBox.question(
            self,
            "Confirmer l'installation",
            "\n".join(details) + "\n\nLancer cette commande ?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        process = QProcess(self)
        process.setWorkingDirectory(str(BASE_DIR))
        process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        process.readyReadStandardOutput.connect(self._read_catalog_install_output)
        process.finished.connect(self._finish_catalog_installation)
        process.errorOccurred.connect(self._catalog_install_error)
        self.install_process = process
        self._install_output = ""
        self._install_prompt_buffer = ""
        self.install_button.setEnabled(False)
        self.install_button.setText("Installation en cours…")
        command = list(plan["command"])
        executable, arguments = command[0], command[1:]
        if executable == "sudo":
            arguments.insert(0, "-S")
        process.start(executable, arguments)

    def _read_catalog_install_output(self):
        if not self.install_process:
            return
        chunk = bytes(self.install_process.readAllStandardOutput()).decode("utf-8", errors="replace")
        self._install_output = (self._install_output + chunk)[-64_000:]
        self._install_prompt_buffer = (self._install_prompt_buffer + chunk)[-300:]
        prompt = self._install_prompt_buffer.casefold()
        if ("password" in prompt or "mot de passe" in prompt) and prompt.rstrip().endswith(":"):
            self._install_prompt_buffer = ""
            password, accepted = QInputDialog.getText(
                self,
                "Authentification système",
                "Mot de passe sudo",
                QLineEdit.EchoMode.Password,
            )
            if accepted:
                self.install_process.write((password + "\n").encode("utf-8"))
            else:
                self.install_process.terminate()

    def _finish_catalog_installation(self, exit_code, _exit_status):
        output = self._install_output.strip()
        self.install_process = None
        self.install_button.setEnabled(True)
        self.install_button.setText("↓   Installer une application")
        if exit_code == 0:
            message = "Installation terminée."
            if output:
                message += "\n\n" + output[-6000:]
            QMessageBox.information(self, "Application installée", message)
        else:
            message = f"L'installation s'est terminée avec le code {exit_code}."
            if output:
                message += "\n\n" + output[-6000:]
            QMessageBox.warning(self, "Échec de l'installation", message)

    def _catalog_install_error(self, error):
        if error != QProcess.ProcessError.FailedToStart:
            return
        self.install_process = None
        self.install_button.setEnabled(True)
        self.install_button.setText("↓   Installer une application")
        QMessageBox.warning(self, "Installation impossible", "Le gestionnaire n'a pas pu démarrer.")

    def _open_terminal(self):
        environment = os.environ.copy()
        environment["LOCAL_IA_GUI_CHILD"] = "1"
        for variable in (
            "LOCAL_IA_PROVIDER",
            "LOCAL_IA_ACCOUNT",
            "LOCAL_IA_OPENROUTER_KEY",
            "LOCAL_IA_OPENROUTER_KEYS",
            "OPENROUTER_API_KEY",
        ):
            environment.pop(variable, None)
        try:
            if os.name == "nt":
                subprocess.Popen([sys.executable, str(BASE_DIR / "main.py")], cwd=BASE_DIR, creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0), env=environment)
            else:
                import shutil

                terminal = shutil.which("konsole") or shutil.which("x-terminal-emulator")
                if terminal is None:
                    raise FileNotFoundError("Konsole ou x-terminal-emulator introuvable.")
                args = [terminal]
                if Path(terminal).name == "konsole":
                    args.append("--separate")
                args.extend(("-e", sys.executable, str(BASE_DIR / "main.py")))
                subprocess.Popen(args, cwd=BASE_DIR, env=environment, start_new_session=True)
        except OSError as error:
            QMessageBox.warning(self, "Terminal indisponible", str(error))

    def closeEvent(self, event):
        if self.git_update_task and self.git_update_task.isRunning():
            QMessageBox.information(self, "Mise à jour en cours", "Attends la fin de la mise à jour avant de fermer KAIRO.")
            event.ignore()
            return
        if self.python_process and self.python_process.state() != QProcess.ProcessState.NotRunning:
            answer = QMessageBox.question(
                self,
                "Script Python en cours",
                "Arrêter le script Python et fermer KAIRO ?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            self.python_process.terminate()
            if not self.python_process.waitForFinished(3000):
                self.python_process.kill()
                self.python_process.waitForFinished(1000)
        if self.install_process and self.install_process.state() != QProcess.ProcessState.NotRunning:
            QMessageBox.information(self, "Installation en cours", "Attends la fin de l'installation avant de fermer KAIRO.")
            event.ignore()
            return
        if self.oauth_task and self.oauth_task.isRunning():
            QMessageBox.information(
                self,
                "Connexion OpenRouter en cours",
                "Termine ou ferme l'autorisation dans le navigateur avant de fermer KAIRO.",
            )
            event.ignore()
            return
        if self.worker and self.worker.isRunning():
            QMessageBox.information(self, "Traitement en cours", "Attends la fin de la demande avant de fermer KAIRO.")
            event.ignore()
            return
        self.save_timer.stop()
        if not self._save_open_file():
            answer = QMessageBox.question(
                self,
                "Modifications non enregistrées",
                "Le fichier ne peut pas être sauvegardé. Fermer quand même et perdre ces modifications ?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
        self.agent.close()
        self.connection.close()
        event.accept()


def run_gui():
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName("KAIRO")
    app.setStyle("Fusion")
    window = KairoWorkspace()
    window.show()
    return app.exec()
