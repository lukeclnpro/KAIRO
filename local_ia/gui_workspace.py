"""Interface graphique KAIRO partageant moteur et donnees avec le CLI."""

from __future__ import annotations

import json
import ast
import difflib
import hashlib
import os
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import QIODevice, QPropertyAnimation, QRegularExpression, QSaveFile, QSettings, QThread, QTimer, Qt, Signal
from PySide6.QtGui import QColor, QFont, QKeySequence, QShortcut, QTextCharFormat, QSyntaxHighlighter
from PySide6.QtWidgets import (
    QApplication,
    QAbstractItemView,
    QFileSystemModel,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QComboBox,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
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
from local_ia.core import accounts, code_projects
from local_ia.core.agent import LocalAgent, TOOL_NAMES
from local_ia.core.context import load_context
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
from local_ia.tools import file as file_tool
from local_ia.tools.edit import backup_file
import file_commands

BASE_DIR = Path(__file__).resolve().parents[1]
LOCAL_CODE_TOOLS = frozenset({"file", "write", "edit", "list", "search", "calculator"})
LOCAL_CODE_READ_TOOLS = frozenset({"file", "list", "search", "calculator"})
MAX_PREVIEW_BYTES = 1_000_000
MAX_SINGLE_FILE_AI_BYTES = 64_000
OPENROUTER_MODEL_PRESETS = (
    ("OpenAI · rapide et polyvalent", "openai/gpt-4o-mini"),
    ("Anthropic · code et raisonnement", "anthropic/claude-3.5-sonnet"),
)


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
        self.external_info = external_info
        self.allowed_tools = allowed_tools
        self.file_edit_content = file_edit_content
        self.file_path = file_path

    def run(self):
        try:
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
                )
            elif self.code_mode:
                from local_ia.cli.interface import _local_code_proposal_instructions

                answer = self.agent.respond(
                    self.chat,
                    self.request,
                    external_info=_local_code_proposal_instructions(self.project),
                    allowed_tools=LOCAL_CODE_READ_TOOLS,
                    local_code=True,
                )
            else:
                answer = self.agent.respond(
                    self.chat,
                    self.request,
                    external_info=self.external_info,
                    allowed_tools=self.allowed_tools,
                    stream=False,
                )
            self.completed.emit(True, str(answer or "").strip())
        except Exception as error:
            self.completed.emit(False, f"{type(error).__name__}: {error}")

    def _write_tools(self):
        tools = set(LOCAL_CODE_TOOLS)
        if self.command_enabled:
            tools.add("command")
        return tools


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
        self.save_timer = QTimer(self)
        self.save_timer.setSingleShot(True)
        self.save_timer.setInterval(700)
        self.save_timer.timeout.connect(self._save_open_file)
        self._build_ui()
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
        self.setCentralWidget(root)
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

        self.connect_button = ActionButton("⤴   Connexion", "connectButton")
        self.connect_button.clicked.connect(self._connect_account)
        side.addWidget(self.connect_button)
        self.manage_keys_button = ActionButton("⚿   Gérer les clés API")
        self.manage_keys_button.clicked.connect(self._manage_api_keys)
        side.addWidget(self.manage_keys_button)
        self.new_chat_button = ActionButton("＋   Nouveau chat")
        self.new_chat_button.clicked.connect(self._new_chat)
        side.addWidget(self.new_chat_button)
        self.open_file_button = ActionButton("▤   Ouvrir un fichier")
        self.open_file_button.clicked.connect(self._open_single_file)
        side.addWidget(self.open_file_button)
        self.code_button = ActionButton("⌘   Mode Code")
        self.code_button.setCheckable(True)
        self.code_button.clicked.connect(self._toggle_code_mode)
        side.addWidget(self.code_button)
        self.terminal_button = ActionButton("▣   Ouvrir le terminal")
        self.terminal_button.clicked.connect(self._open_terminal)
        side.addWidget(self.terminal_button)
        self.settings_button = ActionButton("⚙   Paramètres")
        self.settings_button.clicked.connect(self._open_settings)
        side.addWidget(self.settings_button)

        label = QLabel("CONVERSATIONS RÉCENTES")
        label.setObjectName("sectionLabel")
        side.addSpacing(16)
        side.addWidget(label)
        self.chat_list = QListWidget()
        self.chat_list.setObjectName("chatList")
        self.chat_list.itemActivated.connect(self._open_chat_item)
        self.chat_list.itemClicked.connect(self._open_chat_item)
        side.addWidget(self.chat_list, stretch=1)

        files_heading = QLabel("EXPLORATEUR DE PROJET")
        files_heading.setObjectName("sectionLabel")
        side.addWidget(files_heading)
        self.files_hint = QLabel("Active Mode Code pour choisir ou créer un projet.")
        self.files_hint.setObjectName("mutedText")
        self.files_hint.setWordWrap(True)
        side.addWidget(self.files_hint)
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
        side.addWidget(self.file_tree, stretch=1)
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
        subtitle = QLabel("Les conversations et réglages sont partagés avec l'invite de commande.")
        subtitle.setObjectName("subtitle")
        titles.addWidget(self.chat_title)
        titles.addWidget(subtitle)
        header.addLayout(titles)
        header.addStretch(1)
        self.model_picker = QComboBox()
        self.model_picker.setObjectName("modelPicker")
        self.model_picker.setToolTip("Modèle OpenRouter utilisé par le GUI et enregistré dans config.json")
        self.model_picker.activated.connect(self._model_choice)
        header.addWidget(self.model_picker, alignment=Qt.AlignmentFlag.AlignVCenter)
        self.status = QLabel("●  Connexion OpenRouter requise")
        self.status.setObjectName("status")
        header.addWidget(self.status, alignment=Qt.AlignmentFlag.AlignVCenter)
        main_layout.addLayout(header)

        workspace_splitter = QSplitter(Qt.Orientation.Horizontal)
        workspace_splitter.setObjectName("workspaceSplitter")
        chat_panel = QWidget()
        chat_layout = QVBoxLayout(chat_panel)
        chat_layout.setContentsMargins(0, 0, 8, 0)
        chat_layout.setSpacing(12)

        self.transcript = QPlainTextEdit()
        self.transcript.setObjectName("transcript")
        self.transcript.setReadOnly(True)
        self.transcript.setFont(QFont("Noto Sans", 11))
        self.transcript.setPlaceholderText("Pose une question ou choisis une action à gauche.")
        chat_layout.addWidget(self.transcript, stretch=1)
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
        workspace_splitter.addWidget(chat_panel)

        editor_panel = QWidget()
        editor_panel.setObjectName("editorPanel")
        editor_layout = QVBoxLayout(editor_panel)
        editor_layout.setContentsMargins(8, 0, 0, 0)
        editor_layout.setSpacing(10)
        editor_header = QHBoxLayout()
        self.editor_file_label = QLabel("Aperçu du code")
        self.editor_file_label.setObjectName("editorFileLabel")
        editor_header.addWidget(self.editor_file_label, stretch=1)
        self.save_button = ActionButton("Enregistrer", "saveButton")
        self.save_button.clicked.connect(self._save_open_file)
        editor_header.addWidget(self.save_button)
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
        self.highlighter = CodeHighlighter(self.code_editor.document())
        self.save_shortcut = QShortcut(QKeySequence.StandardKey.Save, self.code_editor)
        self.save_shortcut.activated.connect(self._save_open_file)
        editor_layout.addWidget(self.code_editor, stretch=1)
        self.editor_status = QLabel("Aucun fichier ouvert")
        self.editor_status.setObjectName("editorStatus")
        editor_layout.addWidget(self.editor_status)
        workspace_splitter.addWidget(editor_panel)
        workspace_splitter.setStretchFactor(0, 3)
        workspace_splitter.setStretchFactor(1, 2)
        workspace_splitter.setSizes([690, 520])
        main_layout.addWidget(workspace_splitter, stretch=1)
        root_layout.addWidget(main, stretch=1)

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

    def _open_settings(self):
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
        connect_button.clicked.connect(self._connect_account)
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

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.ui_settings.setValue("appearance/theme", theme_picker.currentData())
            self.ui_settings.setValue("notifications/sound", sound_enabled.isChecked())
            self._apply_style()

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
            self.status.setText(f"●  {account or 'OpenRouter'}")
            self.connect_button.setText("●   API connectée")
            self.prompt.setEnabled(True)
            self.send_button.setEnabled(True)
        else:
            self.status.setText("●  Connexion API requise")
            self.connect_button.setText("⤴   Connexion OpenRouter")
            self.prompt.setEnabled(False)
            self.send_button.setEnabled(False)

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
        names = accounts.list_accounts()
        if not names:
            answer = QMessageBox.question(
                self,
                "Aucun compte",
                "Aucun compte local. Voulez-vous en créer un ?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes,
            )
            if answer == QMessageBox.StandardButton.Yes:
                self._create_account()
            return
        username, accepted = QInputDialog.getItem(self, "Connexion", "Compte local", names, 0, False)
        if not accepted or not username:
            return
        password, accepted = QInputDialog.getText(
            self,
            "Connexion",
            "Mot de passe du compte",
            QLineEdit.EchoMode.Password,
        )
        if not accepted:
            return
        try:
            api_keys = accounts.authenticate_api_keys(username, password)
        except ValueError as error:
            QMessageBox.warning(self, "Connexion refusée", str(error))
            return
        self._set_provider(username, api_keys)

    def _create_account(self):
        username, accepted = QInputDialog.getText(self, "Créer un compte", "Nom du compte")
        if not accepted or not username.strip():
            return
        password, accepted = QInputDialog.getText(
            self,
            "Créer un compte",
            "Mot de passe (8 caractères minimum)",
            QLineEdit.EchoMode.Password,
        )
        if not accepted:
            return
        api_key, accepted = QInputDialog.getText(
            self,
            "Créer un compte",
            "Clé API OpenRouter",
            QLineEdit.EchoMode.Password,
        )
        if not accepted:
            return
        try:
            accounts.create_account(username, password, api_key)
            api_keys = accounts.authenticate_api_keys(username, password)
        except (OSError, ValueError) as error:
            QMessageBox.warning(self, "Création impossible", str(error))
            return
        self._set_provider(username, api_keys)

    def _set_provider(self, username, api_keys, remember=True):
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
                accounts.save_session(username, api_keys)
            except Exception:
                self.notice.setText(f"Connecté au compte {username}; session non mémorisée par le trousseau système.")
                return
        self.notice.setText(f"Connecté au compte {username}; reconnexion automatique activée.")

    def _manage_api_keys(self):
        username = os.environ.get("LOCAL_IA_ACCOUNT", "").strip()
        if not username:
            QMessageBox.information(self, "Connexion requise", "Connecte-toi d'abord à un compte local.")
            return
        password, accepted = QInputDialog.getText(
            self,
            "Gérer les clés API",
            f"Mot de passe du compte {username}",
            QLineEdit.EchoMode.Password,
        )
        if not accepted:
            return
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
        dialog.remove_button.clicked.connect(remove_key)
        dialog.toggle_button.clicked.connect(toggle_key)
        dialog.usage_button.clicked.connect(show_usage)
        dialog.exec()

    def _new_chat(self):
        self.chat = create_chat()
        self.project_root = None
        self.agent.prepare_chat(self.chat)
        self._load_chat_into_view()
        self._refresh_chat_list()
        self._set_project_root(None)
        self.notice.setText("Nouvelle conversation créée et partagée avec le CLI.")

    def _refresh_chat_list(self):
        current_id = self.chat.get("id") if hasattr(self, "chat") else None
        self.chat_list.clear()
        for chat in list_chats()[:20]:
            title = chat.get("topic") or chat.get("title") or "Conversation sans titre"
            item = QListWidgetItem(f"{title}\n#{chat['id']} · {len(chat.get('messages', []))} messages")
            item.setData(Qt.ItemDataRole.UserRole, int(chat["id"]))
            self.chat_list.addItem(item)
            if current_id == chat["id"]:
                self.chat_list.setCurrentItem(item)

    def _open_chat_item(self, item):
        chat_id = item.data(Qt.ItemDataRole.UserRole)
        loaded = load_chat(chat_id)
        if loaded is None:
            self.notice.setText("Cette conversation est introuvable.")
            self._refresh_chat_list()
            return
        self.chat = loaded
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
        title = self.chat.get("topic") or self.chat.get("title") or f"Conversation #{self.chat['id']}"
        self.chat_title.setText(title)
        self.transcript.clear()
        for message in self.chat.get("messages", []):
            if message.get("role") in {"user", "assistant"}:
                self._append_message(message["role"], message.get("content", ""))

    def _toggle_code_mode(self, checked):
        if not checked:
            self.code_armed = False
            self.prompt.setPlaceholderText("Écris une demande, /help, /commande …")
            return
        project = self._choose_project()
        if project is None:
            self.code_button.setChecked(False)
            return
        self.project_root = project
        self.code_armed = True
        self.chat["code_project_name"] = project.name
        self.chat["code_project_path"] = str(project)
        save_chat(self.chat, async_mode=False)
        code_projects.install_code_examples(project)
        self._set_project_root(project)
        self.prompt.setPlaceholderText("Décris le changement à proposer; le diff sera soumis à approbation…")
        self.notice.setText(f"Mode Code · {project.name} · modifications après approbation")

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
        self.code_button.setChecked(False)
        self.code_armed = False
        self.project_root = None
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

    def _close_editor_file(self):
        self.current_file = None
        self.single_file_mode = False
        self.editor_project_root = None
        self._saved_hash = None
        self._backed_up_files = set()
        self._loading_editor = True
        self.code_editor.clear()
        self.code_editor.document().setModified(False)
        self._loading_editor = False
        self.editor_file_label.setText("Aperçu du code")
        self.editor_status.setText("Aucun fichier ouvert")
        self.ai_file_button.setEnabled(False)

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
        code_mode = self.code_armed or request.startswith("/code ")
        if request.startswith("/code "):
            request = request[6:].strip()
        if request == "/code":
            self._toggle_code_mode(True)
            return
        if code_mode and not self.project_root:
            project = self._choose_project()
            if project is None:
                return
            self.project_root = project
            self.chat["code_project_name"] = project.name
            self.chat["code_project_path"] = str(project)
            save_chat(self.chat, async_mode=False)
            code_projects.install_code_examples(project)
            self._set_project_root(project)
        self._append_message("user", request)
        self.notice.setText("Analyse du projet…" if code_mode else "KAIRO réfléchit…")
        self._set_busy(True)
        external_info = self._single_file_context() if not code_mode else None
        command_enabled = self._commands_enabled()
        allowed_tools = set(TOOL_NAMES)
        if not command_enabled:
            allowed_tools.discard("command")
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
        self.worker.completed.connect(lambda success, answer: self._proposal_finished(request, code_mode, success, answer))
        self.worker.start()

    def _proposal_finished(self, request, code_mode, success, answer):
        self._set_busy(False)
        if not success:
            self._append_message("assistant", f"Erreur : {answer}")
            self.notice.setText("La demande a échoué.")
            return
        if code_mode:
            self._append_message("assistant", answer)
            approved = QMessageBox.question(
                self,
                "Appliquer la proposition ?",
                "La proposition est affichée dans le chat. Appliquer les changements et lancer les vérifications autorisées ?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            ) == QMessageBox.StandardButton.Yes
            if not approved:
                add_chat_message(self.chat, "user", request)
                add_chat_message(self.chat, "assistant", answer + "\n\nProposition refusée; aucun fichier modifié.")
                self._refresh_chat_list()
                self.notice.setText("Proposition refusée; aucun fichier modifié.")
                self.code_armed = False
                self.code_button.setChecked(False)
                return
            self.notice.setText("Application du diff et vérifications…")
            self._set_busy(True)
            self.worker = AgentTask(
                self.agent,
                self.chat,
                request,
                proposal=answer,
                project=self.project_root,
                command_enabled=self._commands_enabled(),
            )
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
        self.code_armed = False
        self.code_button.setChecked(False)
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

    def _set_busy(self, busy):
        connected = bool(openrouter_api_keys())
        self.send_button.setEnabled(not busy and connected)
        self.prompt.setEnabled(not busy and connected)
        self.new_chat_button.setEnabled(not busy)
        self.code_button.setEnabled(not busy)

    def _commands_enabled(self):
        value = load_config().get("command_execution", {})
        return isinstance(value, dict) and bool(value.get("enabled"))

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
