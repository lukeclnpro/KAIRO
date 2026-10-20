"""Interface graphique KAIRO partageant moteur et donnees avec le CLI."""

from __future__ import annotations

import json
import ast
import difflib
import hashlib
import html
import os
import re
import shutil
import shlex
import subprocess
import sys
import uuid
from pathlib import Path
from urllib.parse import quote_plus

from PySide6.QtCore import QEasingCurve, QEventLoop, QIODevice, QItemSelectionModel, QProcess, QProcessEnvironment, QPoint, QPropertyAnimation, QRect, QRegularExpression, QSaveFile, QSettings, QThread, QTimer, QUrl, Qt, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QKeySequence, QPixmap, QShortcut, QTextCharFormat, QTextCursor, QSyntaxHighlighter
from PySide6.QtWidgets import (
    QApplication,
    QAbstractItemView,
    QFileSystemModel,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QComboBox,
    QCheckBox,
    QColorDialog,
    QDialog as _QtDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox as _QtMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSlider,
    QSplitter,
        QStackedWidget,
    QSpinBox,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTabBar,
    QToolButton,
    QTextBrowser,
    QTreeView,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtWebEngineWidgets import QWebEngineView

from local_ia.config.manager import (
    effective_openrouter_power,
    load_config,
    model_config,
    openrouter_api_keys,
    openrouter_base_url,
    openrouter_model,
    openrouter_power,
    save_config,
)
from local_ia import desktop_tray, models as model_catalog, updater
from local_ia import theme_library
from local_ia.core import accounts, code_projects, conversation as conversation_store
from local_ia.core import notifications as app_notifications
from local_ia.core import tool_health as tool_health_diagnostics
from local_ia.core.agent import LocalAgent, TOOL_NAMES
from local_ia.core.context import load_context
from local_ia.core.tool_manager import ToolManager
from local_ia.core.openrouter_oauth import authorize_openrouter
from local_ia.http_client import Request, open_url as urlopen
from local_ia.llm.ollama import ask_ollama, get_openrouter_key_usage
import application_launcher
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
MAX_OPENROUTER_KEYS_PER_CREATION = 10
MODEL_NEED_LABELS = {
    "general": "Général",
    "code": "Code",
    "reasoning": "Raisonnement",
    "math": "Mathématiques",
    "vision": "Vision / images",
    "translation": "Traduction",
    "embeddings": "RAG / embeddings",
    "agents": "Agents",
    "technical": "Technique",
    "long_context": "Grand contexte",
}
MODEL_POWER_LABELS = {
    "light": "Léger",
    "medium": "Équilibré",
    "heavy": "Puissant",
    "unknown": "Non estimé",
}


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
            preview = " ".join(str(message.get("content", "")).split())
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
        role_index = self.role_picker.findText(str(message.get("role", "user")), Qt.MatchFixedString)
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
        self.setObjectName("conversationManagerDialog")
        self.setWindowTitle("Gestion des conversations")
        self.setMinimumSize(900, 580)
        self.resize(1180, 760)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(14)

        filters = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Rechercher par nom, catégorie ou message…")
        self.category_filter = QComboBox()
        filters.addWidget(self.search_input, stretch=1)
        filters.addWidget(self.category_filter)
        layout.addLayout(filters)

        self.table = QTableWidget(0, 4)
        self.table.setObjectName("conversationManagerTable")
        self.table.setHorizontalHeaderLabels(("Conversation", "Catégorie", "Messages", "Modifiée"))
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.setWordWrap(False)
        self.table.horizontalHeader().setObjectName("conversationManagerHeader")
        self.table.horizontalHeader().setMinimumSectionSize(90)
        self.table.horizontalHeader().setDefaultSectionSize(150)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setColumnWidth(0, 360)
        self.table.setColumnWidth(1, 170)
        self.table.setColumnWidth(2, 100)
        self.table.setColumnWidth(3, 190)
        self.table.verticalHeader().hide()
        self.table.doubleClicked.connect(self._open_selected)
        layout.addWidget(self.table, stretch=1)

        selection_bar = QHBoxLayout()
        self.selection_summary = QLabel("Aucune conversation sélectionnée")
        self.selection_summary.setObjectName("conversationSelectionSummary")
        selection_bar.addWidget(self.selection_summary, stretch=1)
        self.select_all_button = QPushButton("Tout sélectionner")
        self.clear_selection_button = QPushButton("Effacer la sélection")
        selection_bar.addWidget(self.select_all_button)
        selection_bar.addWidget(self.clear_selection_button)
        layout.addLayout(selection_bar)

        actions = QHBoxLayout()
        actions.setSpacing(7)
        self.open_button = QPushButton("Ouvrir")
        self.rename_button = QPushButton("Renommer")
        self.edit_button = QPushButton("Modifier")
        self.category_button = QPushButton("Classer")
        self.copy_button = QPushButton("Copier")
        self.export_button = QPushButton("Exporter")
        self.import_button = QPushButton("Importer")
        self.delete_button = QPushButton("Supprimer")
        self.delete_button.setObjectName("conversationDeleteButton")
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
        self.table.itemSelectionChanged.connect(self._update_selection_state)
        self.select_all_button.clicked.connect(self.table.selectAll)
        self.clear_selection_button.clicked.connect(self.table.clearSelection)
        self.open_button.clicked.connect(self._open_selected)
        self.rename_button.clicked.connect(self._rename_selected)
        self.edit_button.clicked.connect(self._edit_selected)
        self.category_button.clicked.connect(self._classify_selected)
        self.copy_button.clicked.connect(self._copy_selected)
        self.export_button.clicked.connect(self._export_selected)
        self.import_button.clicked.connect(self._import_conversation)
        self.delete_button.clicked.connect(self._delete_selected)
        self._refresh()

    def _refresh(self, *_args, selected_ids=None):
        selected = set(selected_ids if selected_ids is not None else self._selected_ids())
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
        self.table.blockSignals(True)
        self.table.setRowCount(0)
        for chat in chats:
            title = self._display_title(chat)
            chat_category = str(chat.get("category") or "")
            if self.category_filter.currentText() != "Toutes les catégories" and chat_category != self.category_filter.currentText():
                continue
            searchable = f"{title} {chat_category} {' '.join(str(item.get('content', '')) for item in chat.get('messages', []))}".casefold()
            if query and query not in searchable:
                continue
            row = self.table.rowCount()
            self.table.insertRow(row)
            self.table.setRowHeight(row, 48)
            title_item = QTableWidgetItem(title)
            title_item.setData(Qt.ItemDataRole.UserRole, int(chat["id"]))
            self.table.setItem(row, 0, title_item)
            self.table.setItem(row, 1, QTableWidgetItem(chat_category or "—"))
            self.table.setItem(row, 2, QTableWidgetItem(str(len(chat.get("messages", [])))))
            self.table.setItem(row, 3, QTableWidgetItem(str(chat.get("updated_at") or "")))
            if int(chat["id"]) in selected:
                self.table.selectionModel().select(
                    self.table.model().index(row, 0),
                    QItemSelectionModel.SelectionFlag.Select
                    | QItemSelectionModel.SelectionFlag.Rows,
                )
        self.table.blockSignals(False)
        self._update_selection_state()

    @staticmethod
    def _display_title(chat):
        return str(chat.get("custom_title") or chat.get("topic") or chat.get("title") or f"Conversation #{chat['id']}")

    def _selected_ids(self):
        rows = sorted({index.row() for index in self.table.selectionModel().selectedRows()})
        selected_ids = []
        for row in rows:
            item = self.table.item(row, 0)
            if item is not None:
                selected_ids.append(int(item.data(Qt.ItemDataRole.UserRole)))
        return selected_ids

    def _selected_id(self):
        selected_ids = self._selected_ids()
        return selected_ids[0] if len(selected_ids) == 1 else None

    def _update_selection_state(self):
        count = len(self._selected_ids())
        if count == 0:
            self.selection_summary.setText("Aucune conversation sélectionnée")
        else:
            self.selection_summary.setText(
                f"{count} conversation{'s' if count > 1 else ''} sélectionnée{'s' if count > 1 else ''}"
            )
        single_selection = count == 1
        multiple_or_single = count > 0
        for button in (self.open_button, self.rename_button, self.edit_button):
            button.setEnabled(single_selection)
        for button in (
            self.category_button,
            self.copy_button,
            self.export_button,
            self.delete_button,
        ):
            button.setEnabled(multiple_or_single)

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
        self._refresh(selected_ids=[chat["id"]])

    def _classify_selected(self):
        chat_ids = self._selected_ids()
        if not chat_ids:
            return
        chat = conversation_store.load_chat(chat_ids[0])
        if chat is None:
            return
        subject = "cette conversation" if len(chat_ids) == 1 else f"ces {len(chat_ids)} conversations"
        category, accepted = QInputDialog.getText(
            self,
            "Classer les conversations",
            f"Catégorie pour {subject} (laisser vide pour retirer)",
            text=str(chat.get("category") or ""),
        )
        if not accepted:
            return
        failures = []
        for chat_id in chat_ids:
            try:
                conversation_store.set_chat_category(chat_id, category)
                self._sync_parent(chat_id)
            except (OSError, ValueError) as error:
                failures.append(f"#{chat_id} : {error}")
        self._refresh(selected_ids=chat_ids)
        if failures:
            QMessageBox.warning(self, "Classement partiel", "\n".join(failures))

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
        self._refresh(selected_ids=[chat["id"]])

    def _copy_selected(self):
        chat_ids = self._selected_ids()
        if not chat_ids:
            return
        duplicate_ids = []
        failures = []
        for chat_id in chat_ids:
            try:
                duplicate = conversation_store.copy_chat(chat_id)
                duplicate_ids.append(duplicate["id"])
            except (OSError, ValueError) as error:
                failures.append(f"#{chat_id} : {error}")
        self._refresh(selected_ids=duplicate_ids)
        if failures:
            QMessageBox.warning(self, "Copie partielle", "\n".join(failures))

    def _export_selected(self):
        chat_ids = self._selected_ids()
        if not chat_ids:
            return
        if len(chat_ids) == 1:
            destination, _selected_filter = QFileDialog.getSaveFileName(
                self,
                "Exporter la conversation",
                f"conversation-{chat_ids[0]}.json",
                "Conversations JSON (*.json)",
            )
            if not destination:
                return
            try:
                conversation_store.export_chat(chat_ids[0], destination)
            except (OSError, ValueError) as error:
                QMessageBox.warning(self, "Export impossible", str(error))
                return
        else:
            destination = QFileDialog.getExistingDirectory(
                self, "Choisir le dossier d’export des conversations"
            )
            if not destination:
                return
            failures = []
            for chat_id in chat_ids:
                try:
                    conversation_store.export_chat(
                        chat_id, Path(destination) / f"conversation-{chat_id}.json"
                    )
                except (OSError, ValueError) as error:
                    failures.append(f"#{chat_id} : {error}")
            if failures:
                QMessageBox.warning(self, "Export partiel", "\n".join(failures))
                return
        QMessageBox.information(
            self,
            "Export terminé",
            f"{len(chat_ids)} conversation{'s' if len(chat_ids) > 1 else ''} exportée{'s' if len(chat_ids) > 1 else ''}.",
        )

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
        self._refresh(selected_ids=[chat["id"]])

    def _delete_selected(self):
        chat_ids = self._selected_ids()
        if not chat_ids:
            return
        title = "Supprimer la conversation" if len(chat_ids) == 1 else "Supprimer les conversations"
        target = "cette conversation et tous ses messages" if len(chat_ids) == 1 else f"ces {len(chat_ids)} conversations et tous leurs messages"
        answer = QMessageBox.question(
            self,
            title,
            f"Supprimer définitivement {target} ?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        parent = self.parent()
        parent_chat = getattr(parent, "chat", None)
        new_chat = getattr(parent, "_new_chat", None)
        deleted_current = isinstance(parent_chat, dict) and parent_chat.get("id") in chat_ids
        deleted = []
        failures = []
        for chat_id in chat_ids:
            try:
                if conversation_store.delete_chat(chat_id):
                    deleted.append(chat_id)
                else:
                    failures.append(f"#{chat_id} : conversation introuvable")
            except OSError as error:
                failures.append(f"#{chat_id} : {error}")
        if deleted_current and deleted and callable(new_chat):
            new_chat()
        self._refresh()
        if failures:
            QMessageBox.warning(self, "Suppression partielle", "\n".join(failures))


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
        self.create_count = QSpinBox()
        self.create_count.setRange(1, MAX_OPENROUTER_KEYS_PER_CREATION)
        self.create_count.setValue(1)
        count_row = QHBoxLayout()
        count_row.addWidget(QLabel("Clés à créer"))
        count_row.addWidget(self.create_count)
        count_row.addStretch(1)
        count_row.addWidget(self.create_button)
        layout.addLayout(count_row)
        self.toggle_button = QPushButton("Désactiver")
        self.remove_button = QPushButton("Supprimer")
        self.close_button = QPushButton("Fermer")
        for button in (
            self.usage_button,
            self.add_button,
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
    completed = Signal(bool, object)
    progress = Signal(str)

    def __init__(self, count=1, parent=None):
        super().__init__(parent)
        self.count = max(1, min(int(count), MAX_OPENROUTER_KEYS_PER_CREATION))

    def run(self):
        api_keys = []
        for index in range(self.count):
            self.progress.emit(f"Autorisation de la clé {index + 1}/{self.count} dans le navigateur…")
            try:
                api_keys.append(authorize_openrouter())
            except Exception as error:
                if api_keys:
                    self.completed.emit(False, {"keys": api_keys, "error": str(error)})
                else:
                    self.completed.emit(False, str(error))
                return
        try:
            self.completed.emit(True, api_keys)
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


def _update_version_key(version):
    numbers = [int(number) for number in re.findall(r"\d+", str(version))[:4]]
    numbers.extend([0] * (4 - len(numbers)))
    beta = re.search(r"beta\s*(\d*)", str(version), re.I)
    return (*numbers, 0 if beta else 1, int(beta.group(1) or 0) if beta else 0)


class UpdateVersionItem(QTableWidgetItem):
    def __lt__(self, other):
        return _update_version_key(self.text()) < _update_version_key(other.text())


def _format_code_statistics(statistics):
    if not isinstance(statistics, dict):
        return "—"
    total = statistics.get("total", {})
    if not isinstance(total, dict):
        total = {}

    def format_number(value):
        try:
            return f"{int(value):,}".replace(",", " ")
        except (TypeError, ValueError):
            return "0"

    lines = [
        f"TOTAL · {format_number(total.get('fichiers'))} fichiers · "
        f"{format_number(total.get('lignes'))} lignes"
    ]
    extensions = statistics.get("extensions", {})
    if isinstance(extensions, dict):
        for extension, counts in extensions.items():
            if not isinstance(counts, dict):
                continue
            lines.append(
                f"{extension} · {format_number(counts.get('fichiers'))} fichiers · "
                f"{format_number(counts.get('lignes'))} lignes"
            )
    ignored = statistics.get("fichiers_ignores")
    if ignored:
        lines.append(f"Fichiers ignorés · {format_number(ignored)}")
    return "\n".join(lines)


class UpdateHistoryDialog(_QtDialog):
    HEADERS = ("Version", "Date", "Titre", "Changements", "Base de code")

    def __init__(self, entries, parent=None, light_theme=False):
        super().__init__(parent)
        self.setWindowTitle("Historique des mises à jour KAIRO")
        self.setMinimumSize(1040, 540)
        self.resize(1320, 720)
        layout = QVBoxLayout(self)
        heading = QLabel("Historique des mises à jour")
        heading.setObjectName("settingsTitle")
        layout.addWidget(heading)

        versions = [entry for entry in entries if isinstance(entry, dict)]
        latest_version = max(
            (str(entry.get("version", "")) for entry in versions),
            key=_update_version_key,
            default="",
        )
        self.summary = QLabel(
            f"{len(versions)} versions · plus récente : {latest_version or 'inconnue'} · "
            "vert : plus récente · jaune : bêta"
        )
        self.summary.setObjectName("mutedText")
        layout.addWidget(self.summary)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Filtrer par version, date, titre ou changement")
        layout.addWidget(self.search)
        self.table = QTableWidget(len(versions), len(self.HEADERS), self)
        self.table.setHorizontalHeaderLabels(self.HEADERS)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSortingEnabled(False)
        self.table.setWordWrap(True)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().hide()
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setColumnWidth(0, 150)
        self.table.setColumnWidth(1, 105)
        self.table.setColumnWidth(2, 220)
        self.table.setColumnWidth(3, 430)
        self.table.setColumnWidth(4, 270)

        latest_background = QColor("#dcefe0" if light_theme else "#294b35")
        latest_foreground = QColor("#20432c" if light_theme else "#e6f5e9")
        beta_background = QColor("#fff1c2" if light_theme else "#514323")
        beta_foreground = QColor("#55420d" if light_theme else "#fff0c2")
        for row, entry in enumerate(versions):
            version = str(entry.get("version", ""))
            changes = entry.get("changes", [])
            if not isinstance(changes, list):
                changes = [str(changes)]
            changes_text = "\n".join(f"• {change}" for change in changes)
            code_statistics = _format_code_statistics(entry.get("code_statistics"))
            values = (
                version,
                str(entry.get("date", "")),
                str(entry.get("title", "")),
                changes_text,
                code_statistics,
            )
            version_item = UpdateVersionItem(version)
            version_item.setData(Qt.ItemDataRole.UserRole, " ".join(values).casefold())
            version_item.setFont(QFont(version_item.font().family(), version_item.font().pointSize(), QFont.Weight.Bold))
            self.table.setItem(row, 0, version_item)
            for column, value in enumerate(values[1:], start=1):
                self.table.setItem(row, column, QTableWidgetItem(value))
            background = latest_background if version == latest_version else None
            foreground = latest_foreground if version == latest_version else None
            if "beta" in version.casefold() and version != latest_version:
                background = beta_background
                foreground = beta_foreground
            if background is not None:
                for column in range(len(self.HEADERS)):
                    item = self.table.item(row, column)
                    item.setBackground(background)
                    item.setForeground(foreground)
        self.table.setSortingEnabled(True)
        self.table.sortItems(0, Qt.SortOrder.DescendingOrder)
        self.table.resizeRowsToContents()
        self.search.textChanged.connect(self._filter_rows)
        layout.addWidget(self.table, stretch=1)
        close_button = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close_button.rejected.connect(self.reject)
        close_button.accepted.connect(self.accept)
        layout.addWidget(close_button)

    def _filter_rows(self, query):
        needle = str(query or "").strip().casefold()
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            searchable = str(item.data(Qt.ItemDataRole.UserRole) or "")
            self.table.setRowHidden(row, needle not in searchable)


class ToolPageTask(QThread):
    completed = Signal(bool, object)

    def __init__(self, tool_name, arguments, parent=None):
        super().__init__(parent)
        self.tool_name = tool_name
        self.arguments = arguments

    def run(self):
        try:
            result = ToolManager.execute(
                {"tool": self.tool_name, "arguments": self.arguments},
                chat={},
                connection=None,
                allowed_tools={self.tool_name},
            )
            self.completed.emit(True, result)
        except Exception as error:
            self.completed.emit(False, str(error))


class OllamaModelTask(QThread):
    result_ready = Signal(dict)
    progress = Signal(str)

    def __init__(self, action, base_url, model="", api_key="", parent=None):
        super().__init__(parent)
        self.action = action
        self.base_url = str(base_url or "").strip().rstrip("/")
        self.model = str(model or "").strip()
        self.api_key = str(api_key or "").strip()

    def run(self):
        base_url = self.base_url[:-4] if self.base_url.endswith("/api") else self.base_url
        try:
            if self.action == "openrouter-list":
                if not self.api_key:
                    raise ValueError("Connecte-toi à OpenRouter pour charger son catalogue de modèles.")
                request = Request(
                    f"{base_url}/models",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    method="GET",
                )
                with urlopen(request, timeout=20) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                models = payload.get("data", []) if isinstance(payload, dict) else []
                self.result_ready.emit({
                    "action": self.action,
                    "base_url": base_url,
                    "models": [model for model in models if isinstance(model, dict) and model.get("id")],
                })
                return

            if self.action == "list":
                with urlopen(f"{base_url}/api/tags", timeout=5) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                raw_models = payload.get("models", []) if isinstance(payload, dict) else []
                models = {
                    item["name"]: item
                    for item in raw_models
                    if isinstance(item, dict) and item.get("name")
                }
                self.result_ready.emit({
                    "action": self.action,
                    "base_url": base_url,
                    "models": sorted(models.values(), key=lambda item: item["name"].casefold()),
                })
                return

            endpoint = "pull" if self.action == "pull" else "delete"
            body = {"name": self.model, "stream": True} if self.action == "pull" else {"name": self.model}
            request = Request(
                f"{base_url}/api/{endpoint}",
                data=json.dumps(body).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urlopen(request, timeout=3600 if self.action == "pull" else 60) as response:
                if self.action == "pull":
                    for line in response:
                        if not line:
                            continue
                        update = json.loads(line.decode("utf-8"))
                        if update.get("error"):
                            raise RuntimeError(update["error"])
                        status = str(update.get("status") or "Téléchargement Ollama…")
                        total = update.get("total")
                        completed = update.get("completed")
                        if isinstance(total, (int, float)) and total > 0 and isinstance(completed, (int, float)):
                            status += f" · {int(completed * 100 / total)}%"
                        self.progress.emit(status)
                else:
                    result = response.read()
                    if result:
                        payload = json.loads(result.decode("utf-8"))
                        if isinstance(payload, dict) and payload.get("error"):
                            raise RuntimeError(payload["error"])
            self.result_ready.emit({"action": self.action, "base_url": base_url, "model": self.model, "success": True})
        except Exception as error:
            self.result_ready.emit({"action": self.action, "base_url": base_url, "error": str(error)})


class ProviderCallTestTask(QThread):
    result_ready = Signal(dict)

    def __init__(self, provider, model, api_key="", base_url="", parent=None):
        super().__init__(parent)
        self.provider = provider
        self.model = model
        self.api_key = api_key
        self.base_url = base_url

    def run(self):
        try:
            answer = ask_ollama(
                [{
                    "role": "user",
                    "content": "Combien font 19 × 23 ? Réponds uniquement avec le résultat numérique.",
                }],
                model=self.model,
                timeout=90,
                max_tokens=32,
                api_key=self.api_key or None,
                provider=self.provider,
                base_url=self.base_url if self.provider == "ollama" else None,
            )
            text = str(answer or "").strip()
            self.result_ready.emit({
                "success": bool(re.search(r"(?<!\d)437(?!\d)", text)),
                "answer": text,
                "provider": self.provider,
                "model": self.model,
            })
        except Exception as error:
            self.result_ready.emit({"error": str(error), "provider": self.provider, "model": self.model})


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
        self._task_progress_range = None
        self.utility_task = None
        self.oauth_task = None
        self.git_update_task = None
        self.ollama_task = None
        self._ollama_refresh_after_task = False
        self._ollama_refresh_url = ""
        configured_local_model = model_config(self.config)
        if configured_local_model:
            model_catalog.merge_provider_models("ollama", [{
                "id": configured_local_model,
                "name": configured_local_model,
                "installed": False,
                "chat_compatible": True,
            }])
        configured_cloud_model = str(self.config.get("openrouter", {}).get("model", "")).strip()
        if configured_cloud_model:
            model_catalog.merge_provider_models("openrouter", [{
                "id": configured_cloud_model,
                "name": configured_cloud_model,
                "_configured": True,
                "available": False,
                "chat_compatible": True,
            }])
        self._ollama_catalog = model_catalog.get_provider_models("ollama", chat_only=True)
        self._openrouter_catalog = model_catalog.get_provider_models(
            "openrouter", chat_only=True, available_only=True
        )
        self.provider_test_task = None
        self.git_update_button = None
        self.install_process = None
        self.python_process = None
        self.tool_health_process = None
        self._tool_health_output = ""
        self._tool_health_error_output = ""
        self._tool_health_error_reported = False
        self._tool_health_report = {
            "checks": [],
            "issues": [],
            "checked": 0,
            "passed": 0,
            "stderr": "",
            "exit_code": None,
        }
        self._active_notification_kind = "habit"
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
        self._restore_saved_session()
        self._set_connection_status()
        self.notification_poll_timer = QTimer(self)
        self.notification_poll_timer.setInterval(500)
        self.notification_poll_timer.timeout.connect(self._poll_habit_notifications)
        self.notification_poll_timer.start()
        QTimer.singleShot(1800, self._start_startup_tool_health_check)

    def _new_agent(self):
        config = getattr(self, "config", None) or load_config()
        provider = self._selected_provider(config)
        os.environ["LOCAL_IA_PROVIDER"] = provider
        model = openrouter_model(config) if provider == "openrouter" else model_config(config)
        agent = LocalAgent(model=model)
        return agent

    @staticmethod
    def _selected_provider(config):
        provider = str(config.get("provider", "auto")).strip().casefold()
        if provider in {"ollama", "openrouter"}:
            return provider
        return "openrouter" if openrouter_api_keys() else "ollama"

    @staticmethod
    def _chat_provider_is_ready(provider, api_keys):
        return provider == "ollama" or (provider == "openrouter" and bool(api_keys))

    def _build_ui(self):
        root = QWidget()
        root.setObjectName("root")
        root_layout = QHBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        sidebar = QWidget()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(52)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(5, 14, 5, 14)
        side.setSpacing(0)

        self.conversation_section = QWidget(sidebar)
        conversation_layout = QVBoxLayout(self.conversation_section)
        conversation_layout.setContentsMargins(0, 0, 0, 0)
        conversation_layout.setSpacing(9)
        self.conversation_toggle = QToolButton()
        self.conversation_toggle.setObjectName("conversationToggle")
        self.conversation_toggle.setText("☰")
        self.conversation_toggle.setToolTip("Ouvrir l’historique des conversations")
        self.conversation_toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.conversation_toggle.setFixedSize(42, 42)
        self.conversation_toggle.setArrowType(Qt.ArrowType.RightArrow)
        self.conversation_toggle.setCheckable(True)
        self.conversation_toggle.setChecked(False)
        self.conversation_toggle.toggled.connect(self._toggle_conversation_menu)
        conversation_layout.addWidget(self.conversation_toggle)
        side.addWidget(self.conversation_section)
        side.addStretch(1)

        self.sidebar = sidebar
        self.conversation_drawer = QWidget(root)
        self.conversation_drawer.setObjectName("conversationDrawer")
        self.conversation_drawer_width = 340
        self.conversation_drawer.setMaximumWidth(self.conversation_drawer_width)
        drawer_layout = QVBoxLayout(self.conversation_drawer)
        drawer_layout.setContentsMargins(16, 14, 16, 16)
        drawer_layout.setSpacing(10)
        drawer_header = QHBoxLayout()
        drawer_title = QLabel("Conversations")
        drawer_title.setObjectName("drawerTitle")
        drawer_header.addWidget(drawer_title, stretch=1)
        self.conversation_close_button = QToolButton()
        self.conversation_close_button.setObjectName("notificationClose")
        self.conversation_close_button.setText("×")
        self.conversation_close_button.setToolTip("Fermer l’historique")
        self.conversation_close_button.setAutoRaise(True)
        self.conversation_close_button.clicked.connect(
            lambda: self.conversation_toggle.setChecked(False)
        )
        drawer_header.addWidget(self.conversation_close_button)
        drawer_layout.addLayout(drawer_header)
        self.drawer_new_chat_button = ActionButton(
            "＋   Nouvelle conversation", "drawerNewChatButton"
        )
        self.drawer_new_chat_button.clicked.connect(self._new_chat_from_drawer)
        drawer_layout.addWidget(self.drawer_new_chat_button)
        self.chat_search = QLineEdit()
        self.chat_search.setPlaceholderText("Rechercher une conversation")
        self.chat_search.textChanged.connect(self._refresh_chat_list)
        drawer_layout.addWidget(self.chat_search)
        self.chat_list = QListWidget()
        self.chat_list.setObjectName("chatList")
        self.chat_list.itemActivated.connect(self._open_chat_item)
        self.chat_list.itemClicked.connect(self._open_chat_item)
        drawer_layout.addWidget(self.chat_list, stretch=1)
        self.conversation_drawer.hide()
        self.conversation_drawer_animation = QPropertyAnimation(
            self.conversation_drawer, b"geometry", self
        )
        self.conversation_drawer_animation.setDuration(260)
        self.conversation_drawer_animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.conversation_drawer_animation.finished.connect(
            self._conversation_drawer_animation_finished
        )

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
        root_layout.addWidget(sidebar)

        main = QWidget()
        main.setObjectName("mainPanel")
        main_layout = QVBoxLayout(main)
        main_layout.setContentsMargins(25, 20, 25, 20)
        main_layout.setSpacing(14)
        self.habit_notification_banner = QPushButton(self)
        self.habit_notification_banner.setObjectName("habitNotificationBanner")
        self.habit_notification_banner.setCursor(Qt.CursorShape.PointingHandCursor)
        self.habit_notification_banner.setVisible(False)
        self.habit_notification_banner.setFixedWidth(400)
        banner_layout = QVBoxLayout(self.habit_notification_banner)
        banner_layout.setContentsMargins(14, 9, 14, 9)
        banner_layout.setSpacing(7)
        banner_header = QHBoxLayout()
        self.habit_notification_title = QLabel()
        self.habit_notification_title.setObjectName("habitNotificationTitle")
        banner_header.addWidget(self.habit_notification_title, stretch=1)
        self.habit_notification_close = QToolButton(self.habit_notification_banner)
        self.habit_notification_close.setObjectName("notificationClose")
        self.habit_notification_close.setText("×")
        self.habit_notification_close.setToolTip("Fermer la notification")
        self.habit_notification_close.setAutoRaise(True)
        self.habit_notification_close.clicked.connect(self._dismiss_notification)
        banner_header.addWidget(self.habit_notification_close)
        banner_layout.addLayout(banner_header)
        self.habit_notification_message = QTextBrowser()
        self.habit_notification_message.setObjectName("habitNotificationMessage")
        self.habit_notification_message.setReadOnly(True)
        self.habit_notification_message.setFrameShape(QTextBrowser.Shape.NoFrame)
        self.habit_notification_message.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.habit_notification_message.setFixedHeight(74)
        banner_layout.addWidget(self.habit_notification_message)
        self.habit_notification_banner.clicked.connect(self._open_habits_from_notification)
        self._notification_animation_direction = "in"
        self.notification_animation = QPropertyAnimation(
            self.habit_notification_banner, b"pos", self
        )
        self.notification_animation.setDuration(320)
        self.notification_animation.finished.connect(self._notification_animation_finished)
        self.habit_notification_timer = QTimer(self)
        self.habit_notification_timer.setSingleShot(True)
        self.habit_notification_timer.setInterval(6500)
        self.habit_notification_timer.timeout.connect(self._dismiss_notification)
        header = QHBoxLayout()
        titles = QVBoxLayout()
        self.chat_title = QLabel("Nouvelle conversation")
        self.chat_title.setObjectName("pageTitle")
        self.page_subtitle = QLabel("Les conversations et réglages sont partagés dans KAIRO.")
        self.page_subtitle.setObjectName("subtitle")
        titles.addWidget(self.chat_title)
        titles.addWidget(self.page_subtitle)
        header.addLayout(titles)
        header.addStretch(1)
        self.model_indicator = QLabel()
        self.model_indicator.setObjectName("modelIndicator")
        self.model_indicator.setMaximumWidth(260)
        self.model_indicator.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        header.addWidget(self.model_indicator, alignment=Qt.AlignmentFlag.AlignVCenter)
        self.compare_button = ActionButton("◫  Comparer")
        self.compare_button.setToolTip("Afficher une autre conversation côte à côte")
        self.compare_button.clicked.connect(self._toggle_comparison)
        header.addWidget(self.compare_button)
        self.profile_avatar = QToolButton()
        self.profile_avatar.setObjectName("profileAvatar")
        self.profile_avatar.setFixedSize(38, 38)
        self.profile_avatar.setText("♙")
        self.profile_avatar.setToolTip("Ouvrir le menu du compte")
        self.profile_avatar.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        profile_menu = QMenu(self.profile_avatar)
        account_action = profile_menu.addAction("Compte")
        account_action.triggered.connect(lambda: self._open_settings("Compte"))
        conversations_action = profile_menu.addAction("Conversation")
        conversations_action.triggered.connect(self._manage_conversations)
        settings_action = profile_menu.addAction("Paramètre")
        settings_action.triggered.connect(self._open_settings)
        self.profile_avatar.setMenu(profile_menu)
        header.addWidget(self.profile_avatar, alignment=Qt.AlignmentFlag.AlignVCenter)

        self.tool_navigation = QTabBar()
        self.tool_navigation.setObjectName("toolNavigation")
        self.tool_navigation.setDrawBase(False)
        self.tool_navigation.setExpanding(False)
        self.tool_navigation.setUsesScrollButtons(True)
        self.tool_navigation.setElideMode(Qt.TextElideMode.ElideRight)
        self.tool_navigation.setMinimumHeight(46)
        for label in ("Conversation", "Traducteur", "Habitudes", "Calculatrice", "Web", "Erreurs outils"):
            index = self.tool_navigation.addTab(label)
            self.tool_navigation.setTabToolTip(index, label)
        main_layout.addWidget(self.tool_navigation)
        main_layout.addLayout(header)

        self.workspace_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.workspace_splitter.setObjectName("workspaceSplitter")
        self.chat_panel = QWidget()
        self.chat_panel.setObjectName("chatPanel")
        chat_layout = QVBoxLayout(self.chat_panel)
        chat_layout.setContentsMargins(0, 0, 8, 0)
        chat_layout.setSpacing(12)

        self.chat_content_stack = QStackedWidget()
        self.welcome_page = QWidget()
        self.welcome_page.setObjectName("welcomePage")
        welcome_layout = QVBoxLayout(self.welcome_page)
        welcome_layout.setContentsMargins(20, 20, 20, 20)
        welcome_layout.setSpacing(22)
        welcome_layout.addStretch(1)
        welcome_actions = QHBoxLayout()
        welcome_actions.addStretch(1)
        self.open_conversation_button = QPushButton("Ouvrir une conversation")
        self.open_conversation_button.setObjectName("welcomeSecondaryButton")
        self.open_conversation_button.clicked.connect(self._manage_conversations)
        welcome_actions.addWidget(self.open_conversation_button)
        self.start_conversation_button = QPushButton("Commencer une conversation")
        self.start_conversation_button.setObjectName("welcomePrimaryButton")
        self.start_conversation_button.clicked.connect(self._new_chat)
        welcome_actions.addWidget(self.start_conversation_button)
        welcome_actions.addStretch(1)
        welcome_layout.addLayout(welcome_actions)
        self.welcome_label = QLabel("Ravi de vous revoir, vous")
        self.welcome_label.setObjectName("welcomeGreeting")
        self.welcome_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.welcome_label.setWordWrap(True)
        welcome_layout.addWidget(self.welcome_label)
        welcome_layout.addStretch(1)
        self.chat_content_stack.addWidget(self.welcome_page)

        conversation_page = QWidget()
        conversation_layout = QVBoxLayout(conversation_page)
        conversation_layout.setContentsMargins(0, 0, 0, 0)
        conversation_layout.setSpacing(12)

        self.transcript = QTextBrowser()
        self.transcript.setObjectName("transcript")
        self.transcript.setReadOnly(True)
        self.transcript.setFont(QFont("Noto Sans", 11))
        self.transcript.setOpenExternalLinks(True)
        self._transcript_messages = []
        self.transcript.setMarkdown("*Pose une question ou choisis une action à gauche.*")
        conversation_layout.addWidget(self.transcript, stretch=1)
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
        conversation_layout.addWidget(self.downloads_panel)
        self.notice = QLabel("Prêt")
        self.notice.setObjectName("notice")
        conversation_layout.addWidget(self.notice)
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
        conversation_layout.addLayout(composer)
        self.chat_content_stack.addWidget(conversation_page)
        self.chat_content_stack.setCurrentWidget(self.welcome_page)
        chat_layout.addWidget(self.chat_content_stack, stretch=1)
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
        self.editor_content_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.editor_content_splitter.setObjectName("editorContentSplitter")
        self.editor_content_splitter.addWidget(self.files_section)
        self.editor_content_splitter.addWidget(self.editor_tabs)
        self.editor_content_splitter.setStretchFactor(0, 1)
        self.editor_content_splitter.setStretchFactor(1, 3)
        self.editor_content_splitter.setSizes([210, 590])
        editor_layout.addWidget(self.editor_content_splitter, stretch=1)
        self.editor_status = QLabel("Aucun fichier ouvert")
        self.editor_status.setObjectName("editorStatus")
        editor_layout.addWidget(self.editor_status)
        self.workspace_splitter.addWidget(self.editor_panel)
        self.compare_panel = QWidget()
        self.compare_panel.setObjectName("comparePanel")
        compare_layout = QVBoxLayout(self.compare_panel)
        compare_layout.setContentsMargins(8, 0, 0, 0)
        compare_layout.setSpacing(10)
        compare_header = QHBoxLayout()
        self.compare_title = QLabel("Conversation à comparer")
        self.compare_title.setObjectName("editorFileLabel")
        compare_header.addWidget(self.compare_title, stretch=1)
        self.compare_chat_picker = QComboBox()
        self.compare_chat_picker.setMinimumWidth(180)
        self.compare_chat_picker.currentIndexChanged.connect(self._render_comparison_chat)
        compare_header.addWidget(self.compare_chat_picker)
        compare_layout.addLayout(compare_header)
        self.compare_transcript = QTextBrowser()
        self.compare_transcript.setObjectName("transcript")
        self.compare_transcript.setReadOnly(True)
        self.compare_transcript.setOpenExternalLinks(True)
        compare_layout.addWidget(self.compare_transcript, stretch=1)
        self.compare_panel.hide()
        self.workspace_splitter.addWidget(self.compare_panel)
        self.workspace_splitter.setStretchFactor(0, 3)
        self.workspace_splitter.setStretchFactor(1, 2)
        self.workspace_splitter.setStretchFactor(2, 2)
        self.workspace_splitter.setSizes([690, 520, 0])
        self.tool_page_stack = QStackedWidget()
        self.tool_page_stack.addWidget(self.workspace_splitter)
        self._build_translator_page()
        self._build_habits_page()
        self._build_calculator_page()
        self._build_web_page()
        self._build_tool_health_page()
        self.tool_navigation.currentChanged.connect(self._select_tool_page)
        main_layout.addWidget(self.tool_page_stack, stretch=1)
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
        self.new_chat_shortcut = QShortcut(QKeySequence("Ctrl+T"), self)
        self.new_chat_shortcut.activated.connect(self._new_chat)
        self.new_chat_alt_shortcut = QShortcut(QKeySequence("Ctrl+N"), self)
        self.new_chat_alt_shortcut.activated.connect(self._new_chat)
        self.close_shortcut = QShortcut(QKeySequence("Ctrl+W"), self)
        self.close_shortcut.activated.connect(self._close_current_view)
        self.search_shortcut = QShortcut(QKeySequence("Ctrl+F"), self)
        self.search_shortcut.activated.connect(self._open_conversation_search)
        self.prompt_shortcut = QShortcut(QKeySequence("Ctrl+L"), self)
        self.prompt_shortcut.activated.connect(self.prompt.setFocus)

    def _new_tool_page(self, title):
        page = QWidget()
        page.setObjectName("toolPage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(8, 12, 8, 8)
        layout.setSpacing(12)
        heading = QLabel(title)
        heading.setObjectName("pageTitle")
        layout.addWidget(heading)
        return page, layout

    def _build_translator_page(self):
        page, layout = self._new_tool_page("Traducteur")
        languages = QFormLayout()
        self.translation_source = QLineEdit("auto")
        self.translation_target = QLineEdit()
        self.translation_target.setPlaceholderText("Langue cible")
        languages.addRow("Langue source", self.translation_source)
        languages.addRow("Langue cible", self.translation_target)
        layout.addLayout(languages)

        layout.addWidget(QLabel("Texte"))
        self.translation_input = QPlainTextEdit()
        self.translation_input.setPlaceholderText("Texte à traduire")
        layout.addWidget(self.translation_input, stretch=2)
        self.translate_button = ActionButton("Traduire", "sendButton")
        self.translate_button.clicked.connect(self._translate_text)
        layout.addWidget(self.translate_button, alignment=Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(QLabel("Traduction"))
        self.translation_output = QPlainTextEdit()
        self.translation_output.setReadOnly(True)
        layout.addWidget(self.translation_output, stretch=2)
        self.tool_page_stack.addWidget(page)

    def _build_habits_page(self):
        page, layout = self._new_tool_page("Habitudes")
        columns = QHBoxLayout()
        columns.setSpacing(24)
        creation = QVBoxLayout()
        creation.setSpacing(12)
        creation.addWidget(QLabel("Nouvelle habitude"))
        self.habit_task_input = QLineEdit()
        self.habit_task_input.setPlaceholderText("Nom de l’habitude")
        creation.addWidget(self.habit_task_input)
        self.habit_frequency = QComboBox()
        for label, value in (("Chaque jour", "daily"), ("Chaque semaine", "weekly"), ("Chaque mois", "monthly")):
            self.habit_frequency.addItem(label, value)
        creation.addWidget(self.habit_frequency)
        self.habit_time_input = QLineEdit()
        self.habit_time_input.setPlaceholderText("Heure (HH:MM), facultative")
        creation.addWidget(self.habit_time_input)
        self.add_habit_button = ActionButton("Ajouter", "sendButton")
        self.add_habit_button.clicked.connect(self._add_habit)
        creation.addWidget(self.add_habit_button)
        creation.addStretch(1)
        columns.addLayout(creation, stretch=1)

        divider = QWidget()
        divider.setFixedWidth(1)
        divider.setStyleSheet("background: palette(mid);")
        columns.addWidget(divider)

        collection = QVBoxLayout()
        collection.setSpacing(10)
        list_header = QHBoxLayout()
        list_header.addWidget(QLabel("Mes habitudes"))
        list_header.addStretch(1)
        self.habit_summary = QLabel("0 habitude")
        self.habit_summary.setObjectName("mutedText")
        list_header.addWidget(self.habit_summary)
        collection.addLayout(list_header)

        self.habits_list = QListWidget()
        self.habits_list.setObjectName("toolList")
        self.habits_list.currentRowChanged.connect(self._update_habit_action_buttons)
        collection.addWidget(self.habits_list, stretch=1)
        actions = QHBoxLayout()
        self.test_habit_button = QPushButton("Tester l'habitude")
        self.test_habit_button.clicked.connect(self._test_selected_habit)
        actions.addWidget(self.test_habit_button)
        self.complete_habit_button = QPushButton("Marquer terminée")
        self.complete_habit_button.clicked.connect(lambda: self._run_selected_habit_action("complete"))
        self.delete_habit_button = QPushButton("Supprimer")
        self.delete_habit_button.clicked.connect(lambda: self._run_selected_habit_action("delete"))
        actions.addWidget(self.complete_habit_button)
        actions.addWidget(self.delete_habit_button)
        actions.addStretch(1)
        collection.addLayout(actions)

        weather = QHBoxLayout()
        self.habit_city_input = QLineEdit()
        self.habit_city_input.setPlaceholderText("Ville météo")
        weather.addWidget(self.habit_city_input, stretch=1)
        self.save_habit_city_button = QPushButton("Ville")
        self.save_habit_city_button.clicked.connect(self._save_habit_city)
        weather.addWidget(self.save_habit_city_button)
        self.habit_weather_button = QPushButton("Météo")
        self.habit_weather_button.clicked.connect(self._get_habit_weather)
        weather.addWidget(self.habit_weather_button)
        collection.addLayout(weather)
        self.habit_weather_output = QLabel()
        self.habit_weather_output.setWordWrap(True)
        collection.addWidget(self.habit_weather_output)
        columns.addLayout(collection, stretch=2)
        layout.addLayout(columns, stretch=1)
        self._update_habit_action_buttons()
        self.tool_page_stack.addWidget(page)

    def _build_calculator_page(self):
        page, layout = self._new_tool_page("Calculatrice")
        calculator = QWidget()
        calculator.setMaximumWidth(460)
        calculator_layout = QVBoxLayout(calculator)
        calculator_layout.setContentsMargins(0, 0, 0, 0)
        calculator_layout.setSpacing(8)
        self.calculator_history = QLabel("")
        self.calculator_history.setObjectName("mutedText")
        self.calculator_history.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        calculator_layout.addWidget(self.calculator_history)
        self.calculator_display = QLineEdit("0")
        self.calculator_display.setObjectName("calculatorDisplay")
        self.calculator_display.setReadOnly(True)
        self.calculator_display.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.calculator_display.setMinimumHeight(68)
        self.calculator_display.setFont(QFont("Noto Sans", 28, QFont.Weight.DemiBold))
        calculator_layout.addWidget(self.calculator_display)

        memory_row = QHBoxLayout()
        for label, action in (("MC", "memory_clear"), ("MR", "memory_recall"), ("M+", "memory_add"), ("M-", "memory_subtract"), ("MS", "memory_store")):
            button = QPushButton(label)
            button.setObjectName("calculatorMemoryKey")
            button.clicked.connect(lambda _checked=False, selected=action: self._calculator_press(selected))
            memory_row.addWidget(button)
        calculator_layout.addLayout(memory_row)

        keypad = QGridLayout()
        keypad.setSpacing(7)
        keys = (
            ("%", "CE", "C", "⌫"),
            ("1/x", "x²", "√x", "÷"),
            ("7", "8", "9", "×"),
            ("4", "5", "6", "−"),
            ("1", "2", "3", "+"),
            ("±", "0", ".", "="),
        )
        for row_index, row_keys in enumerate(keys):
            for column_index, key in enumerate(row_keys):
                button = QPushButton(key)
                button.setObjectName("calculatorEqualsKey" if key == "=" else "calculatorOperatorKey" if key in {"%", "CE", "C", "⌫", "1/x", "x²", "√x", "÷", "×", "−", "+", "±"} else "calculatorDigitKey")
                button.setMinimumSize(64, 48)
                button.clicked.connect(lambda _checked=False, selected=key: self._calculator_press(selected))
                keypad.addWidget(button, row_index, column_index)
        calculator_layout.addLayout(keypad)
        calculator_layout.addStretch(1)
        layout.addWidget(calculator, alignment=Qt.AlignmentFlag.AlignHCenter)
        layout.addStretch(1)
        keyboard_keys = {
            **{str(value): str(value) for value in range(10)},
            ".": ".", "+": "+", "-": "−", "*": "×", "/": "÷",
            "%": "%", "Return": "=", "Enter": "=", "Backspace": "⌫",
            "Escape": "C",
        }
        for key, action in keyboard_keys.items():
            shortcut = QShortcut(QKeySequence(key), calculator)
            shortcut.activated.connect(lambda selected=action: self._calculator_press(selected))
        self._calculator_accumulator = None
        self._calculator_operator = None
        self._calculator_new_entry = True
        self._calculator_memory = 0.0
        self.tool_page_stack.addWidget(page)

    def _build_web_page(self):
        page = QWidget()
        page.setObjectName("toolPage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        toolbar = QHBoxLayout()
        toolbar.setSpacing(6)
        self.browser_back_button = QPushButton("←")
        self.browser_back_button.setToolTip("Page précédente")
        self.browser_back_button.setEnabled(False)
        self.browser_back_button.clicked.connect(lambda: self.browser_view.back())
        toolbar.addWidget(self.browser_back_button)
        self.browser_forward_button = QPushButton("→")
        self.browser_forward_button.setToolTip("Page suivante")
        self.browser_forward_button.setEnabled(False)
        self.browser_forward_button.clicked.connect(lambda: self.browser_view.forward())
        toolbar.addWidget(self.browser_forward_button)
        reload_button = QPushButton("↻")
        reload_button.setToolTip("Actualiser")
        reload_button.clicked.connect(lambda: self.browser_view.reload())
        toolbar.addWidget(reload_button)
        home_button = QPushButton("⌂")
        home_button.setToolTip("Accueil")
        home_button.clicked.connect(self._browser_home)
        toolbar.addWidget(home_button)
        self.browser_search_engine = QComboBox()
        self.browser_search_engine.addItem("DuckDuckGo", "https://duckduckgo.com/?q=")
        self.browser_search_engine.addItem("Google", "https://www.google.com/search?q=")
        self.browser_search_engine.addItem("Brave", "https://search.brave.com/search?q=")
        toolbar.addWidget(self.browser_search_engine)
        self.web_query_input = QLineEdit()
        self.web_query_input.setObjectName("browserAddressBar")
        self.web_query_input.setPlaceholderText("Adresse ou recherche")
        self.web_query_input.returnPressed.connect(self._search_web)
        toolbar.addWidget(self.web_query_input, stretch=1)
        layout.addLayout(toolbar)
        self.browser_view = QWebEngineView()
        self.browser_view.setObjectName("webView")
        self.browser_view.urlChanged.connect(self._browser_url_changed)
        self.browser_view.loadFinished.connect(self._browser_load_finished)
        layout.addWidget(self.browser_view, stretch=1)
        self._browser_started = False
        self.tool_page_stack.addWidget(page)

    def _build_tool_health_page(self):
        page, layout = self._new_tool_page("Erreurs outils")
        toolbar = QHBoxLayout()
        self.tool_health_summary = QLabel("Aucun diagnostic exécuté.")
        self.tool_health_summary.setObjectName("mutedText")
        toolbar.addWidget(self.tool_health_summary, stretch=1)
        self.tool_health_refresh_button = ActionButton("Relancer le diagnostic")
        self.tool_health_refresh_button.clicked.connect(self._start_startup_tool_health_check)
        toolbar.addWidget(self.tool_health_refresh_button)
        layout.addLayout(toolbar)

        details = QSplitter(Qt.Orientation.Horizontal)
        self.tool_health_table = QTableWidget(0, 3)
        self.tool_health_table.setObjectName("toolHealthTable")
        self.tool_health_table.setHorizontalHeaderLabels(("Outil", "État", "Explication"))
        self.tool_health_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tool_health_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tool_health_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tool_health_table.verticalHeader().hide()
        self.tool_health_table.horizontalHeader().setStretchLastSection(True)
        self.tool_health_table.currentCellChanged.connect(self._show_selected_tool_health_log)
        details.addWidget(self.tool_health_table)

        log_panel = QWidget()
        log_layout = QVBoxLayout(log_panel)
        log_layout.setContentsMargins(8, 0, 0, 0)
        log_layout.addWidget(QLabel("Log détaillé"))
        self.tool_health_log = QPlainTextEdit()
        self.tool_health_log.setObjectName("toolHealthLog")
        self.tool_health_log.setReadOnly(True)
        self.tool_health_log.setPlaceholderText("Sélectionne un outil pour consulter son résultat détaillé.")
        log_layout.addWidget(self.tool_health_log, stretch=1)
        details.addWidget(log_panel)
        details.setStretchFactor(0, 2)
        details.setStretchFactor(1, 3)
        layout.addWidget(details, stretch=1)
        self.tool_page_stack.addWidget(page)
        self._render_tool_health_report()

    def _select_tool_page(self, index):
        self.tool_page_stack.setCurrentIndex(index)
        titles = ("Nouvelle conversation", "Traducteur", "Habitudes", "Calculatrice", "Navigateur Web", "Erreurs outils")
        subtitles = (
            "Votre espace de discussion avec KAIRO",
            "",
            "",
            "",
            "",
            "",
        )
        self.chat_title.setText(titles[index])
        if index == 0:
            self._apply_mode(self.code_mode_active)
        else:
            self.page_subtitle.setText(subtitles[index])
        if index == 2:
            self._refresh_habits()
        elif index == 4 and not self._browser_started:
            self._browser_home()
        elif index == 5:
            self._render_tool_health_report()

    def _poll_habit_notifications(self):
        try:
            events = app_notifications.consume(self.connection)
        except Exception:
            return
        if not events:
            return
        habit_events = [event for event in events if event.get("kind") == "habit"]
        conversation_updated = False
        for event in habit_events:
            add_chat_message(
                self.chat,
                "assistant",
                f"Habitude · {event.get('title', 'KAIRO')}\n{event.get('message', '')}",
            )
            conversation_updated = True
        known_kinds = {"habit", "tool_health"}
        for event in events:
            if event.get("kind") not in known_kinds:
                add_chat_message(
                    self.chat,
                    "assistant",
                    f"{event.get('title', 'Notification KAIRO')}\n{event.get('message', '')}",
                )
                conversation_updated = True
        if conversation_updated:
            self._load_chat_into_view()
        self._refresh_chat_list()
        event = events[-1]
        self._active_notification_kind = event.get("kind", "habit")
        if self._active_notification_kind == "tool_health":
            title = str(event.get("title", "Diagnostic des outils"))
        elif self._active_notification_kind == "habit":
            title = f"Habitude · {event.get('title', 'KAIRO')}"
        else:
            title = str(event.get("title", "Notification KAIRO"))
        self.habit_notification_title.setText(title)
        self.habit_notification_message.setPlainText(str(event.get("message", "")))
        self._show_notification()

    def _open_habits_from_notification(self):
        self._dismiss_notification()
        self.page_stack.setCurrentIndex(0)
        page_index = 5 if self._active_notification_kind == "tool_health" else 2 if self._active_notification_kind == "habit" else 0
        self.tool_navigation.setCurrentIndex(page_index)

    def _show_notification(self):
        banner = self.habit_notification_banner
        self.habit_notification_timer.stop()
        self.notification_animation.stop()
        banner.setFixedWidth(max(280, min(420, self.width() - 32)))
        banner.adjustSize()
        banner.layout().activate()
        banner.setFixedHeight(max(112, banner.layout().sizeHint().height()))
        target = QPoint(max(16, self.width() - banner.width() - 20), 16)
        start = QPoint(self.width() + 16, target.y())
        banner.move(start)
        banner.show()
        banner.raise_()
        self._notification_animation_direction = "in"
        self.notification_animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.notification_animation.setStartValue(start)
        self.notification_animation.setEndValue(target)
        self.notification_animation.start()
        self.habit_notification_timer.start()

    def _dismiss_notification(self):
        banner = self.habit_notification_banner
        self.habit_notification_timer.stop()
        if not banner.isVisible():
            return
        self.notification_animation.stop()
        self._notification_animation_direction = "out"
        self.notification_animation.setEasingCurve(QEasingCurve.Type.InCubic)
        self.notification_animation.setStartValue(banner.pos())
        self.notification_animation.setEndValue(QPoint(self.width() + 16, banner.y()))
        self.notification_animation.start()

    def _notification_animation_finished(self):
        if self._notification_animation_direction == "out":
            self.habit_notification_banner.hide()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        banner = getattr(self, "habit_notification_banner", None)
        if (
            banner is not None
            and banner.isVisible()
            and self._notification_animation_direction != "out"
        ):
            banner.move(QPoint(max(16, self.width() - banner.width() - 20), 16))
        drawer = getattr(self, "conversation_drawer", None)
        toggle = getattr(self, "conversation_toggle", None)
        if drawer is not None and toggle is not None and toggle.isChecked():
            drawer.setGeometry(
                self.sidebar.width(),
                12,
                self.conversation_drawer_width,
                max(120, self.centralWidget().widget(0).height() - 24),
            )

    def _start_startup_tool_health_check(self):
        if self.tool_health_process is not None and self.tool_health_process.state() != QProcess.ProcessState.NotRunning:
            return
        self.tool_health_summary.setText("Diagnostic des outils en cours…")
        self.tool_health_refresh_button.setEnabled(False)
        self._tool_health_output = ""
        self._tool_health_error_output = ""
        self._tool_health_error_reported = False
        process = QProcess(self)
        process.setWorkingDirectory(str(Path(__file__).resolve().parents[1]))
        process.setProgram(sys.executable)
        process.setArguments(["-m", "local_ia.core.tool_health"])
        process.setProcessEnvironment(self._tool_health_process_environment())
        process.setProcessChannelMode(QProcess.ProcessChannelMode.SeparateChannels)
        process.readyReadStandardOutput.connect(self._read_tool_health_output)
        process.readyReadStandardError.connect(self._read_tool_health_error)
        process.finished.connect(self._startup_tool_health_finished)
        process.errorOccurred.connect(self._startup_tool_health_process_error)
        self.tool_health_process = process
        process.start()

    def _tool_health_process_environment(self):
        environment = QProcessEnvironment.systemEnvironment()
        api_keys = openrouter_api_keys()
        if not api_keys:
            try:
                saved_session = accounts.load_saved_session()
            except Exception:
                saved_session = None
            api_keys = saved_session[1] if saved_session else []
        if api_keys:
            environment.insert("LOCAL_IA_OPENROUTER_KEYS", json.dumps(api_keys))
        environment.insert("LOCAL_IA_OPENROUTER_BASE_URL", openrouter_base_url(self.config))
        environment.insert("LOCAL_IA_OPENROUTER_MODEL", openrouter_model(self.config))
        return environment

    def _read_tool_health_output(self):
        if self.tool_health_process is not None:
            self._tool_health_output += bytes(
                self.tool_health_process.readAllStandardOutput()
            ).decode("utf-8", errors="replace")

    def _read_tool_health_error(self):
        if self.tool_health_process is not None:
            self._tool_health_error_output += bytes(
                self.tool_health_process.readAllStandardError()
            ).decode("utf-8", errors="replace")[-4000:]

    def _startup_tool_health_process_error(self, error):
        if error == QProcess.ProcessError.FailedToStart and not self._tool_health_error_reported:
            self._tool_health_error_reported = True
            issue = {
                "tool": "startup",
                "status": "failed",
                "detail": "Impossible de démarrer le processus de diagnostic.",
            }
            self._tool_health_report = {
                "checks": [issue],
                "issues": [issue],
                "checked": 0,
                "passed": 0,
                "stderr": self._tool_health_error_output,
                "exit_code": None,
            }
            self.tool_health_refresh_button.setEnabled(True)
            self._render_tool_health_report()
            self._publish_tool_health_issues([issue], checked=0)

    def _startup_tool_health_finished(self, exit_code, _exit_status):
        self._read_tool_health_output()
        self._read_tool_health_error()
        if self._tool_health_error_reported:
            return
        try:
            result = json.loads(self._tool_health_output)
            if not isinstance(result, dict):
                raise ValueError("Le diagnostic n'a pas renvoyé un objet JSON.")
        except (json.JSONDecodeError, ValueError) as error:
            detail = f"Résultat du diagnostic illisible : {error}."
            if self._tool_health_error_output.strip():
                detail += f"\n{self._tool_health_error_output.strip()[-1200:]}"
            issue = {"tool": "startup", "status": "failed", "detail": detail}
            self._tool_health_report = {
                "checks": [issue],
                "issues": [issue],
                "checked": 0,
                "passed": 0,
                "stderr": self._tool_health_error_output,
                "exit_code": exit_code,
            }
            self.tool_health_refresh_button.setEnabled(True)
            self._render_tool_health_report()
            self._publish_tool_health_issues([issue], checked=0)
            return
        issues = result.get("issues", [])
        checks = list(result.get("checks", []))
        if exit_code != 0 and not issues:
            issue = {
                "tool": "startup",
                "status": "failed",
                "detail": self._tool_health_error_output.strip() or f"Le processus s'est terminé avec le code {exit_code}.",
            }
            issues = [issue]
            checks.append(issue)
        self._tool_health_report = {
            **result,
            "checks": checks,
            "issues": issues,
            "stderr": self._tool_health_error_output,
            "exit_code": exit_code,
        }
        self.tool_health_refresh_button.setEnabled(True)
        self._render_tool_health_report()
        if issues:
            self._publish_tool_health_issues(issues, checked=result.get("checked", 0))

    def _render_tool_health_report(self):
        report = self._tool_health_report
        checks = list(report.get("checks") or [])
        if not checks:
            checks = list(report.get("issues") or [])
        self._tool_health_rows = checks
        self.tool_health_table.setRowCount(0)
        self.tool_health_table.blockSignals(True)
        for check in checks:
            row = self.tool_health_table.rowCount()
            self.tool_health_table.insertRow(row)
            status = str(check.get("status", "failed" if check in report.get("issues", []) else "unknown"))
            status_label = {"ok": "Réussi", "blocked": "Bloqué", "failed": "Échec"}.get(status, status)
            raw_detail = str(check.get("detail", "Aucun détail fourni."))
            if status == "ok":
                explanation = raw_detail
            else:
                problem = tool_health_diagnostics.explain_tool_problem(
                    raw_detail,
                    check.get("traceback", ""),
                    report.get("stderr", ""),
                    status,
                )
                explanation = f"{problem['title']} · {problem['message']}"
            values = (
                str(check.get("tool", "outil")),
                status_label,
                explanation,
            )
            if status == "failed":
                row_background = QColor("#5a2528")
                row_foreground = QColor("#ffe2e3")
            elif status == "blocked":
                row_background = QColor("#55441f")
                row_foreground = QColor("#ffedc2")
            else:
                row_background = None
                row_foreground = None
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if row_background is not None and row_foreground is not None:
                    item.setBackground(row_background)
                    item.setForeground(row_foreground)
                if column == 2:
                    item.setToolTip(raw_detail)
                self.tool_health_table.setItem(row, column, item)
        self.tool_health_table.blockSignals(False)

        checked = int(report.get("checked", len(checks)) or 0)
        passed = int(report.get("passed", 0) or 0)
        issues = report.get("issues", [])
        if not checked and not checks:
            self.tool_health_summary.setText("Aucun diagnostic exécuté.")
        else:
            summary = f"{passed} outil(s) validé(s) sur {checked} contrôlé(s) · {len(issues)} problème(s)"
            if report.get("exit_code") is not None:
                summary += f" · code de sortie {report['exit_code']}"
            self.tool_health_summary.setText(summary)
        if checks:
            self.tool_health_table.selectRow(0)
            self._show_selected_tool_health_log()
        else:
            self.tool_health_log.clear()

    def _show_selected_tool_health_log(self, *_args):
        row = self.tool_health_table.currentRow()
        if not 0 <= row < len(self._tool_health_rows):
            self.tool_health_log.clear()
            return
        check = self._tool_health_rows[row]
        status = str(check.get("status", "failed" if check in self._tool_health_report.get("issues", []) else "unknown"))
        details = [f"Outil : {check.get('tool', 'outil')}", f"État : {status}", ""]
        if status != "ok":
            problem = tool_health_diagnostics.explain_tool_problem(
                check.get("detail", ""),
                check.get("traceback", ""),
                self._tool_health_report.get("stderr", ""),
                status,
            )
            details.extend((
                f"{problem['title']}\n{problem['message']}",
                f"À essayer : {problem['action']}",
                "",
                "Log brut :",
                str(check.get("detail", "Aucun détail fourni.")),
            ))
        else:
            details.extend(("Résultat :", str(check.get("detail", "Aucun détail fourni."))))
        if check.get("traceback"):
            details.extend(("", "Trace complète :", str(check["traceback"])))
        if self._tool_health_report.get("stderr"):
            details.extend(("", "Sortie d’erreur du processus :", str(self._tool_health_report["stderr"])))
        self.tool_health_log.setPlainText("\n".join(details))

    def _publish_tool_health_issues(self, issues, checked):
        details = [
            f"- {item.get('tool', 'outil')} : {item.get('detail', 'échec inconnu')}"
            for item in issues[:6]
        ]
        if len(issues) > len(details):
            details.append(f"- et {len(issues) - len(details)} autre(s) problème(s)")
        message = f"{len(issues)} outil(s) en échec ou bloqué(s) sur {checked} contrôlé(s).\n" + "\n".join(details)
        app_notifications.publish(
            self.connection,
            "tool_health",
            "Diagnostic des outils KAIRO",
            message,
        )

    def _run_tool_page_action(self, tool_name, arguments, callback):
        if self.utility_task is not None and self.utility_task.isRunning():
            self.notice.setText("Une action est déjà en cours.")
            return
        task = ToolPageTask(tool_name, arguments, self)
        self.utility_task = task
        task.completed.connect(
            lambda success, result: self._finish_tool_page_action(task, callback, success, result)
        )
        task.finished.connect(task.deleteLater)
        self.notice.setText("Action en cours…")
        task.start()

    def _finish_tool_page_action(self, task, callback, success, result):
        if self.utility_task is task:
            self.utility_task = None
        self.notice.setText("Prêt" if success else f"Erreur : {result}")
        callback(success, result)

    def _translate_text(self):
        text = self.translation_input.toPlainText().strip()
        target = self.translation_target.text().strip()
        if not text or not target:
            self.translation_output.setPlainText("Saisis un texte et une langue cible.")
            return
        self.translate_button.setEnabled(False)

        def finished(success, result):
            self.translate_button.setEnabled(True)
            self.translation_output.setPlainText(
                result.get("translation", "") if success and isinstance(result, dict) else str(result)
            )

        self._run_tool_page_action("translate", {
            "text": text,
            "target_language": target,
            "source_language": self.translation_source.text().strip() or "auto",
        }, finished)

    def _refresh_habits(self):
        self._run_tool_page_action("habits", {"action": "list"}, self._show_habits)

    def _show_habits(self, success, result):
        if not success or not isinstance(result, dict):
            self.habit_weather_output.setText(str(result))
            return
        self.habits_list.clear()
        for habit in result.get("habits", []):
            frequency = habit.get("frequency", "daily")
            frequency = {"daily": "Chaque jour", "weekly": "Chaque semaine", "monthly": "Chaque mois"}.get(frequency, frequency)
            time = f" · {habit['time']}" if habit.get("time") else ""
            status = "" if habit.get("active", True) else " · désactivée"
            item = QListWidgetItem(f"{habit.get('task', 'Habitude')} · {frequency}{time}{status}")
            item.setData(Qt.ItemDataRole.UserRole, habit.get("task", ""))
            self.habits_list.addItem(item)
        total = len(result.get("habits", []))
        active = sum(bool(habit.get("active", True)) for habit in result.get("habits", []))
        self.habit_summary.setText(f"{total} habitude(s) · {active} active(s)")
        self.habit_city_input.setText(result.get("city", ""))
        self._update_habit_action_buttons()

    def _update_habit_action_buttons(self, *_):
        has_selection = self.habits_list.currentItem() is not None
        self.test_habit_button.setEnabled(has_selection)
        self.complete_habit_button.setEnabled(has_selection)
        self.delete_habit_button.setEnabled(has_selection)

    def _test_selected_habit(self):
        item = self.habits_list.currentItem()
        if item is None:
            return
        if self.utility_task is not None and self.utility_task.isRunning():
            self.notice.setText("Une action est déjà en cours.")
            return

        task = item.data(Qt.ItemDataRole.UserRole)
        self.test_habit_button.setEnabled(False)
        self.habit_weather_output.setText("Génération de l'aperçu…")

        def finished(success, result):
            self.test_habit_button.setEnabled(self.habits_list.currentItem() is not None)
            preview = result.get("preview", "") if success and isinstance(result, dict) else str(result)
            self.habit_weather_output.setText(str(preview))

        self._run_tool_page_action("habits", {"action": "preview", "task": task}, finished)

    def _add_habit(self):
        task = self.habit_task_input.text().strip()
        if not task:
            self.habit_weather_output.setText("Indique le nom de l’habitude.")
            return
        habit = {
            "task": task,
            "frequency": self.habit_frequency.currentData(),
            "time": self.habit_time_input.text().strip() or None,
        }

        def finished(success, result):
            self.habit_weather_output.setText(
                "Habitude ajoutée." if success else str(result)
            )
            if success:
                self.habit_task_input.clear()
                self.habit_time_input.clear()
                self._refresh_habits()

        self._run_tool_page_action("habits", {"action": "add", "habit": habit}, finished)

    def _run_selected_habit_action(self, action):
        item = self.habits_list.currentItem()
        if item is None:
            return

        def finished(success, result):
            self.habit_weather_output.setText(
                "Habitude mise à jour." if success else str(result)
            )
            if success:
                self._refresh_habits()

        self._run_tool_page_action("habits", {
            "action": action,
            "task": item.data(Qt.ItemDataRole.UserRole),
        }, finished)

    def _save_habit_city(self):
        city = self.habit_city_input.text().strip()
        self._run_tool_page_action(
            "habits", {"action": "set_city", "city": city},
            lambda success, result: self.habit_weather_output.setText(
                "Ville enregistrée." if success else str(result)
            ),
        )

    def _get_habit_weather(self):
        self._run_tool_page_action(
            "habits", {"action": "weather_now"},
            lambda success, result: self.habit_weather_output.setText(
                result.get("weather", "") if success and isinstance(result, dict) else str(result)
            ),
        )

    @staticmethod
    def _calculator_format(value):
        return format(value, ".12g")

    def _calculator_value(self):
        try:
            return float(self.calculator_display.text())
        except ValueError:
            return 0.0

    def _calculator_apply_pending(self, right):
        left = self._calculator_accumulator
        operation = self._calculator_operator
        if left is None or operation is None:
            return right
        if operation == "+":
            return left + right
        if operation == "−":
            return left - right
        if operation == "×":
            return left * right
        if operation == "÷":
            if right == 0:
                raise ZeroDivisionError("Division par zéro impossible.")
            return left / right
        return right

    def _calculator_press(self, key):
        if key in {"memory_clear", "memory_recall", "memory_add", "memory_subtract", "memory_store"}:
            value = self._calculator_value()
            if key == "memory_clear":
                self._calculator_memory = 0.0
            elif key == "memory_recall":
                self.calculator_display.setText(self._calculator_format(self._calculator_memory))
                self._calculator_new_entry = True
            elif key == "memory_add":
                self._calculator_memory += value
            elif key == "memory_subtract":
                self._calculator_memory -= value
            else:
                self._calculator_memory = value
            return

        if key.isdigit() or key == ".":
            current = self.calculator_display.text()
            if self._calculator_new_entry or current == "Erreur":
                current = "0"
            if key == ".":
                if "." not in current:
                    current += "."
            elif current == "0":
                current = key
            else:
                current += key
            self.calculator_display.setText(current)
            self._calculator_new_entry = False
            return

        value = self._calculator_value()
        if key == "C":
            self._calculator_accumulator = None
            self._calculator_operator = None
            self.calculator_history.clear()
            self.calculator_display.setText("0")
            self._calculator_new_entry = True
            return
        if key == "CE":
            self.calculator_display.setText("0")
            self._calculator_new_entry = True
            return
        if key == "⌫":
            if not self._calculator_new_entry:
                current = self.calculator_display.text()
                current = current[:-1] if len(current) > 1 else "0"
                self.calculator_display.setText("-0" if current == "-" else current)
            return
        if key == "±":
            self.calculator_display.setText(self._calculator_format(-value))
            return
        if key == "%":
            if self._calculator_accumulator is not None and self._calculator_operator in {"+", "−"}:
                value = self._calculator_accumulator * value / 100
            else:
                value /= 100
        elif key == "1/x":
            if value == 0:
                self.calculator_display.setText("Erreur")
                self._calculator_new_entry = True
                return
            value = 1 / value
        elif key == "x²":
            value **= 2
        elif key == "√x":
            if value < 0:
                self.calculator_display.setText("Erreur")
                self._calculator_new_entry = True
                return
            value **= 0.5
        elif key in {"+", "−", "×", "÷"}:
            if self._calculator_operator and not self._calculator_new_entry:
                try:
                    value = self._calculator_apply_pending(value)
                except ZeroDivisionError:
                    self.calculator_display.setText("Erreur")
                    self._calculator_accumulator = None
                    self._calculator_operator = None
                    self._calculator_new_entry = True
                    return
                self.calculator_display.setText(self._calculator_format(value))
            self._calculator_accumulator = value
            self._calculator_operator = key
            self.calculator_history.setText(f"{self._calculator_format(value)} {key}")
            self._calculator_new_entry = True
            return
        elif key == "=":
            if self._calculator_operator is None:
                return
            left = self._calculator_accumulator
            operation = self._calculator_operator
            right = value
            try:
                value = self._calculator_apply_pending(right)
            except ZeroDivisionError:
                self.calculator_display.setText("Erreur")
                self._calculator_accumulator = None
                self._calculator_operator = None
                self._calculator_new_entry = True
                return
            self.calculator_history.setText(
                f"{self._calculator_format(left)} {operation} {self._calculator_format(right)} ="
            )
            self._calculator_accumulator = None
            self._calculator_operator = None
            self.calculator_display.setText(self._calculator_format(value))
            self._calculator_new_entry = True
            return
        else:
            return

        self.calculator_display.setText(self._calculator_format(value))
        self._calculator_new_entry = True

    def _calculate_expression(self):
        self._calculator_press("=")

    def _browser_home(self):
        search_url = self.browser_search_engine.currentData()
        homepage = search_url.split("?", 1)[0]
        self.browser_view.setUrl(QUrl(homepage))
        self._browser_started = True

    def _search_web(self):
        entry = self.web_query_input.text().strip()
        if not entry:
            return
        address_pattern = r"^(?:https?://|www\.|localhost(?::\d+)?(?:/|$)|(?:[\w-]+\.)+[a-z]{2,}(?::\d+)?(?:/|$))"
        if re.match(address_pattern, entry, re.I) and not re.search(r"\s", entry):
            url = QUrl.fromUserInput(entry)
        else:
            url = QUrl(self.browser_search_engine.currentData() + quote_plus(entry))
        self.browser_view.setUrl(url)
        self._browser_started = True

    def _browser_url_changed(self, url):
        self.web_query_input.setText(url.toString())

    def _browser_load_finished(self, loaded):
        self.browser_back_button.setEnabled(self.browser_view.history().canGoBack())
        self.browser_forward_button.setEnabled(self.browser_view.history().canGoForward())

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

        self.signup_api_keys = []
        self.signup_api_key = QLineEdit()
        self.signup_api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.signup_api_key.setPlaceholderText("Clé API OpenRouter")
        signup_layout.addWidget(self.signup_api_key)
        key_creation_row = QHBoxLayout()
        key_creation_row.addWidget(QLabel("Clés à créer"))
        self.signup_key_count = QSpinBox()
        self.signup_key_count.setRange(1, MAX_OPENROUTER_KEYS_PER_CREATION)
        self.signup_key_count.setValue(1)
        key_creation_row.addWidget(self.signup_key_count)
        key_creation_row.addStretch(1)
        signup_layout.addLayout(key_creation_row)
        authorize_button = QPushButton("Autoriser OpenRouter dans le navigateur")
        authorize_button.clicked.connect(
            lambda _checked=False: self._start_openrouter_key_creation(
                self._remember_signup_api_keys,
                self.signup_key_count.value(),
            )
        )
        signup_layout.addWidget(authorize_button)
        self.signup_key_status = QLabel("Chaque clé nécessite une autorisation OpenRouter.")
        self.signup_key_status.setObjectName("mutedText")
        self.signup_key_status.setWordWrap(True)
        signup_layout.addWidget(self.signup_key_status)
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
        api_keys = list(self.signup_api_keys)
        if api_key and api_key not in api_keys:
            api_keys.insert(0, api_key)
        if not all((username, email, password)) or not api_keys:
            self.signup_error.setText("Complétez le nom, l’e-mail, le mot de passe et la clé OpenRouter.")
            return
        try:
            avatar = self._store_profile_avatar(username)
            accounts.create_account(username, password, api_keys, email=email, avatar=avatar)
            api_keys = accounts.authenticate_api_keys(username, password)
        except (OSError, ValueError) as error:
            self.signup_error.setText(str(error))
            return
        self.signup_error.clear()
        self._set_provider(username, api_keys, account_password=password)

    def _remember_signup_api_keys(self, api_keys):
        values = api_keys if isinstance(api_keys, list) else [api_keys]
        self.signup_api_keys = list(dict.fromkeys(
            self.signup_api_keys + [
                str(value).strip() for value in values if str(value).strip()
            ]
        ))
        if self.signup_api_keys:
            self.signup_api_key.setText(self.signup_api_keys[0])
            self.signup_key_status.setText(
                f"{len(self.signup_api_keys)} clé{'s' if len(self.signup_api_keys) != 1 else ''} autorisée{'s' if len(self.signup_api_keys) != 1 else ''}."
            )

    def _apply_mode(self, code_mode):
        self.code_mode_active = bool(code_mode)
        if self.code_mode_active and self.compare_panel.isVisible():
            self._close_comparison()
        self._update_python_run_button()
        self.code_button.blockSignals(True)
        self.code_button.setChecked(self.code_mode_active)
        self.code_button.setText("⌘   Mode Conversation" if self.code_mode_active else "⌘   Mode Code")
        self.code_button.blockSignals(False)
        self.conversation_section.setVisible(not self.code_mode_active)
        self.files_section.setVisible(self.code_mode_active)
        if self.code_mode_active and self.conversation_toggle.isChecked():
            self.conversation_toggle.setChecked(False)
        if self.code_mode_active:
            self.workspace_splitter.insertWidget(0, self.editor_panel)
            self.editor_panel.show()
            self.chat_panel.show()
            self.workspace_splitter.setStretchFactor(0, 3)
            self.workspace_splitter.setStretchFactor(1, 2)
            self.workspace_splitter.setSizes([700, 390, 0])
            project_name = self.project_root.name if self.project_root else "Projet"
            if self.tool_page_stack.currentIndex() == 0:
                self.page_subtitle.setText(f"{project_name} · éditeur et assistant IA")
        else:
            self.workspace_splitter.insertWidget(0, self.chat_panel)
            self.chat_panel.show()
            self.editor_panel.hide()
            self.workspace_splitter.setSizes([self.workspace_splitter.width(), 0, 0])
            if self.tool_page_stack.currentIndex() == 0:
                self.page_subtitle.setText("Votre espace de discussion avec KAIRO")

    def _apply_style(self, theme_override=None):
        saved_themes = self.ui_settings.value("appearance/themeLibrary", "[]")
        profiles = theme_library.load_library(str(saved_themes))
        selected_id = str(self.ui_settings.value("appearance/themeProfile", ""))
        selected_theme = theme_override or theme_library.find_theme(profiles, selected_id)
        if selected_theme is None:
            base = self.ui_settings.value("appearance/theme", "dark")
            selected_theme = theme_library.find_theme(
                profiles, "paper" if base == "light" else "forest"
            )
        style = """
            QWidget { color: #e7eee9; font-family: 'Noto Sans'; font-size: 10pt; }
            QWidget#root, QWidget#mainPanel, QWidget#authPage { background: #111714; }
            QWidget#sidebar { background: #171f1b; border-right: 1px solid #29352e; }
            QWidget#sidebar QWidget { background: transparent; }
            QWidget#conversationDrawer { background: #171f1b; border: 1px solid #39473e; border-radius: 0 10px 10px 0; }
            QWidget#accountOverview { background: #1a231e; border: 1px solid #344138; border-radius: 10px; }
            QLabel#accountMonogram { color: #173722; background: #b9e9c6; border-radius: 22px; font-size: 16px; font-weight: 800; }
            QLabel#accountName { color: #f2f5f2; font-size: 12pt; font-weight: 700; }
            QLabel#accountMeta { color: #98a89f; }
            QLabel#brand { color: #c2f0d1; font-size: 23px; font-weight: 800; }
            QLabel#tagline { color: #91a59a; font-size: 9pt; font-weight: 700; }
            QLabel#sectionLabel { color: #87988e; font-size: 8pt; font-weight: 800; margin-top: 7px; }
            QToolButton#conversationToggle { color: #87988e; background: transparent; border: 0; padding: 5px 0; font-size: 8pt; font-weight: 800; text-align: left; }
            QToolButton#conversationToggle:hover { color: #c2f0d1; }
            QLabel#drawerTitle { color: #f2f5f2; font-size: 14pt; font-weight: 700; }
            QLabel#pageTitle { color: #f2f5f2; font-size: 21pt; font-weight: 700; }
            QLabel#welcomeGreeting { color: #f2f5f2; font-size: 24pt; font-weight: 700; }
            QLabel#subtitle, QLabel#mutedText, QLabel#notice, QLabel#editorStatus { color: #98a89f; }
            QLabel#status { color: #c7efd3; background: #20372a; border: 1px solid #395b43; border-radius: 13px; padding: 7px 12px; font-size: 9pt; }
            QComboBox, QLineEdit, QPlainTextEdit, QTextBrowser, QTableWidget {
                background: #1a231e; color: #e7eee9; border: 1px solid #344138;
                border-radius: 9px; padding: 8px 10px; selection-background-color: #477957;
            }
            QComboBox:hover, QLineEdit:hover { border-color: #607668; }
            QComboBox:focus, QLineEdit:focus, QPlainTextEdit:focus { border: 1px solid #9bd6ad; }
            QComboBox QAbstractItemView { background: #202a24; color: #e7eee9; border: 1px solid #3a4a3e; selection-background-color: #355940; padding: 5px; }
            QListWidget#chatList, QTreeView#fileTree { background: #141c17; color: #d0d9d3; border: 1px solid #29362d; border-radius: 10px; padding: 5px; }
            QDialog#conversationManagerDialog { background: #111714; color: #e7eee9; }
            QTableWidget#conversationManagerTable { background: #151d18; alternate-background-color: #1a241d; color: #e1e9e3; border: 1px solid #344138; border-radius: 9px; gridline-color: transparent; selection-background-color: #355940; selection-color: #f5fff7; }
            QTableWidget#conversationManagerTable::item { padding: 10px 12px; border-bottom: 1px solid #29362d; }
            QHeaderView#conversationManagerHeader::section { color: #a9d9b6; background: #202a24; border: 0; border-bottom: 1px solid #3a493e; padding: 11px 12px; font-weight: 700; }
            QLabel#conversationSelectionSummary { color: #a9d9b6; font-weight: 700; }
            QPushButton#conversationDeleteButton { color: #ffe2e3; background: #512b2e; border-color: #754247; }
            QPushButton#conversationDeleteButton:hover { background: #693438; border-color: #a75a61; }
            QListWidget#toolList { background: transparent; color: #d0d9d3; border: 0; border-radius: 8px; padding: 2px; }
            QListWidget#chatList::item { padding: 10px; border-radius: 7px; }
            QListWidget#chatList::item:hover { background: #202c23; }
            QListWidget#chatList::item:selected { background: #2b4934; color: #f1fff4; }
            QListWidget#toolList::item { padding: 13px 10px; border-bottom: 1px solid #29362d; }
            QListWidget#toolList::item:selected { background: #294333; color: #f1fff4; border-radius: 5px; }
            QLineEdit#calculatorDisplay { background: #111714; border: 0; padding: 6px 10px; }
            QPushButton#calculatorDigitKey { background: #26332a; border-color: #35463a; font-size: 14pt; }
            QPushButton#calculatorDigitKey:hover { background: #34483a; }
            QPushButton#calculatorOperatorKey, QPushButton#calculatorMemoryKey { background: #202a24; color: #c6d8cb; }
            QPushButton#calculatorEqualsKey { background: #b9e9c6; color: #102016; border-color: #c9f4d4; font-size: 14pt; }
            QPushButton#calculatorEqualsKey:hover { background: #d0f4d9; }
            QWebEngineView#webView { background: white; border: 1px solid #344138; border-radius: 8px; }
            QTextBrowser#transcript { background: #141b17; border-color: #2d3931; border-radius: 12px; padding: 18px; }
            QWidget#editorPanel { background: #171f1b; border: 1px solid #2c3930; border-radius: 12px; }
            QLabel#editorFileLabel { color: #d3e2d8; font-family: 'Noto Sans Mono'; font-size: 10pt; }
            QWidget#authPanel { background: #19221d; border: 1px solid #344239; border-radius: 16px; }
            QLabel#authError { color: #ff9d8e; }
            QLabel#avatarPreview { color: #e5f3e9; background: #294333; border: 1px solid #55745d; border-radius: 36px; font-size: 24px; }
            QToolButton#profileAvatar { color: #e5f3e9; background: #294333; border: 1px solid #55745d; border-radius: 19px; font-weight: 700; font-size: 16px; padding: 0; }
            QToolButton#profileAvatar:hover { background: #355f43; border-color: #8bb594; }
            QPushButton#welcomePrimaryButton, QPushButton#welcomeSecondaryButton { text-align: center; padding: 10px 14px; }
            QPushButton#welcomePrimaryButton { color: #102016; background: #b9e9c6; border-color: #c9f4d4; }
            QPushButton#welcomePrimaryButton:hover { background: #d0f4d9; }
            QPushButton#drawerNewChatButton, QPushButton#accountPrimaryButton { color: #102016; background: #b9e9c6; border-color: #c9f4d4; text-align: center; }
            QPushButton#drawerNewChatButton:hover, QPushButton#accountPrimaryButton:hover { background: #d0f4d9; }
            QMenu { color: #e7eee9; background: #202a24; border: 1px solid #3a4a3e; padding: 5px; }
            QMenu::item { padding: 8px 24px 8px 12px; border-radius: 5px; }
            QMenu::item:selected { color: #f5fff7; background: #355940; }
            QPlainTextEdit#codeEditor { background: #111714; border: 0; border-radius: 8px; padding: 14px; }
            QLineEdit#composer { background: #202a24; border: 1px solid #46574b; border-radius: 12px; padding: 13px 15px; font-size: 11pt; }
            QPushButton {
                color: #e1e9e3; background: #222d26; border: 1px solid #3b4b3f;
                border-radius: 9px; padding: 9px 13px; font-weight: 600; text-align: left;
            }
            QPushButton:hover { color: #f5fff7; background: #2d3c31; border-color: #6c9875; }
            QPushButton:pressed { background: #1b2820; }
            QPushButton:checked { color: #102016; background: #b9e9c6; border-color: #c9f4d4; }
            QPushButton#connectButton { background: #274832; border-color: #527a5d; }
            QPushButton#sendButton, QPushButton#saveButton, QPushButton#authPrimaryButton {
                color: #102016; background: #b9e9c6; border-color: #c9f4d4; text-align: center; font-weight: 700;
            }
            QPushButton#habitNotificationBanner { color: #e6f5e9; background: #294b35; border: 1px solid #5c946b; border-left: 4px solid #9fe0b0; border-radius: 8px; padding: 0; text-align: left; }
            QPushButton#habitNotificationBanner:hover { background: #355f43; }
            QLabel#habitNotificationTitle { color: #e6f5e9; font-weight: 700; }
            QTextBrowser#habitNotificationMessage { color: #d5ead9; background: transparent; border: 0; padding: 0; }
            QToolButton#notificationClose { color: #d5ead9; background: transparent; border: 0; padding: 0 4px; font-size: 16px; }
            QToolButton#notificationClose:hover { color: #ffffff; background: #477957; border-radius: 4px; }
            QPushButton#sendButton { min-width: 110px; padding: 12px 16px; }
            QPushButton#sendButton:hover, QPushButton#saveButton:hover, QPushButton#authPrimaryButton:hover { background: #d0f4d9; }
            QPushButton:disabled { color: #748078; background: #1b231e; border-color: #2c3730; }
            QCheckBox { spacing: 9px; }
            QCheckBox::indicator { width: 17px; height: 17px; border: 1px solid #58675c; border-radius: 5px; background: #1a231e; }
            QCheckBox::indicator:checked { background: #aaddb8; border-color: #aaddb8; }
            QSlider::groove:horizontal { height: 6px; background: #344138; border-radius: 3px; }
            QSlider::sub-page:horizontal { background: #a8dfb6; border-radius: 3px; }
            QSlider::handle:horizontal { width: 18px; margin: -7px 0; border-radius: 9px; background: #d2f2da; border: 2px solid #6b9b77; }
            QSlider::handle:horizontal:hover { background: #ffffff; }
            QTabWidget::pane { border: 1px solid #303d34; border-radius: 10px; top: -1px; background: #171f1b; }
            QTabBar::tab { color: #aab8af; background: transparent; padding: 10px 14px; border-bottom: 2px solid transparent; }
            QTabBar::tab:selected { color: #d0f0d8; border-bottom-color: #a8dfb6; font-weight: 700; }
            QTabBar::tab:hover { color: #f0f6f1; background: #202a24; }
            QDialog#embeddedDialog, QDialog#embeddedInputDialog, QDialog#embeddedMessageDialog,
            QFileDialog#embeddedFileDialog { background: #171f1b; color: #e7eee9; border: 1px solid #3a493e; border-radius: 14px; }
            QWidget#settingsHeader { background: transparent; }
            QLabel#settingsEyebrow { color: #a9d9b6; font-size: 8pt; font-weight: 800; }
            QLabel#settingsTitle { color: #f2f5f2; font-size: 21pt; font-weight: 700; }
            QLabel#settingsSubtitle, QLabel#settingsHint { color: #98a89f; }
            QLabel#settingsSummary { color: #cbd7cf; background: #202a24; border: 1px solid #344138; border-radius: 10px; padding: 12px 14px; }
            QLabel#modelIndicator { color: #cbd7cf; background: #202a24; border: 1px solid #344138; border-radius: 8px; padding: 7px 10px; font-size: 8pt; font-weight: 700; }
            QWidget#powerCard { background: #202a24; border: 1px solid #3a493e; border-radius: 12px; }
            QLabel#powerTitle { color: #edf4ef; font-size: 12pt; font-weight: 700; }
            QLabel#powerValue { color: #c7efd3; font-size: 15pt; font-weight: 800; }
            QLabel#powerScale { color: #87988e; font-size: 8pt; }
            QDialogButtonBox { border-top: 1px solid #303d34; padding-top: 12px; }
            QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
            QScrollBar::handle:vertical { background: #46564a; min-height: 30px; border-radius: 5px; }
            QScrollBar::handle:vertical:hover { background: #687f6d; }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
        """
        if selected_theme.get("base", "dark") == "light":
            style += """
                QWidget { color: #25352c; }
                QWidget#root, QWidget#mainPanel, QWidget#authPage { background: #f1f4ef; }
                QWidget#sidebar { background: #e8eee8; border-right-color: #d4ddd4; }
                QDialog#conversationManagerDialog { background: #f1f4ef; color: #25352c; }
                QTableWidget#conversationManagerTable { background: #ffffff; alternate-background-color: #f1f6f0; color: #26372c; border-color: #cbd8cd; selection-background-color: #c8e3cd; selection-color: #173722; }
                QTableWidget#conversationManagerTable::item { border-bottom-color: #e1e9e1; }
                QHeaderView#conversationManagerHeader::section { color: #28573a; background: #e5eee6; border-bottom-color: #cbd8cd; }
                QLabel#conversationSelectionSummary { color: #347145; }
                QPushButton#conversationDeleteButton { color: #782f33; background: #f7e4e4; border-color: #e4b9bb; }
                QPushButton#conversationDeleteButton:hover { color: #64262a; background: #efd0d1; border-color: #d49498; }
                QWidget#conversationDrawer { background: #e8eee8; border-color: #cbd8cc; }
                QWidget#accountOverview { background: #fbfcf9; border-color: #d2ddd3; }
                QLabel#accountMonogram { color: #ffffff; background: #3e7850; }
                QLabel#accountName { color: #1e3326; }
                QLabel#accountMeta { color: #65766a; }
                QLabel#brand { color: #28573a; }
                QLabel#drawerTitle { color: #1e3326; }
                QLabel#tagline, QLabel#sectionLabel, QLabel#subtitle, QLabel#mutedText,
                QLabel#notice, QLabel#editorStatus, QLabel#settingsSubtitle, QLabel#settingsHint,
                QLabel#powerScale { color: #65766a; }
                QLabel#pageTitle, QLabel#settingsTitle, QLabel#welcomeGreeting { color: #1e3326; }
                QLabel#status { color: #28573a; background: #dcefe0; border-color: #b6d8bd; }
                QComboBox, QLineEdit, QPlainTextEdit, QTextBrowser, QTableWidget { background: #fbfcf9; color: #26372c; border-color: #d2ddd3; }
                QComboBox QAbstractItemView { background: #fbfcf9; color: #26372c; border-color: #d2ddd3; selection-background-color: #deefe2; }
                QListWidget#chatList, QTreeView#fileTree { background: #f9fbf8; color: #2a3a30; border-color: #d6dfd6; }
                QListWidget#toolList { background: transparent; color: #2a3a30; }
                QListWidget#chatList::item:hover { background: #eaf1ea; }
                QListWidget#chatList::item:selected { background: #dcefe0; color: #20432c; }
                QListWidget#toolList::item { border-bottom-color: #dce5dc; }
                QListWidget#toolList::item:selected { background: #dcefe0; color: #20432c; }
                QTextBrowser#transcript { background: #fbfcf9; color: #26372c; border-color: #d7e0d7; }
                QPlainTextEdit#codeEditor { background: #fbfcf9; color: #26372c; border-color: #d7e0d7; }
                QWidget#editorPanel, QWidget#authPanel, QTabWidget::pane { background: #fbfcf9; border-color: #d7e0d7; }
                QLabel#editorFileLabel { color: #2e4936; }
                QLabel#avatarPreview { color: #28523a; background: #dcefe0; border-color: #b3d5ba; }
                QToolButton#profileAvatar { color: #28523a; background: #dcefe0; border-color: #b3d5ba; }
                QLineEdit#composer { background: #ffffff; color: #23372b; border-color: #cbd8cd; }
                QPushButton { color: #294334; background: #e7eee7; border-color: #cbd8cd; }
                QPushButton:hover { color: #1e492d; background: #dceade; border-color: #8bb594; }
                QPushButton:checked, QPushButton#sendButton, QPushButton#saveButton, QPushButton#authPrimaryButton { color: #173722; background: #a9ddb5; border-color: #91c99f; }
                QPushButton#habitNotificationBanner { color: #20432c; background: #dcefe0; border-color: #b3d5ba; border-left-color: #4e8b5d; }
                QPushButton#habitNotificationBanner:hover { background: #cce8d2; }
                QLabel#habitNotificationTitle { color: #20432c; }
                QTextBrowser#habitNotificationMessage { color: #365d40; }
                QToolButton#notificationClose { color: #365d40; }
                QPushButton#connectButton { background: #dcefe0; border-color: #b3d5ba; }
                QLineEdit#calculatorDisplay { background: #fbfcf9; color: #26372c; }
                QPushButton#calculatorDigitKey { background: #f4f7f3; border-color: #d2ddd3; }
                QPushButton#calculatorDigitKey:hover { background: #e4eee4; }
                QPushButton#calculatorOperatorKey, QPushButton#calculatorMemoryKey { background: #e7eee7; color: #294334; }
                QPushButton#calculatorEqualsKey { color: #173722; background: #a9ddb5; border-color: #91c99f; }
                QTabBar::tab { color: #65766a; }
                QTabBar::tab:selected { color: #28573a; border-bottom-color: #4e8b5d; }
                QTabBar::tab:hover { color: #28573a; background: #edf3ed; }
                QWidget#settingsHeader { background: transparent; }
                QLabel#settingsEyebrow { color: #438154; }
                QLabel#settingsSummary, QWidget#powerCard { color: #2b3b30; background: #f2f6f1; border-color: #d7e0d7; }
                QLabel#modelIndicator { color: #28573a; background: #e6efe7; border-color: #cbd8cd; }
                QLabel#powerTitle { color: #26372c; }
                QLabel#powerValue { color: #347145; }
                QSlider::groove:horizontal { background: #d5e0d6; }
                QSlider::sub-page:horizontal { background: #62a773; }
                QSlider::handle:horizontal { background: #fff; border-color: #559365; }
                QDialog#embeddedDialog, QDialog#embeddedInputDialog, QDialog#embeddedMessageDialog,
                QFileDialog#embeddedFileDialog { background: #fbfcf9; color: #25352c; border-color: #d2ddd3; }
                QDialogButtonBox { border-top-color: #d7e0d7; }
                QScrollBar::handle:vertical { background: #c2d0c4; }
                QScrollBar::handle:vertical:hover { background: #93ae98; }
            """
        wallpaper_url = ""
        wallpaper_path = str(selected_theme.get("wallpaper", "")).strip()
        if wallpaper_path:
            local_wallpaper = Path(wallpaper_path).expanduser()
            if local_wallpaper.is_file():
                wallpaper_url = QUrl.fromLocalFile(str(local_wallpaper.resolve())).toString(
                    QUrl.ComponentFormattingOption.FullyEncoded
                )
        style += theme_library.stylesheet_overrides(selected_theme, wallpaper_url)
        self.setStyleSheet(style)

    def _open_notification_settings(self):
        self._open_settings("Notifications")

    def _bug_log_html(self):
        try:
            data = json.loads((BASE_DIR / "bug.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return "<p>Le journal des correctifs est indisponible.</p>"

        versions = data.get("versions", {})
        if not isinstance(versions, dict) or not versions:
            return "<p>Aucun correctif n’est enregistré.</p>"

        light_theme = self.ui_settings.value("appearance/theme", "dark") == "light"
        if light_theme:
            body_background = "#fbfcf9"
            body_color = "#26372c"
            heading_color = "#347145"
            heading_border = "#d2ddd3"
            component_color = "#2e4936"
        else:
            body_background = "#1a231e"
            body_color = "#e7eee9"
            heading_color = "#b9e9c6"
            heading_border = "#344138"
            component_color = "#d3e2d8"

        sections = []
        for version, fixes in reversed(list(versions.items())):
            sections.append(f"<h2>Version {html.escape(str(version))}</h2>")
            if not isinstance(fixes, list):
                continue
            for item in fixes:
                if not isinstance(item, dict):
                    continue
                component = html.escape(str(item.get("component", "Correctif")))
                bug = html.escape(str(item.get("bug", "")))
                fix = html.escape(str(item.get("fix", "")))
                sections.append(
                    f"<h3>{component}</h3><p><b>Bug :</b> {bug}</p>"
                    f"<p><b>Correction :</b> {fix}</p>"
                )
        return (
            "<html><head><style>"
            f"body {{ background: {body_background}; color: {body_color}; font-family: sans-serif; }}"
            f"h2 {{ color: {heading_color}; border-bottom: 1px solid {heading_border}; padding-bottom: 5px; }}"
            f"h3 {{ color: {component_color}; margin-bottom: 4px; }}"
            "p { margin-top: 3px; }"
            "</style></head><body>" + "".join(sections) + "</body></html>"
        )

    def _open_settings(self, initial_tab=None):
        previous_page = getattr(self, "_settings_page", None)
        if previous_page is not None:
            self.page_stack.removeWidget(previous_page)
            previous_page.deleteLater()
        page = QWidget()
        page.setObjectName("settingsPage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(26, 22, 26, 20)
        layout.setSpacing(16)
        settings_header = QWidget()
        settings_header.setObjectName("settingsHeader")
        header_layout = QVBoxLayout(settings_header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(3)
        eyebrow = QLabel("KAIRO  /  PRÉFÉRENCES")
        eyebrow.setObjectName("settingsEyebrow")
        heading = QLabel("Paramètres")
        heading.setObjectName("settingsTitle")
        subtitle = QLabel("Personnalisez votre espace et le comportement de l’assistant.")
        subtitle.setObjectName("settingsSubtitle")
        header_layout.addWidget(eyebrow)
        header_layout.addWidget(heading)
        header_layout.addWidget(subtitle)
        layout.addWidget(settings_header)
        tabs = QTabWidget()
        tabs.setObjectName("settingsTabs")
        layout.addWidget(tabs)

        self.ollama_url_input = QLineEdit(str(self.config.get("ollama", {}).get("url", "http://127.0.0.1:11434")))
        self.ollama_model_picker = QComboBox()
        self.openrouter_model_picker = QComboBox()
        self.ollama_status_label = QLabel("Connexion Ollama non vérifiée.")
        self.ollama_refresh_button = QPushButton("Tester la connexion et actualiser")
        self.openrouter_refresh_button = QPushButton("Actualiser les modèles OpenRouter")
        self.ollama_pull_button = QPushButton("Télécharger le modèle")
        self.ollama_delete_button = QPushButton("Supprimer le modèle sélectionné")
        self.provider_test_button = QPushButton("Tester l’appel avec un calcul")
        self.provider_test_status = QLabel("Le modèle doit répondre 437 à 19 × 23.")

        ollama_page = QWidget()
        ollama_layout = QVBoxLayout(ollama_page)
        ollama_layout.setContentsMargins(20, 20, 20, 20)
        ollama_layout.setSpacing(12)
        self.ai_provider_picker = QComboBox()
        self.ai_provider_picker.addItem("Local", "ollama")
        self.ai_provider_picker.addItem("Cloud", "openrouter")
        self.ai_provider_picker.setCurrentIndex(
            max(0, self.ai_provider_picker.findData(self._selected_provider(self.config)))
        )
        ollama_layout.addWidget(QLabel("Catégorie de l’IA"))
        ollama_layout.addWidget(self.ai_provider_picker)
        classification_filters = QHBoxLayout()
        self.model_need_picker = QComboBox()
        for label, need in (
            ("Tous les besoins", "all"),
            ("Général", "general"),
            ("Code", "code"),
            ("Raisonnement", "reasoning"),
            ("Mathématiques", "math"),
            ("Vision / images", "vision"),
            ("Traduction", "translation"),
            ("RAG / embeddings", "embeddings"),
            ("Agents", "agents"),
            ("Technique", "technical"),
            ("Grand contexte", "long_context"),
        ):
            self.model_need_picker.addItem(label, need)
        self.model_power_picker = QComboBox()
        self.model_power_picker.addItem("Toute puissance", "all")
        for tier, label in MODEL_POWER_LABELS.items():
            self.model_power_picker.addItem(label, tier)
        self.model_power_picker.setToolTip(
            "Estimation locale basée sur les paramètres ou la taille disque; estimation cloud basée sur le nom du modèle."
        )
        self.model_sort_picker = QComboBox()
        self.model_sort_picker.addItem("Besoins puis puissance", "need")
        self.model_sort_picker.addItem("Puissance croissante", "power")
        self.model_sort_picker.addItem("Nom", "name")
        classification_filters.addWidget(self.model_need_picker, stretch=2)
        classification_filters.addWidget(self.model_power_picker, stretch=1)
        classification_filters.addWidget(self.model_sort_picker, stretch=1)
        ollama_layout.addLayout(classification_filters)
        self.ollama_status_label.setObjectName("settingsSummary")
        self.ollama_status_label.setWordWrap(True)
        ollama_layout.addWidget(self.ollama_status_label)

        self.provider_model_stack = QStackedWidget()
        local_model_page = QWidget()
        local_model_layout = QVBoxLayout(local_model_page)
        local_model_layout.setContentsMargins(0, 0, 0, 0)
        local_model_layout.setSpacing(10)
        ollama_form = QFormLayout()
        self.ollama_url_input.setPlaceholderText("http://127.0.0.1:11434")
        ollama_form.addRow("Adresse du serveur Ollama", self.ollama_url_input)
        local_model_layout.addLayout(ollama_form)
        ollama_help = QLabel("Ollama doit être installé et démarré sur cette machine ou accessible à cette adresse.")
        ollama_help.setWordWrap(True)
        local_model_layout.addWidget(ollama_help)
        ollama_actions = QHBoxLayout()
        self.ollama_refresh_button.clicked.connect(
            lambda: self._start_ollama_task("list", self.ollama_url_input.text())
        )
        ollama_actions.addWidget(self.ollama_refresh_button)
        local_model_layout.addLayout(ollama_actions)
        self.ollama_model_picker.setToolTip("Modèle Ollama utilisé quand Ollama est le fournisseur actif")
        local_model_layout.addWidget(QLabel("Modèle local"))
        local_model_layout.addWidget(self.ollama_model_picker)
        pull_row = QHBoxLayout()
        self.ollama_pull_input = QLineEdit()
        self.ollama_pull_input.setPlaceholderText("Nom du modèle, par exemple qwen2.5:3b")
        self.ollama_pull_input.textChanged.connect(self._update_ollama_model_actions)
        self.ollama_pull_button.clicked.connect(
            self._download_ollama_model
        )
        pull_row.addWidget(self.ollama_pull_input, stretch=1)
        pull_row.addWidget(self.ollama_pull_button)
        local_model_layout.addLayout(pull_row)
        self.ollama_delete_button.clicked.connect(self._delete_ollama_model)
        local_model_layout.addWidget(self.ollama_delete_button)
        local_model_layout.addStretch(1)
        self.provider_model_stack.addWidget(local_model_page)

        cloud_model_page = QWidget()
        cloud_model_layout = QVBoxLayout(cloud_model_page)
        cloud_model_layout.setContentsMargins(0, 0, 0, 0)
        cloud_model_layout.setSpacing(10)
        cloud_model_layout.addWidget(QLabel("Modèle cloud OpenRouter"))
        cloud_model_layout.addWidget(self.openrouter_model_picker)
        self.openrouter_model_picker.setToolTip("Le modèle cloud utilisé par KAIRO et enregistré dans config.json")
        self.openrouter_refresh_button.clicked.connect(self._refresh_openrouter_models)
        cloud_model_layout.addWidget(self.openrouter_refresh_button)
        cloud_model_hint = QLabel("La liste nécessite une connexion OpenRouter active. Le modèle choisi sera utilisé pour les prochains appels.")
        cloud_model_hint.setWordWrap(True)
        cloud_model_layout.addWidget(cloud_model_hint)
        cloud_model_layout.addStretch(1)
        self.provider_model_stack.addWidget(cloud_model_page)
        ollama_layout.addWidget(self.provider_model_stack, stretch=1)
        self.provider_test_button.clicked.connect(self._start_provider_test)
        ollama_layout.addWidget(self.provider_test_button)
        self.provider_test_status.setWordWrap(True)
        ollama_layout.addWidget(self.provider_test_status)
        self.ai_provider_picker.currentIndexChanged.connect(self._provider_category_changed)
        self.model_need_picker.currentIndexChanged.connect(self._refresh_model_choices)
        self.model_power_picker.currentIndexChanged.connect(self._refresh_model_choices)
        self.model_sort_picker.currentIndexChanged.connect(self._refresh_model_choices)
        self.ollama_model_picker.currentIndexChanged.connect(self._update_ollama_model_actions)
        self.provider_model_stack.setCurrentIndex(
            0 if self.ai_provider_picker.currentData() == "ollama" else 1
        )
        self._set_ollama_models(self._ollama_catalog)
        self._set_openrouter_models(self._openrouter_catalog)
        tabs.addTab(ollama_page, "IA & modèles")

        appearance = QWidget()
        appearance.setObjectName("settingsPage")
        appearance_layout = QVBoxLayout(appearance)
        appearance_layout.setContentsMargins(20, 20, 20, 20)
        appearance_layout.setSpacing(12)
        profile_row = QHBoxLayout()
        profile_picker = QComboBox()
        profile_picker.setMinimumWidth(180)
        profile_library = theme_library.load_library(
            str(self.ui_settings.value("appearance/themeLibrary", "[]"))
        )
        for profile in profile_library:
            profile_picker.addItem(profile["name"], profile["id"])
        selected_profile_id = str(self.ui_settings.value("appearance/themeProfile", ""))
        if not theme_library.find_theme(profile_library, selected_profile_id):
            selected_base = self.ui_settings.value("appearance/theme", "dark")
            selected_profile_id = "paper" if selected_base == "light" else "forest"
        profile_picker.setCurrentIndex(max(0, profile_picker.findData(selected_profile_id)))
        new_profile_button = QPushButton("Créer un thème")
        delete_profile_button = QPushButton("Supprimer")
        profile_row.addWidget(QLabel("Bibliothèque"))
        profile_row.addWidget(profile_picker, stretch=1)
        profile_row.addWidget(new_profile_button)
        profile_row.addWidget(delete_profile_button)
        appearance_layout.addLayout(profile_row)

        appearance_form = QFormLayout()
        appearance_form.setVerticalSpacing(10)
        profile_name = QLineEdit()
        base_picker = QComboBox()
        base_picker.addItem("Sombre", "dark")
        base_picker.addItem("Clair", "light")
        appearance_form.addRow("Nom", profile_name)
        appearance_form.addRow("Contraste", base_picker)
        appearance_layout.addLayout(appearance_form)

        colors_layout = QGridLayout()
        colors_layout.setHorizontalSpacing(12)
        colors_layout.setVerticalSpacing(8)
        color_labels = (
            ("window", "Fond"),
            ("surface", "Panneaux"),
            ("text", "Texte"),
            ("accent", "Accent"),
            ("button_background", "Boutons"),
            ("button_text", "Texte des boutons"),
            ("primary_text", "Texte des actions"),
        )
        color_buttons = {}
        for index, (field, label) in enumerate(color_labels):
            row = index // 3
            column = (index % 3) * 2
            colors_layout.addWidget(QLabel(label), row, column)
            swatch = QPushButton()
            swatch.setMinimumWidth(92)
            swatch.setToolTip(f"Choisir la couleur : {label.lower()}")
            colors_layout.addWidget(swatch, row, column + 1)
            color_buttons[field] = swatch
        appearance_layout.addLayout(colors_layout)

        button_style = QComboBox()
        button_style.addItem("Arrondis", "rounded")
        button_style.addItem("Carrés", "square")
        button_style.addItem("Pilule", "pill")
        appearance_form.addRow("Forme des boutons", button_style)

        wallpaper_row = QHBoxLayout()
        wallpaper_input = QLineEdit()
        wallpaper_input.setPlaceholderText("Aucun fond d’écran")
        wallpaper_button = QPushButton("Choisir une image")
        clear_wallpaper_button = QPushButton("Retirer")
        wallpaper_row.addWidget(wallpaper_input, stretch=1)
        wallpaper_row.addWidget(wallpaper_button)
        wallpaper_row.addWidget(clear_wallpaper_button)
        appearance_layout.addWidget(QLabel("Image de fond"))
        appearance_layout.addLayout(wallpaper_row)

        preview = QWidget()
        preview.setObjectName("themePreview")
        preview_layout = QHBoxLayout(preview)
        preview_layout.setContentsMargins(12, 10, 12, 10)
        preview_label = QLabel("Aperçu du thème")
        preview_layout.addWidget(preview_label, stretch=1)
        preview_primary = QPushButton("Action principale")
        preview_primary.setObjectName("themePreviewPrimary")
        preview_layout.addWidget(preview_primary)
        preview_secondary = QPushButton("Action secondaire")
        preview_layout.addWidget(preview_secondary)
        appearance_layout.addWidget(preview)
        appearance_hint = QLabel("Les changements sont prévisualisés immédiatement et conservés après Enregistrer.")
        appearance_hint.setObjectName("settingsHint")
        appearance_hint.setWordWrap(True)
        appearance_layout.addWidget(appearance_hint)
        appearance_layout.addStretch(1)

        editing_profile = {"value": None}

        def current_profile_values():
            profile = dict(editing_profile["value"] or profile_library[0])
            profile["name"] = profile_name.text().strip() or "Mon thème"
            profile["base"] = base_picker.currentData()
            profile["button_style"] = button_style.currentData()
            profile["wallpaper"] = wallpaper_input.text().strip()
            for field, swatch in color_buttons.items():
                profile[field] = swatch.property("themeColor")
            return profile

        def apply_profile_preview():
            profile = current_profile_values()
            editing_profile["value"] = profile
            wallpaper_path = Path(profile["wallpaper"]).expanduser() if profile["wallpaper"] else None
            wallpaper_url = (
                QUrl.fromLocalFile(str(wallpaper_path.resolve())).toString(
                    QUrl.ComponentFormattingOption.FullyEncoded
                )
                if wallpaper_path and wallpaper_path.is_file()
                else ""
            )
            preview.setStyleSheet(
                f"background-color: {profile['surface']}; border: 1px solid {profile['accent']};"
                f"border-radius: {theme_library.BUTTON_STYLES[profile['button_style']]}px;"
            )
            self._apply_style(profile)

        def load_profile(index):
            profile = theme_library.find_theme(profile_library, profile_picker.itemData(index))
            if profile is None:
                return
            editing_profile["value"] = dict(profile)
            profile_name.blockSignals(True)
            base_picker.blockSignals(True)
            button_style.blockSignals(True)
            wallpaper_input.blockSignals(True)
            profile_name.setText(profile["name"])
            profile_name.setEnabled(profile["id"].startswith("custom-"))
            base_picker.setCurrentIndex(max(0, base_picker.findData(profile["base"])))
            button_style.setCurrentIndex(max(0, button_style.findData(profile["button_style"])))
            wallpaper_input.setText(profile["wallpaper"])
            profile_name.blockSignals(False)
            base_picker.blockSignals(False)
            button_style.blockSignals(False)
            wallpaper_input.blockSignals(False)
            for field, swatch in color_buttons.items():
                color = profile[field]
                swatch.setProperty("themeColor", color)
                swatch.setText(color)
                swatch.setStyleSheet(f"background-color: {color}; color: {profile['text']};")
            delete_profile_button.setEnabled(profile["id"].startswith("custom-"))
            apply_profile_preview()

        def choose_theme_color(field):
            profile = current_profile_values()
            selected = QColorDialog.getColor(QColor(profile[field]), self, "Choisir une couleur")
            if not selected.isValid():
                return
            color = selected.name().upper()
            swatch = color_buttons[field]
            swatch.setProperty("themeColor", color)
            swatch.setText(color)
            swatch.setStyleSheet(f"background-color: {color}; color: {profile['text']};")
            apply_profile_preview()

        def choose_wallpaper():
            path, _selected_filter = QFileDialog.getOpenFileName(
                self,
                "Choisir une image de fond",
                wallpaper_input.text() or str(Path.home()),
                "Images (*.png *.jpg *.jpeg *.webp *.bmp)",
            )
            if path:
                wallpaper_input.setText(path)
                apply_profile_preview()

        def create_profile():
            name, accepted = QInputDialog.getText(self, "Nouveau thème", "Nom du thème")
            if not accepted or not name.strip():
                return
            source = current_profile_values()
            profile = theme_library.create_custom_theme(name, source, uuid.uuid4().hex[:10])
            profile_library.append(profile)
            profile_picker.addItem(profile["name"], profile["id"])
            profile_picker.setCurrentIndex(profile_picker.count() - 1)

        def delete_profile():
            profile = editing_profile["value"] or {}
            if not profile.get("id", "").startswith("custom-"):
                return
            answer = QMessageBox.question(
                self,
                "Supprimer le thème",
                f"Supprimer « {profile['name']} » de la bibliothèque ?",
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
            profile_library[:] = [item for item in profile_library if item["id"] != profile["id"]]
            profile_picker.removeItem(profile_picker.currentIndex())
            if profile_picker.count():
                profile_picker.setCurrentIndex(0)

        for field, swatch in color_buttons.items():
            swatch.clicked.connect(lambda _checked=False, key=field: choose_theme_color(key))
        profile_picker.currentIndexChanged.connect(load_profile)
        base_picker.currentIndexChanged.connect(lambda _index: apply_profile_preview())
        button_style.currentIndexChanged.connect(lambda _index: apply_profile_preview())
        wallpaper_input.textChanged.connect(lambda _text: apply_profile_preview())
        profile_name.textChanged.connect(lambda _text: apply_profile_preview())
        wallpaper_button.clicked.connect(choose_wallpaper)
        clear_wallpaper_button.clicked.connect(lambda: wallpaper_input.clear())
        new_profile_button.clicked.connect(create_profile)
        delete_profile_button.clicked.connect(delete_profile)
        load_profile(profile_picker.currentIndex())
        tabs.addTab(appearance, "Apparence")

        applications_page = QWidget()
        applications_layout = QVBoxLayout(applications_page)
        applications_layout.setContentsMargins(20, 20, 20, 20)
        applications_layout.setSpacing(12)
        applications_hint = QLabel(
            "KAIRO détecte les applications installées et mémorise celles ajoutées ici pour les retrouver par leur nom au lancement."
        )
        applications_hint.setWordWrap(True)
        applications_layout.addWidget(applications_hint)
        applications_table = QTableWidget(0, 3)
        applications_table.setHorizontalHeaderLabels(("Application", "Emplacement", "État"))
        applications_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        applications_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        applications_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        applications_table.setWordWrap(False)
        applications_table.horizontalHeader().setStretchLastSection(True)
        applications_layout.addWidget(applications_table, stretch=1)
        applications_status = QLabel()
        applications_status.setObjectName("settingsHint")
        applications_layout.addWidget(applications_status)
        applications_actions = QHBoxLayout()
        refresh_applications = QPushButton("Actualiser la détection")
        add_application = QPushButton("Ajouter une application")
        remove_application = QPushButton("Retirer de la liste")
        applications_actions.addWidget(refresh_applications)
        applications_actions.addWidget(add_application)
        applications_actions.addWidget(remove_application)
        applications_actions.addStretch(1)
        applications_layout.addLayout(applications_actions)

        def refresh_application_settings():
            registered = application_launcher.list_registered_applications()
            entries = {
                application["name"].casefold(): {
                    "name": application["name"],
                    "path": "",
                    "registered_path": "",
                }
                for application in application_launcher.list_applications()
            }
            for application in registered:
                key = application["name"].casefold()
                entry = entries.setdefault(
                    key,
                    {"name": application["name"], "path": "", "registered_path": ""},
                )
                entry["path"] = application["path"]
                entry["registered_path"] = application["path"]

            applications_table.setRowCount(0)
            for application in sorted(entries.values(), key=lambda item: item["name"].casefold()):
                row = applications_table.rowCount()
                applications_table.insertRow(row)
                name_item = QTableWidgetItem(application["name"])
                name_item.setData(Qt.ItemDataRole.UserRole, application["registered_path"])
                path_text = application["path"] or "Détectée sur cet appareil"
                state_text = "Ajoutée pour le lancement par nom" if application["registered_path"] else "Détectée"
                applications_table.setItem(row, 0, name_item)
                applications_table.setItem(row, 1, QTableWidgetItem(path_text))
                applications_table.setItem(row, 2, QTableWidgetItem(state_text))
            applications_table.resizeColumnsToContents()
            applications_status.setText(
                f"{len(entries)} application{'s' if len(entries) != 1 else ''} détectée{'s' if len(entries) != 1 else ''} · "
                f"{len(registered)} ajoutée{'s' if len(registered) != 1 else ''} au registre de lancement"
            )

        def update_remove_application_state():
            row = applications_table.currentRow()
            item = applications_table.item(row, 0) if row >= 0 else None
            remove_application.setEnabled(bool(item and item.data(Qt.ItemDataRole.UserRole)))

        def add_application_path():
            if sys.platform == "darwin":
                path = QFileDialog.getExistingDirectory(
                    self, "Choisir une application", str(Path.home() / "Applications")
                )
            else:
                file_filter = (
                    "Applications (*.exe *.com *.lnk);;Tous les fichiers (*)"
                    if os.name == "nt"
                    else "Applications (*.desktop *.appimage);;Tous les fichiers (*)"
                )
                path, _selected_filter = QFileDialog.getOpenFileName(
                    self, "Choisir une application", str(Path.home()), file_filter
                )
            if not path:
                return
            try:
                application_launcher.register_application("", path)
            except (OSError, ValueError) as error:
                QMessageBox.warning(self, "Ajout impossible", str(error))
                return
            refresh_application_settings()

        def remove_selected_application():
            row = applications_table.currentRow()
            item = applications_table.item(row, 0) if row >= 0 else None
            path = item.data(Qt.ItemDataRole.UserRole) if item else ""
            if not path:
                return
            application_launcher.unregister_application(path)
            refresh_application_settings()

        refresh_applications.clicked.connect(refresh_application_settings)
        add_application.clicked.connect(add_application_path)
        remove_application.clicked.connect(remove_selected_application)
        applications_table.itemSelectionChanged.connect(update_remove_application_state)
        refresh_application_settings()
        update_remove_application_state()
        tabs.addTab(applications_page, "Applications")

        account_page = QWidget()
        account_layout = QVBoxLayout(account_page)
        account_layout.setContentsMargins(20, 18, 20, 20)
        account_layout.setSpacing(14)
        account_name = os.environ.get("LOCAL_IA_ACCOUNT", "")
        account_keys = openrouter_api_keys()
        account_overview = QWidget()
        account_overview.setObjectName("accountOverview")
        overview_layout = QHBoxLayout(account_overview)
        overview_layout.setContentsMargins(16, 14, 16, 14)
        overview_layout.setSpacing(12)
        account_monogram = QLabel(account_name[:1].upper() if account_name else "K")
        account_monogram.setObjectName("accountMonogram")
        account_monogram.setFixedSize(44, 44)
        account_monogram.setAlignment(Qt.AlignmentFlag.AlignCenter)
        overview_layout.addWidget(account_monogram)
        account_details = QVBoxLayout()
        account_details.setSpacing(3)
        account_title = QLabel(account_name or "Aucun compte connecté")
        account_title.setObjectName("accountName")
        account_details.addWidget(account_title)
        provider_label = (
            "Ollama"
            if self._selected_provider(self.config) == "ollama"
            else "OpenRouter" if account_keys else "Aucun fournisseur actif"
        )
        account_meta = QLabel(
            f"{provider_label} · {len(account_keys)} clé(s) API active(s)"
        )
        account_meta.setObjectName("accountMeta")
        account_details.addWidget(account_meta)
        overview_layout.addLayout(account_details, stretch=1)
        account_layout.addWidget(account_overview)

        account_actions = QHBoxLayout()
        account_actions.setSpacing(8)
        connect_button = QPushButton("Connexion / création")
        connect_button.setObjectName("accountPrimaryButton")

        def open_connection_page():
            self.page_stack.setCurrentIndex(0)
            self._connect_account()

        connect_button.clicked.connect(open_connection_page)
        manage_button = QPushButton("Gérer les clés API")
        manage_button.setEnabled(bool(account_name))
        manage_button.clicked.connect(self._manage_api_keys)
        disconnect_button = QPushButton("Déconnexion")
        disconnect_button.setEnabled(bool(account_name or account_keys))

        def disconnect_account():
            self.page_stack.setCurrentIndex(0)
            self._disconnect_account()

        disconnect_button.clicked.connect(disconnect_account)
        account_actions.addWidget(connect_button)
        account_actions.addWidget(manage_button)
        account_actions.addWidget(disconnect_button)
        account_layout.addLayout(account_actions)

        current_power = openrouter_power()
        power_card = QWidget()
        power_card.setObjectName("powerCard")
        power_layout = QVBoxLayout(power_card)
        power_layout.setContentsMargins(18, 16, 18, 14)
        power_layout.setSpacing(10)
        power_heading = QHBoxLayout()
        power_title = QLabel("Puissance IA")
        power_title.setObjectName("powerTitle")
        power_label = QLabel()
        power_label.setObjectName("powerValue")
        power_slider = QSlider(Qt.Orientation.Horizontal)
        power_slider.setObjectName("powerSlider")
        power_slider.setRange(1, 100)
        power_slider.setValue(current_power)
        power_slider.setToolTip("Choisissez la part des clés actives que KAIRO peut utiliser.")
        power_heading.addWidget(power_title)
        power_heading.addStretch(1)
        power_heading.addWidget(power_label)
        power_layout.addLayout(power_heading)
        power_hint = QLabel(
            "Choisis combien de clés OpenRouter peuvent être utilisées pour chaque demande."
        )
        power_hint.setObjectName("settingsHint")
        power_hint.setWordWrap(True)
        power_layout.addWidget(power_hint)
        power_layout.addWidget(power_slider)
        power_scale = QHBoxLayout()
        power_minimum = QLabel("1x  ·  minimum")
        power_minimum.setObjectName("powerScale")
        power_maximum = QLabel(
            f"{len(account_keys)} clés  ·  maximum" if account_keys else "Aucune clé OpenRouter"
        )
        power_maximum.setObjectName("powerScale")
        power_scale.addWidget(power_minimum)
        power_scale.addStretch(1)
        power_scale.addWidget(power_maximum)
        power_layout.addLayout(power_scale)
        account_layout.addWidget(power_card)

        def sync_power_label(value):
            effective_x = effective_openrouter_power(account_keys or ["demo"], power=value)
            if account_keys:
                power_label.setText(f"{effective_x}/{len(account_keys)} clés · {value}%")
            else:
                power_label.setText("0 clé active")

        power_slider.valueChanged.connect(sync_power_label)
        sync_power_label(current_power)
        account_layout.addStretch(1)
        tabs.addTab(account_page, "Compte")

        data_page = QWidget()
        data_layout = QVBoxLayout(data_page)
        data_layout.setContentsMargins(20, 20, 20, 20)
        data_layout.setSpacing(12)
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
        notification_layout.setContentsMargins(20, 20, 20, 20)
        notification_layout.setSpacing(12)
        sound_enabled = QCheckBox("Son à la fin d’une réponse")
        sound_enabled.setChecked(self.ui_settings.value("notifications/sound", True, type=bool))
        notification_layout.addWidget(sound_enabled)
        test_sound = QPushButton("Tester le son")
        test_sound.clicked.connect(QApplication.beep)
        notification_layout.addWidget(test_sound)
        notification_layout.addStretch(1)
        tabs.addTab(notifications, "Notifications")

        bug_fixes_page = QWidget()
        bug_fixes_layout = QVBoxLayout(bug_fixes_page)
        bug_fixes_layout.setContentsMargins(20, 20, 20, 20)
        bug_fixes_layout.setSpacing(12)
        bug_fixes_header = QWidget()
        bug_fixes_header_layout = QHBoxLayout(bug_fixes_header)
        bug_fixes_header_layout.setContentsMargins(0, 0, 0, 0)
        bug_logo = QLabel()
        bug_logo.setFixedSize(48, 48)
        bug_logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        bug_logo.setPixmap(desktop_tray._create_icon().pixmap(48, 48))
        bug_fixes_header_layout.addWidget(bug_logo)
        bug_fixes_title = QLabel("Correctifs KAIRO")
        bug_fixes_title.setObjectName("settingsTitle")
        bug_fixes_header_layout.addWidget(bug_fixes_title)
        bug_fixes_header_layout.addStretch(1)
        bug_fixes_layout.addWidget(bug_fixes_header)
        bug_fixes_browser = QTextBrowser()
        bug_fixes_browser.setOpenExternalLinks(False)
        bug_fixes_browser.setHtml(self._bug_log_html())
        bug_fixes_layout.addWidget(bug_fixes_browser, 1)
        tabs.addTab(bug_fixes_page, "Correctifs")

        background = QWidget()
        background_layout = QVBoxLayout(background)
        background_layout.setContentsMargins(20, 20, 20, 20)
        background_layout.setSpacing(12)
        background_note = QLabel(
            "Sleep maintient les rappels et les habitudes actives lorsque la fenêtre KAIRO est fermée. "
            "La commande iahelp reste disponible séparément dans le terminal."
        )
        background_note.setWordWrap(True)
        background_layout.addWidget(background_note)
        auto_start = QCheckBox("Démarrer Sleep automatiquement avec l’ordinateur")
        auto_start.setChecked(desktop_tray.autostart_enabled(self.ui_settings))
        background_layout.addWidget(auto_start)
        service_status = QLabel(
            "Service Sleep actif" if desktop_tray.service_running() else "Service Sleep inactif"
        )
        service_status.setObjectName("settingsSummary")
        background_layout.addWidget(service_status)
        app_actions = QHBoxLayout()
        shutdown_button = QPushButton("Éteindre KAIRO")
        shutdown_button.clicked.connect(self._shutdown_application)
        restart_button = QPushButton("Redémarrer KAIRO")
        restart_button.clicked.connect(self._restart_application)
        app_actions.addWidget(shutdown_button)
        app_actions.addWidget(restart_button)
        app_actions.addStretch(1)
        background_layout.addLayout(app_actions)
        background_layout.addStretch(1)
        tabs.addTab(background, "Arrière-plan")

        update_page = QWidget()
        update_layout = QVBoxLayout(update_page)
        update_layout.setContentsMargins(20, 20, 20, 20)
        update_layout.setSpacing(12)
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
        update_actions = QHBoxLayout()
        update_actions.addWidget(git_update_button)
        history_button = QPushButton("Voir l’historique")
        history_button.clicked.connect(self._show_update_history)
        update_actions.addWidget(history_button)
        update_actions.addStretch(1)
        update_layout.addLayout(update_actions)
        update_layout.addStretch(1)
        tabs.addTab(update_page, "Mise à jour")
        if initial_tab:
            requested_tab = str(initial_tab).casefold()
            for index in range(tabs.count()):
                if tabs.tabText(index).casefold() == requested_tab:
                    tabs.setCurrentIndex(index)
                    break

        tools_page = QWidget()
        tools_layout = QVBoxLayout(tools_page)
        tools_layout.setContentsMargins(20, 20, 20, 20)
        tools_layout.setSpacing(10)
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

        def cancel_settings():
            self._apply_style()
            self.page_stack.setCurrentIndex(0)

        def save_settings():
            active_profile = current_profile_values()
            for index, profile in enumerate(profile_library):
                if profile["id"] == active_profile["id"]:
                    profile_library[index] = active_profile
                    break
            else:
                profile_library.append(active_profile)
            self.ui_settings.setValue("appearance/theme", active_profile["base"])
            self.ui_settings.setValue("appearance/themeProfile", active_profile["id"])
            self.ui_settings.setValue(
                "appearance/themeLibrary",
                theme_library.serialize_library(profile_library),
            )
            self.ui_settings.setValue("notifications/sound", sound_enabled.isChecked())
            desktop_tray.set_autostart_enabled(auto_start.isChecked(), self.ui_settings)
            if not desktop_tray.service_running():
                desktop_tray.start_tray()
            config = load_config()
            config["provider"] = self.ai_provider_picker.currentData()
            config.setdefault("ollama", {})["url"] = self.ollama_url_input.text().strip().rstrip("/")
            local_index = self.ollama_model_picker.currentIndex()
            local_model = self.ollama_model_picker.currentData()
            local_is_installed = self.ollama_model_picker.itemData(
                local_index, Qt.ItemDataRole.UserRole + 1
            )
            if local_model and local_is_installed:
                config["ollama"]["model"] = str(local_model)
            config.setdefault("openrouter", {})
            cloud_model = self.openrouter_model_picker.currentData()
            if cloud_model:
                config["openrouter"]["model"] = str(cloud_model)
            config["openrouter"]["power"] = power_slider.value()
            save_config(config)
            self.config = config
            os.environ["LOCAL_IA_PROVIDER"] = config["provider"]
            os.environ["LOCAL_IA_OPENROUTER_MODEL"] = str(
                config["openrouter"].get("model") or "openai/gpt-4o-mini"
            )
            self.agent.close()
            self.agent = self._new_agent()
            self._apply_style()
            self._set_connection_status()
            self.notice.setText(f"Fournisseur actif : {config['provider']} · configuration enregistrée.")

        buttons.accepted.connect(save_settings)
        buttons.rejected.connect(cancel_settings)
        layout.addWidget(buttons)
        self._settings_page = page
        page_index = self.page_stack.addWidget(page)
        self.page_stack.setCurrentIndex(page_index)
        QTimer.singleShot(0, self._load_selected_model_catalog)

    def _shutdown_application(self):
        self.close()

    def _restart_application(self):
        try:
            process = desktop_tray.launch_gui()
        except OSError as error:
            QMessageBox.warning(self, "Redémarrage impossible", str(error))
            return
        if not self.close():
            process.terminate()

    def _show_update_history(self):
        try:
            data = json.loads((BASE_DIR / "update.json").read_text(encoding="utf-8"))
            entries = data.get("versions", []) if isinstance(data, dict) else []
            if not isinstance(entries, list):
                raise ValueError("Le champ versions doit être une liste.")
        except (OSError, json.JSONDecodeError, ValueError) as error:
            QMessageBox.warning(self, "Historique indisponible", str(error))
            return
        dialog = UpdateHistoryDialog(
            entries,
            self,
            light_theme=self.ui_settings.value("appearance/theme", "dark") == "light",
        )
        dialog.exec()

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

    def _provider_category_changed(self, *_args):
        self.provider_model_stack.setCurrentIndex(
            0 if self.ai_provider_picker.currentData() == "ollama" else 1
        )
        if self.ai_provider_picker.currentData() == "ollama":
            self.ollama_status_label.setText("Modèles Ollama locaux ou distants.")
        elif not openrouter_api_keys():
            self.ollama_status_label.setText("Connecte-toi à OpenRouter pour charger le catalogue cloud.")
        self._load_selected_model_catalog()

    def _load_selected_model_catalog(self):
        if self.ai_provider_picker.currentData() == "ollama":
            self._start_ollama_task("list", self.ollama_url_input.text())
        else:
            self._refresh_openrouter_models()

    def _refresh_openrouter_models(self):
        keys = openrouter_api_keys()
        if not keys:
            self._ollama_progress("Connecte-toi à OpenRouter pour charger le catalogue cloud.")
            return
        self._start_ollama_task(
            "openrouter-list",
            openrouter_base_url(self.config),
            api_key=keys[0],
        )

    def _set_openrouter_models(self, models):
        model_catalog.merge_provider_models("openrouter", models, replace_snapshot=True)
        self._openrouter_catalog = model_catalog.get_provider_models(
            "openrouter", chat_only=True, available_only=True
        )
        self._refresh_model_choices()

    def _refresh_model_choices(self, *_args):
        provider = self.ai_provider_picker.currentData()
        picker = self.ollama_model_picker if provider == "ollama" else self.openrouter_model_picker
        catalog = self._ollama_catalog if provider == "ollama" else self._openrouter_catalog
        selected_model = picker.currentData()
        if provider == "ollama":
            configured_model = model_config(self.config)
        else:
            configured_model = str(self.config.get("openrouter", {}).get("model", "")).strip()

        entries = [dict(item) for item in catalog if item.get("chat_compatible", True)]
        if provider == "ollama":
            for entry in entries:
                entry["_installed"] = bool(entry.get("installed"))
        identifiers = {
            str(item.get("id") or item.get("name") or "").strip()
            for item in entries
        }
        if configured_model and configured_model not in identifiers:
            entries.append({
                "id": configured_model,
                "name": configured_model,
                "_configured": True,
                "_installed": False,
            })

        selected_need = self.model_need_picker.currentData()
        selected_power = self.model_power_picker.currentData()
        classified = []
        for entry in entries:
            profile = entry.get("attributes")
            if not isinstance(profile, dict):
                profile = model_catalog.classify_model(entry, provider=provider)
            profile = {
                "needs": tuple(profile.get("needs", ("general",))),
                "power": str(profile.get("power", "unknown")),
                "footprint": str(profile.get("footprint", "")),
            }
            if selected_need != "all" and selected_need not in profile["needs"]:
                continue
            if selected_power != "all" and selected_power != profile["power"]:
                continue
            classified.append((entry, profile))

        need_order = {need: index for index, need in enumerate(MODEL_NEED_LABELS)}
        power_order = {"light": 0, "medium": 1, "heavy": 2, "unknown": 3}
        sort_mode = self.model_sort_picker.currentData()
        if sort_mode == "power":
            classified.sort(key=lambda row: (
                power_order[row[1]["power"]],
                str(row[0].get("name") or row[0].get("id", "")).casefold(),
            ))
        elif sort_mode == "name":
            classified.sort(key=lambda row: str(row[0].get("name") or row[0].get("id", "")).casefold())
        else:
            classified.sort(key=lambda row: (
                min(need_order.get(need, len(need_order)) for need in row[1]["needs"]),
                power_order[row[1]["power"]],
                str(row[0].get("name") or row[0].get("id", "")).casefold(),
            ))

        picker.blockSignals(True)
        picker.clear()
        for entry, profile in classified:
            model_id = str(entry.get("id") or entry.get("name") or "").strip()
            name = str(entry.get("name") or model_id).strip()
            power_label = MODEL_POWER_LABELS[profile["power"]]
            need_label = " · ".join(MODEL_NEED_LABELS[need] for need in profile["needs"])
            if provider == "ollama":
                install_label = "Installé" if entry.get("_installed") else "À télécharger"
                label = f"{name} · {install_label} · {power_label}"
                if profile["footprint"]:
                    label += f" · {profile['footprint']}"
                elif entry.get("recommended_size"):
                    label += f" · {entry['recommended_size']} disque"
            else:
                label = f"{name} · {model_id} · {power_label} estimé"
            if need_label:
                label += f" · {need_label}"
            if entry.get("_configured") or (provider == "openrouter" and not entry.get("available", True)):
                label += " · non installé" if provider == "ollama" else " · configuré"
            picker.addItem(label, model_id)
            if provider == "ollama":
                picker.setItemData(
                    picker.count() - 1,
                    bool(entry.get("_installed")),
                    Qt.ItemDataRole.UserRole + 1,
                )
            tooltip = f"Besoins : {need_label}\nPuissance : {power_label}"
            if profile["footprint"]:
                tooltip += f"\nTaille du modèle : {profile['footprint']}"
            elif provider == "openrouter":
                tooltip += "\nEstimation cloud heuristique; les paramètres du modèle ne sont pas publics."
            picker.setItemData(picker.count() - 1, tooltip, Qt.ItemDataRole.ToolTipRole)

        selected_index = picker.findData(selected_model or configured_model)
        if selected_index < 0:
            placeholder = (
                "Choisis un modèle correspondant"
                if classified
                else "Aucun modèle ne correspond aux filtres"
            )
            picker.insertItem(0, placeholder, None)
            selected_index = 0
        picker.setCurrentIndex(selected_index)
        picker.blockSignals(False)
        if provider == "ollama":
            self._update_ollama_model_actions()

    def _start_provider_test(self):
        if self.provider_test_task is not None and self.provider_test_task.isRunning():
            return
        provider = self.ai_provider_picker.currentData()
        picker = self.ollama_model_picker if provider == "ollama" else self.openrouter_model_picker
        model = str(picker.currentData() or "").strip()
        if not model:
            self.provider_test_status.setText("Choisis un modèle avant de lancer le test.")
            return
        if provider == "ollama" and not picker.itemData(
            picker.currentIndex(), Qt.ItemDataRole.UserRole + 1
        ):
            self.provider_test_status.setText("Télécharge d’abord le modèle Ollama sélectionné.")
            return
        keys = openrouter_api_keys() if provider == "openrouter" else []
        if provider == "openrouter" and not keys:
            self.provider_test_status.setText("Connecte-toi à OpenRouter avant de tester un modèle cloud.")
            return
        self.provider_test_button.setEnabled(False)
        self.provider_test_status.setText(f"Appel réel en cours · {model}…")
        task = ProviderCallTestTask(
            provider,
            model,
            keys[0] if keys else "",
            self.ollama_url_input.text() if provider == "ollama" else "",
            self,
        )
        self.provider_test_task = task
        task.result_ready.connect(self._provider_test_result)
        task.finished.connect(lambda selected=task: self._provider_test_finished(selected))
        task.finished.connect(task.deleteLater)
        task.start()

    def _provider_test_result(self, result):
        if result.get("error"):
            text = f"Échec de l’appel : {result['error']}"
        elif result.get("success"):
            text = f"Test réussi · réponse attendue : 437 · {result.get('model')}"
        else:
            answer = result.get("answer") or "(réponse vide)"
            text = f"Appel reçu, résultat inattendu · attendu 437, reçu : {answer}"
        try:
            self.provider_test_status.setText(text)
        except RuntimeError:
            self.provider_test_status = None

    def _provider_test_finished(self, task):
        if self.provider_test_task is task:
            self.provider_test_task = None
        button = getattr(self, "provider_test_button", None)
        if button is not None:
            try:
                button.setEnabled(True)
            except RuntimeError:
                self.provider_test_button = None

    def _set_ollama_models(self, models):
        normalized = [{"name": model} if isinstance(model, str) else model for model in models]
        normalized = [
            {**model, "installed": True}
            for model in normalized
            if isinstance(model, dict)
        ]
        model_catalog.merge_provider_models("ollama", normalized, replace_snapshot=True)
        self._ollama_catalog = model_catalog.get_provider_models("ollama", chat_only=True)
        self._refresh_model_choices()

    def _update_ollama_model_actions(self, *_args):
        try:
            index = self.ollama_model_picker.currentIndex()
            installed = bool(self.ollama_model_picker.itemData(index, Qt.ItemDataRole.UserRole + 1))
            self.ollama_delete_button.setEnabled(installed)
            manual_model = bool(self.ollama_pull_input.text().strip())
            self.ollama_pull_button.setEnabled(not installed or manual_model)
        except (AttributeError, RuntimeError):
            pass

    def _download_ollama_model(self):
        manual_model = self.ollama_pull_input.text().strip()
        if manual_model:
            model = manual_model
        else:
            index = self.ollama_model_picker.currentIndex()
            model = str(self.ollama_model_picker.currentData() or "").strip()
            if not model:
                self._ollama_progress("Choisis un modèle ou saisis son nom avant de le télécharger.")
                return
            if self.ollama_model_picker.itemData(index, Qt.ItemDataRole.UserRole + 1):
                self._ollama_progress("Ce modèle est déjà installé.")
                return
        self._start_ollama_task("pull", self.ollama_url_input.text(), model)

    def _start_ollama_task(self, action, base_url=None, model=None, api_key=""):
        if self.ollama_task is not None and self.ollama_task.isRunning():
            return
        base_url = str(base_url or self.ollama_url_input.text()).strip()
        model = str(model if model is not None else "").strip()
        if action in {"pull", "delete"} and not model:
            self._ollama_progress("Indique un nom de modèle Ollama.")
            return
        if action == "list":
            progress_message = "Connexion à Ollama et chargement des modèles…"
        elif action == "openrouter-list":
            progress_message = "Chargement du catalogue OpenRouter…"
        else:
            progress_message = f"Préparation de {model}…"
        self._ollama_progress(progress_message)
        for name in (
            "ollama_refresh_button",
            "openrouter_refresh_button",
            "ollama_pull_button",
            "ollama_delete_button",
        ):
            button = getattr(self, name, None)
            if button is not None:
                button.setEnabled(False)
        task = OllamaModelTask(action, base_url, model, api_key, self)
        self.ollama_task = task
        task.result_ready.connect(self._ollama_task_result)
        task.progress.connect(self._ollama_progress)
        task.finished.connect(lambda selected=task: self._ollama_task_finished(selected))
        task.finished.connect(task.deleteLater)
        task.start()

    def _ollama_task_finished(self, task):
        if self.ollama_task is task:
            self.ollama_task = None
        for name in (
            "ollama_refresh_button",
            "openrouter_refresh_button",
            "ollama_pull_button",
            "ollama_delete_button",
        ):
            button = getattr(self, name, None)
            if button is not None:
                try:
                    button.setEnabled(True)
                except RuntimeError:
                    pass
        if self._ollama_refresh_after_task:
            self._ollama_refresh_after_task = False
            self._start_ollama_task("list", self._ollama_refresh_url)

    def _ollama_task_result(self, result):
        action = result.get("action")
        if result.get("error"):
            source = "OpenRouter" if action == "openrouter-list" else "Ollama"
            self._ollama_progress(f"Catalogue {source} indisponible : {result['error']}")
            return
        if action == "list":
            models = result.get("models", [])
            self._set_ollama_models(models)
            self._ollama_progress(f"Connecté à Ollama · {len(models)} modèle(s) installé(s).")
        elif action == "openrouter-list":
            models = result.get("models", [])
            self._set_openrouter_models(models)
            self._ollama_progress(f"Catalogue OpenRouter chargé · {len(models)} modèle(s).")
        elif action in {"pull", "delete"}:
            if action == "delete" and self.config.get("ollama", {}).get("model") == result.get("model"):
                self.config.setdefault("ollama", {})["model"] = ""
                try:
                    save_config(self.config)
                except OSError as error:
                    self._ollama_progress(f"Modèle supprimé, mais configuration non enregistrée : {error}")
                if self._selected_provider(self.config) == "ollama":
                    self.agent.close()
                    self.agent = self._new_agent()
            verb = "Téléchargement terminé" if action == "pull" else "Modèle supprimé"
            self._ollama_progress(f"{verb} : {result.get('model')}.")
            self._ollama_refresh_after_task = True
            self._ollama_refresh_url = result.get("base_url", "")

    def _ollama_progress(self, message):
        label = getattr(self, "ollama_status_label", None)
        if label is not None:
            try:
                label.setText(str(message))
            except RuntimeError:
                self.ollama_status_label = None

    def _delete_ollama_model(self):
        index = self.ollama_model_picker.currentIndex()
        model = self.ollama_model_picker.currentData()
        if not model or not self.ollama_model_picker.itemData(
            index, Qt.ItemDataRole.UserRole + 1
        ):
            return
        answer = QMessageBox.question(
            self,
            "Supprimer le modèle Ollama",
            f"Supprimer définitivement le modèle « {model} » du serveur Ollama ?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self._start_ollama_task("delete", self.ollama_url_input.text(), model)

    def _set_connection_status(self):
        self._refresh_welcome()
        self._refresh_model_indicator()
        if self._selected_provider(self.config) == "ollama":
            self.prompt.setEnabled(True)
            self.send_button.setEnabled(True)
            if hasattr(self, "page_stack"):
                self.page_stack.setCurrentIndex(0)
                self.auth_back_button.hide()
                self._refresh_profile_avatar()
            return
        if openrouter_api_keys():
            self.prompt.setEnabled(True)
            self.send_button.setEnabled(True)
            if hasattr(self, "page_stack"):
                self.page_stack.setCurrentIndex(0)
                self.auth_back_button.show()
                self._refresh_profile_avatar()
        else:
            self.prompt.setEnabled(False)
            self.send_button.setEnabled(False)
            if hasattr(self, "page_stack"):
                self.page_stack.setCurrentIndex(1)
                self.auth_back_button.hide()
                self._refresh_profile_avatar()

    def _refresh_welcome(self):
        account = os.environ.get("LOCAL_IA_ACCOUNT", "").strip()
        try:
            name = accounts.account_profile(account)["username"] if account else "vous"
        except (OSError, ValueError):
            name = account or "vous"
        self.welcome_label.setText(f"Ravi de vous revoir, {name}")

    def _refresh_model_indicator(self, provider=None, model=None):
        indicator = getattr(self, "model_indicator", None)
        if indicator is None:
            return
        selected_provider = provider or self._selected_provider(self.config)
        if model is None:
            model = (
                getattr(self.agent, "last_selected_model", None)
                or getattr(self.agent, "model", "")
            )
        model = str(model or "Modèle non défini").strip()
        provider_label = "Ollama" if selected_provider == "ollama" else "OpenRouter"
        indicator.setText(f"{provider_label} · {model}")
        indicator.setToolTip(f"Modèle actuellement utilisé : {provider_label} · {model}")

    def _refresh_profile_avatar(self):
        account = os.environ.get("LOCAL_IA_ACCOUNT", "").strip()
        try:
            profile = accounts.account_profile(account)
        except (OSError, ValueError):
            self.profile_avatar.setIcon(QIcon())
            self.profile_avatar.setText(account[:1].upper() or "♙")
            self.profile_avatar.show()
            return
        pixmap = QPixmap(profile["avatar"])
        if not pixmap.isNull():
            self.profile_avatar.setIcon(
                QIcon(pixmap.scaled(
                    38,
                    38,
                    Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                    Qt.TransformationMode.SmoothTransformation,
                ))
            )
            self.profile_avatar.setText("")
        else:
            self.profile_avatar.setIcon(QIcon())
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
        if self._selected_provider(self.config) == "ollama":
            if openrouter_api_keys():
                self.config["provider"] = "openrouter"
                save_config(self.config)
                self.agent.close()
                self.agent = self._new_agent()
                self._set_connection_status()
                return
            self.page_stack.setCurrentWidget(self.auth_page)
            self._set_auth_mode("login")
            return
        if not openrouter_api_keys():
            self.page_stack.setCurrentWidget(self.auth_page)
            self._set_auth_mode("login")

    def _create_account(self):
        self.page_stack.setCurrentWidget(self.auth_page)
        self._set_auth_mode("signup")

    def _set_provider(self, username, api_keys, remember=True, account_password=None):
        self.config["provider"] = "openrouter"
        try:
            save_config(self.config)
        except OSError:
            pass
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

        def add_openrouter_keys(api_keys):
            values = api_keys if isinstance(api_keys, list) else [api_keys]
            existing_keys = {
                record["key"]
                for record in accounts.authenticate_api_key_records(username, password)
            }
            added = 0
            try:
                for api_key in values:
                    key = str(api_key).strip()
                    if key and key not in existing_keys:
                        accounts.add_api_key(username, password, key)
                        existing_keys.add(key)
                        added += 1
            except (OSError, ValueError) as error:
                refresh_keys()
                QMessageBox.warning(dialog, "Ajout impossible", str(error))
                return
            refresh_keys()
            self.notice.setText(f"{added} clé{'s' if added != 1 else ''} OpenRouter ajoutée{'s' if added != 1 else ''}.")

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
            lambda _checked=False: self._start_openrouter_key_creation(
                add_openrouter_keys,
                dialog.create_count.value(),
            )
        )
        dialog.remove_button.clicked.connect(remove_key)
        dialog.toggle_button.clicked.connect(toggle_key)
        dialog.usage_button.clicked.connect(show_usage)
        dialog.exec()

    def _start_openrouter_key_creation(self, on_key_created, count=1):
        if self.oauth_task and self.oauth_task.isRunning():
            return
        task = OpenRouterKeyTask(count, self)
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
            if isinstance(result, dict):
                api_keys = result.get("keys", [])
                if api_keys:
                    try:
                        on_key_created(api_keys)
                    except Exception as error:
                        QMessageBox.warning(self, "Enregistrement impossible", str(error))
                error_message = result.get("error", "Autorisation interrompue.")
                if api_keys:
                    error_message = f"{len(api_keys)} clé(s) obtenue(s) avant l’interruption.\n{error_message}"
            else:
                error_message = str(result)
            QMessageBox.warning(self, "Connexion OpenRouter impossible", error_message)
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
        self.chat_content_stack.setCurrentWidget(self.chat_content_stack.widget(1))
        self._refresh_chat_list()
        self._set_project_root(None)
        self.notice.setText("Nouvelle conversation créée et partagée avec le CLI.")

    def _toggle_comparison(self):
        if self.compare_panel.isVisible():
            self._close_comparison()
            return
        if self.code_mode_active:
            return
        self.compare_panel.show()
        self.editor_panel.hide()
        self._refresh_comparison_options()
        width = self.workspace_splitter.width()
        self.workspace_splitter.setSizes([width // 2, 0, width // 2])
        self.compare_button.setText("◫  Fermer la comparaison")

    def _close_comparison(self):
        self.compare_panel.hide()
        self.compare_button.setText("◫  Comparer")
        if self.code_mode_active:
            self.editor_panel.show()
            self.workspace_splitter.setSizes([700, 390, 0])
        else:
            self.editor_panel.hide()
            self.workspace_splitter.setSizes([self.workspace_splitter.width(), 0, 0])

    def _close_current_view(self):
        if self.compare_panel.isVisible():
            self._close_comparison()
        else:
            self.close()

    def _refresh_comparison_options(self, chats=None):
        chats = list_chats() if chats is None else chats
        current_id = self.chat.get("id")
        selected_id = self.compare_chat_picker.currentData()
        available = [chat for chat in chats if chat.get("id") != current_id]
        self.compare_chat_picker.blockSignals(True)
        self.compare_chat_picker.clear()
        for chat in available:
            title = chat.get("custom_title") or chat.get("topic") or chat.get("title") or f"Conversation #{chat['id']}"
            self.compare_chat_picker.addItem(title, int(chat["id"]))
        selected_index = self.compare_chat_picker.findData(selected_id)
        self.compare_chat_picker.setCurrentIndex(selected_index if selected_index >= 0 else 0)
        self.compare_chat_picker.setEnabled(bool(available))
        self.compare_chat_picker.blockSignals(False)
        self._render_comparison_chat()

    def _render_comparison_chat(self, *_args):
        chat_id = self.compare_chat_picker.currentData()
        compared = load_chat(chat_id) if chat_id is not None else None
        if compared is None:
            self.compare_title.setText("Aucune autre conversation")
            self.compare_transcript.setMarkdown("*Créez ou ouvrez une autre conversation pour la comparer ici.*")
            return
        title = compared.get("custom_title") or compared.get("topic") or compared.get("title") or f"Conversation #{compared['id']}"
        self.compare_title.setText(title)
        messages = []
        for message in compared.get("messages", []):
            if message.get("role") in {"user", "assistant"}:
                label = "TOI" if message["role"] == "user" else "KAIRO"
                messages.append(f"**{label}**\n\n{message.get('content', '')}")
        self.compare_transcript.setMarkdown("\n\n".join(messages) or "*Cette conversation ne contient aucun message.*")

    def _manage_conversations(self):
        active_id = self.chat.get("id") if hasattr(self, "chat") else None
        conversation_store.delete_empty_chats(
            exclude_ids=(active_id,) if active_id is not None else ()
        )
        ConversationManagerDialog(self).exec()
        self._refresh_chat_list()

    def _toggle_conversation_menu(self, expanded):
        drawer = self.conversation_drawer
        self.conversation_drawer_animation.stop()
        self.conversation_toggle.setArrowType(
            Qt.ArrowType.LeftArrow if expanded else Qt.ArrowType.RightArrow
        )
        parent_height = self.centralWidget().widget(0).height()
        drawer_x = self.sidebar.width()
        closed = QRect(drawer_x, 12, 0, max(120, parent_height - 24))
        opened = QRect(
            drawer_x,
            12,
            self.conversation_drawer_width,
            max(120, parent_height - 24),
        )
        if expanded:
            drawer.setGeometry(closed)
            drawer.show()
            drawer.raise_()
            self.conversation_drawer_animation.setStartValue(closed)
            self.conversation_drawer_animation.setEndValue(opened)
            self.conversation_drawer_animation.start()
        elif drawer.isVisible():
            self.conversation_drawer_animation.setStartValue(drawer.geometry())
            self.conversation_drawer_animation.setEndValue(closed)
            self.conversation_drawer_animation.start()

    def _conversation_drawer_animation_finished(self):
        if not self.conversation_toggle.isChecked():
            self.conversation_drawer.hide()

    def _new_chat_from_drawer(self):
        self._new_chat()
        self.conversation_toggle.setChecked(False)

    def _open_conversation_search(self):
        self.conversation_toggle.setChecked(True)
        QTimer.singleShot(260, self.chat_search.setFocus)

    def _refresh_chat_list(self):
        current_id = self.chat.get("id") if hasattr(self, "chat") else None
        conversation_store.delete_empty_chats(
            exclude_ids=(current_id,) if current_id is not None else ()
        )
        query = self.chat_search.text().strip().casefold()
        self.chat_list.clear()
        chats = list_chats()
        for chat in chats:
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
        self._refresh_comparison_options(chats)

    def _open_chat_item(self, item):
        chat_id = item.data(Qt.ItemDataRole.UserRole)
        self._open_conversation_id(chat_id)
        self.conversation_toggle.setChecked(False)

    def _open_conversation_id(self, chat_id):
        loaded = load_chat(chat_id)
        if loaded is None:
            self.notice.setText("Cette conversation est introuvable.")
            self._refresh_chat_list()
            return
        if self.tool_navigation.currentIndex() != 0:
            self.tool_navigation.setCurrentIndex(0)
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
        self.chat_content_stack.setCurrentWidget(self.chat_content_stack.widget(1))
        self._refresh_chat_list()
        self._set_project_root(self.project_root)

    def _load_chat_into_view(self):
        title = self.chat.get("custom_title") or self.chat.get("topic") or self.chat.get("title") or f"Conversation #{self.chat['id']}"
        self.chat_title.setText(title)
        self.transcript.clear()
        self._transcript_messages = []
        for message in self.chat.get("messages", []):
            if message.get("role") in {"user", "assistant"}:
                self._append_message(message["role"], message.get("content", ""))
        if not self._transcript_messages:
            self.transcript.setMarkdown("*Pose une question ou choisis une action à gauche.*")
        self.chat_content_stack.setCurrentWidget(
            self.chat_content_stack.widget(1) if self._transcript_messages else self.welcome_page
        )

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
            self.files_hint.setText("Choisis un fichier du projet à ouvrir.")
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
        if self.tool_health_process is not None and self.tool_health_process.state() != QProcess.ProcessState.NotRunning:
            self.tool_health_process.terminate()
            if not self.tool_health_process.waitForFinished(1000):
                self.tool_health_process.kill()
                self.tool_health_process.waitForFinished(1000)
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
        self._start_task_progress(f"Préparation d'une proposition pour {self.current_file.name}…")
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
        self._clear_task_progress()
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
        provider = self._selected_provider(self.config)
        api_keys = openrouter_api_keys()
        if not self._chat_provider_is_ready(provider, api_keys):
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
        self._start_task_progress("Analyse du projet…" if code_mode else "Préparation de la réponse…")
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
        self._clear_task_progress()
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
            self._start_task_progress("Application du diff et vérifications…")
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
        self._clear_task_progress()
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
        self._transcript_messages.append((label, str(content or "")))
        markdown = "\n\n".join(
            f"**{message_label}**\n\n{message_content}"
            for message_label, message_content in self._transcript_messages
        )
        self.transcript.setMarkdown(markdown)
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
        connected = self._chat_provider_is_ready(
            self._selected_provider(self.config),
            openrouter_api_keys(),
        )
        self.send_button.setEnabled(not busy and connected)
        self.prompt.setEnabled(not busy and connected)
        self.code_button.setEnabled(True)
        self.chat_list.setEnabled(not busy)
        self.file_tree.setEnabled(not busy)
        self.create_entry_button.setEnabled(not busy)
        self.rename_entry_button.setEnabled(not busy)
        self.delete_entry_button.setEnabled(not busy)
        self.code_editor.setEnabled(not busy)
        self.save_button.setEnabled(not busy)

    def _show_task_progress(self, message):
        text = str(message).strip()
        model_prefix = "Modèle OpenRouter choisi pour cette demande :"
        if text.startswith(model_prefix):
            self._refresh_model_indicator(
                "openrouter",
                text[len(model_prefix):].strip(),
            )
        self.notice.setText(text)
        if self._task_progress_range is None:
            return
        lowered = text.casefold()
        if "sous-tâche" in lowered:
            stage = "Tâche"
        elif re.match(r"étape\s+\d+/\d+\s*:", lowered):
            stage = "Outil"
        elif "vérification" in lowered or "vérifie" in lowered:
            stage = "Vérification"
        elif "plan" in lowered or "découpage" in lowered or "préparation" in lowered:
            stage = "Planification"
        else:
            stage = "En cours"
        self._replace_task_progress(f"{stage} · {text}")

    def _start_task_progress(self, message):
        self._clear_task_progress()
        cursor = self.transcript.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        start = cursor.position()
        cursor.insertText(f"\nKAIRO · EN COURS\n{message}")
        self._task_progress_range = (start, cursor.position())
        self.transcript.setTextCursor(cursor)
        scrollbar = self.transcript.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
        self.notice.setText(str(message))

    def _replace_task_progress(self, message):
        start, end = self._task_progress_range
        cursor = QTextCursor(self.transcript.document())
        cursor.setPosition(start)
        cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
        cursor.insertText(f"\nKAIRO · EN COURS\n{message}")
        self._task_progress_range = (start, cursor.position())
        self.transcript.setTextCursor(cursor)
        scrollbar = self.transcript.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def _clear_task_progress(self):
        if self._task_progress_range is None:
            return
        start, end = self._task_progress_range
        cursor = QTextCursor(self.transcript.document())
        cursor.setPosition(start)
        cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
        cursor.removeSelectedText()
        self._task_progress_range = None
        self.transcript.setTextCursor(cursor)

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
        if self.provider_test_task and self.provider_test_task.isRunning():
            QMessageBox.information(self, "Test IA en cours", "Attends la fin du test du modèle avant de fermer KAIRO.")
            event.ignore()
            return
        if self.ollama_task and self.ollama_task.isRunning():
            QMessageBox.information(self, "Modèle Ollama en cours", "Attends la fin de l'opération Ollama avant de fermer KAIRO.")
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
    desktop_tray.start_tray()
    window = KairoWorkspace()
    window.show()
    return app.exec()
